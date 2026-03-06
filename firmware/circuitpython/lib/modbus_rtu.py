# modbus_rtu.py - Modbus RTU protocol
# CircuitPython Ver

import struct

class ModbusRTU:
    """standard Modbus RTU protocol实现"""
    
    # 功能码
    FUNC_READ_HOLDING = 0x03
    FUNC_WRITE_SINGLE = 0x06
    FUNC_WRITE_MULTI = 0x10
    
    # 测斜仪寄存器address
    REG_ANGLE_A = 0x0000      # Aaxis角度 (2byte, signed)
    REG_ANGLE_B = 0x0001      # Baxis角度
    REG_ANGLE_Z = 0x0002      # Zaxis
    REG_TEMP = 0x0003         # temp
    REG_STATUS = 0x0004       # status
    REG_MODEL = 0x0005        # model
    REG_VERSION = 0x0006      # Ver
    
    def __init__(self, rs485_driver):
        self.driver = rs485_driver
    
    def _calc_crc16(self, data: bytes) -> int:
        """计算 Modbus CRC16"""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc
    
    def _build_read_frame(self, slave_id: int, start_register: int, register_count: int) -> bytes:
        """buildread寄存器command"""
        frame = bytes([
            slave_id,
            self.FUNC_READ_HOLDING,
            (start_register >> 8) & 0xFF,
            start_register & 0xFF,
            (register_count >> 8) & 0xFF,
            register_count & 0xFF
        ])
        crc = self._calc_crc16(frame)
        return frame + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
    
    def _build_write_frame(self, slave_id: int, register_address: int, value: int) -> bytes:
        """buildwrote单寄存器command"""
        frame = bytes([
            slave_id,
            self.FUNC_WRITE_SINGLE,
            (register_address >> 8) & 0xFF,
            register_address & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF
        ])
        crc = self._calc_crc16(frame)
        return frame + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
    
    def _parse_response(self, data: bytes, slave_id: int, func_code: int) -> bytes:
        """parseresponseframe，returndatapartial"""
        if not data or len(data) < 5:
            return None
        
        # verifyfrom机 ID
        if data[0] != slave_id:
            return None
        
        # checkErrresponse
        if data[1] & 0x80:
            error_code = data[2]
            print(f"[Modbus] Errresponse: {error_code}")
            return None
        
        # verify功能码
        if data[1] != func_code:
            return None
        
        # verify CRC
        crc_received = data[-2] | (data[-1] << 8)
        crc_calc = self._calc_crc16(data[:-2])
        if crc_received != crc_calc:
            print("[Modbus] CRC Checksumfail")
            return None
        
        # returndatapartial (skipfrom机 ID, 功能码, Byte count)
        if func_code == self.FUNC_READ_HOLDING:
            byte_count = data[2]
            return data[3:3 + byte_count]
        
        return data[2:-2]
    
    def read_data(self, address: int, timeout_ms: int = 200) -> dict:
        """
        readsensordata
        
        Args:
            address: Modbus from机address (1-247)
        
        Returns:
            {a, b, z, temp, status, model}
        """
        # read 7 寄存器 (角度A, 角度B, 角度Z, temp, status, model, Ver)
        command = self._build_read_frame(address, self.REG_ANGLE_A, 7)
        
        response = self.driver.send_and_receive(
            command, response_size=19, timeout_ms=timeout_ms
        )
        
        if not response:
            return None
        
        data = self._parse_response(response, address, self.FUNC_READ_HOLDING)
        if not data or len(data) < 14:
            return None
        
        # parse寄存器value (large端序)
        a_raw = struct.unpack(">h", data[0:2])[0]
        b_raw = struct.unpack(">h", data[2:4])[0]
        z_raw = struct.unpack(">h", data[4:6])[0]
        temp_raw = struct.unpack(">h", data[6:8])[0]
        status = struct.unpack(">H", data[8:10])[0]
        model = struct.unpack(">H", data[10:12])[0]
        version = struct.unpack(">H", data[12:14])[0]
        
        return {
            "a": a_raw / 100.0,
            "b": b_raw / 100.0,
            "z": z_raw / 100.0,
            "temp": temp_raw / 10.0,
            "status": "C" if status == 0 else "E",
            "model": model,
            "version": version / 100.0
        }
    
    def read_temp(self, address: int, timeout_ms: int = 200) -> dict:
        """readtempandmodel"""
        # readtempandmodel寄存器
        command = self._build_read_frame(address, self.REG_TEMP, 2)
        
        response = self.driver.send_and_receive(
            command, response_size=9, timeout_ms=timeout_ms
        )
        
        if not response:
            return {"error": "no responseonse"}
        
        data = self._parse_response(response, address, self.FUNC_READ_HOLDING)
        if not data or len(data) < 4:
            return {"error": "invalid response"}
        
        temp_raw = struct.unpack(">h", data[0:2])[0]
        model = struct.unpack(">H", data[2:4])[0]
        
        return {
            "temp": temp_raw / 10.0,
            "model": model
        }
    
    def write_address(self, old_address: int, new_address: int,
                                timeout_ms: int = 200) -> bool:
        """
        moduleifyfrom机address
        Note意: Modbus standardnot支持直接moduleifyaddress，这里usesextendedcommand
        """
        # false设uses寄存器 0x0100 存储from机address
        REG_SLAVE_ADDR = 0x0100
        command = self._build_write_frame(old_address, REG_SLAVE_ADDR, new_address)
        
        response = self.driver.send_and_receive(
            command, response_size=8, timeout_ms=timeout_ms
        )
        
        if not response:
            return False
        
        data = self._parse_response(response, old_address, self.FUNC_WRITE_SINGLE)
        return data is not None
    
    def write_model(self, address: int, model: int,
                                 timeout_ms: int = 200) -> bool:
        """wrotemodel"""
        command = self._build_write_frame(address, self.REG_MODEL, model)
        
        response = self.driver.send_and_receive(
            command, response_size=8, timeout_ms=timeout_ms
        )
        
        if not response:
            return False
        
        data = self._parse_response(response, address, self.FUNC_WRITE_SINGLE)
        return data is not None

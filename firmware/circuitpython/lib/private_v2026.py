# private_v2026.py - Private Protocol V2026
# CircuitPython Ver
# 参考 inclinometer_client/protocol.py

import time
import struct



# Frame markers
FRAME_HEADER_CMD = 0xCC
FRAME_HEADER_RSP = 0xDD
FRAME_END = 0xEE

class PrivateProtocolV2026:
    """
    Inclinometer Private Protocol V2026
    
    sendframe: CC [总Byte count] [command2B] [data] [Checksum] EE
    responseframe: DD [总Byte count] [command2B] [data] [Checksum] EE
    Checksum: fromframehead到Checksumbit之before的allbyte XOR
    """
    
    # Command definitions
    CMD_WRITE_ADDR_BY_AUTOID = 0x00A0  # byAutoIDwrotefixedaddress
    CMD_REACQ_AUTO_ID = 0x00A1         # 重newgetAutoID
    CMD_RETURN_FIXED_ADDR = 0x00A2     # returnfixedaddress (by AutoID)
    CMD_READ_DATA_SLEEP = 0x00A3       # readdata (带Sleep)
    CMD_READ_ALL_DATA = 0x00A4         # returnalldata
    CMD_READ_DATA_AWAKE = 0x005A       # readdata (notSleep)
    CMD_UPDATE_FIXED_ADDR = 0x00A6     # updatefixedaddress (一yes一)
    CMD_MODIFY_FIXED_ADDR = 0x00A7     # moduleifyfixedaddress
    CMD_READ_TEMP = 0x00A8             # readtempandsensortype
    CMD_SET_MODEL = 0x00C7             # writemodel/量程
    CMD_READ_MODEL = 0x00C8            # readmodel/量程
    CMD_SET_MODBUS_ID = 0x00AB         # Write Modbus ID
    
    # responsecommand
    RSP_WRITE_ADDR_BY_AUTOID = 0x00B0
    RSP_RETURN_FIXED_ADDR = 0x00B2
    RSP_READ_DATA_SLEEP = 0x003B
    RSP_READ_ALL_DATA = 0x004B
    RSP_READ_DATA_AWAKE = 0x005B
    RSP_MODIFY_FIXED_ADDR = 0x007B
    RSP_READ_TEMP = 0x008B
    RSP_READ_MODEL = 0x008D
    RSP_SET_MODBUS_ID = 0x00BA
    
    def __init__(self, rs485_driver):
        self.driver = rs485_driver
    
    def _xor_checksum(self, data: bytes) -> int:
        """计算 XOR Checksumand"""
        result = 0
        for b in data:
            result ^= b
        return result
    
    def _build_frame(self, command: int, data: bytes = b'') -> bytes:
        """
        buildsendframe
        format: CC [length] [commandhigh] [commandlow] [data...] [Checksum] EE
        """
        # length = Header + Len + Cmd(2) + Data + Check + End
        length = 1 + 1 + 2 + len(data) + 1 + 1
        frame = bytes([
            FRAME_HEADER_CMD,
            length,
            (command >> 8) & 0xFF,
            command & 0xFF
        ]) + data
        checksum = self._xor_checksum(frame)
        frame += bytes([checksum, FRAME_END])
        return frame
    
    def _parse_response(self, data: bytes, expected_command: int) -> dict:
        """parseresponseframe"""
        if not data or len(data) < 6:
            return None
        
        # 查找framehead DD
        start = -1
        for i in range(len(data)):
            if data[i] == FRAME_HEADER_RSP:
                start = i
                break
        
        if start < 0:
            return None
        
        data = data[start:]
        if len(data) < 6:
            return None
        
        # checkFrame end
        if data[-1] != FRAME_END:
            return None
        
        length = data[1]
        command = (data[2] << 8) | data[3]
        payload = data[4:-2]
        checksum = data[-2]
        
        # verifyChecksumand
        if self._xor_checksum(data[:-2]) != checksum:
            return None
        
        # verifycommand
        if command != expected_command:
            return None
        
        return {
            "command": command,
            "length": length,
            "payload": payload
        }
    
    def read_data(self, address: int, timeout_ms: int = 200) -> dict:
        """
        readsensordata (A3 command，带Sleep) - syncVer
        
        Returns:
            {a, b, z, status, voltage, version, is_2axis}
        """
        # buildcommand: fixedaddress 4 byte
        data = struct.pack(">I", address)
        command_frame = self._build_frame(self.CMD_READ_DATA_SLEEP, data)
        
        # send并recv (sync)
        response = self.driver.send_and_receive(
            command_frame, response_size=30, timeout_ms=timeout_ms
        )
        
        if not response:
            return None
        
        parsed = self._parse_response(response, self.RSP_READ_DATA_SLEEP)
        if not parsed:
            return None
        
        return self._parse_axis_data(parsed["payload"])
    
    def scan_address(self, auto_id: int, timeout_ms: int = 300) -> dict:
        """
        Scanaddress (A2 command)
        
        Args:
            auto_id: AutoID (0-1023)
            timeout_ms: timeouttime
        
        Returns:
            {auto_id, fixed_address} or None
        """
        # buildcommand: AutoID (2byte)
        data = struct.pack(">H", auto_id)
        command_frame = self._build_frame(self.CMD_RETURN_FIXED_ADDR, data)
        
        # send并recv (sync)
        response = self.driver.send_and_receive(
            command_frame, response_size=12, timeout_ms=timeout_ms
        )
        
        if not response:
            return None
        
        parsed = self._parse_response(response, self.RSP_RETURN_FIXED_ADDR)
        if not parsed or len(parsed["payload"]) < 6:
            return None
        
        # parseresponse: AutoID(2) + FixedAddr(4)
        resp_auto_id = struct.unpack(">H", parsed["payload"][0:2])[0]
        fixed_address = struct.unpack(">I", parsed["payload"][2:6])[0]
        
        # invalidaddressfilter
        if fixed_address == 0 or fixed_address == 0xFFFFFFFF:
            return None
        
        return {
            "auto_id": resp_auto_id,
            "fixed_addr": fixed_address
        }
    
    def write_address_by_autoid(self, auto_id: int, fixed_address: int, timeout_ms: int = 300) -> bool:
        """
        by AutoID wrotefixedaddress (A0 command)
        
        Args:
            auto_id: AutoID (0-1023)
            fixed_address: 要wrote的fixedaddress
            timeout_ms: timeouttime
        
        Returns:
            True ok, False fail
        """
        # buildcommand: AutoID (2byte) + FixedAddr (4byte)
        data = struct.pack(">H", auto_id) + struct.pack(">I", fixed_address)
        command_frame = self._build_frame(self.CMD_WRITE_ADDR_BY_AUTOID, data)
        
        # send并recv (sync)
        response = self.driver.send_and_receive(
            command_frame, response_size=12, timeout_ms=timeout_ms
        )
        
        if not response:
            return False
        
        parsed = self._parse_response(response, self.RSP_WRITE_ADDR_BY_AUTOID)
        return parsed is not None
    
    def read_temp(self, address: int, timeout_ms: int = 200) -> dict:
        """readtempandmodel (A8 command) - syncVer"""
        data = struct.pack(">I", address)
        command_frame = self._build_frame(self.CMD_READ_TEMP, data)
        
        response = self.driver.send_and_receive(
            command_frame, response_size=20, timeout_ms=timeout_ms
        )
        
        if not response:
            return {"error": "no responseonse"}
        
        parsed = self._parse_response(response, self.RSP_READ_TEMP)
        if not parsed:
            return {"error": "parse failed"}
        
        payload = parsed["payload"]
        if len(payload) < 5:
            return {"error": "invalid payload"}
        
        # address 4B + temp 4B (float) + model 1B
        fixed_address = struct.unpack(">I", payload[0:4])[0]
        temp = struct.unpack(">f", payload[4:8])[0] if len(payload) >= 8 else 0.0
        model = payload[8] if len(payload) > 8 else 0
        
        return {
            "address": fixed_address,
            "temp": temp,
            "model": model
        }
    
    def read_all_data(self, timeout_ms: int = 500) -> dict:
        """
        A4 command - read all data (includes AutoID)
        A4 为广播命令，不需要地址参数
        Response 0x4B: AutoID(2B) + fixed_addr(4B) + axis data
        """
        command_frame = self._build_frame(self.CMD_READ_ALL_DATA)
        
        response = self.driver.send_and_receive(
            command_frame, response_size=30, timeout_ms=timeout_ms
        )
        
        if not response:
            return None
        
        parsed = self._parse_response(response, self.RSP_READ_ALL_DATA)
        if not parsed:
            return None
        
        payload = parsed["payload"]
        if len(payload) < 19:
            return None
        
        # AutoID (2B) + fixed_addr (4B) + axis data
        auto_id = struct.unpack(">H", payload[0:2])[0]
        fixed_addr = struct.unpack(">I", payload[2:6])[0]
        
        # Parse axis data (offset by 2 for AutoID)
        is_2axis = len(payload) < 23
        if is_2axis:
            a_axis = struct.unpack(">f", payload[6:10])[0]
            z_axis = 0.0
            b_axis = struct.unpack(">f", payload[10:14])[0]
            voltage_version = struct.unpack(">f", payload[14:18])[0]
            status = payload[18] if len(payload) > 18 else 0
        else:
            a_axis = struct.unpack(">f", payload[6:10])[0]
            z_axis = struct.unpack(">f", payload[10:14])[0]
            b_axis = struct.unpack(">f", payload[14:18])[0]
            voltage_version = struct.unpack(">f", payload[18:22])[0]
            status = payload[22] if len(payload) > 22 else 0
        
        return {
            "auto_id": auto_id,
            "address": fixed_addr,
            "a": a_axis,
            "b": b_axis,
            "z": z_axis,
            "status": "C" if status == 0x03 else "E"
        }
    
    def update_address(self, new_address: int, timeout_ms: int = 500):
        """A6 command - update fixed address (one-to-one, fire-and-forget, no response)"""
        data = struct.pack(">I", new_address)
        command_frame = self._build_frame(self.CMD_UPDATE_FIXED_ADDR, data)
        
        # Fire-and-forget: just send, don't expect response
        self.driver.send_and_receive(
            command_frame, response_size=15, timeout_ms=timeout_ms
        )
    
    def write_address(self, old_address: int, new_address: int,
                      timeout_ms: int = 300) -> bool:
        """A7 command - modify fixed address (sync)"""
        self.driver.set_address_scan(True)
        time.sleep(0.05)
        
        data = struct.pack(">II", old_address, new_address)
        command_frame = self._build_frame(self.CMD_MODIFY_FIXED_ADDR, data)
        
        response = self.driver.send_and_receive(
            command_frame, response_size=15, timeout_ms=timeout_ms
        )
        
        self.driver.set_address_scan(False)
        
        if not response:
            return False
        
        parsed = self._parse_response(response, self.RSP_MODIFY_FIXED_ADDR)
        return parsed is not None
    
    def write_model(self, address: int, model: int,
                    timeout_ms: int = 200) -> bool:
        """C7 command - write model (fire-and-forget + A8 verify)"""
        data = struct.pack(">I", address) + bytes([model])
        command_frame = self._build_frame(self.CMD_SET_MODEL, data)
        
        self.driver.send(command_frame)
        time.sleep(1.0)  # device needs ~1s to process
        
        # verify
        result = self.read_temp(address, timeout_ms)
        return result.get("model") == model
    
    def read_model(self, address: int, timeout_ms: int = 200) -> dict:
        """C8 command - read model (sync)"""
        data = struct.pack(">I", address)
        command_frame = self._build_frame(self.CMD_READ_MODEL, data)
        
        response = self.driver.send_and_receive(
            command_frame, response_size=15, timeout_ms=timeout_ms
        )
        
        if not response:
            return {"error": "no response"}
        
        parsed = self._parse_response(response, self.RSP_READ_MODEL)
        if not parsed:
            return {"error": "parse failed"}
        
        payload = parsed["payload"]
        if len(payload) < 5:
            return {"error": "invalid payload"}
        
        fixed_address = struct.unpack(">I", payload[0:4])[0]
        model_val = payload[4]
        
        return {
            "address": fixed_address,
            "model": model_val
        }
    
    def write_modbus_id(self, address: int, modbus_id: int,
                        timeout_ms: int = 300) -> bool:
        """AB command - set Modbus ID (sync)"""
        data = struct.pack(">I", address) + bytes([modbus_id])
        command_frame = self._build_frame(self.CMD_SET_MODBUS_ID, data)
        
        response = self.driver.send_and_receive(
            command_frame, response_size=15, timeout_ms=timeout_ms
        )
        
        if not response:
            return False
        
        parsed = self._parse_response(response, self.RSP_SET_MODBUS_ID)
        return parsed is not None
    
    def _parse_axis_data(self, payload: bytes) -> dict:
        """
        parseaxisdata (3B/5B response)
        
        双axis模式 (17byte): address4B + Aaxis4B + Baxis4B + VoltVer4B + status1B
        三axis模式 (21byte): address4B + Aaxis4B + Zaxis4B + Baxis4B + VoltVer4B + status1B
        """
        if len(payload) < 17:
            return None
        
        # fixedaddress (4byte)
        fixed_address = struct.unpack(">I", payload[0:4])[0]
        
        # 检测双axis/三axis模式
        is_2axis = len(payload) < 21
        
        if is_2axis:
            # 双axis: A + B (noneZ)
            a_axis = struct.unpack(">f", payload[4:8])[0]
            z_axis = 0.0
            b_axis = struct.unpack(">f", payload[8:12])[0]
            voltage_version = struct.unpack(">f", payload[12:16])[0]
            status = payload[16] if len(payload) > 16 else 0
        else:
            # 三axis: A + Z + B
            a_axis = struct.unpack(">f", payload[4:8])[0]
            z_axis = struct.unpack(">f", payload[8:12])[0]
            b_axis = struct.unpack(">f", payload[12:16])[0]
            voltage_version = struct.unpack(">f", payload[16:20])[0]
            status = payload[20] if len(payload) > 20 else 0
        
        # parseVoltandVer: 1205.02 = 12V, 5.02版
        voltage = int(voltage_version / 100)
        version = voltage_version % 100
        
        return {
            "address": fixed_address,
            "a": a_axis,
            "b": b_axis,
            "z": z_axis,
            "voltage": voltage,
            "version": version,
            "status": "C" if status == 0x03 else "E",
            "status_raw": status,
            "is_2axis": is_2axis
        }

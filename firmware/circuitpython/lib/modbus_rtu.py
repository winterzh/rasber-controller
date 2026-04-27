# modbus_rtu.py - Modbus RTU 基类 + PROFILE dispatcher
# 厂商子类只需声明 NAME + PROFILE dict, 基类负责帧收发/CRC/解码.
# PROFILE 不能表达的怪异格式可 override read_data.

import struct
from lib.protocol_base import ProtocolBase


FC_READ_HOLDING = 0x03
FC_READ_INPUT = 0x04


def crc16_modbus(data):
    """CRC-16/MODBUS (poly 0xA001, init 0xFFFF, little-endian on wire)"""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


class ModbusRTU(ProtocolBase):
    """
    Modbus RTU 通用基类. 子类填 PROFILE:

      PROFILE = {
        "a":    {"reg": 0x0000, "type": "float32", "scale": 0.001},
        "b":    {"reg": 0x0002, "type": "float32", "scale": 0.001},
        "temp": {"reg": 0x0010, "type": "int16",   "scale": 0.1, "fc": 0x04},
      }

    type: uint16 / int16 / uint32 / int32 / float32
    fc:   0x03 (默认 holding) 或 0x04 (input)
    swap: bool, 32-bit 字交换 (某些厂商高低字反转)
    """

    NAME = "MODBUS_RTU"
    ADDR_MIN = 0
    ADDR_MAX = 255
    SCAN_MAX = 255
    DEFAULT_FC = FC_READ_HOLDING
    PROFILE = {}

    def _build_read_request(self, slave_id, fc, reg, count):
        body = bytes([slave_id, fc]) + struct.pack(">HH", reg, count)
        crc = crc16_modbus(body)
        return body + struct.pack("<H", crc)

    def _parse_read_response(self, data, slave_id, fc, expected_count):
        expected_len = 5 + expected_count * 2
        if not data or len(data) < expected_len:
            return None
        body = data[:expected_len - 2]
        recv_crc = struct.unpack("<H", data[expected_len - 2:expected_len])[0]
        if crc16_modbus(body) != recv_crc:
            return None
        if data[0] != slave_id or data[1] != fc:
            return None
        if data[2] != expected_count * 2:
            return None
        return data[3:3 + expected_count * 2]

    def _decode(self, regs, offset, dtype, scale, swap):
        if dtype == "uint16":
            return struct.unpack(">H", regs[offset:offset + 2])[0] * scale
        if dtype == "int16":
            return struct.unpack(">h", regs[offset:offset + 2])[0] * scale
        if dtype in ("uint32", "int32", "float32"):
            chunk = regs[offset:offset + 4]
            if swap:
                chunk = chunk[2:4] + chunk[0:2]
            if dtype == "uint32":
                return struct.unpack(">I", chunk)[0] * scale
            if dtype == "int32":
                return struct.unpack(">i", chunk)[0] * scale
            return struct.unpack(">f", chunk)[0] * scale
        return None

    def read_data(self, address, timeout_ms=300):
        if not self.PROFILE:
            return None

        # 按 fc 分组, 每组一次性读取 [min_reg, max_reg_end] 范围
        by_fc = {}
        for name, spec in self.PROFILE.items():
            fc = spec.get("fc", self.DEFAULT_FC)
            by_fc.setdefault(fc, []).append((name, spec))

        result = {"address": address}
        for fc, fields in by_fc.items():
            min_reg = min(s["reg"] for _, s in fields)
            max_reg_end = max(
                s["reg"] + (2 if s["type"] in ("uint32", "int32", "float32") else 1)
                for _, s in fields
            )
            count = max_reg_end - min_reg

            request = self._build_read_request(address, fc, min_reg, count)
            response = self.driver.send_and_receive(
                request,
                response_size=5 + count * 2,
                timeout_ms=timeout_ms,
                expected_bytes=5 + count * 2,
            )
            regs = self._parse_read_response(response, address, fc, count)
            if regs is None:
                return None

            for name, spec in fields:
                offset = (spec["reg"] - min_reg) * 2
                result[name] = self._decode(
                    regs, offset, spec["type"],
                    spec.get("scale", 1.0),
                    spec.get("swap", False),
                )

        result["status"] = "C"
        return result

    def scan_address(self, index, timeout_ms=100):
        # Modbus 无 AutoID, 扫描 = ping slave_id, 任何合法响应 (含异常码) 都说明从机存在
        request = self._build_read_request(index, self.DEFAULT_FC, 0x0000, 1)
        response = self.driver.send_and_receive(
            request, response_size=7, timeout_ms=timeout_ms
        )
        if response and len(response) >= 5 and response[0] == index:
            return {"auto_id": index, "fixed_addr": index}
        return None

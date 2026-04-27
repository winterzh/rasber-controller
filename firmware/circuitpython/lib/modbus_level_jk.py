# modbus_level_jk.py - 金坛基勘 BRG-485 电桥测量模块 (压差式静力水准仪) Modbus 协议
# 厂商: 常州市金坛基勘土木工程仪器厂  V1.0.1 2024-06-12
# 标准 Modbus RTU, FC=0x03/0x06, 从机地址 1~254 (0xFF=广播)
# 主输出: 寄存器 40-41 PHY_VAL (FLOAT32, 用户自定义物理单位)
# 协议文档: ref/protocol/压差式静力水准仪通讯协议最新.docx

from lib.modbus_rtu import ModbusRTU


class ModbusLevelJK(ModbusRTU):
    NAME = "MODBUS_LevelJK"
    ADDR_MIN = 1
    ADDR_MAX = 254
    SCAN_MAX = 254

    # 实时数据块寄存器 33~41 (基类按 fc 分组一次性读取)
    PROFILE = {
        "vin":   {"reg": 0x21, "type": "uint16",  "scale": 1.0},   # 输入电压 mV
        "temp":  {"reg": 0x22, "type": "uint16",  "scale": 0.01},  # 环境温度 ℃ (固件文档标注暂无意义)
        "exsou": {"reg": 0x24, "type": "float32", "scale": 1.0},   # 激励源实时值 mV
        "brg":   {"reg": 0x26, "type": "float32", "scale": 1.0},   # 电桥实时值 mV
        "phy":   {"reg": 0x28, "type": "float32", "scale": 1.0},   # 物理实时值 (主输出, U)
    }

    def read_data(self, address, timeout_ms=300):
        raw = super().read_data(address, timeout_ms)
        if raw is None:
            return None
        # 适配上层 a/b/z/temp/voltage/status 字段
        return {
            "address": address,
            "a": raw.get("phy", 0.0),     # 主物理量 (水位 mm 或压力 Pa, 取决于设备 PHY_RANGE 配置)
            "b": raw.get("brg", 0.0),     # 电桥原始 mV (调试用)
            "z": raw.get("exsou", 0.0),   # 激励源 mV (调试用)
            "temp": raw.get("temp", 0.0),
            "voltage": raw.get("vin", 0) / 1000.0,  # mV -> V
            "status": raw.get("status", "C"),
            "is_2axis": True,
        }

# protocol_base.py - RS485 协议抽象基类
# 所有 RS485 协议实现必须继承本类并填充元数据 + 实现关键方法.
# 元数据被 list_protocols BLE 命令上报给 APP, 用于地址校验与扫描范围.

class ProtocolBase:
    NAME = "BASE"          # 协议标识符 (config 字符串与 registry key)
    ADDR_MIN = 0           # 合法传感器地址下限 (含)
    ADDR_MAX = 0xFFFFFFFF  # 合法传感器地址上限 (含)
    SCAN_MAX = 0           # 扫描 index 上限 (PRIVATE 用 auto_id 上限, Modbus 用 slave_id 上限)

    def __init__(self, rs485_driver):
        self.driver = rs485_driver

    def read_data(self, address, timeout_ms=200):
        raise NotImplementedError

    def scan_address(self, index, timeout_ms=300):
        raise NotImplementedError

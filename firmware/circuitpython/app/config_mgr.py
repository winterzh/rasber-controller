# config_mgr.py - NVM 配置管理器
# CircuitPython Ver — 所有配置存储在 microcontroller.nvm (20KB)

import json
import microcontroller
import struct


class ConfigManager:
    """NVM 配置管理器
    
    NVM 布局:
      nvm[0]     = USB 模式标志 (boot.py 独立管理)
      nvm[1:9]   = 保留
      nvm[10:12] = uint16 big-endian 长度头
      nvm[12:]   = JSON UTF-8 字符串
    NVM 为空时使用 _get_defaults() 硬编码兜底；
    出厂初始配置从 /config.default 文件加载（由 BLE load_default 命令触发）。
    """
    
    NVM_OFFSET = 10   # 配置数据起始偏移
    HEADER_SIZE = 2   # uint16 big-endian 长度头
    NVM_MAX = len(microcontroller.nvm) - NVM_OFFSET - HEADER_SIZE
    
    def __init__(self):
        self.config = {}
        
        if self._nvm_has_valid_config():
            print("[ConfigMgr] loaded from NVM")
        else:
            print("[ConfigMgr] NVM empty, using defaults (点APP导入配置)")
            self.config = self._get_defaults()
    
    def _nvm_has_valid_config(self) -> bool:
        """检查 NVM 是否有有效 JSON 配置，并加载"""
        try:
            o = self.NVM_OFFSET
            length = struct.unpack(">H", microcontroller.nvm[o:o+2])[0]
            if length == 0 or length > self.NVM_MAX:
                return False
            json_bytes = bytes(microcontroller.nvm[o+2:o+2 + length])
            data = json.loads(json_bytes.decode("utf-8"))
            if isinstance(data, dict) and "system" in data:
                self.config = data
                print(f"[ConfigMgr] NVM valid: {length} bytes")
                return True
            return False
        except Exception as e:
            print(f"[ConfigMgr] NVM check failed: {e}")
            return False
    
    def load(self) -> bool:
        """从 NVM 加载配置"""
        try:
            o = self.NVM_OFFSET
            length = struct.unpack(">H", microcontroller.nvm[o:o+2])[0]
            if length == 0 or length > self.NVM_MAX:
                print("[ConfigMgr] NVM data invalid")
                self.config = self._get_defaults()
                return False
            
            json_bytes = bytes(microcontroller.nvm[o+2:o+2 + length])
            self.config = json.loads(json_bytes.decode("utf-8"))
            print(f"[ConfigMgr] loaded from NVM: {length} bytes")
            return True
        except Exception as e:
            print(f"[ConfigMgr] NVM load failed: {e}")
            self.config = self._get_defaults()
            return False
    
    def save(self) -> bool:
        """将完整配置写入 NVM"""
        try:
            json_str = json.dumps(self.config)
            json_bytes = json_str.encode("utf-8")
            length = len(json_bytes)
            
            if length > self.NVM_MAX:
                print(f"[ConfigMgr] config too large: {length} > {self.NVM_MAX}")
                return False
            
            # 写长度头 + JSON 数据 (偏移 10)
            o = self.NVM_OFFSET
            microcontroller.nvm[o:o+2] = struct.pack(">H", length)
            microcontroller.nvm[o+2:o+2 + length] = json_bytes
            
            print(f"[ConfigMgr] saved to NVM: {length} bytes")
            return True
        except Exception as e:
            print(f"[ConfigMgr] NVM save failed: {e}")
            return False
    
    def get(self, key: str, default=None):
        """获取配置值，支持点分隔 key
        e.g.: get("network.mqtt_broker") -> config["network"]["mqtt_broker"]
        """
        value = self.config
        for part in key.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default
        return value
    
    def set(self, key: str, value) -> bool:
        """设置配置值，支持点分隔 key"""
        parts = key.split(".")
        target = self.config
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]
        target[parts[-1]] = value
        return True
    
    def get_all(self) -> dict:
        """获取完整配置"""
        return self.config.copy()
    
    def get_section(self, section: str) -> dict:
        """获取指定配置段"""
        if section in self.config:
            value = self.config[section]
            return value if isinstance(value, dict) else {"value": value}
        return {}
    
    def set_all(self, new_config: dict) -> bool:
        """替换完整配置并保存"""
        self.config = new_config
        return self.save()
    
    def merge(self, partial: dict) -> bool:
        """递归合并部分配置并保存"""
        self._recursive_merge(self.config, partial)
        return self.save()
    
    def _recursive_merge(self, base: dict, update: dict):
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._recursive_merge(base[key], value)
            else:
                base[key] = value
    
    def import_address_list(self, filepath: str = "/address_list.csv") -> dict:
        """从 address_list.csv 导入传感器地址列表到配置
        
        CSV 格式 (统一 3 列):
            com,baud,protocol
            1,9600,PRIVATE_V2026
            26130201,,
            26130202,,
            2,9600,PRIVATE_V2026
            26130301,,
        
        - 3 列都有值 = COM 口声明
        - 第 2/3 列为空 = 传感器地址
        
        Returns:
            {"com1": count1, "com2": count2, ...} 或 {"error": "..."}
        """
        try:
            with open(filepath, "r") as f:
                lines = f.readlines()
        except Exception as e:
            return {"error": f"file read failed: {e}"}
        
        com_data = {}
        cur_com = None
        cur_baud = 9600
        cur_protocol = "PRIVATE_V2026"
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.lower().startswith("com,"):
                continue
            
            parts = [p.strip() for p in line.split(",")]
            
            # 补齐到 3 列
            while len(parts) < 3:
                parts.append("")
            
            if parts[1] and parts[2]:
                # COM 口声明: com,baud,protocol (3 列都有值)
                try:
                    cur_com = int(parts[0])
                    cur_baud = int(parts[1])
                    cur_protocol = parts[2]
                    if cur_com not in com_data:
                        com_data[cur_com] = {"baud": cur_baud, "protocol": cur_protocol, "sensors": []}
                except (ValueError, IndexError):
                    continue
            else:
                # 地址行: addr,, (第 2/3 列为空)
                if cur_com is None:
                    continue
                try:
                    addr = int(parts[0])
                    com_data[cur_com]["sensors"].append({"addr": addr})
                except ValueError:
                    continue
        
        # 先清空所有 COM 口的 sensors (避免残留旧地址)
        for key in list(self.config.keys()):
            if key.startswith("rs485_") and isinstance(self.config[key], dict):
                self.config[key]["sensors"] = []
        
        # 写入新地址
        result = {}
        for com, data in com_data.items():
            self._save_com_config(com, data["baud"], data["protocol"], data["sensors"])
            result[f"com{com}"] = len(data["sensors"])
        
        if result or com_data == {}:
            self.save()
            print(f"[ConfigMgr] address_list imported: {result}")
        
        return result
    
    def _save_com_config(self, com: int, baud: int, protocol: str, sensors: list):
        """更新指定 COM 口的配置"""
        key = f"rs485_{com}"
        if key not in self.config:
            self.config[key] = {}
        self.config[key]["baud"] = baud
        self.config[key]["protocol"] = protocol
        self.config[key]["sensors"] = sensors
        self.config[key]["enabled"] = True
    
    def _get_defaults(self) -> dict:
        return {
            "system": {
                "id": "2026750001",
                "interval_preset": 5,
                "interval_custom_min": 60,
                "max_sensors_per_seg": 15,
                "sleep_between_polls": True,
                "sleep_mode": "light",
                "log_level": "INFO",
                "usb_rw": True,
                "rs485_ext": False,
                "merge_segments": False
            },
            "local_storage": {
                "enabled": False,
                "period": "month"
            },
            "ble": {
                "name": "UniControl",
                "pin": "1234",
                "enabled": True
            },
            "network": {
                "priority": ["4g", "wifi", "ethernet", "usb_cdc"],
                "mqtt_broker": "47.95.250.46",
                "mqtt_port": 1883,
                "mqtt_topic": "controllerdata-cirpy",
                "mqtt_user": "rasberdevice",
                "mqtt_pass": "***",
                "4g": {"enabled": True, "modem": "A7670C_yundtu", "apn": "cmnet", "cops": "0"},
                "wifi": {"enabled": False, "ssid": "", "password": "***"},
                "ethernet": {"enabled": False}
            },
            "rs485_1": {
                "enabled": True,
                "baud": 9600,
                "protocol": "PRIVATE_V2026",
                "power_on_delay_ms": 100,
                "sensors": []
            },
            "rs485_2": {
                "enabled": True,
                "baud": 9600,
                "protocol": "PRIVATE_V2026",
                "power_on_delay_ms": 100,
                "sensors": []
            }
        }

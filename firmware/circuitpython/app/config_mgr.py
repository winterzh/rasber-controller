# config_mgr.py - Cfg管理器
# CircuitPython Ver

import json
import os

class ConfigManager:
    """Cfgfile管理器，JSON persist and nested key access"""
    
    def __init__(self, config_file: str = "/config.json"):
        self.config_file = config_file
        self.backup_file = config_file + ".bak"
        self.config = {}
        self.load()
    
    def load(self) -> bool:
        """loadCfgfile，fail时tryfrombackupresume"""
        try:
            with open(self.config_file, "r") as f:
                self.config = json.load(f)
            return True
        except Exception as e:
            print(f"[ConfigMgr] load config failed: {e}")
            # tryfrombackupresume
            try:
                with open(self.backup_file, "r") as f:
                    self.config = json.load(f)
                print("[ConfigMgr] restored from backup")
                self.save()  # resume主file
                return True
            except:
                print("[ConfigMgr] backup failed, using defaults")
                self.config = self._get_defaults()
                return False
    
    def save(self) -> bool:
        """saveCfg到file，先backup原file"""
        try:
            # Createbackup
            try:
                with open(self.config_file, "r") as f:
                    backup_data = f.read()
                with open(self.backup_file, "w") as f:
                    f.write(backup_data)
                    f.flush()
            except:
                pass  # No original file on first save
            
            # savenewCfg
            with open(self.config_file, "w") as f:
                json.dump(self.config, f)
                f.flush()
            
            # 确保wroteflash
            try:
                import storage
                storage.remount("/", readonly=False)
            except:
                pass
            
            print("[ConfigMgr] config saved")
            return True
        except Exception as e:
            print(f"[ConfigMgr] save config failed: {e}")
            return False
    
    def get(self, key: str, default=None):
        """
        getCfgvalue，Support dot-separated key
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
        """
        setCfgvalue，Support dot-separated key
        e.g.: set("network.mqtt_broker", "192.168.1.1")
        """
        parts = key.split(".")
        target = self.config
        
        # Traverse to parent
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]
        
        # setvalue
        target[parts[-1]] = value
        return True
    
    def get_all(self) -> dict:
        """get完整Cfg"""
        return self.config.copy()
    
    def get_section(self, section: str) -> dict:
        """get指定Cfgseg的allinner容
        
        Args:
            section: 顶级Cfgsegname，如 "system", "network", "rs485_1"
            
        Returns:
            该seg的Cfgdict，ifsegnotexistreturnnulldict
        """
        if section in self.config:
            value = self.config[section]
            return value if isinstance(value, dict) else {"value": value}
        return {}
    
    def set_all(self, new_config: dict) -> bool:
        """替换完整Cfg"""
        self.config = new_config
        return self.save()
    
    def merge(self, partial: dict) -> bool:
        """递归mergepartialCfg"""
        self._recursive_merge(self.config, partial)
        return self.save()
    
    def _recursive_merge(self, base: dict, update: dict):
        """Recursive merge dict"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._recursive_merge(base[key], value)
            else:
                base[key] = value
    
    def _get_defaults(self) -> dict:
        """returndefaultCfg"""
        return {
            "system": {
                "id": "2026750001",
                "interval_preset": 5,
                "interval_custom_min": 60,
                "max_sensors_per_seg": 15,
                "com_expansion_enabled": False,
                "log_level": "INFO",
                "sleep_between_polls": True,
                "sleep_mode": "light"
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
                "mqtt_topic": "controllerdata-cirpy"
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

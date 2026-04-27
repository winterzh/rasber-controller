# upload_counter.py - Uploadserial numbercount器
# CircuitPython Ver

import json

class UploadCounter:
    """持久化Uploadserial numbercount器"""
    
    COUNTER_FILE = "/data/counter.json"
    
    def __init__(self):
        self.counters = {}
        self._load()
    
    def _load(self):
        """Load counter"""
        try:
            with open(self.COUNTER_FILE, "r") as f:
                self.counters = json.load(f)
        except:
            self.counters = {"default": 0}
    
    def _save(self):
        """Save counter"""
        try:
            with open(self.COUNTER_FILE, "w") as f:
                json.dump(self.counters, f)
        except Exception as e:
            print(f"[UploadCounter] Save failed: {e}")
    
    def get_next(self, channel: str = "default") -> int:
        """getdown一serial number并自增"""
        current = self.counters.get(channel, 0)
        self.counters[channel] = current + 1
        self._save()
        return current + 1
    
    def get_current(self, channel: str = "default") -> int:
        """get当beforeserial number (no increment)"""
        return self.counters.get(channel, 0)
    
    def reset(self, channel: str = "default"):
        """resetserial number"""
        self.counters[channel] = 0
        self._save()

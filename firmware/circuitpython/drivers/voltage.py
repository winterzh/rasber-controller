# voltage.py - ADC Volt监测
# CircuitPython Ver

import analogio
import pins

class VoltageMonitor:
    """多CH ADC Volt监测"""
    
    # 参考Volt
    VREF = 3.3
    
    # 分压比Cfg (per hardware)
    DIVIDER_RATIO = {
        "vin": 5.0,    # 输inVolt (12-24V 分压到 3.3V)
        "V485": 3.0,   # RS485 COM1~4 共享电压 (~12V)
    }
    
    def __init__(self):
        self.adcs = {}
        self._init_adcs()
    
    def _init_adcs(self):
        """初始化 ADC CH"""
        for name, pin in pins.ADC_CHANNELS.items():
            try:
                self.adcs[name] = analogio.AnalogIn(pin)
                print(f"[Voltage] ADC {name} init OK")
            except Exception as e:
                print(f"[Voltage] ADC {name} init FAIL: {e}")
    
    def read(self, channel: str) -> float:
        """
        read指定CHVolt
        
        Args:
            channel: CHname (vin, V5V, V4G, V1, V2, V3)
        
        Returns:
            Voltvalue (V)
        """
        adc = self.adcs.get(channel)
        if not adc:
            return 0.0
        
        try:
            # CircuitPython AnalogIn.value return 0-65535
            raw = adc.value
            # 转换asVolt
            adc_voltage = (raw / 65535.0) * self.VREF
            # Apply divider
            ratio = self.DIVIDER_RATIO.get(channel, 1.0)
            actual_voltage = adc_voltage * ratio
            
            return round(actual_voltage, 2)
            
        except Exception as e:
            print(f"[Voltage] read {channel} fail: {e}")
            return 0.0
    
    def read_all(self) -> dict:
        """readallCHVolt"""
        result = {}
        for name in self.adcs.keys():
            result[name] = self.read(name)
        return result
    
    def read_raw(self, channel: str) -> int:
        """readraw ADC value (0-65535)"""
        adc = self.adcs.get(channel)
        if adc:
            return adc.value
        return 0
    
    def get_vin_status(self) -> str:
        """get输inVoltstatus"""
        vin = self.read("vin")
        if vin < 10.0:
            return "LOW"
        elif vin > 28.0:
            return "HIGH"
        return "OK"
    
    def deinit(self):
        """Release resources"""
        for adc in self.adcs.values():
            try:
                adc.deinit()
            except:
                pass

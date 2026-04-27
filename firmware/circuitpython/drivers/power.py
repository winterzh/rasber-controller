# power.py - 电源管理
# CircuitPython Ver

import alarm
import time
import microcontroller

class PowerManager:
    """电源管理，支持depthSleepand轻度Sleep"""
    
    def __init__(self):
        self._wake_reason = self._detect_wake_reason()
        self._boot_time = time.monotonic()
    
    def _detect_wake_reason(self) -> str:
        """检测Wakereason"""
        wake_alarm = alarm.wake_alarm
        
        if wake_alarm is None:
            # 首timespower onorRST
            reset_reason = microcontroller.cpu.reset_reason
            if hasattr(reset_reason, 'name'):
                return reset_reason.name
            return "POWER_ON"
        
        if isinstance(wake_alarm, alarm.time.TimeAlarm):
            return "TIMER"
        elif isinstance(wake_alarm, alarm.pin.PinAlarm):
            return "PIN"
        elif isinstance(wake_alarm, alarm.touch.TouchAlarm):
            return "TOUCH"
        
        return "UNKNOWN"
    
    def get_wake_reason(self) -> str:
        """getWakereason"""
        return self._wake_reason
    
    def get_uptime(self) -> int:
        """get运rowtime (s)"""
        return int(time.monotonic() - self._boot_time)
    
    def light_sleep(self, duration_ms: int):
        """
        轻度Sleep，保持 RAM inner容
        
        Args:
            duration_ms: Sleeptime (毫s)
        """
        time_alarm = alarm.time.TimeAlarm(
            monotonic_time=time.monotonic() + duration_ms / 1000.0
        )
        print(f"[Power] 轻度Sleep {duration_ms}ms")
        alarm.light_sleep_until_alarms(time_alarm)
        print("[Power] from轻度SleepWake")
    
    def deep_sleep(self, duration_ms: int, preserve_dios=None):
        """
        depthSleep，Wakeafterfrom boot.py 重newstart
        
        Args:
            duration_ms: Sleeptime (毫s)
            preserve_dios: DigitalInOut 对象列表，深度休眠期间保持其 GPIO 输出状态
                          (仅 Espressif 芯片支持，会增加约 250µA 功耗)
        """
        time_alarm = alarm.time.TimeAlarm(
            monotonic_time=time.monotonic() + duration_ms / 1000.0
        )
        print(f"[Power] depthSleep {duration_ms}ms")
        if preserve_dios:
            alarm.exit_and_deep_sleep_until_alarms(time_alarm, preserve_dios=preserve_dios)
        else:
            alarm.exit_and_deep_sleep_until_alarms(time_alarm)
        # not会return到这里
    
    def deep_sleep_until_pin(self, pin, value: bool = False, pull: bool = True):
        """
        depthSleep直到引脚status变化
        
        Args:
            pin: Wake引脚
            value: Wake时的引脚电平
            pull: ifoninner部up拉/down拉
        """
        pin_alarm = alarm.pin.PinAlarm(pin, value=value, pull=pull)
        print(f"[Power] depthSleepWait引脚Wake")
        alarm.exit_and_deep_sleep_until_alarms(pin_alarm)
    
    def reset(self):
        """软件RST"""
        print("[Power] 软件RST")
        microcontroller.reset()
    
    def get_reset_reason(self) -> str:
        """getRSTreason"""
        reason = microcontroller.cpu.reset_reason
        if hasattr(reason, 'name'):
            return reason.name
        return str(reason)
    
    def get_cpu_temperature(self) -> float:
        """get CPU temp (if支持)"""
        try:
            return microcontroller.cpu.temperature
        except:
            return 0.0
    
    def get_cpu_frequency(self) -> int:
        """get CPU frequency (Hz)"""
        return microcontroller.cpu.frequency

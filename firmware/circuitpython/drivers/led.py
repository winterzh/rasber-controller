# led.py - LED statusIndicate
# CircuitPython Ver

import digitalio
import time
import pins



class LEDDriver:
    """status LED driver"""
    
    # LED mode definitions
    MODES = {
        "idle": [(0.5, True), (2.5, False)],       # slow blink：free
        "transmit": [(0.1, True), (0.1, False)],   # fast blink：传输center
        "error": [(0.2, True), (0.2, False), (0.2, True), (0.6, False)],  # double blink：error
        "connected": [(0.1, True), (0.9, False)],  # short on：doneconnection
        "off": [(1.0, False)],                      # always off
        "on": [(1.0, True)],                        # always on
    }
    
    def __init__(self):
        self.led = digitalio.DigitalInOut(pins.LED_STATUS)
        self.led.direction = digitalio.Direction.OUTPUT
        self.led.value = False
        
        self._mode = "idle"
        self._running = False
        self._task = None
    
    def set_mode(self, mode: str):
        """设置 LED 模式"""
        if mode in self.MODES:
            self._mode = mode
    
    def on(self):
        """On LED"""
        self.led.value = True
    
    def off(self):
        """Off LED"""
        self.led.value = False
    
    def toggle(self):
        """切换 LED status"""
        self.led.value = not self.led.value
    
    def blink(self, count: int = 1, on_time: float = 0.1, off_time: float = 0.1):
        """Blink n times"""
        for _ in range(count):
            self.led.value = True
            time.sleep(on_time)
            self.led.value = False
            time.sleep(off_time)
    
    
    
    def indicate_error(self):
        """Indicateerror (fast速闪烁 3 times)"""
        self.blink(3, 0.1, 0.1)
    
    def indicate_success(self):
        """Indicate success (长亮afterOff)"""
        self.on()
        time.sleep(0.5)
        self.off()
    
    def deinit(self):
        """Release resources"""
        self.stop_heartbeat()
        self.led.deinit()

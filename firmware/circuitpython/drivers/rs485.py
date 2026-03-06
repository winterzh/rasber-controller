# rs485.py - RS485 通信driver
# CircuitPython Ver

import busio
import digitalio
import time
import pins



class RS485Driver:
    """RS485 UART driver，支持 DE Dir ctrland电源管理"""
    
    def __init__(self, channel: int, baud: int = 9600, power_on_delay_ms: int = 100):
        self.channel = channel
        self.baud = baud
        self.power_on_delay_ms = power_on_delay_ms
        self._power_on = False
        
        # getCH引脚Cfg
        ch_pins = pins.RS485_CHANNELS.get(channel)
        if not ch_pins:
            raise ValueError(f"invalid的 RS485 CH: {channel}")
        
        # 只has硬件 UART CH才初始化 UART
        if ch_pins.get("type") == "hardware":
            self.uart = busio.UART(
                ch_pins["tx"], ch_pins["rx"],
                baudrate=baud,
                timeout=0.1,
                bits=8, parity=None, stop=1
            )
        else:
            # SC16IS752 extendedCH (needs I2C driver)
            self.uart = None
            print(f"[RS485] CH {channel} isextendedCH，needs SC16IS752 driver")
        
        # DE Dir ctrl引脚
        self.de_pin = digitalio.DigitalInOut(ch_pins["de"])
        self.de_pin.direction = digitalio.Direction.OUTPUT
        self.de_pin.value = False  # defaultrecv模式
        
        # VCC Power ctrl引脚
        self.vcc_pin = digitalio.DigitalInOut(ch_pins["vcc"])
        self.vcc_pin.direction = digitalio.Direction.OUTPUT
        self.vcc_pin.value = False  # Default off
        
        # ADDR scan address使能引脚
        self.address_pin = digitalio.DigitalInOut(ch_pins["address"])
        self.address_pin.direction = digitalio.Direction.OUTPUT
        self.address_pin.value = False  # defaultoff
    
    def power_on(self):
        """opensensor电源"""
        if not self._power_on:
            self.vcc_pin.value = True
            self._power_on = True
            time.sleep(self.power_on_delay_ms / 1000.0)
            print(f"[RS485] CH {self.channel} power on")
    
    def power_off(self):
        """closesensor电源"""
        if self._power_on:
            self.vcc_pin.value = False
            self._power_on = False
            print(f"[RS485] CH {self.channel} power off")
    
    def set_address_scan(self, enabled: bool):
        """setscan address模式"""
        self.address_pin.value = enabled
    
    def send(self, data: bytes):
        """senddata (blocking)"""
        if self.uart is None:
            return
        
        # 切换到send模式
        self.de_pin.value = True
        time.sleep(0.00005)  # 50us 稳定time
        
        # senddata
        self.uart.write(data)
        
        # Waitsenddone
        # time = databit数 / 波特率 + safety margin
        tx_time = len(data) * 10 / self.baud + 0.0005
        time.sleep(tx_time)
        
        # 切换回recv模式
        self.de_pin.value = False
    
    def read(self, size: int = 64, timeout_ms: int = 200) -> bytes:
        """readdata (blocking)"""
        if self.uart is None:
            return None
        
        start = time.monotonic()
        buffer = bytearray()
        
        while (time.monotonic() - start) < (timeout_ms / 1000.0):
            if self.uart.in_waiting:
                chunk = self.uart.read(min(size - len(buffer), self.uart.in_waiting))
                if chunk:
                    buffer.extend(chunk)
                    if len(buffer) >= size:
                        break
            time.sleep(0.001)
        
        return bytes(buffer) if buffer else None
    
    def send_and_receive(self, command: bytes, response_size: int = 64, 
                          timeout_ms: int = 200) -> bytes:
        """sendcommand并recvresponse"""
        # 清nullrecvbuffer
        if self.uart and self.uart.in_waiting:
            self.uart.read(self.uart.in_waiting)
        
        # send
        self.send(command)
        
        # recv
        return self.read(response_size, timeout_ms)
    
    def clear_buffer(self):
        """清nullrecvbuffer"""
        if self.uart and self.uart.in_waiting:
            self.uart.read(self.uart.in_waiting)
    
    def deinit(self):
        """Release resources"""
        self.power_off()
        if self.uart:
            self.uart.deinit()
        self.de_pin.deinit()
        self.vcc_pin.deinit()
        self.address_pin.deinit()

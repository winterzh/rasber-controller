# rs485.py - RS485 通信driver
# CircuitPython Ver

import busio
import digitalio
import time
import usb_cdc
import pins



class RS485Driver:
    """RS485 UART driver，使用硬件 rs485_dir 自动管理 DE 引脚"""
    
    def __init__(self, channel: int, baud: int = 9600, power_on_delay_ms: int = 100):
        self.channel = channel
        self.baud = baud
        self.power_on_delay_ms = power_on_delay_ms
        self._power_on = False
        self.cdc_log = True  # RX hex log 开关，默认开启
        
        # getCH引脚Cfg
        ch_pins = pins.RS485_CHANNELS.get(channel)
        if not ch_pins:
            raise ValueError(f"invalid的 RS485 CH: {channel}")
        
        # 硬件 UART + rs485_dir 自动 DE 管理
        if ch_pins.get("type") == "hardware":
            self.uart = busio.UART(
                ch_pins["tx"], ch_pins["rx"],
                baudrate=baud,
                timeout=0.1,
                bits=8, parity=None, stop=1,
                rs485_dir=ch_pins["de"],    # 硬件自动管理 DE
                rs485_invert=False          # DE=HIGH 发送
            )
        else:
            # SC16IS752 extendedCH (needs I2C driver)
            self.uart = None
            print(f"[RS485] CH {channel} isextendedCH，needs SC16IS752 driver")
        
        # VCC Power ctrl引脚
        self.vcc_pin = digitalio.DigitalInOut(ch_pins["vcc"])
        self.vcc_pin.direction = digitalio.Direction.OUTPUT
        self.vcc_pin.value = False  # Default off
        
        # SCAN 扫描使能引脚 (各通道独立)
        self.scan_pin = digitalio.DigitalInOut(ch_pins["scan"])
        self.scan_pin.direction = digitalio.Direction.OUTPUT
        self.scan_pin.value = False  # defaultoff
    
    def power_on(self):
        """opensensor电源"""
        if not self._power_on:
            self.vcc_pin.value = True
            self._power_on = True
            print(f"[RS485] CH {self.channel} power on")
    
    def power_off(self):
        """closesensor电源"""
        if self._power_on:
            time.sleep(0.05)  # 50ms wait before power off, 防止掉电损坏Flash
            self.vcc_pin.value = False
            self._power_on = False
            print(f"[RS485] CH {self.channel} power off")
    
    def set_address_scan(self, enabled: bool):
        """setscan address模式"""
        self.scan_pin.value = enabled
    
    def send(self, data: bytes):
        """发送数据 — DE 由硬件自动管理，精确到 bit 级别"""
        if self.uart is None:
            return
        self.uart.write(data)
    
    def read(self, size: int = 64, timeout_ms: int = 200, expected_bytes: int = 0) -> bytes:
        """readdata (blocking, with gap detection matching ref ui_main.py)
        
        expected_bytes > 0 时：收到足够字节立即返回，gap 延长至 500ms
        """
        if self.uart is None:
            return None
        
        start = time.monotonic()
        buffer = bytearray()
        last_recv_time = 0
        
        while (time.monotonic() - start) < (timeout_ms / 1000.0):
            if self.uart.in_waiting:
                chunk = self.uart.read(min(size - len(buffer), self.uart.in_waiting))
                if chunk:
                    buffer.extend(chunk)
                    last_recv_time = time.monotonic()
                    if len(buffer) >= size:
                        break
                    # 收到预期字节数，立即返回
                    if expected_bytes > 0 and len(buffer) >= expected_bytes:
                        break
                time.sleep(0.005)
            else:
                if buffer and last_recv_time > 0:
                    # Gap 检测: 有预期长度未达到用 500ms，否则 250ms
                    gap = 0.5 if (expected_bytes > 0 and len(buffer) < expected_bytes) else 0.25
                    if (time.monotonic() - last_recv_time) > gap:
                        break
                    time.sleep(0.005)
                else:
                    time.sleep(0.01)
        
        return bytes(buffer) if buffer else None
    
    def _cdc_print(self, msg: str):
        """输出到 serial console 和 CDC data port"""
        print(msg)
        if usb_cdc.data:
            try:
                usb_cdc.data.write((msg + "\r\n").encode())
            except:
                pass

    def send_and_receive(self, command: bytes, response_size: int = 64, 
                          timeout_ms: int = 200, expected_bytes: int = 0) -> bytes:
        """sendcommand并recvresponse (timing matching ref ui_main.py)"""
        # 清空接收缓冲区
        if self.uart and self.uart.in_waiting:
            self.uart.read(self.uart.in_waiting)
        
        # send
        self.send(command)
        
        # recv
        result = self.read(response_size, timeout_ms, expected_bytes)
        
        # RX log only
        if self.cdc_log:
            self._cdc_print(f"  [CH{self.channel}] RX: {result.hex().upper() if result else 'None'}")
        
        # 清理残留数据
        if self.uart and self.uart.in_waiting:
            self.uart.read(self.uart.in_waiting)
        
        return result
    
    def clear_buffer(self):
        """清nullrecvbuffer"""
        if self.uart and self.uart.in_waiting:
            self.uart.read(self.uart.in_waiting)
    
    def deinit(self):
        """Release resources"""
        self.power_off()
        if self.uart:
            self.uart.deinit()
        self.vcc_pin.deinit()
        self.scan_pin.deinit()

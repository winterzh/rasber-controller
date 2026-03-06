# ble_uart.py - BLE UART NUS 服务
# uses adafruit_ble high级lib实现

try:
    from adafruit_ble import BLERadio
    from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
    from adafruit_ble.services.nordic import UARTService
    _HAS_ADAFRUIT_BLE = True
except ImportError:
    _HAS_ADAFRUIT_BLE = False
    print("[BLE] WARN: adafruit_ble library missing")


class BLEUART:
    """
    uses adafruit_ble 实现的 Nordic UART Service (NUS)
    """
    
    def __init__(self, name: str = "ESP32_Ctrl"):
        self._name = name
        self._connected = False
        self._ble = None
        self._uart = None
        self._advertisement = None
        self._initialized = False
        self._poll_count = 0
        self._rx_buffer = ""
        
        if not _HAS_ADAFRUIT_BLE:
            print("[BLE] init FAIL: missing adafruit_ble lib")
            return
        
        try:
            self._ble = BLERadio()
            self._ble.name = name
            self._uart = UARTService()
            self._advertisement = ProvideServicesAdvertisement(self._uart)
            self._initialized = True
            print(f"[BLE] init done: {name}")
        except Exception as e:
            print(f"[BLE] init FAIL: {e}")
    
    def start_advertising(self):
        """advertising"""
        if not self._initialized or not self._ble:
            print("[BLE] not init，cannot advertise")
            return
        
        try:
            if not self._ble.advertising:
                self._ble.start_advertising(self._advertisement)
                print(f"[BLE] advertising: {self._name}")
        except Exception as e:
            print(f"[BLE] advertise failed: {e}")
    
    def poll(self) -> str:
        """
        轮询recvdata (notblocking)
        """
        if not self._initialized:
            return None
        
        self._poll_count += 1
        
        try:
            is_connected = self._ble.connected
            
            if is_connected:
                if not self._connected:
                    self._connected = True
                    print("[BLE] Connected!")
                
                # checkdata
                waiting = self._uart.in_waiting
                if waiting > 0:
                    # uses read 而notis readline
                    data = self._uart.read(waiting)
                    if data:
                        raw = data.decode("utf-8", errors="ignore")
                        self._rx_buffer += raw
                
                # Check buffer for complete line
                if "\n" in self._rx_buffer:
                    lines = self._rx_buffer.split("\n")
                    self._rx_buffer = lines[-1]  # 保留notdonepartial
                    for line in lines[:-1]:
                        line = line.strip()
                        if line:
                            print(f"[BLE RX] {line[:80]}{'...' if len(line) > 80 else ''}")
                            return line
            else:
                if self._connected:
                    self._connected = False
                    print("[BLE] Disconnected")
                    self.start_advertising()
        except Exception as e:
            print(f"[BLE] poll error: {e}")
        
        return None
    
    def send(self, data: str):
        """senddata（分片sendlargedata）"""
        if not self._initialized or not self._ble.connected:
            print(f"[BLE TX] skip (not connected)")
            return
        
        try:
            encoded = data.encode("utf-8")
            print(f"[BLE TX] send {len(encoded)} byte")
            
            # 分片send，每片 20 byte
            chunk_size = 20
            for i in range(0, len(encoded), chunk_size):
                chunk = encoded[i:i+chunk_size]
                self._uart.write(chunk)
                if i + chunk_size < len(encoded):
                    import time
                    time.sleep(0.02)  # 20ms delay
            
            print(f"[BLE TX] done")
        except Exception as e:
            print(f"[BLE] send failed: {e}")
    
    def is_connected(self) -> bool:
        """checkconnectionstatus"""
        if not self._initialized or not self._ble:
            return False
        return self._ble.connected
    
    def disconnect(self):
        """断开所有连接"""
        if not self._initialized or not self._ble:
            return
        try:
            for connection in self._ble.connections:
                connection.disconnect()
        except:
            pass
        self._connected = False
    
    def stop_advertising(self):
        """停止 BLE 广播"""
        if not self._initialized or not self._ble:
            return
        try:
            self._ble.stop_advertising()
            print("[BLE] advertising stopped")
        except Exception as e:
            print(f"[BLE] stop_advertising failed: {e}")

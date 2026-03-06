# wifi.py - WiFi driver
# CircuitPython Ver

import wifi
import socketpool




class WiFiDriver:
    """WiFi driver"""
    
    def __init__(self, config):
        self.config = config
        self.ssid = config.get("network.wifi.ssid", "")
        self.password = config.get("network.wifi.password", "")
        self.mqtt_broker = config.get("network.mqtt_broker", "")
        self.mqtt_port = config.get("network.mqtt_port", 1883)
        self.mqtt_user = config.get("network.mqtt_user", "")
        self.mqtt_pass = config.get("network.mqtt_pass", "")
        
        self._connected = False
        self._pool = None
        self._mqtt_client = None
        self.last_error = ""
    
    def connect(self) -> bool:
        """连接 WiFi 网络并建立 MQTT（同步版本）"""
        if not self.ssid:
            self.last_error = "未配置 SSID"
            return False
        
        # WiFi 射频连接 (不捕获异常，让调用者看到错误)
        wifi.radio.connect(self.ssid, self.password)
        
        self._connected = True
        self._pool = socketpool.SocketPool(wifi.radio)
        
        ip = wifi.radio.ipv4_address
        rssi = wifi.radio.ap_info.rssi if wifi.radio.ap_info else 0
        print(f"[WiFi] OK: {self.ssid} IP:{ip} RSSI:{rssi}")
        
        # 连接 MQTT
        if not self._connect_mqtt():
            self.last_error = f"WiFi OK, {self.last_error}"
            return False
        
        return True
    
    def _connect_mqtt(self) -> bool:
        """连接 MQTT 服务器 (plain TCP, 非 SSL)"""
        if not self._pool or not self.mqtt_broker:
            self.last_error = "no pool or broker"
            return False
        
        try:
            import adafruit_minimqtt
            mqtt_class = getattr(adafruit_minimqtt, 'MQTT', None)
            if mqtt_class is None:
                # package import — need submodule
                from adafruit_minimqtt.adafruit_minimqtt import MQTT as mqtt_class
            
            self._mqtt_client = mqtt_class(
                broker=self.mqtt_broker,
                port=self.mqtt_port,
                socket_pool=self._pool,
                username=self.mqtt_user if self.mqtt_user else None,
                password=self.mqtt_pass if self.mqtt_pass else None,
            )
            
            self._mqtt_client.connect()
            print(f"[WiFi] MQTT OK: {self.mqtt_broker}:{self.mqtt_port}")
            return True
            
        except ImportError as e:
            self.last_error = f"no minimqtt: {e}"
            return False
        except Exception as e:
            self.last_error = f"MQTT: {e}"
            return False
    
    def is_connected(self) -> bool:
        """checkconnectionstatus"""
        return self._connected and wifi.radio.connected
    
    def publish(self, topic: str, message: str) -> bool:
        """Publish MQTT message"""
        if not self._mqtt_client:
            return False
        
        try:
            self._mqtt_client.publish(topic, message)
            return True
        except Exception as e:
            print(f"[WiFi] Publishfail: {e}")
            return False
    
    def subscribe(self, topic: str, callback):
        """subscribe MQTT topic"""
        if not self._mqtt_client:
            return False
        
        try:
            self._mqtt_client.subscribe(topic)
            # setcallback
            return True
        except Exception as e:
            print(f"[WiFi] Subscribe failed: {e}")
            return False
    
    def get_ip(self) -> str:
        """获取 IP 地址"""
        if self._connected:
            return str(wifi.radio.ipv4_address)
        return ""
    
    def get_rssi(self) -> int:
        """getSignal strength (RSSI)"""
        try:
            return wifi.radio.ap_info.rssi if wifi.radio.connected else 0
        except:
            return 0
    
    def get_signal(self) -> str:
        """getSignal strength str"""
        rssi = self.get_rssi()
        return f"RSSI:{rssi}"
    
    def disconnect(self):
        """disconnectconnection"""
        try:
            if self._mqtt_client:
                self._mqtt_client.disconnect()
            wifi.radio.enabled = False
            self._connected = False
        except:
            pass

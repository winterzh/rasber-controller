# ethernet.py - W5500 ETHdriver
# CircuitPython Ver

import board
import busio
import digitalio
import pins




class EthernetDriver:
    """W5500 SPI ETHdriver"""
    
    def __init__(self, config):
        self.config = config
        self.dhcp = config.get("network.ethernet.dhcp", True)
        self.static_ip = config.get("network.ethernet.static_ip", "")
        self.gateway = config.get("network.ethernet.gateway", "")
        self.subnet = config.get("network.ethernet.subnet", "255.255.255.0")
        self.dns = config.get("network.ethernet.dns", "")
        
        self.mqtt_broker = config.get("network.mqtt_broker", "")
        self.mqtt_port = config.get("network.mqtt_port", 1883)
        
        self._connected = False
        self._eth = None
        self._mqtt_client = None
        
        self._init_hardware()
    
    def _init_hardware(self):
        """Init hardware"""
        try:
            
            # Init SPI
            self.spi = busio.SPI(pins.ETH_SCK, MOSI=pins.ETH_MOSI, MISO=pins.ETH_MISO)
            
            # CS 引脚
            self.cs_pin = digitalio.DigitalInOut(pins.ETH_CS)
            self.cs_pin.direction = digitalio.Direction.OUTPUT
            self.cs_pin.value = True
            
            # RST 引脚
            self.rst_pin = digitalio.DigitalInOut(pins.ETH_RST)
            self.rst_pin.direction = digitalio.Direction.OUTPUT
            
            # RST W5500
            self.rst_pin.value = False
            import time
            time.sleep(0.1)
            self.rst_pin.value = True
            time.sleep(0.5)
            
            # 初始化 Wiznet lib (needs adafruit_wiznet5k)
            try:
                import adafruit_wiznet5k.adafruit_wiznet5k as wiznet
                from adafruit_wiznet5k.adafruit_wiznet5k import WIZNET5K
                
                self._eth = WIZNET5K(self.spi, self.cs_pin)
                print("[Ethernet] W5500 init OK")
                print(f"[Ethernet] MAC: {':'.join(['%02X' % b for b in self._eth.mac_address])}")
                
            except ImportError:
                print("[Ethernet] needs adafruit_wiznet5k lib")
                self._eth = None
                
        except Exception as e:
            print(f"[Ethernet] 硬件init FAIL: {e}")
    
    def connect(self) -> bool:
        """连接网络（同步版本）"""
        if not self._eth:
            return False
        
        try:
            if self.dhcp:
                # DHCP
                print("[Ethernet] 获取 DHCP...")
                self._eth.set_dhcp()
            else:
                # 静态 IP
                import adafruit_wiznet5k.adafruit_wiznet5k_socket as socket
                self._eth.ifconfig = (
                    self.static_ip,
                    self.subnet,
                    self.gateway,
                    self.dns
                )
            
            self._connected = True
            print(f"[Ethernet] IP: {self._eth.pretty_ip(self._eth.ip_address)}")
            
            return True
            
        except Exception as e:
            print(f"[Ethernet] 连接失败: {e}")
            self._connected = False
            return False
    
    def _connect_mqtt(self) -> bool:
        """connection MQTT"""
        if not self._eth or not self.mqtt_broker:
            return False
        
        try:
            import adafruit_wiznet5k.adafruit_wiznet5k_socket as socket
            import adafruit_minimqtt.adafruit_minimqtt as MQTT
            
            MQTT.set_socket(socket, self._eth)
            
            self._mqtt_client = MQTT.MQTT(
                broker=self.mqtt_broker,
                port=self.mqtt_port
            )
            
            self._mqtt_client.connect()
            print(f"[Ethernet] MQTT doneconnection: {self.mqtt_broker}")
            return True
            
        except ImportError:
            print("[Ethernet] needs adafruit_minimqtt lib")
            return False
        except Exception as e:
            print(f"[Ethernet] MQTT connectionfail: {e}")
            return False
    
    def is_connected(self) -> bool:
        """checkconnectionstatus"""
        if not self._eth:
            return False
        return self._connected and self._eth.link_status
    
    def publish(self, topic: str, message: str) -> bool:
        """Publish MQTT message"""
        if not self._mqtt_client:
            return False
        
        try:
            self._mqtt_client.publish(topic, message)
            return True
        except Exception as e:
            print(f"[Ethernet] Publishfail: {e}")
            return False
    
    def get_signal(self) -> str:
        """getconnectionstatus"""
        if self._eth and self._eth.link_status:
            return "LINK:UP"
        return "LINK:DOWN"
    
    def get_ip(self) -> str:
        """get IP address"""
        if self._eth:
            return self._eth.pretty_ip(self._eth.ip_address)
        return ""
    
    def deinit(self):
        """Release resources"""
        if self._mqtt_client:
            try:
                self._mqtt_client.disconnect()
            except:
                pass
        self._connected = False

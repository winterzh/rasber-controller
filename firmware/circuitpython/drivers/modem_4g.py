# modem_4g.py - 4G moduledriver (SIM7672E)
# CircuitPython Ver

import busio
import digitalio
import time
import pins




class Modem4G:
    """SIM7672E 4G module AT commanddriver"""
    
    def __init__(self, config):
        self.config = config
        self.apn = config.get("network.4g.apn", "cmnet")
        self.cops = config.get("network.4g.cops", "0")  # COPS 运营商选择
        self.mqtt_broker = config.get("network.mqtt_broker", "")
        self.mqtt_port = config.get("network.mqtt_port", 1883)
        
        # 初始化 UART
        self.uart = busio.UART(
            pins.MODEM_TX, pins.MODEM_RX,
            baudrate=115200,
            timeout=0.1
        )
        
        # Power ctrl
        self.pwr_pin = digitalio.DigitalInOut(pins.MODEM_PWR)
        self.pwr_pin.direction = digitalio.Direction.OUTPUT
        self.pwr_pin.value = False
        
        self._connected = False
        self._mqtt_connected = False
    
    def power_on(self):
        """openmodule电源"""
        self.pwr_pin.value = True
        time.sleep(2)  # Waitmodule启动
        print("[4G] modulepower on")
    
    def power_off(self):
        """closemodule电源"""
        self.pwr_pin.value = False
        self._connected = False
        self._mqtt_connected = False
        print("[4G] modulepower off")
    
    def send_at(self, command: str, timeout_ms: int = 1000, expect: str = "OK") -> tuple:
        """
        send AT command并Waitresponse
        Returns: (success, response_lines)
        """
        # Clear buffer
        if self.uart.in_waiting:
            self.uart.read(self.uart.in_waiting)
        
        # sendcommand
        self.uart.write((command + "\r\n").encode())
        
        # readresponse
        start = time.monotonic()
        response = ""
        
        while (time.monotonic() - start) < (timeout_ms / 1000.0):
            if self.uart.in_waiting:
                chunk = self.uart.read(self.uart.in_waiting)
                if chunk:
                    response += chunk.decode("utf-8", errors="ignore")
                    if expect in response:
                        return (True, response.strip().split("\n"))
                    if "ERROR" in response:
                        return (False, response.strip().split("\n"))
            time.sleep(0.01)
        
        return (False, response.strip().split("\n") if response else [])
    
    def connect(self) -> bool:
        """连接网络（同步版本）"""
        self.power_on()
        
        # 基础检测
        ok, _ = self.send_at("AT", 2000)
        if not ok:
            print("[4G] 模块无响应")
            return False
        
        # 关闭回显
        self.send_at("ATE0", 1000)
        
        # 检查 SIM 卡
        ok, resp = self.send_at("AT+CPIN?", 5000, "READY")
        if not ok:
            print("[4G] SIM 卡未就绪")
            return False
        
        # 设置运营商选择 (COPS)
        if self.cops and self.cops != "0":
            print(f"[4G] 设置 COPS: {self.cops}")
            self.send_at(f"AT+COPS={self.cops}", 30000)
        
        # 检查网络注册
        for _ in range(30):
            ok, resp = self.send_at("AT+CREG?", 2000)
            for line in resp:
                if "+CREG:" in line and (",1" in line or ",5" in line):
                    self._connected = True
                    print("[4G] 网络已注册")
                    break
            if self._connected:
                break
            time.sleep(1)
        
        if not self._connected:
            print("[4G] 网络注册失败")
            return False
        
        # 设置 APN
        self.send_at(f'AT+CGDCONT=1,"IP","{self.apn}"', 2000)
        
        # 激活 PDP
        self.send_at("AT+CGACT=1,1", 10000)
        
        # 连接 MQTT (同步)
        self._connect_mqtt_sync()
        
        return self._connected
    
    def _connect_mqtt_sync(self) -> bool:
        """连接 MQTT 服务器（同步版本）"""
        if not self.mqtt_broker:
            return False
        
        # 配置 MQTT
        self.send_at("AT+CMQTTSTART", 5000)
        self.send_at('AT+CMQTTACCQ=0,"ESP32_Gateway"', 5000)
        
        # 连接服务器
        ok, _ = self.send_at(
            f'AT+CMQTTCONNECT=0,"tcp://{self.mqtt_broker}:{self.mqtt_port}",60,1',
            30000, "OK"
        )
        
        self._mqtt_connected = ok
        if ok:
            print(f"[4G] MQTT 已连接: {self.mqtt_broker}")
        else:
            print("[4G] MQTT 连接失败")
        
        return ok

    
    def is_connected(self) -> bool:
        """checknetconnectionstatus"""
        return self._connected and self._mqtt_connected
    
    def publish(self, topic: str, message: str) -> bool:
        """Publish MQTT message"""
        if not self._mqtt_connected:
            return False
        
        message_len = len(message)
        
        # settopic
        ok, _ = self.send_at(f'AT+CMQTTTOPIC=0,{len(topic)}', 2000, ">")
        if ok:
            self.uart.write(topic.encode())
            time.sleep(0.1)
        
        # setmessage
        ok, _ = self.send_at(f'AT+CMQTTPAYLOAD=0,{message_len}', 2000, ">")
        if ok:
            self.uart.write(message.encode())
            time.sleep(0.1)
        
        # Publish
        ok, _ = self.send_at("AT+CMQTTPUB=0,1,60", 10000)
        
        return ok
    
    def get_signal(self) -> str:
        """getSignal strength"""
        ok, resp = self.send_at("AT+CSQ", 2000)
        for line in resp:
            if "+CSQ:" in line:
                return line.replace("+CSQ:", "CSQ:").strip()
        return ""
    
    def get_network_time(self) -> str:
        """getnettime"""
        ok, resp = self.send_at("AT+CCLK?", 2000)
        for line in resp:
            if "+CCLK:" in line:
                return line.replace("+CCLK:", "").strip().strip('"')
        return ""
    
    def disconnect_mqtt(self):
        """断开 MQTT 连接，释放 MQTT 资源"""
        if self._mqtt_connected:
            self.send_at("AT+CMQTTDISC=0,60", 5000)
            self.send_at("AT+CMQTTREL=0", 5000)
            self.send_at("AT+CMQTTSTOP", 5000)
            self._mqtt_connected = False
            print("[4G] MQTT 已断开")
    
    def enter_psm(self):
        """命令 4G 模块进入 PSM 省电模式
        
        AT+CPSMS=1 开启 PSM
        TAU timer 和 Active timer 由网络协商
        调用前应先断开 MQTT
        """
        self.disconnect_mqtt()
        ok, resp = self.send_at('AT+CPSMS=1', 5000)
        if ok:
            print("[4G] PSM 已启用")
        else:
            print(f"[4G] PSM 设置失败: {resp}")
        return ok
    
    def deinit(self):
        """Release resources"""
        self.power_off()
        self.uart.deinit()
        self.pwr_pin.deinit()

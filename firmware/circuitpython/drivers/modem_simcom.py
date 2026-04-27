# modem_simcom.py - SIMCom A76XX 原生 AT 驱动 (A7670G 等裸模块)
# CircuitPython Ver
#
# 与 modem_4g.py (YunDTU) 对外接口完全一致:
#   connect() / publish(topic, msg) / get_network_time() / get_signal() /
#   is_connected() / deinit() / _connected / uart
#
# 连接流程:
#   上电 → ATE0 → AT+CPIN? → AT+CSQ → AT+CGDCONT → AT+CGATT=1
#   → 等 AT+CEREG? stat=1/5 → AT+CCLK? → AT+CMQTTSTART
#   → AT+CMQTTACCQ → AT+CMQTTCONNECT
#
# publish(topic, msg):
#   AT+CMQTTTOPIC   (交互式, 等 '>' 再写 topic 裸字节)
#   AT+CMQTTPAYLOAD (交互式, 等 '>' 再写 payload 裸字节)
#   AT+CMQTTPUB     (QoS=1, 等 +CMQTTPUB: 0,0 URC)

import busio
import digitalio
import time
import pins


class ModemSimcom:
    """SIMCom A76XX native AT driver"""

    CLIENT_IDX = 0  # MQTT client index (0-1)

    def __init__(self, config, log_func=print):
        self.config = config
        self.log = log_func
        self.apn = config.get("network.4g.apn", "CMNET")
        self.mqtt_broker = config.get("network.mqtt_broker", "")
        self.mqtt_port = config.get("network.mqtt_port", 1883)
        device_id = config.get("system.id", "ESP32_Gateway")
        self.mqtt_client_id = config.get("network.mqtt_client_id", device_id)
        self.mqtt_username = config.get("network.mqtt_user", "")
        self.mqtt_password = config.get("network.mqtt_pass", "")

        self.uart = busio.UART(
            pins.MODEM_TX, pins.MODEM_RX,
            baudrate=115200,
            timeout=0.1,
        )

        self.pwr_pin = digitalio.DigitalInOut(pins.MODEM_PWR)
        self.pwr_pin.direction = digitalio.Direction.OUTPUT
        self.pwr_pin.value = False

        self._connected = False
        self._mqtt_started = False
        self._mqtt_acquired = False
        self._mqtt_connected = False
        self._cached_time = ""

    def power_on(self):
        self.pwr_pin.value = True
        time.sleep(6)  # 模块冷启动
        self.log("[4G] power on, wait 6s")

    def power_off(self):
        self.pwr_pin.value = False
        self._connected = False
        self._mqtt_started = False
        self._mqtt_acquired = False
        self._mqtt_connected = False
        self.log("[4G] power off")

    # ── 底层 AT 收发 ─────────────────────────────────────────────

    def _drain_rx(self):
        if self.uart.in_waiting:
            self.uart.read(self.uart.in_waiting)

    def send_at(self, command, timeout_ms=1000, expect="OK"):
        """发送 AT 命令, 读到 expect 或 ERROR 为止"""
        self._drain_rx()
        self.uart.write((command + "\r\n").encode())

        start = time.monotonic()
        response = ""

        while (time.monotonic() - start) < (timeout_ms / 1000.0):
            if self.uart.in_waiting:
                chunk = self.uart.read(self.uart.in_waiting)
                if chunk:
                    response += chunk.decode("utf-8", "ignore")
                    if expect in response:
                        return (True, response.strip().split("\n"))
                    if "ERROR" in response:
                        return (False, response.strip().split("\n"))
            time.sleep(0.01)

        return (False, response.strip().split("\n") if response else [])

    def _wait_for(self, token, timeout_ms):
        """等 UART 输入出现 token, 返回 (found, 累积文本)"""
        start = time.monotonic()
        response = ""
        while (time.monotonic() - start) < (timeout_ms / 1000.0):
            if self.uart.in_waiting:
                chunk = self.uart.read(self.uart.in_waiting)
                if chunk:
                    response += chunk.decode("utf-8", "ignore")
                    if token in response:
                        return (True, response)
                    if "ERROR" in response:
                        return (False, response)
            time.sleep(0.01)
        return (False, response)

    def _get_at_value(self, cmd, prefix):
        ok, resp = self.send_at(cmd, 2000)
        for line in resp:
            if prefix in line:
                return line.split(":", 1)[1].strip()
        return ""

    def _ensure_at(self):
        for _ in range(5):
            ok, _ = self.send_at("AT", 1000)
            if ok:
                return True
            time.sleep(0.5)
        return False

    # ── 连接流程 ───────────────────────────────────────────────

    def connect(self):
        self.power_on()

        if not self._ensure_at():
            self.log("[4G] no AT response")
            return False

        self.send_at("ATE0", 1000)  # 关回显, 响应解析更干净

        # SIM 状态 (冷启动后可能延迟出 READY)
        sim_ready = False
        for _ in range(10):
            cpin = self._get_at_value("AT+CPIN?", "+CPIN:")
            if cpin == "READY":
                sim_ready = True
                break
            time.sleep(0.5)
        if not sim_ready:
            self.log(f"[4G] SIM not ready")
            return False

        iccid = self._get_at_value("AT+CICCID", "+ICCID:")
        if iccid:
            self.log(f"[4G] ICCID: {iccid}")

        csq = self._get_at_value("AT+CSQ", "+CSQ:")
        self.log(f"[4G] CSQ: {csq}")

        # PDP context 1 APN
        self.send_at(f'AT+CGDCONT=1,"IP","{self.apn}"', 1000)

        # 附着 PS
        self.send_at("AT+CGATT=1", 10000)

        # 等 EPS 注网 (CEREG: n,stat, stat=1 home / 5 roam)
        registered = False
        for i in range(30):
            creg = self._get_at_value("AT+CEREG?", "+CEREG:")
            parts = creg.split(",") if creg else []
            if len(parts) >= 2:
                stat = parts[1].strip()
                if stat in ("1", "5"):
                    registered = True
                    self.log(f"[4G] EPS registered (stat={stat})")
                    break
            if i % 5 == 0:
                self.log(f"[4G] 等待注册... {i}/30")
            time.sleep(1)

        if not registered:
            self.log("[4G] EPS 注册失败")
            return False

        # 网络时间: 模块未对时返回 70/01/01 (3GPP yy=70 → 1970), 要等运营商下发
        # 轮询最多 8s, 认可范围 [2026, 2037] (CircuitPython time.time() 32位有符号, 2038-01-19 后溢出)
        cclk = ""
        for _ in range(8):
            raw = self._get_at_value("AT+CCLK?", "+CCLK:").strip('"')
            if raw:
                # raw 形如 "25/12/31,08:30:00+32"
                try:
                    yy = int(raw.split("/", 1)[0])
                    if yy >= 100:
                        year = yy
                    elif yy >= 70:
                        year = 1900 + yy  # 3GPP pivot
                    else:
                        year = 2000 + yy
                    if 2026 <= year <= 2037:
                        cclk = raw
                        break
                except Exception:
                    pass
            time.sleep(1)
        if cclk:
            self._cached_time = cclk
            self.log(f"[4G] time: {cclk}")
        else:
            self.log("[4G] 网络时间未下发, 跳过")

        # MQTT 栈
        if not self._mqtt_start():
            return False

        self._connected = True
        self.log("[4G] MQTT ready to publish")
        return True

    def _mqtt_start(self):
        # AT+CMQTTSTART → OK + URC "+CMQTTSTART: 0"
        # (err 23 = network is opened, 认为是已启动)
        ok, resp = self.send_at("AT+CMQTTSTART", 15000, expect="+CMQTTSTART:")
        started_ok = False
        for line in resp:
            if "+CMQTTSTART: 0" in line or "+CMQTTSTART: 23" in line:
                started_ok = True
                break
        if not started_ok:
            self.log(f"[4G] CMQTTSTART fail: {resp}")
            return False
        self._mqtt_started = True

        # 申请 client (TCP, 非 SSL)
        ok, resp = self.send_at(
            f'AT+CMQTTACCQ={self.CLIENT_IDX},"{self.mqtt_client_id}",0',
            3000,
        )
        if not ok:
            self.log(f"[4G] CMQTTACCQ fail: {resp}")
            return False
        self._mqtt_acquired = True

        # 连接 broker: OK + URC "+CMQTTCONNECT: 0,0"
        auth = ""
        if self.mqtt_username:
            auth = f',"{self.mqtt_username}","{self.mqtt_password}"'
        cmd = (
            f'AT+CMQTTCONNECT={self.CLIENT_IDX},'
            f'"tcp://{self.mqtt_broker}:{self.mqtt_port}",60,1{auth}'
        )
        ok, resp = self.send_at(cmd, 20000, expect="+CMQTTCONNECT:")
        connected_ok = False
        for line in resp:
            if f"+CMQTTCONNECT: {self.CLIENT_IDX},0" in line:
                connected_ok = True
                break
        if not connected_ok:
            self.log(f"[4G] CMQTTCONNECT fail: {resp}")
            return False
        self._mqtt_connected = True
        self.log(f"[4G] MQTT connected: {self.mqtt_broker}:{self.mqtt_port}")
        return True

    # ── 发布 ───────────────────────────────────────────────────

    def publish(self, topic, message):
        """交互式发布: TOPIC → PAYLOAD → PUB"""
        if not self._mqtt_connected or not topic:
            return False

        topic_bytes = topic.encode()
        msg_bytes = message.encode() if isinstance(message, str) else message

        # topic
        self._drain_rx()
        self.uart.write(
            f"AT+CMQTTTOPIC={self.CLIENT_IDX},{len(topic_bytes)}\r\n".encode()
        )
        ok, _ = self._wait_for(">", 3000)
        if not ok:
            self.log("[4G] CMQTTTOPIC no prompt")
            return False
        self.uart.write(topic_bytes)
        ok, _ = self._wait_for("OK", 3000)
        if not ok:
            self.log("[4G] CMQTTTOPIC no OK")
            return False

        # payload
        self._drain_rx()
        self.uart.write(
            f"AT+CMQTTPAYLOAD={self.CLIENT_IDX},{len(msg_bytes)}\r\n".encode()
        )
        ok, _ = self._wait_for(">", 3000)
        if not ok:
            self.log("[4G] CMQTTPAYLOAD no prompt")
            return False
        self.uart.write(msg_bytes)
        ok, _ = self._wait_for("OK", 3000)
        if not ok:
            self.log("[4G] CMQTTPAYLOAD no OK")
            return False

        # pub (qos=1, timeout 60s, 等 +CMQTTPUB: 0,0)
        ok, resp = self.send_at(
            f"AT+CMQTTPUB={self.CLIENT_IDX},1,60", 65000, expect="+CMQTTPUB:"
        )
        for line in resp:
            if f"+CMQTTPUB: {self.CLIENT_IDX},0" in line:
                return True
        self.log(f"[4G] CMQTTPUB fail: {resp}")
        return False

    def is_connected(self):
        return self._connected

    def get_network_time(self):
        return self._cached_time

    def get_signal(self):
        if not self._connected:
            return ""
        return self._get_at_value("AT+CSQ", "+CSQ:")

    # ── 生命周期 ───────────────────────────────────────────────

    def deinit(self):
        try:
            if self._mqtt_connected:
                self.send_at(f"AT+CMQTTDISC={self.CLIENT_IDX},120", 5000)
            if self._mqtt_acquired:
                self.send_at(f"AT+CMQTTREL={self.CLIENT_IDX}", 2000)
            if self._mqtt_started:
                self.send_at("AT+CMQTTSTOP", 12000)
            self.send_at("AT+CPOF", 3000)
        except Exception:
            pass
        self.power_off()
        try:
            self.uart.deinit()
        except Exception:
            pass
        try:
            self.pwr_pin.deinit()
        except Exception:
            pass

# modem_4g.py - YunDTU 4G module driver (飞思创 YunDTU AT 指令集)
# CircuitPython Ver
#
# YunDTU 工作原理:
# - 配置通过 AT 指令完成, AT+S 保存后永久生效
# - WKMOD=MQTT 时, DTU 自动管理 MQTT 连接
# - 数据模式下写串口 = 自动 publish 到配置好的 topic
# - +++ 进入 AT 模式, AT+ENTM 回到数据模式
#
# 本驱动策略:
# 1. 上电后进 AT 模式, 检查配置是否已正确
# 2. 如果配置已正确 → 直接 AT+ENTM 回数据模式 (秒级)
# 3. 如果配置不对 → 配置 + AT+S 保存重启 (首次或配置变更时)
# 4. 不使用 admin 超级命令 (MQTT 模式下会泄漏为数据)

import busio
import digitalio
import time
import pins


class Modem4G:
    """YunDTU 4G module AT command driver (飞思创 AT 指令集)"""

    def __init__(self, config, log_func=print):
        self.config = config
        self.log = log_func
        self.apn = config.get("network.4g.apn", "CMNET")
        self.mqtt_broker = config.get("network.mqtt_broker", "")
        self.mqtt_port = config.get("network.mqtt_port", 1883)
        # client_id 用设备 ID 避免冲突
        device_id = config.get("system.id", "ESP32_Gateway")
        self.mqtt_client_id = config.get("network.mqtt_client_id", device_id)
        self.mqtt_username = config.get("network.mqtt_user", "")
        self.mqtt_password = config.get("network.mqtt_pass", "")
        self.mqtt_pub_topic = config.get("network.mqtt_topic", "")
        self.mqtt_sub_topic = config.get("network.mqtt_sub_topic", "")

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
        self._in_at_mode = False
        self._cached_time = ""

    def power_on(self):
        self.pwr_pin.value = True
        time.sleep(6)  # YunDTU 上电后需要几秒启动
        self.log("[4G] power on, wait 6s")

    def power_off(self):
        self.pwr_pin.value = False
        self._connected = False
        self._in_at_mode = False
        self.log("[4G] power off")

    # ── 底层 AT 收发 ─────────────────────────────────────────────

    def _drain_rx(self):
        """清空 UART 接收缓冲区"""
        if self.uart.in_waiting:
            self.uart.read(self.uart.in_waiting)

    def send_at(self, command, timeout_ms=1000, expect="OK"):
        """发送 AT 命令并等待响应 (需在 AT 模式下)"""
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
                    if "ERROR" in response or "ERR:" in response:
                        return (False, response.strip().split("\n"))
            time.sleep(0.01)

        return (False, response.strip().split("\n") if response else [])

    # ── 模式切换 ───────────────────────────────────────────────

    def _exit_passthrough(self):
        """退出数据模式, 进入 AT 指令模式 (+++, 前后静默)"""
        self._drain_rx()
        time.sleep(1)
        self.uart.write(b"+++")
        time.sleep(1.5)
        self._drain_rx()

    def _enter_data_mode(self):
        """退出 AT 模式, 回到数据模式"""
        self.send_at("AT+ENTM", 1000)
        self._in_at_mode = False
        time.sleep(0.5)
        self.log("[4G] → data mode (AT+ENTM)")

    def ensure_at_mode(self):
        """确保模块处于 AT 指令模式"""
        ok, resp = self.send_at("AT", 1000)
        if ok:
            self._in_at_mode = True
            return True

        self._exit_passthrough()
        for i in range(3):
            ok, resp = self.send_at("AT", 2000)
            if ok:
                self._in_at_mode = True
                return True
            time.sleep(0.5)

        self.log("[4G] 模块无响应")
        return False

    # ── 配置检查 ───────────────────────────────────────────────

    def _get_at_value(self, cmd, prefix):
        """发送 AT 查询命令, 提取 +PREFIX:VALUE 中的 VALUE"""
        ok, resp = self.send_at(cmd, 1000)
        for line in resp:
            if prefix in line:
                return line.split(":")[1].strip()
        return ""

    def _check_config_matches(self):
        """检查 DTU 当前配置是否与 config.json 一致
        
        如果一致, 不需要重新配置 + AT+S 重启
        """
        ch = 1

        # 检查 WKMOD
        wkmod = self._get_at_value(f"AT+WKMOD{ch}", f"+WKMOD{ch}:")
        if wkmod != "MQTT":
            self.log(f"[4G] config mismatch: WKMOD={wkmod}, need MQTT")
            return False

        # 检查 MQTT 服务器
        if self.mqtt_broker:
            sv = self._get_at_value(f"AT+MQTTSV{ch}", f"+MQTTSV{ch}:")
            expected_sv = f"{self.mqtt_broker},{self.mqtt_port}"
            if expected_sv not in sv:
                self.log(f"[4G] config mismatch: MQTTSV={sv}")
                return False

        # 检查 pub topic
        if self.mqtt_pub_topic:
            pub = self._get_at_value(f"AT+MQTTPUB{ch}", f"+MQTTPUB{ch}:")
            if self.mqtt_pub_topic not in pub:
                self.log(f"[4G] config mismatch: PUB={pub}")
                return False

        self.log("[4G] config OK, skip reconfigure")
        return True

    # ── 连接流程 ───────────────────────────────────────────────

    def connect(self):
        """连接网络
        
        流程:
        1. 上电 → +++ 进 AT 模式
        2. 检查 SIM/信号/注网
        3. 检查 MQTT 配置是否已正确保存
           - 已正确: AT+ENTM 回数据模式, DTU 自动连 MQTT (快速)
           - 不正确: 配置 + AT+S 重启 (首次)
        4. 等待 MQTT 连接
        """
        self.power_on()

        if not self.ensure_at_mode():
            return False

        self.send_at("AT+E=OFF", 1000)

        # 查询固件版本
        ver = self._get_at_value("AT+VER", "+VER:")
        if ver:
            self.log(f"[4G] firmware: {ver}")

        # SIM 卡
        iccid = self._get_at_value("AT+ICCID", "+ICCID:")
        if not iccid or "not inserted" in iccid.lower():
            self.log("[4G] SIM 卡未插入!")
            return False
        self.log(f"[4G] ICCID: {iccid}")

        # APN
        self.send_at(f"AT+APN={self.apn.upper()},,,0", 1000)

        # 信号
        csq = self._get_at_value("AT+CSQ", "+CSQ:")
        self.log(f"[4G] CSQ: {csq}")

        # 网络注册
        for i in range(30):
            creg = self._get_at_value("AT+CREG", "+CREG:")
            if creg == "1":
                self._connected = True
                self.log("[4G] 网络已注册")
                break
            if i % 5 == 0:
                self.log(f"[4G] 等待注册... {i}/30")
            time.sleep(1)

        if not self._connected:
            self.log("[4G] 网络注册失败")
            return False

        # ── 检查是否需要重新配置 ──
        if self._check_config_matches():
            # 在 AT 模式下缓存网络时间 (避免数据模式下再 +++ 泄漏)
            self._cached_time = self._get_at_value("AT+CCLK", "+CCLK:").strip('"')
            if self._cached_time:
                self.log(f"[4G] time: {self._cached_time}")

            # 配置已正确, 直接回数据模式, DTU 自动连 MQTT
            self._enter_data_mode()
            self.log("[4G] waiting MQTT connect (config saved)...")
            time.sleep(5)
        else:
            # 首次配置或配置变更
            if self.mqtt_broker:
                self._configure_mqtt()

            self.log("[4G] AT+S saving & restarting...")
            self.send_at("AT+S", 5000)
            self._in_at_mode = False

            # 等待 DTU 重启 + 注网 + MQTT 连接
            self.log("[4G] waiting for DTU restart + MQTT connect...")
            time.sleep(15)

        self.log("[4G] ready to publish")
        return True

    def _configure_mqtt(self):
        """配置 YunDTU 的 MQTT 参数 (通道 1)"""
        ch = 1

        self.send_at(f"AT+WKMOD{ch}=MQTT", 1000)
        self.log(f"[4G] CH{ch} → MQTT")

        ok, _ = self.send_at(
            f"AT+MQTTSV{ch}={self.mqtt_broker},{self.mqtt_port}", 1000
        )
        self.log(f"[4G] server: {self.mqtt_broker}:{self.mqtt_port} → {'OK' if ok else 'FAIL'}")

        ok, _ = self.send_at(
            f"AT+MQTTCONN{ch}={self.mqtt_client_id},{self.mqtt_username},"
            f"{self.mqtt_password},60,1", 1000
        )
        self.log(f"[4G] conn params → {'OK' if ok else 'FAIL'}")

        if self.mqtt_pub_topic:
            ok, _ = self.send_at(
                f"AT+MQTTPUB{ch}={self.mqtt_pub_topic},0,0", 1000
            )
            self.log(f"[4G] pub: {self.mqtt_pub_topic} → {'OK' if ok else 'FAIL'}")

        if self.mqtt_sub_topic:
            ok, _ = self.send_at(
                f"AT+MQTTSUB{ch}={self.mqtt_sub_topic},0", 1000
            )
            self.log(f"[4G] sub: {self.mqtt_sub_topic} → {'OK' if ok else 'FAIL'}")

    # ── 数据发送 ───────────────────────────────────────────────

    def publish(self, topic, message):
        """发送数据 — 直接写串口, DTU 自动 publish"""
        if not self._connected:
            return False

        self.uart.write(message.encode())
        time.sleep(0.3)
        return True

    def is_connected(self):
        return self._connected

    # ── 查询 (返回 connect 时缓存的值, 不做 +++ 避免泄漏) ────

    def get_network_time(self):
        """返回 connect() 时缓存的网络时间"""
        return self._cached_time

    def get_signal(self):
        """信号查询 — 数据模式下不可用, 返回空"""
        return ""

    # ── 生命周期 ───────────────────────────────────────────────

    def deinit(self):
        """释放资源, 不修改 DTU 配置"""
        self.power_off()
        self.uart.deinit()
        self.pwr_pin.deinit()

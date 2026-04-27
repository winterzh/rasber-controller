# device_reporter.py - 设备状态上报
# 在每次数据上传时，通过 MQTT 发送设备状态报告
#
# 由 code.py 在 do_network_upload 成功后调用

import gc
import json
import time


def build_report(config) -> dict:
    """构建设备状态报告 JSON"""
    import microcontroller
    import os

    # ---- device ----
    device = {
        "id": config.get("system.id", ""),
        "fw": config.get("system.firmware_version", ""),
        "reset_reason": _get_reset_reason(),
    }

    # boot_count: NVM 持久化
    try:
        boot_count = microcontroller.nvm[0] | (microcontroller.nvm[1] << 8)
        device["boot_count"] = boot_count
    except:
        device["boot_count"] = -1

    # ---- hardware ----
    gc.collect()
    hw = {
        "mem_free": gc.mem_free(),
    }
    try:
        hw["cpu_temp"] = round(microcontroller.cpu.temperature, 1)
    except:
        hw["cpu_temp"] = None
    try:
        st = os.statvfs("/")
        hw["flash_free"] = st[0] * st[3]  # f_bsize * f_bavail
    except:
        hw["flash_free"] = None

    # ---- network ----
    net = _get_network_info(config)

    # ---- channels ----
    channels = []
    for ch_key in ["rs485_1", "rs485_2"]:
        ch_cfg = config.get_section(ch_key) if hasattr(config, 'get_section') else {}
        if not ch_cfg:
            continue
        ch_num = int(ch_key[-1])
        sensors = ch_cfg.get("sensors", [])
        channels.append({
            "ch": ch_num,
            "enabled": ch_cfg.get("enabled", False),
            "protocol": ch_cfg.get("protocol", ""),
            "sensor_count": len(sensors),
        })

    # ---- config ----
    cfg = {
        "interval_preset": config.get("system.interval_preset", 0),
        "interval_custom_min": config.get("system.interval_custom_min", 60),
        "sleep_mode": config.get("system.sleep_mode", "light"),
        "sleep_between_polls": config.get("system.sleep_between_polls", True),
        "rs485_ext": config.get("system.rs485_ext", False),
        "merge_segments": config.get("system.merge_segments", False),
        "log_level": config.get("system.log_level", "INFO"),
        "net_priority": config.get("network.priority", []),
        "4g_enabled": config.get("network.4g.enabled", False),
        "wifi_enabled": config.get("network.wifi.enabled", False),
        "eth_enabled": config.get("network.ethernet.enabled", False),
        "apn": config.get("network.4g.apn", ""),
        "psm_time_min": config.get("network.4g.psm_time_min", 0),
        "ble_enabled": config.get("ble.enabled", False),
        "usb_rw": config.get("system.usb_rw", False),
        "ota_url": config.get("system.ota_url", ""),
        "local_storage": config.get("local_storage.enabled", False),
        "storage_period": config.get("local_storage.period", ""),
    }

    # ---- diagnostics ----
    diag = {
        "last_error": None,
        "error_count": 0,
        "cached_readings": 0,
    }
    # 尝试读取本地存储缓存数
    try:
        from lib.local_storage import LocalStorage
        st = LocalStorage(config)
        diag["cached_readings"] = st.count_readings() if hasattr(st, 'count_readings') else 0
    except:
        pass

    return {
        "type": "boot_report",
        "device": device,
        "hardware": hw,
        "network": net,
        "channels": channels,
        "config": cfg,
        "diagnostics": diag,
        "ts": int(time.time()),
    }


# ---- controller-manager 硬编码 MQTT (不受 config.json 变更影响) ----
_REPORT_BROKER = "47.95.250.46"
_REPORT_PORT = 1883
_REPORT_USER = "rasberdevice"
_REPORT_PASS = "***"
_REPORT_TOPIC = "controller-manager"


def send_report_via_modem(config, modem):
    """通过 4G modem 发送报告

    报告数据和传感器数据走同一个 pub topic (config.network.mqtt_topic)
    两种 modem 驱动的 publish() 对外行为一致:
      - YunDTU 透传: 忽略 topic 参数, 直接写串口
      - SIMCom 原生 AT: 走 CMQTTTOPIC → CMQTTPAYLOAD → CMQTTPUB
    """
    try:
        report = build_report(config)
        payload = json.dumps(report)
        topic = config.get("network.mqtt_topic", "")
        if modem.publish(topic, payload):
            print(f"[Report] sent {len(payload)} bytes via 4G")
            return True
        print("[Report] 4G publish failed")
        return False
    except Exception as e:
        print(f"[Report] 4G error: {e}")
        return False


def send_report_via_wifi(config):
    """通过 WiFi 发送报告 (独立 MQTT 连接到硬编码 broker)

    WiFi 射频需已连接 AP，此函数仅建立独立的 MQTT client
    """
    try:
        import wifi
        if not wifi.radio.connected:
            print("[Report] WiFi not connected")
            return False

        report = build_report(config)
        payload = json.dumps(report)

        import socketpool
        pool = socketpool.SocketPool(wifi.radio)

        try:
            import adafruit_minimqtt
            mqtt_class = getattr(adafruit_minimqtt, 'MQTT', None)
            if mqtt_class is None:
                from adafruit_minimqtt.adafruit_minimqtt import MQTT as mqtt_class
        except ImportError as e:
            print(f"[Report] no minimqtt: {e}")
            return False

        client = mqtt_class(
            broker=_REPORT_BROKER,
            port=_REPORT_PORT,
            socket_pool=pool,
            username=_REPORT_USER,
            password=_REPORT_PASS,
        )
        client.connect()
        client.publish(_REPORT_TOPIC, payload)
        print(f"[Report] sent {len(payload)} bytes via WiFi")
        client.disconnect()
        return True
    except Exception as e:
        print(f"[Report] WiFi error: {e}")
        return False


def _get_reset_reason():
    """获取重启原因"""
    try:
        import microcontroller
        reason = microcontroller.cpu.reset_reason
        # CircuitPython ResetReason enum
        reason_map = {
            0: "POWER_ON",
            1: "BROWNOUT",
            2: "SOFTWARE",
            3: "DEEP_SLEEP_ALARM",
            4: "RESET_PIN",
            5: "WATCHDOG",
        }
        return reason_map.get(int(reason), str(reason))
    except:
        return "UNKNOWN"


def _get_network_info(config):
    """获取当前网络状态"""
    info = {
        "type": None,
        "ip": None,
        "rssi": None,
        "csq": None,
        "mac": None,
    }

    # WiFi
    try:
        import wifi
        if wifi.radio.connected:
            info["type"] = "wifi"
            info["ip"] = str(wifi.radio.ipv4_address) if wifi.radio.ipv4_address else None
            try:
                info["rssi"] = wifi.radio.ap_info.rssi
            except:
                pass
            try:
                mac = wifi.radio.mac_address
                info["mac"] = ":".join(f"{b:02X}" for b in mac)
            except:
                pass
            return info
    except:
        pass

    # 4G — 无直接 IP 可读，标记 type
    if config.get("network.4g.enabled", False):
        info["type"] = "4g"

    return info

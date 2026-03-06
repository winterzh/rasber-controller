# code.py - 柔性测斜仪控制器主程序
# CircuitPython 同步版本 (不使用 asyncio)

import time
import gc
import usb_cdc
import board
import microcontroller
import supervisor

# 禁用 auto-reload，防止 macOS 写入元数据文件触发重启
supervisor.runtime.autoreload = False

# ============================================================
# Log function
# ============================================================

def log(msg: str):
    """Output to serial and Data CDC"""
    print(msg)
    if usb_cdc.data:
        try:
            usb_cdc.data.write((msg + "\r\n").encode())
        except:
            pass

# 等待 USB 稳定
time.sleep(0.5)
log("=== CircuitPython 启动中 ===")

# ============================================================
# importmod
# ============================================================

try:
    from app.config_mgr import ConfigManager
    log("[BOOT] ConfigManager OK")
    from app.data_formatter import DataFormatter
    log("[BOOT] DataFormatter OK")
    from app.upload_counter import UploadCounter
    log("[BOOT] UploadCounter OK")
    
    from drivers.led import LEDDriver
    log("[BOOT] LEDDriver OK")
    from drivers.voltage import VoltageMonitor
    log("[BOOT] VoltageMonitor OK")
    
    from lib.private_v2026 import PrivateProtocolV2026
    log("[BOOT] PrivateProtocolV2026 OK")
    
    log("[启动] 模块加载完成")
except Exception as e:
    log(f"[启动错误] {e}")
    while True:
        time.sleep(1)

# ============================================================
# Verinfo
# ============================================================

FIRMWARE_VERSION = "2026.02.09-sync"  # fallback, 实际从 config.json 读取

# ============================================================
# Helper functions
# ============================================================

def file_exists(path):
    import os
    try:
        os.stat(path)
        return True
    except OSError:
        return False

def get_interval_seconds(preset):
    """getInterval (s)
    
    preset=0: notSleepnotread数, 只waiting
    """
    preset_map = {
        0: 0,  # notSleepnotread数
        1: 5 * 60, 2: 10 * 60, 3: 15 * 60, 4: 30 * 60, 5: 60 * 60,
        6: 120 * 60, 7: 240 * 60, 8: 720 * 60, 9: 1440 * 60, 99: None
    }
    return preset_map.get(preset, 60 * 60)

# 时间同步
_last_send_day = -1  # 上次发送的日期 (yday)，内存中记录

def _parse_gsm_time(time_str):
    """解析 GSM 时间 'YY/MM/DD,HH:MM:SS+TZ' → struct_time"""
    try:
        time_str = time_str.strip('"')
        # 用 rsplit 从右侧分割，避免日期中的 '-' 被错误分割
        if '+' in time_str:
            dt_part, _ = time_str.rsplit('+', 1)
        elif time_str.count('-') > 0:
            # 负时区: '26/02/10,08:30:00-32' 或 '2026-02-10,08:30:00-32'
            # rsplit('-', 1) 从最右边的 '-' 分割
            dt_part, _ = time_str.rsplit('-', 1)
        else:
            dt_part = time_str
        date_part, time_part = dt_part.split(',')
        yy, mm, dd = map(int, date_part.split('/'))
        year = 2000 + yy if yy < 100 else yy
        hh, mi, ss = map(int, time_part.split(':'))
        return time.struct_time((year, mm, dd, hh, mi, ss, 0, -1, -1))
    except:
        return None

def _set_rtc_time(t):
    """设置 RTC 时间"""
    import rtc
    rtc.RTC().datetime = t
    now = time.localtime()
    log(f"[时间] 已同步: {now.tm_year}/{now.tm_mon:02d}/{now.tm_mday:02d} {now.tm_hour:02d}:{now.tm_min:02d}:{now.tm_sec:02d}")

def try_time_sync(config, force=False):
    """发送数据前对时，优先级: 4G模块时间 > WiFi NTP > ETH NTP
    触发条件: 年份 < 2026 或 当前日期 != 上次发送日期
    只尝试已启用的方式
    """
    global _last_send_day
    now = time.localtime()
    
    needs_sync = force
    if now.tm_year < 2026:
        log(f"[时间] 年份 {now.tm_year} < 2026，需要对时")
        needs_sync = True
    elif _last_send_day >= 0 and now.tm_yday != _last_send_day:
        log(f"[时间] 日期变更 (上次:{_last_send_day} 今天:{now.tm_yday})，需要对时")
        needs_sync = True
    
    if not needs_sync:
        return False
    
    # 1. 4G 模块时间
    if config.get("network.4g.enabled", False):
        try:
            from drivers.modem_4g import Modem4G
            modem = Modem4G(config)
            if modem.connect():
                gsm_time = modem.get_network_time()
                if gsm_time:
                    parsed = _parse_gsm_time(gsm_time)
                    if parsed and parsed.tm_year >= 2026:
                        _set_rtc_time(parsed)
                        log("[时间] 4G 模块对时成功")
                        return True
                    else:
                        log(f"[时间] 4G 模块时间无效 (year={parsed.tm_year if parsed else '?'})，尝试 NTP")
                # 4G 模块时间无效，尝试通过 4G 网络 NTP
                # (4G 已连接但时间不对，不单独做 NTP，继续尝试 WiFi)
        except Exception as e:
            log(f"[时间] 4G 对时失败: {e}")
    
    # 2. WiFi NTP
    if config.get("network.wifi.enabled", False):
        try:
            import wifi
            import socketpool
            import adafruit_ntp
            
            ssid = config.get("network.wifi.ssid", "")
            pwd = config.get("network.wifi.password", "")
            if ssid:
                if not wifi.radio.connected:
                    wifi.radio.connect(ssid, pwd)
                pool = socketpool.SocketPool(wifi.radio)
                ntp = adafruit_ntp.NTP(pool, server="ntp.aliyun.com", tz_offset=8)
                _set_rtc_time(ntp.datetime)
                log("[时间] WiFi NTP 对时成功")
                return True
        except Exception as e:
            log(f"[时间] WiFi NTP 失败: {e}")
    
    # 3. 有线网络 NTP (仅 N16R2)
    if config.get("network.ethernet.enabled", False) and not pins.IS_OCTAL_PSRAM:
        try:
            from drivers.ethernet import EthernetDriver
            import adafruit_ntp
            import adafruit_wiznet5k.adafruit_wiznet5k_socket as socket
            
            eth = EthernetDriver(config)
            if eth.connect() and eth._eth:
                # Wiznet5k 需要用自己的 socket 模块
                socket.set_interface(eth._eth)
                ntp = adafruit_ntp.NTP(socket, server="ntp.aliyun.com", tz_offset=8)
                _set_rtc_time(ntp.datetime)
                log("[时间] ETH NTP 对时成功")
                return True
        except Exception as e:
            log(f"[时间] ETH NTP 失败: {e}")
    
    log("[时间] 所有对时方式失败，使用内部时钟")
    return False

def update_last_send_day():
    """记录当前日期为上次发送日期"""
    global _last_send_day
    _last_send_day = time.localtime().tm_yday

def do_address_scan(rs485_drivers: dict, rs485_protocols: dict, config=None):
    """ScanallCH的sensoraddr (AutoID 0-1023)
    
    per inclinometer_client:
    - timeout: 300ms
    - Scaninterval: 200ms
    
    Scan结果会save到 config.json
    """
    log("[Scan] scanning AutoID 0-1023...")
    
    # byCH分group
    found_by_channel = {}
    
    for ch, driver in rs485_drivers.items():
        protocol = rs485_protocols[ch]
        log(f"[Scan] CH {ch}...")
        
        found_by_channel[ch] = []
        
        # pwr on
        driver.power_on()
        time.sleep(0.3)
        
        ch_found = 0
        for auto_id in range(1024):
            # 300ms timeout，per参考client
            result = protocol.scan_address(auto_id, timeout_ms=300)
            if result:
                fixed_addr = result["fixed_addr"]
                log(f"  [CH{ch}] AutoID {auto_id} -> addr {fixed_addr}")
                found_by_channel[ch].append({"addr": fixed_addr})
                ch_found += 1
            
            # 每 100 输out进度
            if (auto_id + 1) % 100 == 0:
                log(f"  [CH{ch}] 进度 {auto_id + 1}/1024, donefound {ch_found} ")
            
            # 200ms Scaninterval
            time.sleep(0.2)
        
        log(f"[Scan] CH {ch} done，found {ch_found} ")
        driver.power_off()
    
    # save到 config
    total_found = 0
    if config:
        for ch, sensors in found_by_channel.items():
            if sensors:
                config.set(f"rs485_{ch}.sensors", sensors)
                total_found += len(sensors)
        if total_found > 0:
            config.save()
            log(f"[Scan] saved {total_found}  sensors to config.json")
    
    # 输out结果
    log(f"[Scan] done! totalfound {total_found}  sensors")
    
    # 输out JSON 结果到 CDC
    if usb_cdc.data and total_found > 0:
        import json
        # 扁平化输out
        all_devices = []
        for ch, sensors in found_by_channel.items():
            for s in sensors:
                all_devices.append({"channel": ch, "addr": s["addr"]})
        result_json = json.dumps({
            "type": "scan_result",
            "count": total_found,
            "devices": all_devices
        })
        usb_cdc.data.write((result_json + "\r\n").encode())

def do_batch_write_addr(rs485_drivers: dict, rs485_protocols: dict, max_addr: int, config=None, timeout_ms: int = 300):
    """批量wroteaddr (from max_addr start，每ok一addr -1)
    
    流程:
    1. 遍历 AutoID 0-1023
    2. hasrsp的设备wrote当beforeaddr
    3. wroteokafteraddr -1
    
    wrote结果会save到 config.json
    """
    log(f"[WriteAddr] batch write, max_addr: {max_addr}, timeout: {timeout_ms}ms")
    
    # byCH分group
    success_by_channel = {}
    current_addr = max_addr
    
    for ch, driver in rs485_drivers.items():
        protocol = rs485_protocols[ch]
        log(f"[WriteAddr] CH {ch}...")
        
        success_by_channel[ch] = []
        
        # pwr on
        driver.power_on()
        time.sleep(0.3)
        
        for auto_id in range(1024):
            # trywroteaddr
            if protocol.write_address_by_autoid(auto_id, current_addr, timeout_ms=timeout_ms):
                log(f"  [CH{ch}] AutoID {auto_id} -> wroteaddr {current_addr} ok")
                success_by_channel[ch].append({"addr": current_addr})
                current_addr -= 1  # addr -1
            
            # 每 100 输out进度
            if (auto_id + 1) % 100 == 0:
                total_written = sum(len(s) for s in success_by_channel.values())
                log(f"  [CH{ch}] 进度 {auto_id + 1}/1024, donewrote {total_written} ")
            
            # 200ms interval
            time.sleep(0.2)
        
        log(f"[WriteAddr] CH {ch} done，wrote {len(success_by_channel[ch])} ")
        driver.power_off()
    
    # save到 config
    total_written = 0
    if config:
        for ch, sensors in success_by_channel.items():
            if sensors:
                config.set(f"rs485_{ch}.sensors", sensors)
                total_written += len(sensors)
        if total_written > 0:
            config.save()
            log(f"[WriteAddr] saved {total_written}  sensors to config.json")
    
    # 输out结果
    log(f"[WriteAddr] done! totalwrote {total_written}  sensors")
    
    # 输out JSON 结果到 CDC
    if usb_cdc.data and total_written > 0:
        import json
        # 扁平化输out
        all_devices = []
        for ch, sensors in success_by_channel.items():
            for s in sensors:
                all_devices.append({"channel": ch, "addr": s["addr"]})
        result_json = json.dumps({
            "type": "write_addr_result",
            "count": total_written,
            "devices": all_devices
        })
        usb_cdc.data.write((result_json + "\r\n").encode())

def do_read_sensors(ch: int, driver, protocol, sensors: list, timeout_ms: int = 5000, 
                    interval_ms: int = 150, reverse: bool = True,
                    progress_callback=None) -> list:
    """统一的传感器数据读取函数
    
    供 BLE 和 CDC 命令共用，保证一致的行为。
    日志格式与主循环完全一致。
    
    Args:
        ch: 通道号
        driver: RS485 驱动
        protocol: 协议对象
        sensors: 传感器配置列表 [{"addr": xxx, "model": xxx}, ...]
        timeout_ms: 单个传感器超时时间 (默认 5000ms，参考 inclinometer_client)
        interval_ms: 传感器间读取间隔 (默认 150ms)
        reverse: 是否倒序读取 (从顶部开始，默认 True)
        progress_callback: 进度回调 fn(index, total, addr, data_or_none)
        
    Returns:
        读取结果列表 [{"addr", "a", "b", "z", "status", ...}, ...]
    """
    all_data = []
    
    log(f"[CH{ch}] reading {len(sensors)}  sensors...")
    
    # 电源开启
    driver.power_on()
    time.sleep(0.3)
    
    # 按顺序读取
    sensor_list = list(reversed(sensors)) if reverse else sensors
    success_count = 0
    fail_count = 0
    
    for i, sensor_cfg in enumerate(sensor_list):
        addr = sensor_cfg.get("addr", 0)
        model = sensor_cfg.get("model", 0)
        
        try:
            log(f"  [CH{ch}] readaddr {addr}...")
            data = protocol.read_data(addr, timeout_ms=timeout_ms)
            if data:
                data["channel"] = ch
                data["model"] = model
                all_data.append(data)
                success_count += 1
                log(f"  [CH{ch}] addr {addr}: A={data.get('a', 0):.2f}, B={data.get('b', 0):.2f}")
            else:
                fail_count += 1
                # 失败的传感器，status 标记为 W
                all_data.append({
                    "addr": addr,
                    "address": addr,
                    "channel": ch,
                    "model": model,
                    "a": 0, "b": 0, "z": 0,
                    "status": "W"
                })
                log(f"  [CH{ch}] addr {addr}: no resp")
        except Exception as e:
            fail_count += 1
            all_data.append({
                "addr": addr,
                "address": addr,
                "channel": ch,
                "model": model,
                "a": 0, "b": 0, "z": 0,
                "status": "W"
            })
            log(f"  [CH{ch}] addr {addr} Err: {e}")
        
        # 进度回调
        if progress_callback:
            progress_callback(i, len(sensors), addr, all_data[-1] if all_data else None)
        
        # 间隔延时
        time.sleep(interval_ms / 1000.0)
    
    # 电源关闭
    driver.power_off()
    log(f"[CH{ch}] done: ok {success_count}, fail {fail_count}")
    
    return all_data

def do_scan_channel(ch: int, driver, protocol, timeout_ms: int = 300, 
                    interval_ms: int = 200, progress_callback=None) -> list:
    """统一的单通道地址扫描函数
    
    供 BLE 和 CDC 命令共用。日志格式与 do_address_scan() 一致。
    
    Args:
        ch: 通道号
        driver: RS485 驱动
        protocol: 协议对象
        timeout_ms: 单个 AutoID 超时时间 (默认 300ms)
        interval_ms: AutoID 间扫描间隔 (默认 200ms)
        progress_callback: 进度回调 fn(auto_id, found_list)
        
    Returns:
        扫描到的传感器列表 [{"addr": xxx}, ...]
    """
    found = []
    
    log(f"[Scan] CH {ch}...")
    driver.power_on()
    time.sleep(0.3)
    
    for auto_id in range(1024):
        result = protocol.scan_address(auto_id, timeout_ms=timeout_ms)
        if result:
            addr = result["fixed_addr"]
            found.append({"addr": addr})
            log(f"  [CH{ch}] AutoID {auto_id} -> addr {addr}")
        
        # 进度回调
        if progress_callback:
            progress_callback(auto_id, found)
        
        # 每 100 个输出进度
        if (auto_id + 1) % 100 == 0:
            log(f"  [CH{ch}] 进度 {auto_id + 1}/1024, donefound {len(found)} ")
        
        time.sleep(interval_ms / 1000.0)
    
    driver.power_off()
    log(f"[Scan] CH {ch} done，found {len(found)} ")
    
    return found

def do_network_upload(config, segments: list):
    """通过netUploaddata (4G > WiFi > Ethernet)
    
    by优先级trysend，ok则return.
    Returns: 4G modem instance if used (for PSM), else None
    """
    if not segments:
        return None
    
    topic = config.get("network.mqtt_topic", "controllerdata-cirpy")
    
    # try 4G
    if config.get("network.4g.enabled", False):
        try:
            from drivers.modem_4g import Modem4G
            modem = Modem4G(config)
            if modem.connect():
                log("[Upload] uses 4G...")
                success = True
                for seg in segments:
                    if not modem.publish(topic, seg):
                        success = False
                        break
                if success:
                    log(f"[Upload] 4G sent {len(segments)} seg")
                    return modem  # 返回 modem 实例，供 PSM 使用
                else:
                    log("[Upload] 4G send fail")
        except Exception as e:
            log(f"[Upload] 4G err: {e}")
    
    # try WiFi
    if config.get("network.wifi.enabled", False):
        try:
            from drivers.wifi import WiFiDriver
            wifi = WiFiDriver(config)
            log("[Upload] try WiFi...")
            if wifi.connect():
                log("[Upload] WiFi+MQTT connected!")
                success = True
                for seg in segments:
                    if not wifi.publish(topic, seg):
                        success = False
                        break
                if success:
                    log(f"[Upload] WiFi sent {len(segments)} seg")
                    return None
                else:
                    log("[Upload] WiFi send fail")
            else:
                log(f"[Upload] WiFi fail: {wifi.last_error}")
        except Exception as e:
            log(f"[Upload] WiFi err: {e}")
    
    # try Ethernet (双重保险: 板型 + config)
    if config.get("network.ethernet.enabled", False):
        if pins.IS_OCTAL_PSRAM:
            log("[Upload] N16R8 板型, ETH 引脚不可用, 跳过")
        else:
            try:
                from drivers.ethernet import EthernetDriver
                eth = EthernetDriver(config)
                if eth.connect():
                    log("[Upload] usesETH...")
                    success = True
                    for seg in segments:
                        if not eth.publish(topic, seg):
                            success = False
                            break
                    if success:
                        log(f"[Upload] ETHsent {len(segments)} seg")
                        return None
                    else:
                        log("[Upload] ETHsend fail")
            except Exception as e:
                log(f"[Upload] ETHerr: {e}")
    
    log("[Upload] noneoknet，仅通过 CDC 输out")
    return None

# 全局cmdbuffer
_cdc_buffer = ""

def check_cdc_commands():
    """check CDC ifhaspendingprocesscmd，returncmdor None"""
    global _cdc_buffer
    
    if not usb_cdc.data:
        return None
    
    waiting = usb_cdc.data.in_waiting
    if waiting == 0:
        return None
    
    try:
        chunk = usb_cdc.data.read(waiting)
        _cdc_buffer += chunk.decode()
        
        if "\n" in _cdc_buffer or "\r" in _cdc_buffer:
            lines = _cdc_buffer.replace("\r", "\n").split("\n")
            _cdc_buffer = lines[-1]  # 保留not完整的partial
            
            for line in lines[:-1]:
                cmd = line.strip().lower()
                if cmd:
                    return cmd
    except:
        pass
    
    return None

def process_commands(rs485_drivers, rs485_protocols, config=None):
    """processallpendingprocess的 CDC cmd，returnifneeds立即采集
    
    cmdfmt:
    - 操作: #scan, #write_addr, #read
    - query: #get_id, #get_interval, #get_sensors, #get_mqtt, #get_wifi, #get_4g
    - set: #set_id, #set_interval, #set_mqtt, #set_wifi, #set_4g_apn
    - onoff: #enable_4g, #disable_4g, #enable_wifi, #disable_wifi
    - SYS: #status, #help, #reboot, #version
    """
    start_requested = False
    
    while True:
        cmd = check_cdc_commands()
        if not cmd:
            break
        
        parts = cmd.split()
        cmd_name = parts[0]
        
        # ========== noneparamcmd ==========
        if cmd_name == "#status":
            gc.collect()
            free_kb = gc.mem_free() // 1024
            device_id = config.get("system.id", "notset") if config else "notset"
            interval = config.get("system.interval_preset", 0) if config else 0
            sensors_ch1 = len(config.get("rs485_1.sensors", [])) if config else 0
            sensors_ch2 = len(config.get("rs485_2.sensors", [])) if config else 0
            # netstatus
            wifi_enabled = config.get("network.wifi.enabled", False) if config else False
            g4_enabled = config.get("network.4g.enabled", False) if config else False
            eth_enabled = config.get("network.ethernet.enabled", False) if config else False
            expansion_enabled = config.get("network.expansion.enabled", False) if config else False
            # 存储status
            storage_enabled = config.get("local_storage.enabled", False) if config else False
            usb_msc = config.get("system.usb_msc_enabled", True) if config else True
            
            log("========== SYSstatus ==========")
            log(f"设备ID: {device_id}")
            log(f"Interval: {interval}")
            log(f"Mem剩余: {free_kb} KB")
            log(f"CH1sensor: {sensors_ch1} ")
            log(f"CH2sensor: {sensors_ch2} ")
            log("--- net功能 ---")
            log(f"WiFi: {'on' if wifi_enabled else 'off'}")
            log(f"4G: {'on' if g4_enabled else 'off'}")
            log(f"ETH: {'on' if eth_enabled else 'off'}")
            log(f"extended板: {'on' if expansion_enabled else 'off'}")
            log("--- 存储功能 ---")
            log(f"storage: {'on' if storage_enabled else 'off'}")
            usb_rw = config.get("system.usb_rw", False) if config else False
            log(f"USB RW(USB_RW): {'enabled-flash' if usb_rw else 'disabled-daily'}")
            log("==============================")
            continue
        
        elif cmd_name == "#version":
            log(f"[Ver] {FIRMWARE_VERSION}")
            continue
        
        elif cmd_name == "#reboot":
            log("[SYS] Rebooting...")
            time.sleep(0.5)
            import microcontroller
            microcontroller.reset()
        
        elif cmd_name == "#enable_usb_rw":
            # onUSB RW模式（flash mode，downtimes启动生效）
            import microcontroller
            microcontroller.nvm[0] = 0  # not17表示flash mode
            log(f"[USB] USB RW enabled (nvm[0]={microcontroller.nvm[0]}), reboot for flash mode")
            continue
        
        elif cmd_name == "#disable_usb_rw":
            # offUSB RW模式（daily mode，downtimes启动生效）
            import microcontroller
            microcontroller.nvm[0] = 17  # 17表示daily mode
            log(f"[USB] USB RW disabled (nvm[0]={microcontroller.nvm[0]}), reboot for daily mode")
            continue
        
        elif cmd_name == "#usb_rw_status":
            # 查看当beforeset
            import microcontroller
            nvm_val = microcontroller.nvm[0]
            enabled = (nvm_val != 17)
            log(f"[USB] USB RW: {'enabled-flash' if enabled else 'disabled-daily'} (nvm[0]={nvm_val})")
            continue
        
        elif cmd_name == "#help":
            log("========== CDC cmdhelp ==========")
            log("--- 操作cmd ---")
            log("#scan [com_port]        - Scansensoraddr")
            log("#write_addr [com_port] addr [timeoutms] - 批量wroteaddr")
            log("#read [com_port]        - 立即采集并Upload")
            log("#read_temp_and_model [com_port] - readtempandmodel")
            log("--- querycmd ---")
            log("#get_id                 - get设备ID")
            log("#get_interval           - getInterval")
            log("#get_sensors [com_port] - getsensorlist")
            log("#get_mqtt               - getMQTTCfg")
            log("#get_wifi               - getWiFiCfg")
            log("#get_4g                 - get4GCfg")
            log("#get_sleep              - getSleep")
            log("--- setcmd (autosave) ---")
            log("#set_id 2026750001      - set设备ID")
            log("#set_interval 5         - setInterval(0=Standby)")
            log("#set_mqtt IP port topic  - setMQTT")
            log("#set_wifi SSID password     - setWiFi")
            log("#set_4g_apn cmnet       - set4G APN")
            log("#set_4g_cops 0          - set运营商(0=auto)")
            log("#set_sleep light|deep   - setSleep")
            log("#write_model [com_port] model - 批量writemodel")
            log("#enable_4g / #disable_4g")
            log("#enable_wifi / #disable_wifi")
            log("#enable_eth / #disable_eth")
            log("#enable_expansion / #disable_expansion")
            log("#enable_storage / #disable_storage - storageonoff")
            log("--- SYScmd ---")
            log("#status                 - 查看status(含net/存储)")
            log("#version                - 固件Ver")
            log("#reboot                 - 重启设备")
            log("#enable_usb_rw          - 电脑可readwrite(flash mode,重启生效)")
            log("#disable_usb_rw         - 设备可readwrite(daily mode,重启生效)")
            log("#usb_rw_status          - 查看USBreadwrite模式")
            log("==================================")
            continue
        
        # ========== querycmd ==========
        elif cmd_name == "#get_id":
            device_id = config.get("system.id", "notset") if config else "notset"
            log(f"[ID] {device_id}")
            continue
        
        elif cmd_name == "#get_interval":
            interval = config.get("system.interval_preset", 0) if config else 0
            preset_names = {0: "Standby", 1: "5分", 2: "10分", 3: "15分", 4: "30分", 
                          5: "1时", 6: "2时", 7: "4时", 8: "12时", 9: "24时", 99: "custom"}
            name = preset_names.get(interval, "not知")
            log(f"[Interval] {interval} ({name})")
            continue
        
        elif cmd_name == "#get_mqtt":
            if config:
                broker = config.get("network.mqtt_broker", "")
                port = config.get("network.mqtt_port", 1883)
                topic = config.get("network.mqtt_topic", "")
                log(f"[MQTT] {broker}:{port} topic:{topic}")
            continue
        
        elif cmd_name == "#get_wifi":
            if config:
                enabled = config.get("network.wifi.enabled", False)
                ssid = config.get("network.wifi.ssid", "")
                log(f"[WiFi] {'on' if enabled else 'off'} SSID:{ssid}")
            continue
        
        elif cmd_name == "#get_4g":
            if config:
                enabled = config.get("network.4g.enabled", False)
                apn = config.get("network.4g.apn", "cmnet")
                cops = config.get("network.4g.cops", "0")
                log(f"[4G] {'on' if enabled else 'off'} APN:{apn} COPS:{cops}")
            continue
        
        elif cmd_name == "#get_sleep":
            if config:
                mode = config.get("system.sleep_mode", "deep")
                log(f"[Sleep] {mode}")
            continue
        
        # ========== onoffcmd ==========
        elif cmd_name == "#enable_4g":
            if config:
                config.set("network.4g.enabled", True)
                config.save()
                log("[4G] doneon")
            continue
        
        elif cmd_name == "#disable_4g":
            if config:
                config.set("network.4g.enabled", False)
                config.save()
                log("[4G] doneoff")
            continue
        
        elif cmd_name == "#enable_wifi":
            if config:
                config.set("network.wifi.enabled", True)
                config.save()
                log("[WiFi] doneon")
            continue
        
        elif cmd_name == "#disable_wifi":
            if config:
                config.set("network.wifi.enabled", False)
                config.save()
                log("[WiFi] doneoff")
            continue
        
        elif cmd_name == "#enable_eth":
            if config:
                config.set("network.ethernet.enabled", True)
                config.save()
                log("[ETH] doneon (W5500)")
            continue
        
        elif cmd_name == "#disable_eth":
            if config:
                config.set("network.ethernet.enabled", False)
                config.save()
                log("[ETH] doneoff")
            continue
        
        elif cmd_name == "#enable_expansion":
            if config:
                config.set("system.expansion_ports_enable", True)
                config.set("rs485_3.enabled", True)
                config.set("rs485_4.enabled", True)
                config.save()
                log("[Expansion port] doneon (SC16IS752: com3, com4)")
            continue
        
        elif cmd_name == "#disable_expansion":
            if config:
                config.set("system.expansion_ports_enable", False)
                config.set("rs485_3.enabled", False)
                config.set("rs485_4.enabled", False)
                config.save()
                log("[Expansion port] doneoff")
            continue
        
        elif cmd_name == "#enable_storage":
            if config:
                config.set("local_storage.enabled", True)
                config.save()
                log("[storage] doneon")
            continue
        
        elif cmd_name == "#disable_storage":
            if config:
                config.set("local_storage.enabled", False)
                config.save()
                log("[storage] doneoff")
            continue
        
        # ========== setcmd (needsparam) ==========
        elif cmd_name == "#set_id":
            if len(parts) < 2:
                log("[err] fmt: #set_id 2026750001")
                continue
            new_id = parts[1]
            if config:
                config.set("system.id", new_id)
                config.save()
                log(f"[ID] set to: {new_id}")
            continue
        
        elif cmd_name == "#set_interval":
            if len(parts) < 2:
                log("[err] fmt: #set_interval 5")
                continue
            try:
                interval = int(parts[1])
                if config:
                    config.set("system.interval_preset", interval)
                    config.save()
                    log(f"[Interval] set to: {interval}")
                    return "reload_config"  # 通知主循环立即重新加载间隔
            except:
                log("[err] intervalrequiredis数word")
            continue
        
        elif cmd_name == "#set_mqtt":
            if len(parts) < 4:
                log("[err] fmt: #set_mqtt IP port topic")
                continue
            try:
                broker = parts[1]
                port = int(parts[2])
                topic = parts[3]
                if config:
                    config.set("network.mqtt_broker", broker)
                    config.set("network.mqtt_port", port)
                    config.set("network.mqtt_topic", topic)
                    config.save()
                    log(f"[MQTT] set: {broker}:{port} topic:{topic}")
            except:
                log("[err] portrequiredis数word")
            continue
        
        elif cmd_name == "#set_wifi":
            if len(parts) < 3:
                log("[err] fmt: #set_wifi SSID password")
                continue
            ssid = parts[1]
            password = parts[2]
            if config:
                config.set("network.wifi.ssid", ssid)
                config.set("network.wifi.password", password)
                config.save()
                log(f"[WiFi] set: {ssid}")
            continue
        
        elif cmd_name == "#set_4g_apn":
            if len(parts) < 2:
                log("[err] fmt: #set_4g_apn cmnet")
                continue
            apn = parts[1]
            if config:
                config.set("network.4g.apn", apn)
                config.save()
                log(f"[4G APN] set: {apn}")
            continue
        
        elif cmd_name == "#set_4g_cops":
            if len(parts) < 2:
                log("[err] fmt: #set_4g_cops 0")
                log("[提示] 0=auto, 46000=move, 46001=联通, 46011=电信")
                continue
            cops = parts[1]
            if config:
                config.set("network.4g.cops", cops)
                config.save()
                log(f"[4G COPS] set: {cops}")
            continue
        
        elif cmd_name == "#set_sleep":
            if len(parts) < 2:
                log("[err] fmt: #set_sleep light|deep")
                continue
            mode = parts[1].lower()
            if mode not in ("light", "deep"):
                log("[err] 模式requiredis light or deep")
                continue
            if config:
                config.set("system.sleep_mode", mode)
                config.save()
                log(f"[Sleep] set: {mode}")
            continue
        
        elif cmd_name == "#get_sensors":
            if len(parts) < 2:
                log("[err] fmt: #get_sensors com1")
                continue
            com_str = parts[1].lower()
            if com_str in ("com1", "1"):
                sensors = config.get("rs485_1.sensors", []) if config else []
            elif com_str in ("com2", "2"):
                sensors = config.get("rs485_2.sensors", []) if config else []
            else:
                log("[err] invalid COM 口")
                continue
            log(f"[sensor] total {len(sensors)} :")
            # 每排显示5
            row = []
            for s in sensors:
                row.append(str(s.get('addr', 0)))
                if len(row) == 5:
                    log("  " + "  ".join(row))
                    row = []
            if row:  # 输out剩余的
                log("  " + "  ".join(row))
            continue
        
        # ========== needs COM param的操作cmd ==========
        if len(parts) < 2:
            log(f"[CDC] unknown cmd: {cmd}")
            log("[help] send #help 查看cmdlist")
            continue
        
        com_str = parts[1].lower()
        
        # parse com 口号 (com1 -> 1, com2 -> 2)
        if com_str in ("com1", "1"):
            target_ch = 1
        elif com_str in ("com2", "2"):
            target_ch = 2
        else:
            log(f"[CDC] invalid COM 口: {com_str}")
            continue
        
        # checkCHifexist
        if target_ch not in rs485_drivers:
            log(f"[CDC] CH {target_ch} noton")
            continue
        
        # Create单CHdict
        single_driver = {target_ch: rs485_drivers[target_ch]}
        single_protocol = {target_ch: rs485_protocols[target_ch]}
        
        if cmd_name == "#scan":
            log(f"[CDC] ScanCH {target_ch}")
            _start = time.monotonic()
            do_address_scan(single_driver, single_protocol, config)
            log(f"[done] 耗时 {time.monotonic() - _start:.1f} s")
        elif cmd_name == "#read":
            log(f"[CDC] trigger立即采集")
            start_requested = True  # letMain loop执row完整采集andup报流程
        elif cmd_name == "#write_addr":
            # parseaddrparam: #write_addr com1 2026020100 [timeoutms]
            if len(parts) < 3:
                log("[CDC] missingaddrparam")
                log("[help] fmt: #write_addr com1 addr [timeoutms]")
                continue
            try:
                max_addr = int(parts[2])
                timeout_ms = int(parts[3]) if len(parts) > 3 else 300
                log(f"[CDC] WriteAddrCH {target_ch}，maxaddr: {max_addr}, timeout: {timeout_ms}ms")
                _start = time.monotonic()
                do_batch_write_addr(single_driver, single_protocol, max_addr, config, timeout_ms=timeout_ms)
                log(f"[done] 耗时 {time.monotonic() - _start:.1f} s")
            except Exception as e:
                log(f"[CDC] paramerr: {e}")
        elif cmd_name == "#read_temp_and_model":
            # readallsensor的tempandmodel
            log(f"[CDC] readCH {target_ch} tempandmodel...")
            _start = time.monotonic()
            driver = single_driver[target_ch]
            protocol = single_protocol[target_ch]
            sensors = config.get(f"rs485_{target_ch}.sensors", []) if config else []
            
            if not sensors:
                log("[CDC] 没hasdoneCfg的sensor，请先 #scan")
                continue
            
            driver.power_on()
            import time as tm
            tm.sleep(0.3)
            
            for s in sensors:
                addr = s.get("addr", 0)
                result = protocol.read_temp(addr, timeout_ms=5000)  # PC端use5000ms
                if "error" not in result:
                    log(f"  addr {addr}: temp={result['temp']:.1f}°C model={result['model']}")
                else:
                    log(f"  addr {addr}: readfail")
                tm.sleep(0.1)  # 100msintervallike PC端
            
            driver.power_off()
            log(f"[done] 耗时 {time.monotonic() - _start:.1f} s")
        elif cmd_name == "#write_model":
            # 批量wrotemodel: #write_model com1 106
            if len(parts) < 3:
                log("[err] fmt: #write_model com1 model")
                continue
            try:
                model = int(parts[2])
            except:
                log("[err] modelrequiredis数word")
                continue
            
            log(f"[CDC] 批量wrotemodel {model} 到CH {target_ch}...")
            _start = time.monotonic()
            driver = single_driver[target_ch]
            protocol = single_protocol[target_ch]
            sensors = config.get(f"rs485_{target_ch}.sensors", []) if config else []
            
            if not sensors:
                log("[CDC] 没hasdoneCfg的sensor，请先 #scan")
                continue
            
            driver.power_on()
            import time as tm
            tm.sleep(0.3)
            
            success = 0
            fail = 0
            for s in sensors:
                addr = s.get("addr", 0)
                protocol.write_model(addr, model, timeout_ms=300)
                tm.sleep(1.0)  # PC端Wait1slet设备process
                
                # verifyread (usesA8cmd, returnpacket含model)
                verify = protocol.read_temp(addr, timeout_ms=300)
                if verify and verify.get("model") == model:
                    log(f"  addr {addr}: wrotemodel {model} ✓")
                    success += 1
                else:
                    actual = verify.get("model", "?") if verify else "?"
                    log(f"  addr {addr}: verifyfail (期望{model}, 实际{actual})")
                    fail += 1
            
            driver.power_off()
            log(f"[done] ok{success} fail{fail}, 耗时 {time.monotonic() - _start:.1f} s")
        elif cmd_name.strip():
            log(f"[CDC] unknown cmd: {cmd_name}")
    
    return start_requested

# ============================================================
# BLE cmdprocess
# ============================================================

def process_ble_command(ble, config, rs485_drivers=None, rs485_protocols=None) -> bool:
    """process BLE JSON cmd，returnifneeds立即采集"""
    if not ble or not ble._initialized or not ble._ble.connected:
        return False
    
    # read BLE data
    waiting = ble._uart.in_waiting
    if waiting > 0:
        data = ble._uart.read(waiting)
        if data:
            raw = data.decode("utf-8")
            if not hasattr(ble, '_cmd_buffer'):
                ble._cmd_buffer = ""
            ble._cmd_buffer += raw
    
    # checkifhas完整cmd
    if not hasattr(ble, '_cmd_buffer') or "\n" not in ble._cmd_buffer:
        return False
    
    lines = ble._cmd_buffer.split("\n")
    ble._cmd_buffer = lines[-1]
    
    cmd_json = None
    for line in lines[:-1]:
        line = line.strip()
        if line and line.startswith("{"):
            cmd_json = line
            break
    
    if not cmd_json:
        return False
    
    log(f"[BLE] 收到: {cmd_json[:60]}...")
    
    try:
        import json
        cmd = json.loads(cmd_json)
        cmd_type = cmd.get("cmd", "")
        
        if cmd_type == "status":
            # return设备status
            gc.collect()
            response = {
                "cmd": "status",
                "id": config.get("system.id", ""),
                "interval": config.get("system.interval_preset", 0),
                "sleep_mode": config.get("system.sleep_mode", "idle"),
                "free_mem": gc.mem_free() // 1024
            }
            ble.send(json.dumps(response) + "\n")
            log("[BLE] donesend status")
            
        elif cmd_type == "read" or cmd_type == "get_all":
            # return完整Cfg
            import microcontroller
            response = {
                "cmd": "config",
                "system": {
                    "id": config.get("system.id", ""),
                    "interval": config.get("system.interval_preset", 0),
                    "sleep_mode": config.get("system.sleep_mode", "idle"),
                    "log_level": config.get("system.log_level", "INFO"),
                    "usb_rw": microcontroller.nvm[0] != 17,  # not17表示flash mode（电脑writable）
                    "rs485_ext": config.get("system.rs485_ext", False),
                    "merge_segments": config.get("system.merge_segments", False)
                },
                "local_storage": {
                    "enabled": config.get("local_storage.enabled", False),
                    "period": config.get("local_storage.period", "month")
                },
                "network": {
                    "priority": config.get("network.priority", [])
                },
                "wifi": {
                    "enabled": config.get("network.wifi.enabled", False),
                    "ssid": config.get("network.wifi.ssid", ""),
                    "password": config.get("network.wifi.password", "")
                },
                "mqtt": {
                    "broker": config.get("network.mqtt_broker", ""),
                    "port": config.get("network.mqtt_port", 1883),
                    "topic": config.get("network.mqtt_topic", "")
                },
                "4g": {
                    "enabled": config.get("network.4g.enabled", False),
                    "apn": config.get("network.4g.apn", "cmnet"),
                    "cops": config.get("network.4g.cops", 0)
                },
                "ble": {
                    "enabled": config.get("ble.enabled", True),
                    "name": config.get("ble.name", "UniControl")
                },
                "sensors": {
                    "com1_count": len(config.get("rs485_1.sensors", [])),
                    "com2_count": len(config.get("rs485_2.sensors", []))
                }
            }
            ble.send(json.dumps(response) + "\n")
            log("[BLE] donesend完整Cfg")
            
        elif cmd_type == "get_section":
            # return指定Cfgseg
            section = cmd.get("section", "")
            if section:
                data = config.get_section(section)
                ble.send(json.dumps({
                    "type": "config_section",
                    "section": section,
                    "data": data
                }) + "\n")
                log(f"[BLE] donesendCfgseg: {section}")
            
        elif cmd_type == "set":
            # 通usesetCfgitem
            key = cmd.get("key", "")
            value = cmd.get("value")
            if key:
                config.set(key, value)
                config.save()
                ble.send(json.dumps({"cmd": "set", "ok": True, "key": key}) + "\n")
                log(f"[BLE] set: {key}")
        
        elif cmd_type == "set_id":
            # set设备ID
            value = cmd.get("value", "")
            if value:
                config.set("system.id", value)
                config.save()
                ble.send(json.dumps({"cmd": "set_id", "ok": True, "value": value}) + "\n")
                log(f"[BLE] IDset: {value}")
                
        elif cmd_type == "set_interval":
            # setInterval
            value = cmd.get("value", 0)
            config.set("system.interval_preset", int(value))
            # ifiscustominterval(99)，savecustommin数
            if int(value) == 99:
                custom_min = cmd.get("custom_min", 60)
                config.set("system.interval_custom_min", int(custom_min))
                log(f"[BLE] setcustominterval: {custom_min} min")
            save_result = config.save()
            log(f"[BLE] setinterval: {value}, save结果: {save_result}")
            ble.send(json.dumps({"cmd": "set_interval", "ok": True, "value": value}) + "\n")
            return "reload_config"  # 通知Main loopreload cfg
            
        elif cmd_type == "set_sleep":
            # setSleep
            value = cmd.get("value", "idle")
            config.set("system.sleep_mode", value)
            config.save()
            ble.send(json.dumps({"cmd": "set_sleep", "ok": True, "value": value}) + "\n")
            log(f"[BLE] Sleep: {value}")
            return "reload_config"  # 通知Main loopreload cfg
            
        elif cmd_type == "set_mqtt":
            # setMQTTCfg
            broker = cmd.get("broker", "")
            port = cmd.get("port", 1883)
            topic = cmd.get("topic", "")
            if broker:
                config.set("network.mqtt_broker", broker)
                config.set("network.mqtt_port", int(port))
                if topic:
                    config.set("network.mqtt_topic", topic)
                config.save()
                ble.send(json.dumps({"cmd": "set_mqtt", "ok": True}) + "\n")
                log(f"[BLE] MQTTset: {broker}:{port}")
                
        elif cmd_type == "set_wifi":
            # setWiFiCfg
            ssid = cmd.get("ssid", "")
            password = cmd.get("password", "")
            if ssid:
                config.set("network.wifi.ssid", ssid)
                config.set("network.wifi.password", password)
                config.save()
                ble.send(json.dumps({"cmd": "set_wifi", "ok": True}) + "\n")
                log(f"[BLE] WiFiset: {ssid}")
                
        elif cmd_type == "set_4g":
            # set4GCfg
            apn = cmd.get("apn", "cmnet")
            cops = cmd.get("cops", 0)
            config.set("network.4g.apn", apn)
            config.set("network.4g.cops", int(cops))
            config.save()
            ble.send(json.dumps({"cmd": "set_4g", "ok": True}) + "\n")
            log(f"[BLE] 4Gset: APN={apn}")
            
        elif cmd_type == "enable_wifi":
            config.set("network.wifi.enabled", True)
            config.save()
            ble.send(json.dumps({"cmd": "enable_wifi", "ok": True}) + "\n")
            
        elif cmd_type == "disable_wifi":
            config.set("network.wifi.enabled", False)
            config.save()
            ble.send(json.dumps({"cmd": "disable_wifi", "ok": True}) + "\n")
            
        elif cmd_type == "enable_4g":
            config.set("network.4g.enabled", True)
            config.save()
            ble.send(json.dumps({"cmd": "enable_4g", "ok": True}) + "\n")
            
        elif cmd_type == "disable_4g":
            config.set("network.4g.enabled", False)
            config.save()
            ble.send(json.dumps({"cmd": "disable_4g", "ok": True}) + "\n")
                
        elif cmd_type == "save":
            # saveCfg
            config.save()
            ble.send(json.dumps({"cmd": "save", "ok": True}) + "\n")
            log("[BLE] cfg saved")
            
        elif cmd_type == "get_sensors":
            # getsensoraddrlist
            com = cmd.get("com", "1")
            com_key = f"rs485_{com}.sensors"
            sensors = config.get(com_key, []) if config else []
            addrs = [s.get("addr", 0) for s in sensors]
            ble.send(json.dumps({"cmd": "get_sensors", "com": com, "addrs": addrs}) + "\n")
            log(f"[BLE] sensorlist COM{com}: {len(addrs)} ")
            
        elif cmd_type == "scan":
            # 扫描传感器地址 - 使用统一函数
            com_str = cmd.get("com", "1")
            com = int(com_str)
            if not rs485_drivers or com not in rs485_drivers:
                ble.send(json.dumps({"cmd": "scan", "error": "invalidCOM口"}) + "\n")
            else:
                log(f"[BLE] scan COM{com} (unified)")
                ble.send(json.dumps({"cmd": "scan_start", "com": com_str}) + "\n")
                
                # 定义进度回调，实时发送 BLE 数据
                def ble_scan_progress(auto_id, found_list):
                    # 如果刚发现新设备，发送结果
                    if found_list and len(found_list) > 0:
                        last_found = found_list[-1]
                        # 只在发现新设备时发送（通过检查是否是刚添加的）
                        # 这里简化处理，通过比较 auto_id 和找到数量来判断
                        pass  # 在回调外处理
                    # 每 100 个发送进度
                    if (auto_id + 1) % 100 == 0:
                        ble.send(json.dumps({"cmd": "scan_progress", "com": com_str, "progress": auto_id + 1}) + "\n")
                
                driver = rs485_drivers[com]
                protocol = rs485_protocols[com]
                
                # 手动调用扫描以便能发送实时结果
                found = []
                log(f"[Scan] CH{com} power on...")
                driver.power_on()
                time.sleep(0.3)
                
                for auto_id in range(1024):
                    result = protocol.scan_address(auto_id, timeout_ms=300)
                    if result:
                        addr = result["fixed_addr"]
                        found.append({"addr": addr})
                        ble.send(json.dumps({"cmd": "scan_result", "com": com_str, "auto_id": auto_id, "addr": addr}) + "\n")
                        log(f"[Scan] CH{com} AutoID {auto_id} -> addr {addr}")
                    
                    if (auto_id + 1) % 100 == 0:
                        ble.send(json.dumps({"cmd": "scan_progress", "com": com_str, "progress": auto_id + 1}) + "\n")
                        log(f"[Scan] CH{com} progress {auto_id + 1}/1024, found {len(found)}")
                    
                    time.sleep(0.2)
                
                driver.power_off()
                log(f"[Scan] CH{com} done, found {len(found)} sensors")
                
                # 保存结果
                if found and config:
                    config.set(f"rs485_{com}.sensors", found)
                    config.save()
                ble.send(json.dumps({"cmd": "scan_complete", "com": com_str, "count": len(found)}) + "\n")
                log(f"[BLE] scan done COM{com}: {len(found)}")
                
        elif cmd_type == "poll":
            # 读取单个传感器
            com_str = cmd.get("com", "1")
            com = int(com_str)
            addr = cmd.get("addr", 0)
            if not rs485_drivers or com not in rs485_drivers or addr == 0:
                ble.send(json.dumps({"cmd": "sensor_data", "com": com_str, "addr": addr, "ok": False}) + "\n")
            else:
                driver = rs485_drivers[com]
                protocol = rs485_protocols[com]
                driver.power_on()
                time.sleep(0.3)
                try:
                    data = protocol.read_data(addr, timeout_ms=5000)
                    if data:
                        ble.send(json.dumps({
                            "cmd": "sensor_data", "com": com_str, "addr": addr,
                            "a": round(data.get("a", 0), 2),
                            "b": round(data.get("b", 0), 2),
                            "z": round(data.get("z", 0), 2),
                            "ok": True
                        }) + "\n")
                        log(f"[BLE] poll addr {addr}: A={data.get('a', 0):.2f}")
                    else:
                        ble.send(json.dumps({"cmd": "sensor_data", "com": com_str, "addr": addr, "ok": False}) + "\n")
                        log(f"[BLE] poll addr {addr}: no resp")
                except Exception as e:
                    ble.send(json.dumps({"cmd": "sensor_data", "com": com_str, "addr": addr, "ok": False}) + "\n")
                    log(f"[BLE] poll addr {addr} err: {e}")
                driver.power_off()

        elif cmd_type == "read_data":
            # 读取传感器数据 - 使用统一函数
            com_str = cmd.get("com", "1")
            com = int(com_str)
            if not rs485_drivers or com not in rs485_drivers:
                ble.send(json.dumps({"cmd": "read_data", "error": "invalidCOM口"}) + "\n")
            else:
                sensors = config.get(f"rs485_{com}.sensors", []) if config else []
                if not sensors:
                    ble.send(json.dumps({"cmd": "read_data", "error": "nonesensorCfg"}) + "\n")
                else:
                    log(f"[BLE] read COM{com} {len(sensors)} sensors (unified)")
                    ble.send(json.dumps({"cmd": "read_start", "com": com_str, "count": len(sensors)}) + "\n")
                    
                    # 定义进度回调，实时发送 BLE 数据
                    def ble_progress(index, total, addr, data):
                        if data and data.get("status") != "W":
                            ble.send(json.dumps({
                                "cmd": "sensor_data", "com": com_str, "addr": addr,
                                "a": data.get("a", 0), "b": data.get("b", 0), "z": data.get("z", 0),
                                "ok": True
                            }) + "\n")
                        else:
                            ble.send(json.dumps({
                                "cmd": "sensor_data", "com": com_str, "addr": addr, "ok": False
                            }) + "\n")
                    
                    # 调用统一读取函数
                    driver = rs485_drivers[com]
                    protocol = rs485_protocols[com]
                    results = do_read_sensors(com, driver, protocol, sensors,
                                              timeout_ms=5000, interval_ms=150, reverse=True,
                                              progress_callback=ble_progress)
                    
                    ok_count = sum(1 for r in results if r.get("status") != "W")
                    fail_count = len(results) - ok_count
                    log(f"[BLE] read done COM{com}: ok={ok_count}, fail={fail_count}")
                    ble.send(json.dumps({"cmd": "read_complete", "com": com_str}) + "\n")
            
        elif cmd_type == "read_model":
            # readmodel (流式return，uses read_temp get model)
            com_str = cmd.get("com", "1")
            com = int(com_str)  # 转换为整数，匹配 rs485_drivers 的 key
            if not rs485_drivers or com not in rs485_drivers:
                ble.send(json.dumps({"cmd": "read_model", "error": "invalidCOM口"}) + "\n")
            else:
                sensors = config.get(f"rs485_{com}.sensors", []) if config else []
                if not sensors:
                    ble.send(json.dumps({"cmd": "read_model", "error": "nonesensorCfg"}) + "\n")
                else:
                    log(f"[BLE] readmodel COM{com} {len(sensors)} ...")
                    ble.send(json.dumps({"cmd": "read_model_start", "com": com_str, "count": len(sensors)}) + "\n")
                    driver = rs485_drivers[com]
                    protocol = rs485_protocols[com]
                    driver.power_on()
                    time.sleep(0.3)
                    for sensor in sensors:
                        addr = sensor.get("addr", 0)
                        # read_temp return {addr, temp, model}
                        data = protocol.read_temp(addr, timeout_ms=500)
                        if data and "error" not in data:
                            ble.send(json.dumps({"cmd": "model_data", "com": com_str, "addr": addr, "model": data.get("model", 0), "temp": round(data.get("temp", 0), 1), "ok": True}) + "\n")
                        else:
                            ble.send(json.dumps({"cmd": "model_data", "com": com_str, "addr": addr, "ok": False}) + "\n")
                        time.sleep(0.1)
                    driver.power_off()
                    ble.send(json.dumps({"cmd": "read_model_complete", "com": com_str}) + "\n")
                    log(f"[BLE] readmodeldone COM{com}")
                    
        elif cmd_type == "set_model":
            # 批量setmodel (C7 cmd)
            com_str = cmd.get("com", "1")
            com = int(com_str)  # 转换为整数，匹配 rs485_drivers 的 key
            model = cmd.get("model", 0)
            if not rs485_drivers or com not in rs485_drivers:
                ble.send(json.dumps({"cmd": "set_model", "error": "invalidCOM口"}) + "\n")
            else:
                sensors = config.get(f"rs485_{com}.sensors", []) if config else []
                if not sensors:
                    ble.send(json.dumps({"cmd": "set_model", "error": "nonesensorCfg"}) + "\n")
                else:
                    log(f"[BLE] setmodel COM{com} model={model} {len(sensors)} ...")
                    ble.send(json.dumps({"cmd": "set_model_start", "com": com_str, "model": model, "count": len(sensors)}) + "\n")
                    driver = rs485_drivers[com]
                    protocol = rs485_protocols[com]
                    driver.power_on()
                    time.sleep(0.3)
                    success_count = 0
                    for sensor in sensors:
                        addr = sensor.get("addr", 0)
                        import struct
                        # C7 cmd: addr(4) + model(1)
                        data = struct.pack(">I", addr) + bytes([model])
                        cmd_frame = protocol._build_frame(0xC7, data)
                        driver.send(cmd_frame)
                        time.sleep(0.15)
                        # C7 没hasrsp，sendafterWait即可
                        ble.send(json.dumps({"cmd": "set_model_result", "com": com_str, "addr": addr, "model": model}) + "\n")
                        success_count += 1
                    driver.power_off()
                    ble.send(json.dumps({"cmd": "set_model_complete", "com": com_str, "count": success_count}) + "\n")
                    log(f"[BLE] setmodeldone COM{com}: {success_count} ")
        
        elif cmd_type == "read_all_a4":
            # A4 单次读取 - 广播命令，不需要地址
            com_str = cmd.get("com", "1")
            com = int(com_str)
            if not rs485_drivers or com not in rs485_drivers:
                ble.send(json.dumps({"cmd": "a4_single_result", "ok": False, "error": "invalid COM"}) + "\n")
            else:
                driver = rs485_drivers[com]
                protocol = rs485_protocols[com]
                driver.power_on()
                time.sleep(0.3)
                result = protocol.read_all_data(timeout_ms=3000)
                driver.power_off()
                if result:
                    ble.send(json.dumps({
                        "cmd": "a4_single_result", "ok": True, "com": com_str,
                        "auto_id": result.get("auto_id", 0),
                        "addr": result.get("address", 0),
                        "a": round(result.get("a", 0), 2),
                        "b": round(result.get("b", 0), 2),
                        "z": round(result.get("z", 0), 2)
                    }) + "\n")
                    log(f"[BLE] A4 read: AutoID={result.get('auto_id',0)} fixed={result.get('address',0)}")
                else:
                    ble.send(json.dumps({"cmd": "a4_single_result", "ok": False}) + "\n")
                    log(f"[BLE] A4 read: no response")
        
        elif cmd_type == "update_addr_a6":
            # A6 一对一更新地址 (fire-and-forget) + 可选 C7/C8 型号写验证
            com_str = cmd.get("com", "1")
            com = int(com_str)
            new_addr = cmd.get("new_addr", 0)
            model = cmd.get("model", -1)  # -1 表示不修改型号
            if not rs485_drivers or com not in rs485_drivers or new_addr == 0:
                ble.send(json.dumps({"cmd": "update_addr_result", "ok": False, "error": "invalid params"}) + "\n")
            else:
                driver = rs485_drivers[com]
                protocol = rs485_protocols[com]
                driver.power_on()
                time.sleep(0.3)
                # A6: fire-and-forget
                protocol.update_address(new_addr, timeout_ms=500)
                log(f"[BLE] A6 update addr -> {new_addr}")
                
                model_ok = None
                read_model = -1
                if model >= 0:
                    # 等待设备处理地址更新
                    time.sleep(1.0)
                    # C7 写型号
                    protocol.write_model(new_addr, model, timeout_ms=500)
                    log(f"[BLE] C7 write model={model} to addr={new_addr}")
                    # 等待设备处理
                    time.sleep(1.0)
                    # C8 读回验证
                    result = protocol.read_model(new_addr, timeout_ms=500)
                    if result:
                        read_model = result.get("model", -1)
                        model_ok = (read_model == model)
                        log(f"[BLE] C8 verify: expect={model} read={read_model} {'ok' if model_ok else 'FAIL'}")
                    else:
                        model_ok = False
                        log(f"[BLE] C8 verify: no response")
                
                driver.power_off()
                resp = {"cmd": "update_addr_result", "ok": True, "new_addr": new_addr}
                if model >= 0:
                    resp["model"] = model
                    resp["model_ok"] = model_ok
                    resp["read_model"] = read_model
                ble.send(json.dumps(resp) + "\n")
        
        elif cmd_type == "scan_all_a4":
            # A2 扫描 + A3 读取 (替代 A4 遍历，A4 是广播命令不能按 AutoID 迭代)
            com_str = cmd.get("com", "1")
            com = int(com_str)
            start_id = cmd.get("start", 0)
            end_id = cmd.get("end", 960)
            if not rs485_drivers or com not in rs485_drivers:
                ble.send(json.dumps({"cmd": "a4_complete", "error": "invalid COM"}) + "\n")
            else:
                driver = rs485_drivers[com]
                protocol = rs485_protocols[com]
                driver.power_on()
                time.sleep(0.3)
                log(f"[BLE] A2+A3 scan COM{com} AutoID {start_id}-{end_id}")
                ble.send(json.dumps({"cmd": "a4_start", "com": com_str}) + "\n")
                found_count = 0
                for auto_id in range(start_id, end_id + 1):
                    # A2: 按 AutoID 扫描固定地址
                    scan_result = protocol.scan_address(auto_id, timeout_ms=300)
                    if scan_result:
                        fixed_addr = scan_result.get("fixed_addr", 0)
                        # A3: 按固定地址读取轴数据
                        data_result = protocol.read_data(fixed_addr, timeout_ms=500)
                        found_count += 1
                        resp = {
                            "cmd": "a4_result", "com": com_str,
                            "auto_id": auto_id,
                            "addr": fixed_addr,
                            "a": round(data_result.get("a", 0), 2) if data_result else 0,
                            "b": round(data_result.get("b", 0), 2) if data_result else 0,
                            "z": round(data_result.get("z", 0), 2) if data_result else 0
                        }
                        ble.send(json.dumps(resp) + "\n")
                        log(f"  A2+A3 found: AutoID={auto_id} addr={fixed_addr}")
                    # progress every 100
                    if auto_id % 100 == 0:
                        ble.send(json.dumps({
                            "cmd": "a4_progress", "current": auto_id,
                            "total": end_id - start_id + 1
                        }) + "\n")
                driver.power_off()
                ble.send(json.dumps({"cmd": "a4_complete", "com": com_str, "count": found_count}) + "\n")
                log(f"[BLE] A2+A3 scan done COM{com}: found {found_count}")
        
        elif cmd_type == "write_addr":
            # A7 一对一修改地址
            com_str = cmd.get("com", "1")
            com = int(com_str)
            old_addr = cmd.get("old_addr", 0)
            new_addr = cmd.get("new_addr", 0)
            if not rs485_drivers or com not in rs485_drivers or old_addr == 0 or new_addr == 0:
                ble.send(json.dumps({"cmd": "write_addr_result", "ok": False, "error": "invalid params"}) + "\n")
            else:
                driver = rs485_drivers[com]
                protocol = rs485_protocols[com]
                driver.power_on()
                time.sleep(0.3)
                ok = protocol.write_address(old_addr, new_addr, timeout_ms=500)
                driver.power_off()
                ble.send(json.dumps({
                    "cmd": "write_addr_result", "ok": ok,
                    "old_addr": old_addr, "new_addr": new_addr
                }) + "\n")
                log(f"[BLE] write_addr {old_addr}->{new_addr}: {'ok' if ok else 'fail'}")
        
        elif cmd_type == "write_model_single":
            # C7 一对一修改型号
            com_str = cmd.get("com", "1")
            com = int(com_str)
            addr = cmd.get("addr", 0)
            model = cmd.get("model", 0)
            if not rs485_drivers or com not in rs485_drivers or addr == 0:
                ble.send(json.dumps({"cmd": "write_model_result", "ok": False}) + "\n")
            else:
                driver = rs485_drivers[com]
                protocol = rs485_protocols[com]
                driver.power_on()
                time.sleep(0.3)
                ok = protocol.write_model(addr, model, timeout_ms=500)
                driver.power_off()
                ble.send(json.dumps({
                    "cmd": "write_model_result", "ok": ok,
                    "addr": addr, "model": model
                }) + "\n")
                log(f"[BLE] write_model addr={addr} model={model}: {'ok' if ok else 'fail'}")
        
        elif cmd_type == "set_modbus_id":
            # AB 设置 Modbus ID
            com_str = cmd.get("com", "1")
            com = int(com_str)
            addr = cmd.get("addr", 0)
            modbus_id = cmd.get("modbus_id", 0)
            if not rs485_drivers or com not in rs485_drivers or addr == 0:
                ble.send(json.dumps({"cmd": "set_modbus_result", "ok": False}) + "\n")
            else:
                driver = rs485_drivers[com]
                protocol = rs485_protocols[com]
                driver.power_on()
                time.sleep(0.3)
                ok = protocol.write_modbus_id(addr, modbus_id, timeout_ms=500)
                driver.power_off()
                ble.send(json.dumps({
                    "cmd": "set_modbus_result", "ok": ok,
                    "addr": addr, "modbus_id": modbus_id
                }) + "\n")
                log(f"[BLE] set_modbus addr={addr} id={modbus_id}: {'ok' if ok else 'fail'}")
        
        elif cmd_type == "batch_addr_write":
            # 批量地址写入 (匹配 inclinometer_client/tab_addr_write.py 逻辑)
            com_str = cmd.get("com", "1")
            com = int(com_str)
            start_autoid = cmd.get("start_autoid", 0)
            end_autoid = cmd.get("end_autoid", 960)
            max_addr = cmd.get("max_addr", 0)
            delay_ms = cmd.get("delay", 300)
            if not rs485_drivers or com not in rs485_drivers or max_addr == 0:
                ble.send(json.dumps({"cmd": "batch_complete", "error": "invalid params"}) + "\n")
            else:
                driver = rs485_drivers[com]
                protocol = rs485_protocols[com]
                driver.power_on()
                time.sleep(0.3)
                log(f"[BLE] batch write COM{com} AutoID {start_autoid}-{end_autoid} maxAddr={max_addr}")
                ble.send(json.dumps({"cmd": "batch_start", "com": com_str}) + "\n")
                current_addr = max_addr
                success_count = 0
                total = end_autoid - start_autoid + 1
                for auto_id in range(start_autoid, end_autoid + 1):
                    ok = protocol.write_address_by_autoid(auto_id, current_addr, timeout_ms=delay_ms)
                    if ok:
                        success_count += 1
                        ble.send(json.dumps({
                            "cmd": "batch_result",
                            "auto_id": auto_id,
                            "addr": current_addr,
                            "ok": True
                        }) + "\n")
                        log(f"  batch: AutoID {auto_id} -> addr {current_addr} ok")
                        current_addr -= 1
                    # progress
                    if (auto_id - start_autoid) % 50 == 0:
                        ble.send(json.dumps({
                            "cmd": "batch_progress",
                            "current": auto_id - start_autoid + 1,
                            "total": total
                        }) + "\n")
                driver.power_off()
                ble.send(json.dumps({
                    "cmd": "batch_complete", "com": com_str,
                    "success": success_count
                }) + "\n")
                log(f"[BLE] batch done COM{com}: {success_count} written")
        
        elif cmd_type == "set_storage":
            # setstorage
            enabled = cmd.get("enabled")
            period = cmd.get("period")
            if enabled is not None:
                config.set("local_storage.enabled", enabled)
            if period in ("month", "day"):
                config.set("local_storage.period", period)
            config.save()
            ble.send(json.dumps({
                "cmd": "set_storage",
                "ok": True,
                "enabled": config.get("local_storage.enabled", False),
                "period": config.get("local_storage.period", "month")
            }) + "\n")
            log(f"[BLE] storageset: enabled={enabled}, period={period}")
            
        elif cmd_type == "set_rs485_ext":
            # set485extended模式（4CH/2CH）
            enabled = cmd.get("enabled", False)
            config.set("system.rs485_ext", enabled)
            config.save()
            ble.send(json.dumps({
                "cmd": "set_rs485_ext",
                "ok": True,
                "enabled": enabled
            }) + "\n")
            log(f"[BLE] 485extendedset: {enabled}")
            
        elif cmd_type == "set_merge_segments":
            # setmergemessage模式
            enabled = cmd.get("enabled", False)
            config.set("system.merge_segments", enabled)
            config.save()
            ble.send(json.dumps({
                "cmd": "set_merge_segments",
                "ok": True,
                "enabled": enabled
            }) + "\n")
            log(f"[BLE] mergemessageset: {enabled}")
            
        elif cmd_type == "get_storage":
            # getstorageset
            ble.send(json.dumps({
                "cmd": "get_storage",
                "enabled": config.get("local_storage.enabled", False),
                "period": config.get("local_storage.period", "month")
            }) + "\n")
            
        elif cmd_type == "list_files":
            # columnoutdatafile
            try:
                from lib.local_storage import LocalStorage
                storage = LocalStorage(config, log)
                files = storage.list_files()
                ble.send(json.dumps({
                    "cmd": "list_files",
                    "files": files
                }) + "\n")
            except Exception as e:
                ble.send(json.dumps({"cmd": "list_files", "error": str(e)}) + "\n")
                
        elif cmd_type == "delete_file":
            # deletedatafile
            filename = cmd.get("filename", "")
            if filename:
                try:
                    from lib.local_storage import LocalStorage
                    storage = LocalStorage(config, log)
                    ok = storage.delete_file(filename)
                    ble.send(json.dumps({"cmd": "delete_file", "filename": filename, "ok": ok}) + "\n")
                except Exception as e:
                    ble.send(json.dumps({"cmd": "delete_file", "error": str(e)}) + "\n")
            else:
                ble.send(json.dumps({"cmd": "delete_file", "error": "filename required"}) + "\n")
            
        elif cmd_type == "read_sensors":
            # triggersensorread
            log("[BLE] 收到readsensorcmd")
            return True
        
        elif cmd_type == "set_usb_rw":
            # setUSB RW模式（usesNVM，downtimes启动生效）
            # nvm[0] = 17: daily mode（设备writable）
            # nvm[0] = 其他value: flash mode（电脑writable）
            import microcontroller
            enabled = cmd.get("enabled", False)  # enabled=True 表示电脑writable（flash mode）
            if enabled:
                microcontroller.nvm[0] = 0  # flash mode
            else:
                microcontroller.nvm[0] = 17  # daily mode
            ble.send(json.dumps({
                "cmd": "set_usb_rw", 
                "ok": True, 
                "enabled": enabled,
                "nvm": microcontroller.nvm[0],
                "note": "重启after生效" + ("，进inflash mode" if enabled else "，进indaily mode")
            }) + "\n")
            log(f"[BLE] USB_RW set: nvm[0]={microcontroller.nvm[0]}")
        
        elif cmd_type == "get_usb_rw":
            # getUSB RW模式set
            import microcontroller
            nvm_value = microcontroller.nvm[0]
            enabled = (nvm_value != 17)  # not17表示flash mode（电脑writable）
            ble.send(json.dumps({
                "cmd": "get_usb_rw",
                "enabled": enabled,
                "nvm": nvm_value,
                "mode": "flash mode" if enabled else "daily mode"
            }) + "\n")
            
        elif cmd_type == "set_time":
            # 手机发送当前时间到控制器（Unix timestamp）
            timestamp = cmd.get("timestamp", 0)
            if timestamp > 0:
                import rtc
                rtc.RTC().datetime = time.localtime(timestamp)
                now = time.localtime()
                time_str = f"{now.tm_year}/{now.tm_mon:02d}/{now.tm_mday:02d} {now.tm_hour:02d}:{now.tm_min:02d}:{now.tm_sec:02d}"
                log(f"[BLE] 手机对时成功: {time_str}")
                ble.send(json.dumps({"cmd": "set_time", "ok": True, "time": time_str}) + "\n")
            else:
                ble.send(json.dumps({"cmd": "set_time", "ok": False, "error": "invalid timestamp"}) + "\n")
            
        elif cmd_type == "reboot":
            # 重启设备
            ble.send(json.dumps({"cmd": "reboot", "ok": True}) + "\n")
            log("[BLE] 正在重启...")
            time.sleep(0.5)  # 等待 BLE 响应发送完成
            import microcontroller
            microcontroller.reset()
            
        else:
            log(f"[BLE] unknown cmd: {cmd_type}")
            
    except Exception as e:
        log(f"[BLE] parse err: {e}")
    
    return False

# ============================================================
# 主程序
# ============================================================

def main():
    log("=" * 50)
    log("  柔性测斜仪控制器 - 同步版")
    log("=" * 50)
    
    # 检查配置文件
    if not file_exists("/config.json"):
        if file_exists("/config.json.default"):
            log("[启动] 从默认模板创建 config.json...")
            with open("/config.json.default", "r") as src:
                with open("/config.json", "w") as dst:
                    dst.write(src.read())
    
    # 加载配置
    config = ConfigManager("/config.json")
    log(f"[配置] 设备ID: {config.get('system.id')}")
    
    interval_preset = config.get("system.interval_preset", 5)
    interval_sec = get_interval_seconds(interval_preset)
    sleep_mode = config.get("system.sleep_mode", "light")
    log(f"[配置] 采集间隔: {interval_sec//60}分钟, 休眠: {sleep_mode}")
    
    # 打印当前时间
    now = time.localtime()
    log(f"[时间] {now.tm_year}/{now.tm_mon:02d}/{now.tm_mday:02d} {now.tm_hour:02d}:{now.tm_min:02d}:{now.tm_sec:02d}")
    
    # 初始化硬件
    led = LEDDriver()
    voltage = VoltageMonitor()
    counter = UploadCounter()
    fw_version = config.get("system.firmware_version", FIRMWARE_VERSION)
    formatter = DataFormatter(config, counter, fw_version)
    
    # 初始化本地存储
    from lib.local_storage import LocalStorage
    storage = LocalStorage(config, log)
    
    # 读取电压
    voltages = voltage.read_all()
    log(f"[电压] vin={voltages.get('vin', 0):.2f}V")
    
    # 内存状态
    gc.collect()
    free_mem = gc.mem_free()
    log(f"[内存] 空闲: {free_mem // 1024} KB")
    
    # 初始化 RS485 驱动和协议
    from drivers.rs485 import RS485Driver
    
    rs485_drivers = {}
    rs485_protocols = {}
    rs485_sensors = {}
    
    for ch in [1, 2]:
        if config.get(f"rs485_{ch}.enabled", False):
            sensors = config.get(f"rs485_{ch}.sensors", [])
            if sensors:
                baud = config.get(f"rs485_{ch}.baud", 9600)
                driver = RS485Driver(ch, baud)
                protocol = PrivateProtocolV2026(driver)
                rs485_drivers[ch] = driver
                rs485_protocols[ch] = protocol
                rs485_sensors[ch] = sensors
                log(f"[RS485] 通道{ch}: {len(sensors)}个传感器, {baud} baud")
    
    total_sensors = sum(len(s) for s in rs485_sensors.values())
    log("=" * 50)
    log(f"  初始化完成，共 {total_sensors} 个传感器")
    log("  发送 @scan 扫描地址, #help 查看帮助")
    log("=" * 50)
    
    # 初始化 BLE
    ble = None
    log("[BLE] 开始初始化...")
    if config.get("ble.enabled", True):
        try:
            log("[BLE] 导入 adafruit_ble 库...")
            from lib.ble_uart import BLEUART, _HAS_ADAFRUIT_BLE
            log(f"[BLE] adafruit_ble 可用: {_HAS_ADAFRUIT_BLE}")
            
            ble_name = f"UniControl_{config.get('system.id', '0000')}"
            log(f"[BLE] 创建 BLEUART: {ble_name}")
            ble = BLEUART(name=ble_name)
            
            if ble._initialized:
                log("[BLE] 初始化成功，开始广播...")
                ble.start_advertising()
                log(f"[BLE] ✓ 广播已启动: {ble_name}")
            else:
                log("[BLE] ✗ 初始化失败")
                ble = None
        except ImportError as e:
            log(f"[BLE] ✗ 库导入失败: {e}")
            ble = None
        except Exception as e:
            log(f"[BLE] ✗ 初始化异常: {e}")
            import sys
            sys.print_exception(e)
            ble = None
    else:
        log("[BLE] 已禁用 (配置: ble.enabled=false)")
    
    # ============================================================
    # 智能启动逻辑
    # Phase 1: 3 秒 CDC 检测窗口
    # Phase 2: 有 CDC → 交互模式等 #read (60s 无输入自动开始)
    #          无 CDC → 直接开始采集
    # ============================================================
    log("[启动] 3 秒 CDC 检测窗口...")
    cdc_detected = False
    detect_start = time.monotonic()
    while (time.monotonic() - detect_start) < 3.0:
        cdc_result = process_commands(rs485_drivers, rs485_protocols, config)
        if cdc_result == "reload_config":
            cdc_detected = True
            interval_preset = config.get("system.interval_preset", 0)
            interval_sec = get_interval_seconds(interval_preset)
            log(f"[配置更新] 间隔已更新为: {interval_sec}秒")
        elif cdc_result:
            cdc_detected = True
            log("[启动] 收到采集命令，开始工作")
            break
        if usb_cdc.data and usb_cdc.data.in_waiting > 0:
            cdc_detected = True
        if ble:
            ble_result = process_ble_command(ble, config, rs485_drivers, rs485_protocols)
            if ble_result == True:
                break
            elif ble_result == "reload_config":
                interval_preset = config.get("system.interval_preset", 0)
                interval_sec = get_interval_seconds(interval_preset)
                log(f"[配置更新] 间隔已更新为: {interval_sec}秒")
        time.sleep(0.1)
    
    # Phase 2: CDC 交互模式
    if cdc_detected:
        log("[启动] CDC 已检测到，进入交互模式 (发送 #read 开始采集, 60s 无输入自动开始)")
        last_input_time = time.monotonic()
        while True:
            cdc_result = process_commands(rs485_drivers, rs485_protocols, config)
            if cdc_result == "reload_config":
                last_input_time = time.monotonic()
                interval_preset = config.get("system.interval_preset", 0)
                interval_sec = get_interval_seconds(interval_preset)
                log(f"[配置更新] 间隔已更新为: {interval_sec}秒")
            elif cdc_result:
                log("[启动] 收到采集命令，开始工作")
                break
            
            # 检测新的 CDC 输入，刷新超时
            if usb_cdc.data and usb_cdc.data.in_waiting > 0:
                last_input_time = time.monotonic()
            
            # BLE 命令
            if ble:
                ble_result = process_ble_command(ble, config, rs485_drivers, rs485_protocols)
                if ble_result == True:
                    break
                elif ble_result == "reload_config":
                    interval_preset = config.get("system.interval_preset", 0)
                    interval_sec = get_interval_seconds(interval_preset)
                    log(f"[配置更新] 间隔已更新为: {interval_sec}秒")
            
            # 60s 无输入超时
            idle_sec = time.monotonic() - last_input_time
            if idle_sec >= 60:
                log("[启动] 60s 无 CDC 输入，自动开始采集")
                break
            
            time.sleep(0.3)
    else:
        log("[启动] 无 CDC 输入，直接开始采集")
    
    # 主循环
    cycle = 0
    while True:
        # 如果 interval_sec == 0，不自动采集，只等待命令
        if interval_sec == 0:
            led.set_mode("idle")
            log("[待命] 等待命令... (发送 #help 查看帮助)")
            while True:
                cdc_result = process_commands(rs485_drivers, rs485_protocols, config)
                if cdc_result == "reload_config":
                    interval_preset = config.get("system.interval_preset", 0)
                    interval_sec = get_interval_seconds(interval_preset)
                    log(f"[配置更新] 间隔已更新为: {interval_sec}秒")
                    if interval_sec > 0:
                        break
                elif cdc_result:
                    break
                # BLE 命令处理
                if ble:
                    ble_result = process_ble_command(ble, config, rs485_drivers, rs485_protocols)
                    if ble_result == True:
                        break
                    elif ble_result == "reload_config":
                        # 重新加载间隔配置
                        interval_preset = config.get("system.interval_preset", 0)
                        interval_sec = get_interval_seconds(interval_preset)
                        log(f"[配置更新] 间隔已更新为: {interval_sec}秒")
                        if interval_sec > 0:  # 如果不再是待命模式，退出待命循环
                            break
                    if ble.is_connected():
                        time.sleep(0.3)
                    else:
                        time.sleep(0.5)
                else:
                    time.sleep(0.5)
            # 重新加载传感器 (可能被 scan/write_addr 更新)
            for ch in rs485_sensors.keys():
                rs485_sensors[ch] = config.get(f"rs485_{ch}.sensors", [])
        
        cycle += 1
        log(f"\n[周期 {cycle}] 开始采集...")
        led.set_mode("transmit")
        
        # 采集sensordata (sync)
        all_data = []
        ble_interrupted = False
        
        log(f"[DEBUG] rs485_sensors keys: {list(rs485_sensors.keys())}")
        
        for ch, sensors in rs485_sensors.items():
            driver = rs485_drivers[ch]
            protocol = rs485_protocols[ch]
            
            log(f"[CH{ch}] reading {len(sensors)}  sensors...")
            
            # pwr on
            driver.power_on()
            time.sleep(0.3)  # pwr on延时 300ms
            
            # read from top to bottom (config.json order)
            success_count = 0
            fail_count = 0
            for sensor_cfg in sensors:
                addr = sensor_cfg.get("addr", 0)
                model = sensor_cfg.get("model", 0)
                try:
                    log(f"  [CH{ch}] readaddr {addr}...")
                    # timeout 5000ms per参考client
                    data = protocol.read_data(addr, timeout_ms=5000)
                    if data:
                        data["channel"] = ch
                        data["model"] = model
                        all_data.append(data)
                        success_count += 1
                        log(f"  [CH{ch}] addr {addr}: A={data.get('a', 0):.2f}, B={data.get('b', 0):.2f}")
                    else:
                        fail_count += 1
                        all_data.append({
                            "addr": addr,
                            "address": addr,
                            "channel": ch,
                            "model": model,
                            "a": 0, "b": 0, "z": 0,
                            "status": "W"
                        })
                        log(f"  [CH{ch}] addr {addr}: no resp")
                except Exception as e:
                    fail_count += 1
                    all_data.append({
                        "addr": addr,
                        "address": addr,
                        "channel": ch,
                        "model": model,
                        "a": 0, "b": 0, "z": 0,
                        "status": "W"
                    })
                    log(f"  [CH{ch}] addr {addr} Err: {e}")
                
                time.sleep(0.15)  # sensorinterval 150ms
                
                # check BLE conn，ifconn则INT采集
                if ble and ble.is_connected():
                    log(f"[BLE] connection detected，interrupt, standby")
                    ble_interrupted = True
                    break
            
            # if BLE INT，跳outCHloop
            if ble_interrupted:
                driver.power_off()
                break
            
            log(f"[CH{ch}] done: ok {success_count}, fail {fail_count}")
            
            # pwr off
            driver.power_off()
        
        log(f"[采集] done，read {len(all_data)} ")
        
        # if BLE INT，skipup报，进in BLE cmdprocessloop
        if ble_interrupted:
            all_data.clear()  # 丢弃不完整数据
            log("[BLE] 进inStandby模式，Wait BLE cmd...")
            led.set_mode("idle")
            while ble and ble.is_connected():
                # 同时process CDC and BLE cmd
                process_commands(rs485_drivers, rs485_protocols, config)
                process_ble_command(ble, config, rs485_drivers, rs485_protocols)
                time.sleep(0.3)
            log("[BLE] conndonedisconnect，resumenormal采集")
            continue
        
        # fmt化data
        voltages = voltage.read_all()
        modem_instance = None  # 用于 deep sleep 前 PSM
        if all_data:
            segments = formatter.format_segments(all_data, voltages)
            
            # send到 CDC (完整 JSON，and 4G Uploadfmt一致)
            log(f"[CDC] send {len(segments)} seg...")
            for seg in segments:
                if usb_cdc.data:
                    usb_cdc.data.write((seg + "\r\n").encode())
            
            # send到net (4G > WiFi > Ethernet)
            # 上传前检查是否需要 NTP 同步
            try_time_sync(config)
            modem_instance = do_network_upload(config, segments)
            update_last_send_day()
            
            # 发送设备状态报告 (独立连接到硬编码 controller-manager broker)
            try:
                if modem_instance:
                    from app.device_reporter import send_report_via_modem
                    send_report_via_modem(config, modem_instance)
                elif config.get("network.wifi.enabled", False):
                    from app.device_reporter import send_report_via_wifi
                    send_report_via_wifi(config)
                log("[Report] device status sent")
            except Exception as e:
                log(f"[Report] err: {e}")
            
            # save到storage
            if storage.enabled:
                # 转换as存储fmt
                storage_readings = []
                for d in all_data:
                    storage_readings.append({
                        "addr": d.get("address", d.get("addr", 0)),
                        "a": d.get("a", 0),
                        "b": d.get("b", 0),
                        "z": d.get("z") if d.get("z") is not None else None
                    })
                storage.save_readings(storage_readings)
        
        log(f"[Cycle {cycle}] read done")
        
        # OTA 检查 (每轮上传完成后，利用 WiFi 连接检查更新)
        if config.get("network.wifi.enabled", False) and config.get("system.ota_url", ""):
            try:
                from app.ota_updater import check_and_update
                check_and_update(config)
            except Exception as e:
                log(f"[OTA] err: {e}")
        
        # Memstatus
        gc.collect()
        free_mem = gc.mem_free()
        log(f"[Mem] free: {free_mem // 1024} KB")
        
        # if interval_sec == 0，回到Standby模式
        if interval_sec == 0:
            continue
        
        # processpendingprocess的 CDC cmd
        if process_commands(rs485_drivers, rs485_protocols, config):
            log("[skipSleep] 收到 #read cmd")
            continue  # skipSleep，立即采集
        
        # ============================================================
        # Deep Sleep 模式: 真正的深度休眠
        # ============================================================
        if sleep_mode == "deep" and interval_sec > 0:
            # 1. 4G 模块处理: PSM 保持供电，非 PSM 则关闭电源
            if config.get("network.4g.enabled", False):
                try:
                    if modem_instance:
                        log("[4G] 进入 PSM 省电模式...")
                        ok = modem_instance.enter_psm()
                        if ok:
                            # PSM 成功: 保持 GPIO5 (PWR) HIGH，模块保持网络注册
                            # 醒来后可快速重连 MQTT
                            log("[4G] PSM 已启用，模块保持供电")
                        else:
                            # PSM 失败: 完全关闭模块省电
                            modem_instance.deinit()
                            log("[4G] PSM 失败，模块已关闭")
                    else:
                        log("[4G] 无活跃连接，跳过 PSM")
                except Exception as e:
                    log(f"[4G] PSM 错误: {e}")
            
            # 2. 关闭 BLE 广播
            if ble:
                try:
                    ble.stop_advertising()
                    log("[BLE] 已停止广播")
                except:
                    pass
            
            # 3. 关闭所有 RS485 驱动 (VCC/DE/ADDR/UART GPIO)
            for ch, driver in rs485_drivers.items():
                try:
                    driver.deinit()  # power_off + uart.deinit + gpio.deinit
                    log(f"[RS485] CH{ch} 已释放")
                except:
                    pass
            
            # 4. 关闭 LED
            try:
                led.off()
                led.deinit()
                log("[LED] 已关闭")
            except:
                pass
            
            # 5. 收集需要保持状态的引脚 (4G PSM: GPIO5 保持 HIGH)
            preserve_pins = []
            if modem_instance and config.get("network.4g.enabled", False):
                try:
                    # modem_instance.pwr_pin 是 GPIO5 的 DigitalInOut 对象
                    if hasattr(modem_instance, 'pwr_pin') and modem_instance.pwr_pin.value:
                        preserve_pins.append(modem_instance.pwr_pin)
                        log("[Deep Sleep] GPIO5 (MODEM_PWR) 将保持 HIGH")
                except:
                    pass
            
            # 6. 进入深度休眠 (设备会完全重启)
            from drivers.power import PowerManager
            pwr = PowerManager()
            sleep_ms = interval_sec * 1000
            log(f"[Deep Sleep] 进入深度休眠 {interval_sec}s ({interval_sec // 60}分钟)...")
            log("[Deep Sleep] 醒来后将从 boot.py 重新启动")
            time.sleep(0.3)  # 等待日志输出完成
            pwr.deep_sleep(sleep_ms, preserve_dios=tuple(preserve_pins) if preserve_pins else None)
            # ← 不会返回到这里，设备从 boot.py 重新启动
        
        # ============================================================
        # Light Sleep 模式: 轮询等待，保持 CDC/BLE 响应
        # ============================================================
        led.set_mode("idle")
        
        log(f"[Sleep] {interval_sec} s (send #read 可立即采集)...")
        sleep_start = time.monotonic()
        while (time.monotonic() - sleep_start) < interval_sec:
            cdc_result = process_commands(rs485_drivers, rs485_protocols, config)
            if cdc_result == "reload_config":
                interval_preset = config.get("system.interval_preset", 5)
                interval_sec = get_interval_seconds(interval_preset)
                log(f"[cfg update] interval updated to: {interval_sec}s")
            elif cdc_result:
                log("[INTSleep] 收到 #read cmd")
                break
            # BLE cmdprocess (始终轮询)
            if ble:
                ble_result = process_ble_command(ble, config, rs485_drivers, rs485_protocols)
                if ble_result == True:
                    log("[INTSleep] 收到 BLE read_sensors cmd")
                    break
                elif ble_result == "reload_config":
                    # 重newloadintervalCfg
                    interval_preset = config.get("system.interval_preset", 5)
                    interval_sec = get_interval_seconds(interval_preset)
                    log(f"[cfg update] interval updated to: {interval_sec}s")
                if ble.is_connected():
                    time.sleep(0.3)  # BLE conn时fast速轮询
                else:
                    time.sleep(1.0)  # normal每scheck一times
            else:
                time.sleep(1.0)

# ============================================================
# Entry
# ============================================================

log("Starting main()...")
try:
    main()
except Exception as e:
    log(f"[FATAL] {e}")
    import sys
    sys.print_exception(e)
    while True:
        time.sleep(1)

# 柔性测斜仪控制器 - CircuitPython 固件

> 同步版本 2026.02.06 - 不使用 asyncio，纯同步架构

## 目录结构

```
firmware/
├── circuitpython/       # CircuitPython 固件
│   ├── boot.py          # USB CDC 配置 (禁用 REPL, 启用数据端口)
│   ├── code.py          # 主程序入口
│   ├── pins.py          # 硬件引脚定义
│   ├── config.json      # 系统配置
│   ├── app/             # 应用逻辑 (4 模块)
│   │   ├── config_mgr.py    # 配置管理器
│   │   ├── data_formatter.py # 数据格式化 (分段 JSON)
│   │   ├── data_logger.py   # 本地日志 (LRU)
│   │   └── upload_counter.py # 上传序号计数器
│   ├── drivers/         # 硬件驱动 (7 模块)
│   │   ├── rs485.py         # RS485 + DE/VCC 控制
│   │   ├── modem_4g.py      # 4G 模块 (SIM7672E)
│   │   ├── wifi.py          # WiFi
│   │   ├── ethernet.py      # W5500 以太网
│   │   ├── voltage.py       # ADC 电压监测
│   │   ├── power.py         # 电源管理 (休眠)
│   │   └── led.py           # LED 状态指示
│   ├── lib/             # 协议库 (3 模块)
│   │   ├── private_v2026.py # 私有协议 V2026
│   │   ├── modbus_rtu.py    # Modbus RTU
│   │   └── ble_uart.py      # BLE UART NUS
│   └── data/            # 数据存储目录
└── deploy_circuitpython.sh  # 部署脚本
```

---

## 功能特性

- **BLE 蓝牙**: Nordic UART Service (NUS)
- **多通道 RS485**: 2-4 通道支持 (SC16IS752 扩展)
- **多协议支持**: Private V2026 / Modbus RTU
- **多网络上报**: 4G > WiFi > 以太网 > USB CDC
- **分段 JSON 上报**: 地址降序排列，支持合并报文
- **低功耗**: 深度休眠 (~10µA) / 轻度休眠 (~130µA)
- **NVM 模式控制**: 设备/电脑读写模式即时切换
- **本地存储**: 按日/月存储传感器数据到设备
- **自动注册**: 首次启动从服务器获取设备 ID (YYYY75XXXX)

---

## 传感器数据流顺序

> 假设杆子从顶到底安装了 25 个传感器：顶部 25010001 → 底部 25010025

### 完整数据流

```
扫地址 (AutoID 0~1024)
  │  顶→底: 25010001, 25010002, ..., 25010025
  ▼
config.json 存储
  │  顶→底: [{addr:25010001}, ..., {addr:25010025}]
  ▼
主循环读取 (for sensor_cfg in sensors)
  │  顶→底: 先读 25010001, 最后读 25010025
  ▼
┌────────────────────────────┬─────────────────────────────┐
│ 网络上传 (MQTT/CDC/4G/WiFi) │ 本地存储 (data/)             │
│ data_formatter.reversed()  │ 直接保存 all_data            │
│ 底→顶: 25010025 → 25010001 │ 顶→底: 25010001 → 25010025  │
└────────────────────────────┴─────────────────────────────┘
```

### 各阶段详情

| 阶段 | 顺序 | 第一个 → 最后一个 | 说明 |
|:---|:---:|:---|:---|
| **扫地址** | 顶→底 | 25010001 → 25010025 | AutoID 0~1024 遍历，按发现顺序追加 |
| **config.json** | 顶→底 | 同扫地址结果 | 扫完直接写入，不排序 |
| **主循环读取** | 顶→底 | 遍历 config 正序 | `for sensor_cfg in sensors` |
| **BLE 读取** | 顶→底 | 读一个发一个 | 不组 JSON，逐条通过 BLE 发送 |
| **网络上传** | **底→顶** | 25010025 → 25010001 | `data_formatter` 内部 `reversed()` |
| **本地存储** | 顶→底 | 同读取顺序 | 直接保存 `all_data` |

> **上传协议规定**：seg 1/n 的 data[0] 为底部传感器（地址最大），所以 formatter 做了反转。

---

## 硬件配置

- **芯片**: N16R8
- **Flash**: 16MB
- **PSRAM**: 8MB
- **已用 GPIO**: 38 个
- **剩余 GPIO**: ~7 个

---

## 引脚定义

### 4G 模块 (SIM7672E)

| 功能 | GPIO |
|:---|:---:|
| MODEM_TX | 43 |
| MODEM_RX | 44 |
| MODEM_PWR | 5 |

### RS485 通道 1

| 功能 | GPIO |
|:---|:---:|
| TX | 17 |
| RX | 18 |
| DE | 16 |
| VCC | 4 |
| ADDR | 15 |

### RS485 通道 2

| 功能 | GPIO |
|:---|:---:|
| TX | 38 |
| RX | 39 |
| DE | 40 |
| VCC | 41 |
| ADDR | 42 |

### RS485 通道 3 (SC16IS752 扩展)

| 功能 | GPIO |
|:---|:---:|
| DE | 11 |
| VCC | 12 |
| ADDR | 13 |
| TX/RX | I2C (47/48) |

### RS485 通道 4 (SC16IS752 扩展)

| 功能 | GPIO |
|:---|:---:|
| DE | 14 |
| VCC | 27 |
| ADDR | 28 |
| TX/RX | I2C (47/48) |

### I2C 总线 (SC16IS752)

| 功能 | GPIO |
|:---|:---:|
| SDA | 47 |
| SCL | 48 |

### 以太网 W5500 (SPI)

| 功能 | GPIO |
|:---|:---:|
| MOSI | 35 |
| MISO | 37 |
| SCK | 36 |
| CS | 34 |
| RST | 33 |
| INT | 21 |

### ADC 电压监测 (ADC1)

| 功能 | GPIO | 通道 |
|:---|:---:|:---:|
| VIN | 3 | CH2 |
| V4 | 4 | CH3 |
| V5V | 6 | CH5 |
| V4G | 7 | CH6 |
| V1 | 8 | CH7 |
| V2 | 9 | CH8 |
| V3 | 10 | CH9 |

> ⚠️ 所有 ADC 都使用 ADC1，因为 ADC2 与 WiFi 冲突

---

## 配置参数

### 系统 (`system`)

| 参数 | 默认值 | 说明 |
|:---|:---:|:---|
| `id` | `"2016750001"` | 设备 ID，自动从服务器获取 |
| `interval_preset` | `0` | 采集间隔 (见下表) |
| `sleep_mode` | `"deep"` | `"light"` / `"deep"` |

**interval_preset 值**:

| 值 | 间隔 |
|:---:|:---|
| 0 | 待命模式 (不自动采集，只响应命令) |
| 1 | 5 分钟 |
| 2 | 10 分钟 |
| 3 | 15 分钟 |
| 4 | 30 分钟 |
| 5 | 1 小时 |
| 6 | 2 小时 |
| 7 | 4 小时 |
| 8 | 12 小时 |
| 9 | 24 小时 |
| 99 | 自定义 (`interval_custom_min`) |

### 网络 (`network`)

| 参数 | 默认值 | 说明 |
|:---|:---:|:---|
| `mqtt_broker` | `"47.95.250.46"` | MQTT 服务器 |
| `mqtt_port` | `1883` | MQTT 端口 |
| `mqtt_topic` | `"controllerdata-cirpy"` | MQTT 主题 |

### 4G (`network.4g`)

| 参数 | 默认值 | 说明 |
|:---|:---:|:---|
| `enabled` | `true` | 启用 4G |
| `apn` | `"cmnet"` | APN |
| `cops` | `"0"` | 运营商选择，`"0"`=自动 |

### RS485 (`rs485_1` / `rs485_2`)

| 参数 | 默认值 | 说明 |
|:---|:---:|:---|
| `enabled` | `true` | 启用通道 |
| `protocol` | `"PRIVATE_V2026"` | 协议类型 |
| `sensors` | `[]` | 传感器地址列表 |

---

## 数据上报格式

### 传感器顺序说明

以 25 个传感器为例（地址 26110001 ~ 26110025）：

| 位置 | 地址 | config.json 顺序 | 读数顺序 |
|------|------|------------------|----------|
| **最上面（顶端）** | 26110001 | 第1个 | 先读 |
| ↓ | 26110002 | 第2个 | ↓ |
| ... | ... | ... | ... |
| **最下面（底端）** | 26110025 | 第25个 | 后读 |

### 完整顺序总结

| 步骤 | 顺序 | 第1个 | 最后1个 | 说明 |
|------|------|-------|---------|------|
| **扫地址** | 底→顶 | 26110025 | 26110001 | AutoID 0 = 底端（电压最低） |
| **config.json 存储** | 顶→底 | 26110001 | 26110025 | 扫描结果**反转后**存储 |
| **读数** | 顶→底 | 26110001 | 26110025 | 按 config.json 顺序 |
| **JSON data[]** | 底→顶 | 26110025 | 26110001 | 读数结果**反转后**输出 |

### 头信息 (seg: 0/n)

```json
{
  "cid": 2026750055,
  "v": "2026.02.09-sync",
  "sdt": "107",
  "V4G": 405,
  "vin": 12.35,
  "V5V": 498,
  "V1": 9.88,
  "V2": 0.00,
  "clock": "2/5/2026 22:30:00",
  "time": 1738765800,
  "hib": 5,
  "signal": "CSQ:31,99",
  "sid1num": 25,
  "sid2num": 0,
  "seg": "0/2"
}
```

### 数据段 (seg: 1/n)

```json
{
  "cid": 2026750055,
  "time": 1738765800,
  "seg": "1/2",
  "data": [
    [26110025, -0.55, 0.71, "C", 1, 998.70],
    [26110024, -0.52, 0.68, "C", 1, 999.20],
    [26110023, -0.48, 0.62, "C", 1, 999.80],
    [26110002, -0.18, 0.25, "C", 1, 1002.10],
    [26110001, -0.15, 0.23, "C", 1, 1001.50]
  ]
}
```

**数据格式**: `[地址, A轴, B轴, 状态, 1, Z轴]`

- **顺序**: 底端在前（26110025），顶端在后（26110001）
- **状态**: `C` = 正常, `W` = 无响应

---

## CDC 命令

通过 USB CDC 串口发送命令控制设备。`[com_port]` 可以是 `com1` 或 `com2` (扩展口启用时还有 `com3`, `com4`)。

### 操作命令

| 命令 | 说明 | 反馈示例 |
|:---|:---|:---|
| `#scan [com_port]` | 扫描传感器地址 | `[扫描] 发现传感器: 2026020101` |
| `#write_addr [com_port] 地址 [超时ms]` | 批量写入地址 (默认300ms) | `[写入] 地址 2026020101 写入成功` |
| `#read [com_port]` | 立即采集并上传 | `[采集] 通道1开始采集...` |
| `#read_temp_and_model [com_port]` | 读取温度和型号 | `地址 2026020101: 温度=25.5°C 型号=106` |
| `#write_model [com_port] 型号` | 批量写入型号 (带验证) | `地址 2026020101: 写入型号 106 ✓` |

### 查询命令

| 命令 | 反馈示例 |
|:---|:---|
| `#get_id` | `[设备ID] 2026750001` |
| `#get_interval` | `[采集间隔] 5 (1小时)` |
| `#get_sensors com1` | `[通道1] 传感器: 2026020101, 2026020100, ...` |
| `#get_mqtt` | `[MQTT] 47.93.29.232:1883 主题:controllerdata-cirpy` |
| `#get_wifi` | `[WiFi] 禁用 SSID:` |
| `#get_4g` | `[4G] 启用 APN:cmnet COPS:0` |
| `#get_sleep` | `[休眠模式] deep` |

### 设置命令 (自动保存)

| 命令 | 反馈示例 |
|:---|:---|
| `#set_id 2026750001` | `[设备ID] 已设置: 2026750001` |
| `#set_interval 5` | `[采集间隔] 已设置: 5 (1小时)` |
| `#set_mqtt IP 端口 主题` | `[MQTT] 已设置: 47.93.29.232:1883 主题:topic` |
| `#set_wifi SSID 密码` | `[WiFi] 已设置: MySSID` |
| `#set_4g_apn cmnet` | `[4G APN] 已设置: cmnet` |
| `#set_4g_cops 0` | `[4G COPS] 已设置: 0` |
| `#set_sleep light` | `[休眠模式] 已设置: light` |

### 开关命令 (自动保存)

| 命令 | 反馈示例 |
|:---|:---|
| `#enable_4g` | `[4G] 已启用` |
| `#disable_4g` | `[4G] 已禁用` |
| `#enable_wifi` | `[WiFi] 已启用` |
| `#disable_wifi` | `[WiFi] 已禁用` |
| `#enable_eth` | `[以太网] 已启用 (W5500)` |
| `#disable_eth` | `[以太网] 已禁用` |
| `#enable_expansion` | `[扩展口] 已启用 (SC16IS752: com3, com4)` |
| `#disable_expansion` | `[扩展口] 已禁用` |
| `#enable_storage` | `[本地存储] 已启用` |
| `#disable_storage` | `[本地存储] 已禁用` |
| `#enable_usb_rw` | `[USB_RW] 已启用 (重启后电脑可读写)` |
| `#disable_usb_rw` | `[USB_RW] 已禁用 (重启后设备可读写)` |

### 系统命令

| 命令 | 反馈示例 |
|:---|:---|
| `#status` | `[状态] ID:2026750001 间隔:5 内存:120KB 通道1:3个 通道2:0个` |
| `#version` | `[版本] CircuitPython 3.01` |
| `#reboot` | `[重启] 设备将在 1 秒后重启...` |
| `#help` | 显示完整帮助信息 (见下) |

### #help 完整输出

```
========== CDC 命令帮助 ==========
--- 操作命令 ---
#scan [com_port]        - 扫描传感器地址
#write_addr [com_port] 地址 [超时ms] - 批量写入地址
#read [com_port]        - 立即采集并上传
#read_temp_and_model [com_port] - 读取温度和型号
--- 查询命令 ---
#get_id                 - 获取设备ID
#get_interval           - 获取采集间隔
#get_sensors [com_port] - 获取传感器列表
#get_mqtt               - 获取MQTT配置
#get_wifi               - 获取WiFi配置
#get_4g                 - 获取4G配置
#get_sleep              - 获取休眠模式
--- 设置命令 (自动保存) ---
#set_id 2026750001      - 设置设备ID
#set_interval 5         - 设置采集间隔(0=待命)
#set_mqtt IP 端口 主题  - 设置MQTT
#set_wifi SSID 密码     - 设置WiFi
#set_4g_apn cmnet       - 设置4G APN
#set_4g_cops 0          - 设置运营商(0=自动)
#set_sleep light|deep   - 设置休眠模式
#write_model [com_port] 型号 - 批量写型号
#enable_4g / #disable_4g
#enable_wifi / #disable_wifi
#enable_eth / #disable_eth
#enable_expansion / #disable_expansion
#enable_storage / #disable_storage - 本地存储开关
--- 系统命令 ---
#status                 - 查看状态(含网络/存储)
#version                - 固件版本
#reboot                 - 重启设备
#enable_usb_rw          - 电脑可读写(烧录模式,重启生效)
#disable_usb_rw         - 设备可读写(日常模式,重启生效)
#usb_rw_status          - 查看USB读写模式
==================================
```

---

## 工作流程

### 1. 轮询读数流程 (`#read comX` 或自动周期)

```
┌────────────────────────────────┐
│ 1. RS485 驱动上电 (300ms 等待)   │
└────────────────────────────────┘
              ↓
┌────────────────────────────────┐
│ 2. 遍历 config.json 中的地址     │
│    从顶端 (大地址) 向底端读取     │
└────────────────────────────────┘
              ↓
┌────────────────────────────────┐
│ 3. 发送 A3 命令读取数据          │
│    - 超时: 5000ms               │
│    - 间隔: 150ms                │
│    - 无响应标记 status = "W"     │
└────────────────────────────────┘
              ↓
┌────────────────────────────────┐
│ 4. 格式化 JSON 分段输出到 CDC    │
│    底端地址在 seg 1/n            │
└────────────────────────────────┘
              ↓
┌────────────────────────────────┐
│ 5. 休眠等待下一周期              │
└────────────────────────────────┘
```

### 2. 扫描地址流程 (`#scan comX`)

```
┌────────────────────────────────┐
│ 1. RS485 驱动上电 (300ms 等待)   │
└────────────────────────────────┘
              ↓
┌────────────────────────────────┐
│ 2. 遍历 AutoID 0-1023           │
│    发送 A2 命令查询固定地址      │
│    - 超时: 300ms                │
│    - 间隔: 200ms                │
└────────────────────────────────┘
              ↓
┌────────────────────────────────┐
│ 3. 收到 B2 响应则记录地址        │
│    过滤无效地址 (0, FFFFFFFF)    │
└────────────────────────────────┘
              ↓
┌────────────────────────────────┐
│ 4. 保存到 config.json           │
│    rs485_x.sensors = [...]      │
└────────────────────────────────┘
              ↓
┌────────────────────────────────┐
│ 5. 输出 JSON 结果到 CDC         │
└────────────────────────────────┘
```

**时间**: 1024 × 500ms ≈ **8.5 分钟/通道**

### 3. 批量写地址流程 (`#write_addr comX 最大地址`)

```
┌────────────────────────────────┐
│ 1. RS485 驱动上电 (300ms 等待)   │
└────────────────────────────────┘
              ↓
┌────────────────────────────────┐
│ 2. 遍历 AutoID 0-1023           │
│    发送 A0 命令写入固定地址      │
│    - 超时: 300ms                │
│    - 间隔: 200ms                │
└────────────────────────────────┘
              ↓
┌────────────────────────────────┐
│ 3. 收到 B0 响应则写入成功        │
│    当前地址 -1 用于下一个传感器   │
└────────────────────────────────┘
              ↓
┌────────────────────────────────┐
│ 4. 保存到 config.json           │
│    rs485_x.sensors = [...]      │
└────────────────────────────────┘
              ↓
┌────────────────────────────────┐
│ 5. 输出 JSON 结果到 CDC         │
└────────────────────────────────┘
```

**时间**: 1024 × 500ms ≈ **8.5 分钟/通道**

---

## 部署

```bash
cd /path/to/ESP32_new_controller
./deploy_firmware.sh
```

---

## USB 端点限制

只有 4 个 USB 端点，`boot.py` 配置：
- 禁用 REPL (console=False)
- 启用 Data CDC
- 保留 Mass Storage

**调试**: 双击 RESET 进入安全模式

---

## NVM 模式控制

使用 `microcontroller.nvm[0]` 控制文件系统权限，无需修改 config.json：

| nvm[0] | 模式 | 设备 | 电脑 |
|--------|------|------|------|
| **17** | 日常模式 | **读写** | 只读 |
| 其他值 | 烧录模式 | 只读 | **读写** |
| - | 无USB连接 | **读写** | N/A |

**优势**：
- NVM 不受文件系统只读限制
- 任何模式下都可通过 BLE/CDC 切换
- 无 USB 连接时设备始终可写

**切换命令**：
- BLE: `{"cmd":"set_usb_rw","enabled":true}` (烧录模式)
- BLE: `{"cmd":"set_usb_rw","enabled":false}` (日常模式)
- CDC: `#enable_usb_rw` / `#disable_usb_rw`

---

## BLE 协议

### 通用格式

所有命令和响应都是 JSON 格式，以 `\n` 结尾。

### 配置命令

| 命令 | 请求 | 响应 |
|------|------|------|
| 读取配置 | `{"cmd":"read"}` | `{"cmd":"config",...}` |
| 设置设备ID | `{"cmd":"set_id","value":"xxx"}` | `{"cmd":"set_id","ok":true}` |
| 设置间隔 | `{"cmd":"set_interval","value":5}` | `{"cmd":"set_interval","ok":true}` |
| 设置休眠 | `{"cmd":"set_sleep","value":"deep"}` | `{"cmd":"set_sleep","ok":true}` |
| 设置MQTT | `{"cmd":"set_mqtt","broker":"...","port":1883,"topic":"..."}` | `{"cmd":"set_mqtt","ok":true}` |
| 设置WiFi | `{"cmd":"set_wifi","ssid":"...","password":"..."}` | `{"cmd":"set_wifi","ok":true}` |
| 同步时间 | `{"cmd":"set_time","timestamp":1739090122}` | `{"cmd":"set_time","ok":true,"time":"2026/02/09 17:35:22"}` |
| 启用4G | `{"cmd":"enable_4g"}` | `{"cmd":"enable_4g","ok":true}` |
| 禁用4G | `{"cmd":"disable_4g"}` | `{"cmd":"disable_4g","ok":true}` |

### 传感器命令

| 命令 | 请求 | 响应 |
|------|------|------|
| 扫描地址 | `{"cmd":"scan","com":"1"}` | `{"cmd":"scan_progress",...}` → `{"cmd":"scan_complete",...}` |
| 读取数据 | `{"cmd":"read_data","com":"1"}` | `{"cmd":"sensor_data",...}` (流式) → `{"cmd":"read_complete"}` |
| 读取型号 | `{"cmd":"read_model","com":"1"}` | `{"cmd":"model_data",...}` (流式) |
| 设置型号 | `{"cmd":"set_model","com":"1","model":6}` | `{"cmd":"set_model_complete",...}` |

### 配置页命令 (ConfigTab)

| 命令 | 请求 | 响应 |
|------|------|------|
| A4 全扫 | `{"cmd":"scan_all_a4","com":"1"}` | `{"cmd":"a4_result",...}` → `{"cmd":"a4_complete",...}` |
| 修改地址 | `{"cmd":"write_addr","com":"1","old_addr":N,"new_addr":N}` | `{"cmd":"write_addr_result","ok":true,...}` |
| 写型号 | `{"cmd":"write_model_single","com":"1","addr":N,"model":M}` | `{"cmd":"write_model_result","ok":true,...}` |
| 设置 Modbus ID | `{"cmd":"set_modbus_id","com":"1","addr":N,"modbus_id":M}` | `{"cmd":"set_modbus_result","ok":true,...}` |
| 批量写地址 | `{"cmd":"batch_addr_write","com":"1","start_autoid":0,"end_autoid":960,"max_addr":N,"delay":300}` | `{"cmd":"batch_result",...}` → `{"cmd":"batch_complete",...}` |

### 高级设置

| 命令 | 请求 | 响应 |
|------|------|------|
| 485扩展 | `{"cmd":"set_rs485_ext","enabled":true}` | `{"cmd":"set_rs485_ext","ok":true}` |
| 合并报文 | `{"cmd":"set_merge_segments","enabled":true}` | `{"cmd":"set_merge_segments","ok":true}` |
| 本地存储 | `{"cmd":"set_storage","enabled":true,"period":"month"}` | `{"cmd":"set_storage","ok":true}` |
| U盘模式 | `{"cmd":"set_usb_rw","enabled":true}` | `{"cmd":"set_usb_rw","ok":true}` |
| 重启 | `{"cmd":"reboot"}` | `{"cmd":"reboot","ok":true}` |

---

## 时间同步

### 对时时机

**仅在发送数据前对时**，不在开机时同步。

### 触发条件

1. RTC 年份 < 2026（说明时间未同步）
2. 当前日期 ≠ 上次发送日期（跨天）

### 对时优先级

| 优先级 | 方式 | 条件 | 说明 |
|--------|------|------|------|
| 1 | **4G 模块时间** | `network.4g.enabled` | AT+CCLK? 获取，年份 < 2026 则继续 |
| 2 | **WiFi NTP** | `network.wifi.enabled` | ntp.aliyun.com, UTC+8 |
| 3 | **ETH NTP** | `network.ethernet.enabled` + N16R2 | ntp.aliyun.com, UTC+8 |
| 4 | **BLE 手机同步** | 手动触发 | App 连接后点「同步时间」按钮 |
| - | **内部 RTC** | 兜底 | 所有方式失败时使用 |

### 未启用的方式

如果某种网络方式未在 config.json 中启用，则**不会尝试**该方式。

### 休眠走时

- **Light sleep**: RTC 持续走时
- **Deep sleep**: 依赖外部 32.768kHz 晶振（±20ppm, ~1.7秒/天漂移）

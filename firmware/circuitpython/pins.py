# pins.py - 倾斜仪控制器硬件引脚定义
# CircuitPython 版本
#
# ============================================================
# 板型配置 — 换板时只改这一行
# ============================================================
PSRAM_SIZE = "8MB"                        # "8MB" = N16R8(Octal), "2MB" = N16R2(Quad)
IS_OCTAL_PSRAM = (PSRAM_SIZE == "8MB")    # True → GPIO33-37 被占用, ETH 不可用
#
# ============================================================
# 兼容模块: N16R8 / N16R2 (同一套代码)
# ============================================================
#
# 使用说明:
#   N16R8 (Octal Flash+PSRAM): PSRAM_SIZE="8MB", ETH 引脚不定义
#   N16R2 (Quad Flash+PSRAM):  PSRAM_SIZE="2MB", ETH 引脚正常定义
#
# GPIO 不可用范围:
#   GPIO22-25: 不存在
#   GPIO26-32: PSRAM SPI (N16R8 和 N16R2 均占用)
#   GPIO33-37: Octal Flash SPI (仅 N16R8 占用, N16R2 可用)
#
# ============================================================
# 引脚总表
# ============================================================
#
#  GPIO  | 功能           | N16R8 | N16R2 | 备注
# -------|----------------|-------|-------|------------------
#    0   | XTAL_32K_P     |   ✅  |   ✅  | RTC 晶振
#    1   | XTAL_32K_N     |   ✅  |   ✅  | RTC 晶振
#    2   | LED_STATUS     |   ✅  |   ✅  | 状态指示灯
#    3   | ADC_VIN        |   ✅  |   ✅  | 输入电压 (12-24V)
#    4   | RS485_1_VCC    |   ✅  |   ✅  | COM1 传感器电源
#    5   | MODEM_PWR      |   ✅  |   ✅  | 4G 模块电源
#    6   | ADC_V5V        |   ✅  |   ✅  | 5V 电源电压
#    7   | ADC_V4G        |   ✅  |   ✅  | 4G 模块电压
#    8   | ADC_V1         |   ✅  |   ✅  | COM1 电压
#    9   | ADC_V2         |   ✅  |   ✅  | COM2 电压
#   10   | ADC_V34        |   ✅  |   ✅  | COM3/4 共享电压
#   11   | RS485_3_DE     |   ✅  |   ✅  | COM3 方向控制
#   12   | RS485_3_VCC    |   ✅  |   ✅  | COM3 传感器电源
#   13   | (空闲)          |   ✅  |   ✅  | 原 COM3 ADDR, 已合并
#   14   | RS485_4_DE     |   ✅  |   ✅  | COM4 方向控制
#   15   | RS485_ADDR     |   ✅  |   ✅  | 四通道共享扫描使能
#   16   | RS485_1_DE     |   ✅  |   ✅  | COM1 方向控制
#   17   | RS485_1_TX     |   ✅  |   ✅  | COM1 UART TX
#   18   | RS485_1_RX     |   ✅  |   ✅  | COM1 UART RX
#  19-20 | USB            |   ✅  |   ✅  | 系统固定
#   21   | ETH_INT        |   ✅  |   ✅  | W5500 中断
# 22-25  | 不存在          |   -   |   -   |
# 26-32  | PSRAM SPI      |   ❌  |   ❌  | 均被占用
#   33   | ETH_RST        |   ❌  |   ✅  | W5500 复位
#   34   | ETH_CS         |   ❌  |   ✅  | W5500 SPI CS
#   35   | ETH_MOSI       |   ❌  |   ✅  | W5500 SPI MOSI
#   36   | ETH_SCK        |   ❌  |   ✅  | W5500 SPI CLK
#   37   | ETH_MISO       |   ❌  |   ✅  | W5500 SPI MISO
#   38   | RS485_2_TX     |   ✅  |   ✅  | COM2 UART TX
#   39   | RS485_2_RX     |   ✅  |   ✅  | COM2 UART RX
#   40   | RS485_2_DE     |   ✅  |   ✅  | COM2 方向控制
#   41   | RS485_2_VCC    |   ✅  |   ✅  | COM2 传感器电源
#   42   | (空闲)          |   ✅  |   ✅  | 原 COM2 ADDR, 已合并
#   43   | MODEM_TX       |   ✅  |   ✅  | 4G UART TX
#   44   | MODEM_RX       |   ✅  |   ✅  | 4G UART RX
#   45   | RS485_4_VCC    |   ✅  |   ✅  | COM4 电源 (strapping)
#   46   | (空闲)          |   ✅  |   ✅  | 原 COM4 ADDR, 已合并
#   47   | I2C_SDA        |   ✅  |   ✅  | SC16IS752 数据
#   48   | I2C_SCL        |   ✅  |   ✅  | SC16IS752 时钟
#

import microcontroller

# ============================================================
# 系统引脚
# ============================================================
XTAL_32K_P = microcontroller.pin.GPIO0   # RTC crystal P
XTAL_32K_N = microcontroller.pin.GPIO1   # RTC crystal N
LED_STATUS = microcontroller.pin.GPIO2   # 状态 LED
USB_DN = microcontroller.pin.GPIO19      # USB D-
USB_DP = microcontroller.pin.GPIO20      # USB D+

# ============================================================
# ADC 电压监测 (全部 ADC1, 不受 WiFi 影响)
# ============================================================
ADC_VIN = microcontroller.pin.GPIO3   # 输入电压 (12-24V) - ADC1_CH2
ADC_V5V = microcontroller.pin.GPIO6   # 5V 电源电压       - ADC1_CH5
ADC_V4G = microcontroller.pin.GPIO7   # 4G 模块电压       - ADC1_CH6
ADC_V1  = microcontroller.pin.GPIO8   # COM1 电压         - ADC1_CH7
ADC_V2  = microcontroller.pin.GPIO9   # COM2 电压         - ADC1_CH8
ADC_V34 = microcontroller.pin.GPIO10  # COM3/4 共享电压   - ADC1_CH9

# ============================================================
# RS485 ADDR 扫描使能 (四通道共享 GPIO15)
# 单个 GPIO 驱动能力足够同时控制 4 路 ADDR 电路
# ============================================================
RS485_ADDR_SHARED = microcontroller.pin.GPIO15

# ============================================================
# RS485 CH1 (硬件 UART)
# ============================================================
RS485_1_VCC = microcontroller.pin.GPIO4    # 传感器电源
RS485_1_DE  = microcontroller.pin.GPIO16   # 方向控制 (DE/RE)
RS485_1_TX  = microcontroller.pin.GPIO17   # UART TX
RS485_1_RX  = microcontroller.pin.GPIO18   # UART RX

# ============================================================
# RS485 CH2 (硬件 UART)
# ============================================================
RS485_2_TX  = microcontroller.pin.GPIO38   # UART TX
RS485_2_RX  = microcontroller.pin.GPIO39   # UART RX
RS485_2_DE  = microcontroller.pin.GPIO40   # 方向控制
RS485_2_VCC = microcontroller.pin.GPIO41   # 传感器电源

# ============================================================
# RS485 CH3 (SC16IS752 扩展, TX/RX 通过 I2C)
# ============================================================
RS485_3_DE  = microcontroller.pin.GPIO11   # 方向控制
RS485_3_VCC = microcontroller.pin.GPIO12   # 传感器电源

# ============================================================
# RS485 CH4 (SC16IS752 扩展, TX/RX 通过 I2C)
# VCC 从 GPIO27 迁移到 GPIO45 (避开 PSRAM)
# GPIO45 为 strapping pin, 内置下拉, 上电默认 LOW = 安全
# ============================================================
RS485_4_DE  = microcontroller.pin.GPIO14   # 方向控制
RS485_4_VCC = microcontroller.pin.GPIO45   # 传感器电源

# ============================================================
# W5500 以太网 SPI
# N16R8: GPIO33-37 被 Octal Flash 占用, 不定义 (避免 import 时出错)
# N16R2: GPIO33-37 可用, 以太网正常工作
# ============================================================
ETH_INT  = microcontroller.pin.GPIO21   # 中断 (所有板型均可用)

if not IS_OCTAL_PSRAM:
    # N16R2: GPIO33-37 可用
    ETH_RST  = microcontroller.pin.GPIO33   # 复位
    ETH_CS   = microcontroller.pin.GPIO34   # SPI CS
    ETH_MOSI = microcontroller.pin.GPIO35   # SPI MOSI
    ETH_SCK  = microcontroller.pin.GPIO36   # SPI CLK
    ETH_MISO = microcontroller.pin.GPIO37   # SPI MISO
else:
    # N16R8: ETH 引脚不可用, 设为 None
    ETH_RST  = None
    ETH_CS   = None
    ETH_MOSI = None
    ETH_SCK  = None
    ETH_MISO = None

# ============================================================
# 4G 模块 SIM7672E
# ============================================================
MODEM_PWR = microcontroller.pin.GPIO5    # 电源控制
MODEM_TX  = microcontroller.pin.GPIO43   # UART TX
MODEM_RX  = microcontroller.pin.GPIO44   # UART RX

# ============================================================
# I2C 总线 (SC16IS752 双通道 UART 扩展)
# ============================================================
I2C_SDA = microcontroller.pin.GPIO47
I2C_SCL = microcontroller.pin.GPIO48

# ============================================================
# 通道配置表 (驱动通过此表获取引脚)
# 所有通道共享 RS485_ADDR_SHARED (GPIO15) 作为扫描使能
# ============================================================
RS485_CHANNELS = {
    1: {
        "tx": RS485_1_TX, "rx": RS485_1_RX, "de": RS485_1_DE,
        "vcc": RS485_1_VCC, "address": RS485_ADDR_SHARED,
        "type": "hardware"
    },
    2: {
        "tx": RS485_2_TX, "rx": RS485_2_RX, "de": RS485_2_DE,
        "vcc": RS485_2_VCC, "address": RS485_ADDR_SHARED,
        "type": "hardware"
    },
    3: {
        "de": RS485_3_DE, "vcc": RS485_3_VCC, "address": RS485_ADDR_SHARED,
        "type": "sc16is752"
    },
    4: {
        "de": RS485_4_DE, "vcc": RS485_4_VCC, "address": RS485_ADDR_SHARED,
        "type": "sc16is752"
    },
}

ADC_CHANNELS = {
    "vin": ADC_VIN,
    "V5V": ADC_V5V,
    "V4G": ADC_V4G,
    "V1": ADC_V1,
    "V2": ADC_V2,
    "V34": ADC_V34,
}

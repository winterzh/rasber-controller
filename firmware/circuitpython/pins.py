# pins.py - 柔性测斜仪控制器硬件引脚定义
# CircuitPython 版本
# 基于原理图: SCH_Schematic1_2026-03-13
# 模块: ESP32-S3-WROOM-1 N8R2
#
# ============================================================
# 引脚总表 (原理图 → 软件映射)
# ============================================================
#
# 原理图通道映射:
#   原理图 CH4 → 软件 COM1 (硬件 UART, GPIO 直连)
#   原理图 CH3 → 软件 COM2 (硬件 UART, GPIO 直连)
#   原理图 CH2 → 软件 COM3 (SC16IS752 I2C 扩展)
#   原理图 CH1 → 软件 COM4 (SC16IS752 I2C 扩展)
#
#  模块Pin | GPIO  | 原理图信号      | 软件功能
# ---------|-------|-----------------|------------------
#     4    | GPIO4 | V485_4S         | ADC COM共享电压
#     5    | GPIO5 | VIN_S           | ADC 输入电压
#     6    | GPIO6 | VOUTCTRL1       | COM4 电源
#     7    | GPIO7 | 485CTRL1        | COM4 DE/RE
#     8    | GPIO15| XTAL_32K_P      | RTC 晶振
#     9    | GPIO16| XTAL_32K_N      | RTC 晶振
#    10    | GPIO17| SCAN1           | COM4 扫描
#    11    | GPIO18| VOUTCTRL2       | COM3 电源
#    12    | GPIO8 | 485CTR2         | COM3 DE/RE
#    13    | GPIO19| USB D-          | USB
#    14    | GPIO20| USB D+          | USB
#    15    | GPIO3 | INT_L           | W5500 中断
#    16    | GPIO46| RST_L           | W5500 复位
#    17    | GPIO9 | SPI_MOSI        | W5500 SPI
#    18    | GPIO10| SPI_MISO        | W5500 SPI
#    19    | GPIO11| SPI_CLK         | W5500 SPI
#    20    | GPIO12| SPI_CS          | W5500 SPI
#    21    | GPIO13| VOUTCTRL3       | COM2 电源
#    22    | GPIO14| 485CTR3         | COM2 DE/RE
#    23    | GPIO21| SCAN2           | COM3 扫描
#    24    | GPIO47| 3V3CTL          | 3.3V 电源控制
#    25    | GPIO48| VOUTCTRL4       | COM1 电源
#    26    | GPIO45| 485CTR4         | COM1 DE/RE
#    27    | GPIO0 | BOOT            | 启动引脚
#    28    | GPIO35| SC16_SDA        | I2C SDA
#    29    | GPIO36| SC16_SCL        | I2C SCL
#    30    | GPIO37| SCAN4           | COM1 扫描
#    31    | GPIO38| CURCTR          | (未使用)
#    32    | GPIO39| TX3             | COM2 TX
#    33    | GPIO40| RX3             | COM2 RX
#    34    | GPIO41| SCAN3           | COM2 扫描
#    35    | GPIO42| V4G_CTRL        | 4G 电源控制
#    36    | GPIO44| U_4G_TX(RXD0)   | 4G UART RX
#    37    | GPIO43| U_4G_RX(TXD0)   | 4G UART TX
#    38    | GPIO2 | TX4             | COM1 TX
#    39    | GPIO1 | RX4             | COM1 RX
#

import microcontroller

# ============================================================
# 系统引脚
# ============================================================
XTAL_32K_P = microcontroller.pin.GPIO15   # RTC crystal P
XTAL_32K_N = microcontroller.pin.GPIO16   # RTC crystal N
USB_DN = microcontroller.pin.GPIO19       # USB D-
USB_DP = microcontroller.pin.GPIO20       # USB D+
CTRL_3V3 = microcontroller.pin.GPIO47     # 3.3V 电源总控

# ============================================================
# ADC 电压监测 (仅 2 路)
# ============================================================
ADC_VIN  = microcontroller.pin.GPIO5   # 输入电压 (VIN_S) - ADC1_CH4
ADC_V485 = microcontroller.pin.GPIO4   # COM1~4 共享电压 (V485_4S) - ADC1_CH3

# ============================================================
# RS485 COM1 (原理图 CH4, 硬件 UART)
# ============================================================
RS485_1_TX   = microcontroller.pin.GPIO2    # UART TX (TX4)
RS485_1_RX   = microcontroller.pin.GPIO1    # UART RX (RX4)
RS485_1_DE   = microcontroller.pin.GPIO45   # DE/RE (485CTR4)
RS485_1_VCC  = microcontroller.pin.GPIO48   # 电源 (VOUTCTRL4)
RS485_1_SCAN = microcontroller.pin.GPIO37   # 扫描使能 (SCAN4)

# ============================================================
# RS485 COM2 (原理图 CH3, 硬件 UART)
# ============================================================
RS485_2_TX   = microcontroller.pin.GPIO39   # UART TX (TX3)
RS485_2_RX   = microcontroller.pin.GPIO40   # UART RX (RX3)
RS485_2_DE   = microcontroller.pin.GPIO14   # DE/RE (485CTR3)
RS485_2_VCC  = microcontroller.pin.GPIO13   # 电源 (VOUTCTRL3)
RS485_2_SCAN = microcontroller.pin.GPIO41   # 扫描使能 (SCAN3)

# ============================================================
# RS485 COM3 (原理图 CH2, SC16IS752 扩展)
# ============================================================
RS485_3_DE   = microcontroller.pin.GPIO8    # DE/RE (485CTR2)
RS485_3_VCC  = microcontroller.pin.GPIO18   # 电源 (VOUTCTRL2)
RS485_3_SCAN = microcontroller.pin.GPIO21   # 扫描使能 (SCAN2)

# ============================================================
# RS485 COM4 (原理图 CH1, SC16IS752 扩展)
# ============================================================
RS485_4_DE   = microcontroller.pin.GPIO7    # DE/RE (485CTRL1)
RS485_4_VCC  = microcontroller.pin.GPIO6    # 电源 (VOUTCTRL1)
RS485_4_SCAN = microcontroller.pin.GPIO17   # 扫描使能 (SCAN1)

# ============================================================
# W5500 以太网 SPI (不再受 PSRAM 影响)
# ============================================================
ETH_MOSI = microcontroller.pin.GPIO9    # SPI MOSI
ETH_MISO = microcontroller.pin.GPIO10   # SPI MISO
ETH_SCK  = microcontroller.pin.GPIO11   # SPI CLK
ETH_CS   = microcontroller.pin.GPIO12   # SPI CS
ETH_INT  = microcontroller.pin.GPIO3    # 中断
ETH_RST  = microcontroller.pin.GPIO46   # 复位

# ============================================================
# 4G 模块 SIM7672
# ============================================================
MODEM_PWR = microcontroller.pin.GPIO42   # PEN 电源使能 (V4G_CTRL)
MODEM_TX  = microcontroller.pin.GPIO43   # UART TX (MCU TXD0 → 4G RXD)
MODEM_RX  = microcontroller.pin.GPIO44   # UART RX (4G TXD → MCU RXD0)

# ============================================================
# I2C 总线 (SC16IS752 双通道 UART 扩展)
# ============================================================
I2C_SDA = microcontroller.pin.GPIO35   # SC16_SDA
I2C_SCL = microcontroller.pin.GPIO36   # SC16_SCL

# ============================================================
# 通道配置表 (驱动通过此表获取引脚)
# 每通道独立 SCAN 引脚
# 上电默认全部断电，仅读数时打开
# ============================================================
RS485_CHANNELS = {
    1: {
        "tx": RS485_1_TX, "rx": RS485_1_RX, "de": RS485_1_DE,
        "vcc": RS485_1_VCC, "scan": RS485_1_SCAN,
        "type": "hardware"
    },
    2: {
        "tx": RS485_2_TX, "rx": RS485_2_RX, "de": RS485_2_DE,
        "vcc": RS485_2_VCC, "scan": RS485_2_SCAN,
        "type": "hardware"
    },
    3: {
        "de": RS485_3_DE, "vcc": RS485_3_VCC, "scan": RS485_3_SCAN,
        "type": "sc16is752"
    },
    4: {
        "de": RS485_4_DE, "vcc": RS485_4_VCC, "scan": RS485_4_SCAN,
        "type": "sc16is752"
    },
}

ADC_CHANNELS = {
    "vin": ADC_VIN,
    "V485": ADC_V485,
}

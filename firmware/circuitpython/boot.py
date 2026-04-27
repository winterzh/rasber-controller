# boot.py - ESP32-S3
# uses NVM 控制 USB readwrite模式
# nvm[0] = 17: 设备可readwrite(daily mode)，电脑readonly
# nvm[0] = 其他value: 电脑可readwrite(flash mode)，设备readonly

import usb_cdc
import usb_hid
import usb_midi
import storage
import microcontroller
import digitalio

# ============================================================
# 启动时立即设置所有输出 GPIO 到安全电平
# 防止深度休眠醒来后 GPIO 浮空导致外设误动作
# ============================================================

def _init_safe_gpio():
    """将所有输出引脚设为安全电平 (在 code.py 驱动初始化前)
    每个引脚独立 try/except，避免单个引脚冲突导致启动失败
    基于原理图 SCH_Schematic1_2026-03-13
    """
    _safe_pins = []
    
    _pin_list = [
        # RS485 VCC (VOUTCTRL) → LOW (传感器断电, 上电默认全断)
        (microcontroller.pin.GPIO48, "COM1_VCC(VOUTCTRL4)"),
        (microcontroller.pin.GPIO13, "COM2_VCC(VOUTCTRL3)"),
        (microcontroller.pin.GPIO18, "COM3_VCC(VOUTCTRL2)"),
        (microcontroller.pin.GPIO6,  "COM4_VCC(VOUTCTRL1)"),
        # RS485 DE → LOW (接收模式)
        (microcontroller.pin.GPIO45, "COM1_DE(485CTR4)"),
        (microcontroller.pin.GPIO14, "COM2_DE(485CTR3)"),
        (microcontroller.pin.GPIO8,  "COM3_DE(485CTR2)"),
        (microcontroller.pin.GPIO7,  "COM4_DE(485CTRL1)"),
        # RS485 SCAN → LOW (各通道独立)
        (microcontroller.pin.GPIO37, "COM1_SCAN(SCAN4)"),
        (microcontroller.pin.GPIO41, "COM2_SCAN(SCAN3)"),
        (microcontroller.pin.GPIO21, "COM3_SCAN(SCAN2)"),
        (microcontroller.pin.GPIO17, "COM4_SCAN(SCAN1)"),
        # W5500 ETH_RST → LOW then HIGH
        (microcontroller.pin.GPIO46, "ETH_RST"),
        # 4G 电源 → LOW (默认关闭)
        (microcontroller.pin.GPIO42, "4G_PWR(V4G_CTRL)"),
    ]
    
    ok_count = 0
    for pin, name in _pin_list:
        try:
            p = digitalio.DigitalInOut(pin)
            p.direction = digitalio.Direction.OUTPUT
            p.value = False
            _safe_pins.append(p)
            ok_count += 1
        except Exception as e:
            print(f"[BOOT] GPIO {name} 跳过: {e}")
    
    # 释放所有引脚 (code.py 的驱动会重新初始化)
    for p in _safe_pins:
        p.deinit()
    
    print(f"[BOOT] N8R2 GPIO 安全初始化: {ok_count}/{len(_pin_list)}")

_init_safe_gpio()
print("[BOOT] GPIO 安全初始化完成")

# ============================================================
# USB 配置
# ============================================================

usb_hid.disable()
usb_midi.disable()
usb_cdc.enable(console=False, data=True)

# NVM 布局:
#   nvm[0]    = USB 模式标志 (17=daily, 其他=flash)
#   nvm[1:9]  = 保留
#   nvm[10:]  = ConfigManager 数据
nvm_value = microcontroller.nvm[0]
daily_mode = (nvm_value == 17)  # 17 = daily mode（设备writable）

if daily_mode:
    # daily mode：设备可readwrite，电脑readonly
    storage.remount("/", readonly=False)
    print(f"[BOOT] daily mode(nvm={nvm_value}) - 设备可readwrite，电脑readonly")
    print("[BOOT] Data CDC enabled. USB mass storage read only.")
else:
    # flash mode：电脑可readwrite，设备readonly
    print(f"[BOOT] flash mode(nvm={nvm_value}) - 电脑可readwrite，设备readonly")
    print("[BOOT] Data CDC enabled. USB mass storage read & write.")


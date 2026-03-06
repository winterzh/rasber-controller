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
    """
    # 导入板型标志
    from pins import IS_OCTAL_PSRAM
    
    _safe_pins = []
    
    # 所有板型通用的引脚
    _pin_list = [
        # RS485 VCC → LOW (传感器断电)
        (microcontroller.pin.GPIO4,  "RS485_1_VCC"),
        (microcontroller.pin.GPIO41, "RS485_2_VCC"),
        (microcontroller.pin.GPIO12, "RS485_3_VCC"),
        (microcontroller.pin.GPIO45, "RS485_4_VCC"),
        # RS485 DE → LOW (接收模式)
        (microcontroller.pin.GPIO16, "RS485_1_DE"),
        (microcontroller.pin.GPIO40, "RS485_2_DE"),
        (microcontroller.pin.GPIO11, "RS485_3_DE"),
        (microcontroller.pin.GPIO14, "RS485_4_DE"),
        # RS485 ADDR → LOW (共享, 单引脚控制 4 路)
        (microcontroller.pin.GPIO15, "RS485_ADDR_SHARED"),
        # LED → LOW
        (microcontroller.pin.GPIO2,  "LED"),
    ]
    
    # N16R2 才初始化 ETH_RST (GPIO33)
    if not IS_OCTAL_PSRAM:
        _pin_list.append((microcontroller.pin.GPIO33, "ETH_RST"))
    
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
    
    board_type = "N16R8(8MB)" if IS_OCTAL_PSRAM else "N16R2(2MB)"
    print(f"[BOOT] {board_type} GPIO 安全初始化: {ok_count}/{len(_pin_list)}")

_init_safe_gpio()
print("[BOOT] GPIO 安全初始化完成")

# ============================================================
# USB 配置
# ============================================================

usb_hid.disable()
usb_midi.disable()
usb_cdc.enable(console=False, data=True)

# read NVM 标志
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


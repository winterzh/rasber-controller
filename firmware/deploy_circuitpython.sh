#!/bin/bash
# deploy_circuitpython.sh - 部署 CircuitPython 代码到 CIRCUITPY 驱动器
# 柔性测斜仪控制器

set -e

SRC_DIR="$(dirname "$0")/circuitpython"
DST_DIR="/Volumes/CIRCUITPY"

# 检查源目录
if [ ! -d "$SRC_DIR" ]; then
    echo "❌ 源目录不存在: $SRC_DIR"
    exit 1
fi

# 检查目标驱动器
if [ ! -d "$DST_DIR" ]; then
    echo "❌ CIRCUITPY 驱动器未挂载!"
    echo ""
    echo "请确保:"
    echo "  1. 已烧录 CircuitPython 固件"
    echo "  2. 设备已通过 USB 连接"
    echo "  3. 如果看不到驱动器，尝试双击 RESET 进入安全模式"
    exit 1
fi

echo "📦 开始部署 CircuitPython 代码..."
echo "   源: $SRC_DIR"
echo "   目标: $DST_DIR"
echo ""

# 创建目录结构
echo "📁 创建目录结构..."
mkdir -p "$DST_DIR/app"
mkdir -p "$DST_DIR/drivers"
mkdir -p "$DST_DIR/lib"
mkdir -p "$DST_DIR/data"

# 复制核心文件
echo "📄 复制核心文件..."
cp "$SRC_DIR/boot.py" "$DST_DIR/"
cp "$SRC_DIR/code.py" "$DST_DIR/"
cp "$SRC_DIR/pins.py" "$DST_DIR/"

# 复制配置文件
# config.json.default 总是覆盖
if [ -f "$SRC_DIR/config.json.default" ]; then
    cp "$SRC_DIR/config.json.default" "$DST_DIR/"
    echo "   ✓ config.json.default"
fi

# config.json 也覆盖
cp "$SRC_DIR/config.json" "$DST_DIR/"
echo "   ✓ config.json"

# 复制应用模块
echo "📄 复制应用模块..."
cp "$SRC_DIR/app/"*.py "$DST_DIR/app/"

# 复制驱动
echo "📄 复制硬件驱动..."
cp "$SRC_DIR/drivers/"*.py "$DST_DIR/drivers/"

# 复制协议库
echo "📄 复制协议库..."
cp "$SRC_DIR/lib/"*.py "$DST_DIR/lib/"

# 创建 __init__.py (如果不存在)
touch "$DST_DIR/app/__init__.py"
touch "$DST_DIR/drivers/__init__.py"
touch "$DST_DIR/lib/__init__.py"

# 同步文件系统
echo "🔄 同步文件系统..."
sync

echo ""
echo "✅ 部署完成!"
echo ""
echo "下一步:"
echo "  1. 断开 USB 线"
echo "  2. 重新连接 USB 线"
echo "  3. 打开串口监视器查看启动日志"
echo ""
echo "串口命令 (macOS):"
echo "  ls /dev/cu.usb*"
echo "  screen /dev/cu.usbmodemXXXX 115200"

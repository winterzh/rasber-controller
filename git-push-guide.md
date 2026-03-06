# Git 推送指南

> 将固件 (firmware) 和 Android App (android) 推送到 GitHub 仓库

## 📋 前置条件

- 已安装 Git
- 目标仓库: https://github.com/winterzh/rasber-controller
- **GitHub 账号**: `winterzh`
- **GitHub 密码**: `P@ssw0rd`

---

## 🚀 一键推送脚本

在项目根目录 (`ESP32_new_controller/`) 执行以下命令：

```bash
#!/bin/bash
# ====================================
# Git 推送脚本 - 固件 + Android App
# ====================================

# 0. 定义变量
PROJ_ROOT="$(cd "$(dirname "$0")" && pwd)"
PUSH_DIR="${PROJ_ROOT}/git_to_push"
REMOTE_URL="https://github.com/winterzh/rasber-controller.git"

# 1. 清空并重建 git_to_push 目录
rm -rf "${PUSH_DIR}"
mkdir -p "${PUSH_DIR}"

# 2. 复制固件目录 (排除 .DS_Store 和 .bin 固件文件)
rsync -av --exclude='.DS_Store' \
          --exclude='*.bin' \
          --exclude='*.pdf' \
          "${PROJ_ROOT}/firmware/" "${PUSH_DIR}/firmware/"

# 3. 复制 Android 目录 (排除构建产物和 IDE 配置)
rsync -av --exclude='.DS_Store' \
          --exclude='.gradle/' \
          --exclude='.idea/' \
          --exclude='build/' \
          --exclude='app/build/' \
          --exclude='local.properties' \
          --exclude='*.pdf' \
          --exclude='key.jks' \
          "${PROJ_ROOT}/android/" "${PUSH_DIR}/android/"

# 4. 复制 README 到推送目录
cp "${PROJ_ROOT}/README.md" "${PUSH_DIR}/README.md"

# 5. 清除所有密码信息 (替换为 ***)
echo "🔒 正在清除密码信息..."

# 5a. 清除 config.json.default 中的 mqtt_pass 值
sed -i '' 's/"mqtt_pass": "[^"]*"/"mqtt_pass": "***"/g' \
    $(find "${PUSH_DIR}" -name "config.json*" -type f 2>/dev/null)

# 5b. 清除 config.json.default 中的 wifi password 值
sed -i '' 's/"password": "[^"]*"/"password": "***"/g' \
    $(find "${PUSH_DIR}" -name "config.json*" -type f 2>/dev/null)

# 5c. 清除 device_reporter.py 中的硬编码密码 _REPORT_PASS
sed -i '' 's/_REPORT_PASS = "[^"]*"/_REPORT_PASS = "***"/g' \
    $(find "${PUSH_DIR}" -name "device_reporter.py" -type f 2>/dev/null)

# 5d. 通用搜索: 查找所有文件中剩余的密码模式并替换
# 匹配 "mqtt_pass": "xxx" 或 'mqtt_pass': 'xxx' 等
find "${PUSH_DIR}" -type f \( -name "*.py" -o -name "*.json" -o -name "*.json.default" \) \
    -exec grep -l -i 'pass\|password' {} \; | while read f; do
    sed -i '' \
        -e 's/"mqtt_pass": "[^"]*"/"mqtt_pass": "***"/g' \
        -e 's/"password": "[^"]*"/"password": "***"/g' \
        -e 's/_REPORT_PASS = "[^"]*"/_REPORT_PASS = "***"/g' \
        "$f"
    echo "  ✅ 已清除: $f"
done

echo "🔒 密码清除完成"

# 6. 去除标题中的 ESP32 相关字样
echo "🏷️ 正在去除 ESP32 相关字样..."
find "${PUSH_DIR}" -type f \( -name "*.md" -o -name "*.py" -o -name "*.sh" \) \
    -exec sed -i '' \
        -e 's/ESP32-S3 //g' \
        -e 's/ESP32 //g' \
        {} \;
echo "🏷️ ESP32 字样去除完成"

# 7. 创建 .gitignore
cat > "${PUSH_DIR}/.gitignore" << 'EOF'
# macOS
.DS_Store
._*

# Android
android/.gradle/
android/.idea/
android/build/
android/app/build/
android/local.properties
android/key.jks
*.apk
*.aab

# Firmware
firmware/*.bin
firmware/*.pdf

# General
*.pdf
*.pyc
__pycache__/
.env
EOF

# 8. 初始化 Git 仓库并推送
cd "${PUSH_DIR}"

git init
git remote add origin "${REMOTE_URL}"
git add -A
git commit -m "feat: 上传固件和Android App源码

- firmware/: ESP32-S3 CircuitPython 固件 (同步架构)
- android/: Kotlin + Jetpack Compose 配置 App
- README.md: 项目完整说明"

# 9. 推送到 main 分支
git branch -M main
git push -u origin main

echo ""
echo "✅ 推送完成！"
echo "📦 仓库地址: ${REMOTE_URL}"
```

---

## 📝 手动执行步骤

如果不想运行脚本，可以逐步手动执行：

### Step 1: 准备推送目录

```bash
cd /Users/dztdash/Antigravity/ESP32_new_controller

# 清空并重建
rm -rf git_to_push
mkdir -p git_to_push
```

### Step 2: 复制固件

```bash
rsync -av --exclude='.DS_Store' \
          --exclude='*.bin' \
          --exclude='*.pdf' \
          firmware/ git_to_push/firmware/
```

### Step 3: 复制 Android App

```bash
rsync -av --exclude='.DS_Store' \
          --exclude='.gradle/' \
          --exclude='.idea/' \
          --exclude='build/' \
          --exclude='app/build/' \
          --exclude='local.properties' \
          --exclude='*.pdf' \
          --exclude='key.jks' \
          android/ git_to_push/android/
```

### Step 4: 复制 README

```bash
cp README.md git_to_push/README.md
```

### Step 5: 清除密码 + 去除 ESP32 字样

```bash
# 搜索 git_to_push 下所有含密码的文件并替换为 ***
find git_to_push -type f \( -name "*.py" -o -name "*.json" -o -name "*.json.default" \) \
    -exec grep -l -i 'pass\|password' {} \; | while read f; do
    sed -i '' \
        -e 's/"mqtt_pass": "[^"]*"/"mqtt_pass": "***"/g' \
        -e 's/"password": "[^"]*"/"password": "***"/g' \
        -e 's/_REPORT_PASS = "[^"]*"/_REPORT_PASS = "***"/g' \
        "$f"
    echo "✅ 已清除: $f"
done
```

> 已知密码位置：
> - `firmware/circuitpython/config.json.default` — `mqtt_pass` 和 WiFi `password`
> - `firmware/circuitpython/app/device_reporter.py` — `_REPORT_PASS` 硬编码密码

```bash
# 去除所有 .md / .py / .sh 文件标题中的 ESP32 字样
find git_to_push -type f \( -name "*.md" -o -name "*.py" -o -name "*.sh" \) \
    -exec sed -i '' -e 's/ESP32-S3 //g' -e 's/ESP32 //g' {} \;
```

### Step 6: 初始化 Git 并推送

```bash
cd git_to_push
git init
git remote add origin https://github.com/winterzh/rasber-controller.git
git add -A
git commit -m "feat: 上传固件和Android App源码"
git branch -M main
git push -u origin main
```

---

## ⚠️ 注意事项

1. **首次推送**: 如果仓库已有内容，使用 `git push -u origin main --force` 强制覆盖
2. **后续更新**: 再次运行脚本即可，会清空 `git_to_push` 并重新复制
3. **敏感文件**: `key.jks`（签名密钥）和 `local.properties` 已被排除
4. **密码清除**: 所有密码值会被自动替换为 `***`（MQTT 密码、WiFi 密码、硬编码密码）
5. **大文件**: `.bin` 固件二进制文件已被排除，避免仓库过大

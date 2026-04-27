# 柔性测斜仪私有协议 — 完整流程规范

> **目标读者**：CircuitPython 固件移植开发者。本文档从 PC 客户端源码中提取，描述**设备端需要实现的所有交互流程**。

---

## 一、帧格式基础

### 1.1 发送帧 (PC → 设备)

```
[0xCC] [Len] [Cmd_H] [Cmd_L] [Data...] [XOR] [0xEE]
```

| 字段 | 字节数 | 说明 |
|------|--------|------|
| Header | 1 | 固定 `0xCC` |
| Len | 1 | 整帧总长度 = `1 + 1 + 2 + len(Data) + 1 + 1` |
| Cmd | 2 | 命令码，大端序 (高字节在前，一般高字节=0x00) |
| Data | N | 命令参数 |
| XOR | 1 | 从 Header 到 Data 最后一字节的 XOR 校验 |
| End | 1 | 固定 `0xEE` |

### 1.2 响应帧 (设备 → PC)

```
[0xDD] [Len] [Rsp_H] [Rsp_L] [Payload...] [XOR] [0xEE]
```

结构完全相同，仅 Header = `0xDD`，Cmd 字段变为响应码。

### 1.3 XOR 校验算法

```python
def xor_checksum(data: bytes) -> int:
    result = 0
    for b in data:
        result ^= b
    return result
```

校验范围：**从 Header (0xCC/0xDD) 到 Data 最后一字节**，不含 XOR 和 0xEE 自身。

### 1.4 构建帧的参考实现

```python
def build_frame(cmd: int, data: bytes = b'') -> bytes:
    length = 1 + 1 + 2 + len(data) + 1 + 1
    frame = bytes([0xCC, length, (cmd >> 8) & 0xFF, cmd & 0xFF]) + data
    checksum = xor_checksum(frame)
    frame += bytes([checksum, 0xEE])
    return frame
```

### 1.5 地址编码

固定地址为 **4 字节大端无符号整数** (`>I`)，如十进制 `26010001` = `0x018CC8A1`。

---

## 二、流程一：地址扫描 (A2 命令)

> 遍历 AutoID 范围 (0~1023)，查询每个 AutoID 对应的固定地址，发现在线设备。

### 2.1 命令：获取固定地址 (0xA2 → 0xB2)

**发送帧** (8 字节)：
```
CC 08 00 A2 [AutoID:2] [XOR] EE
```

| 字段 | 偏移 | 长度 | 说明 |
|------|------|------|------|
| AutoID | 4 | 2 | 大端序 16 位无符号整数, 范围 0~1023 |

**响应帧** (12 字节)：
```
DD 0C 00 B2 [AutoID:2] [FixedAddr:4] [XOR] EE
```

| 字段 | Payload偏移 | 长度 | 说明 |
|------|-------------|------|------|
| AutoID | 0 | 2 | 回显请求的 AutoID |
| FixedAddr | 2 | 4 | 该设备的固定地址 (大端) |

### 2.2 完整流程

```
┌─ PC 端 ─────────────────────────────────────────────┐
│ for auto_id in range(start_autoid, end_autoid + 1):  │
│   1. 构建帧: CC 08 00 A2 [auto_id:2B] [XOR] EE      │
│   2. 发送到串口                                       │
│   3. 等待响应 (超时 300ms, 期望 12 字节)              │
│   4. if 收到响应:                                     │
│        解析 B2 响应                                   │
│        提取 AutoID(2B) + FixedAddr(4B)               │
│        if FixedAddr != 0 且 != 0xFFFFFFFF:           │
│           → 有效设备! 记录 (AutoID, FixedAddr)       │
│   5. 延时 200ms (可配置)                              │
└──────────────────────────────────────────────────────┘
```

### 2.3 设备端实现要点

```
┌─ 设备端 (固件) ───────────────────────────────────────┐
│ 1. 接收到 0xA2 命令                                    │
│ 2. 提取 AutoID (payload[0:2])                         │
│ 3. 检查 AutoID 是否匹配本机                            │
│    ─ AutoID 是设备上电后根据固定地址哈希/计算得到的     │
│ 4. if 匹配:                                           │
│      构建 B2 响应:                                     │
│      DD 0C 00 B2 [本机AutoID:2] [本机FixedAddr:4] XOR EE │
│      发送响应                                          │
│ 5. if 不匹配: 不响应 (静默)                            │
└───────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> 超时仅 **300ms**，不匹配时设备**必须保持静默**，不能发送错误帧。

---

## 三、流程二：读取传感器数据 (0x5A 不休眠)

> 根据固定地址逐个读取设备的 ABZ 轴数据、电压、版本、状态。

### 3.1 命令：读取数据不休眠 (0x5A → 0x5B)

**发送帧** (10 字节)：
```
CC 0A 00 5A [FixedAddr:4] [XOR] EE
```

**响应帧 — 三轴模式** (27 字节)：
```
DD 1B 00 5B [FixedAddr:4] [A_axis:4f] [Z_axis:4f] [B_axis:4f] [VoltVer:4f] [Status:1] [XOR] EE
```

**响应帧 — 双轴模式** (23 字节)：
```
DD 17 00 5B [FixedAddr:4] [A_axis:4f] [B_axis:4f] [VoltVer:4f] [Status:1] [XOR] EE
```

### 3.2 Payload 字段定义

| 字段 | Payload偏移(三轴) | Payload偏移(双轴) | 长度 | 类型 | 说明 |
|------|-------------------|-------------------|------|------|------|
| FixedAddr | 0 | 0 | 4 | uint32 BE | 设备固定地址 |
| A_axis | 4 | 4 | 4 | float32 BE | A轴数据 (IEEE754) |
| Z_axis | 8 | — | 4 | float32 BE | Z轴数据 (仅三轴) |
| B_axis | 12 | 8 | 4 | float32 BE | B轴数据 |
| VoltVer | 16 | 12 | 4 | float32 BE | 电压+版本编码 |
| Status | 20 | 16 | 1 | uint8 | 状态码 |

**双轴/三轴判断**：PC 端通过 **payload 长度** 判断：
- `len(payload) < 21` → 双轴 (payload=17B)
- `len(payload) >= 21` → 三轴 (payload=21B)

### 3.3 VoltVer 编码规则

```
VoltVer = voltage × 100 + version
```

例如 `334.00` → 电压 = `3.3V`，版本 = `4.00`

PC 端解码：
```python
voltage = int(voltage_version / 10) / 10.0   # 3.3
version = voltage_version % 10                # 4.0
```

### 3.4 Status 状态码

| 值 | 含义 |
|----|------|
| `0x03` | 正常 |
| `0xFD` | 量程过大 |
| `0xFE` | 传感器类型错误 |

### 3.5 完整流程

```
┌─ PC 端 ─────────────────────────────────────────────┐
│ for each device_addr in address_list:                 │
│   1. 构建帧: CC 0A 00 5A [addr:4B] [XOR] EE          │
│   2. 发送到串口                                       │
│   3. 等待响应 (超时 5000ms)                           │
│   4. if 收到响应:                                     │
│        解析 5B 响应帧                                 │
│        判断双轴/三轴 (payload 长度)                    │
│        提取: FixedAddr, A/B/Z轴, 电压, 版本, 状态     │
│        解码电压版本: voltage = int(VoltVer/10)/10      │
│   5. 延时 100ms                                       │
└──────────────────────────────────────────────────────┘
```

### 3.6 设备端实现要点

```
┌─ 设备端 (固件) ──────────────────────────────────────┐
│ 1. 接收到 0x5A 命令                                   │
│ 2. 提取 FixedAddr (payload[0:4])                      │
│ 3. if FixedAddr 匹配本机:                             │
│      a. 采集 IMU 数据 (A/B/Z轴)                      │
│      b. 读取电压、版本号                               │
│      c. 计算 VoltVer = voltage*100 + version          │
│      d. 确定状态码                                     │
│      e. 按三轴或双轴格式打包响应                       │
│      f. 构建 0x5B 响应帧并发送                        │
│      g. 设备保持唤醒 (不进入休眠)                      │
│ 4. if 不匹配: 不响应                                  │
└───────────────────────────────────────────────────────┘
```

> [!NOTE]
> 0xA3 命令与 0x5A 完全相同，唯一区别是设备在发送 0x3B 响应后**进入休眠**。

---

## 四、流程三：读取型号 (0xC8 → 0x8D)

### 4.1 帧格式

**发送帧** (10 字节)：
```
CC 0A 00 C8 [FixedAddr:4] [XOR] EE
```

**响应帧**：
```
DD [Len] 00 8D [FixedAddr:4] [Model:1] [XOR] EE
```

| 字段 | Payload偏移 | 长度 | 说明 |
|------|-------------|------|------|
| FixedAddr | 0 | 4 | 设备地址 |
| Model | 4 | 1 | 型号值 (0~12) |

### 4.2 型号值定义

| 值 | 类型 | 说明 |
|----|------|------|
| 0 | 三轴阵列式 | 默认 (Z=g) |
| 1 | 三轴阵列式 | 水平安装 (mm) |
| 2 | 三轴阵列式 | 垂直安装 (Z=1000mm) |
| 6 | 双轴固定式 | 默认 (Z=g) |
| 7 | 双轴固定式 | mm单位 |
| 10 | 三轴固定式 | 默认 (Z=g) |
| 11 | 三轴固定式 | 水平安装 (mm) |
| 12 | 三轴固定式 | 垂直安装 (Z=1000mm) |

### 4.3 完整流程

```
┌─ PC 端 ─────────────────────────────────────────────┐
│ for each device_addr in address_list:                 │
│   1. 构建帧: CC 0A 00 C8 [addr:4B] [XOR] EE          │
│   2. 发送到串口                                       │
│   3. 等待响应 (超时 2000ms)                           │
│   4. if 收到响应:                                     │
│        解析 8D 响应                                   │
│        model = payload[4]                             │
│   5. 延时 100ms                                       │
└──────────────────────────────────────────────────────┘
```

### 4.4 设备端实现要点

```
┌─ 设备端 (固件) ──────────────────────────────────────┐
│ 1. 接收到 0xC8 命令                                   │
│ 2. 提取 FixedAddr                                     │
│ 3. if 匹配: 读取存储的型号值, 构建 0x8D 响应并发送    │
│ 4. if 不匹配: 不响应                                  │
└───────────────────────────────────────────────────────┘
```

---

## 五、流程四：读取温度 (0xA8 → 0x8B)

### 5.1 帧格式

**发送帧** (10 字节)：
```
CC 0A 00 A8 [FixedAddr:4] [XOR] EE
```

**响应帧** (15 字节)：
```
DD 0F 00 8B [FixedAddr:4] [Temp:4f] [SensorType:1] [XOR] EE
```

| 字段 | Payload偏移 | 长度 | 类型 | 说明 |
|------|-------------|------|------|------|
| FixedAddr | 0 | 4 | uint32 BE | 设备地址 |
| Temp | 4 | 4 | float32 BE | 温度 (°C, IEEE754) |
| SensorType | 8 | 1 | uint8 | 传感器芯片型号 |

### 5.2 SensorType 定义

| 值 | 传感器 |
|----|--------|
| 1 | ICM-42605 |
| 2 | ICM-42688 |
| 3 | LSM6DSOX |

### 5.3 完整流程

```
┌─ PC 端 ─────────────────────────────────────────────┐
│ for each device_addr in address_list:                 │
│   1. 构建帧: CC 0A 00 A8 [addr:4B] [XOR] EE          │
│   2. 发送到串口                                       │
│   3. 等待响应 (超时 5000ms)                           │
│   4. if 收到响应:                                     │
│        解析 8B 响应                                   │
│        temp = unpack('>f', payload[4:8])              │
│        sensor_type = payload[8]                       │
│   5. 延时 100ms                                       │
└──────────────────────────────────────────────────────┘
```

### 5.4 设备端实现要点

```
┌─ 设备端 (固件) ──────────────────────────────────────┐
│ 1. 接收到 0xA8 命令                                   │
│ 2. 提取 FixedAddr                                     │
│ 3. if 匹配:                                          │
│      a. 从 IMU 读取温度寄存器                         │
│      b. 确定 SensorType (1/2/3)                      │
│      c. 构建 0x8B 响应 (15字节总长) 并发送            │
│      d. 设备进入休眠                                   │
│ 4. if 不匹配: 不响应                                  │
└───────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> A8 命令执行后设备会**进入休眠**，与 A3 行为一致。

---

## 六、附录：其他关键命令 (设备端需实现)

### 6.1 读取全部数据 (0xA4 → 0x4B)

发送帧**无参数** (仅限一对一通信 / 单个设备连接):
```
CC 04 00 A4 [XOR] EE
```

响应帧 — 三轴 (29 字节):
```
DD 1D 00 4B [AutoID:2] [FixedAddr:4] [A:4f] [Z:4f] [B:4f] [VoltVer:4f] [Status:1] [XOR] EE
```

响应帧 — 双轴 (25 字节):
```
DD 19 00 4B [AutoID:2] [FixedAddr:4] [A:4f] [B:4f] [VoltVer:4f] [Status:1] [XOR] EE
```

差异：比 5B 响应多了 `AutoID(2B)` 前缀。

### 6.2 写入固定地址 (0xA0 → 0xB0)

发送帧 (12 字节):
```
CC 0C 00 A0 [AutoID:2] [NewAddr:4] [XOR] EE
```

响应帧 (12 字节):
```
DD 0C 00 B0 [AutoID:2] [NewAddr:4] [XOR] EE
```

设备端：匹配 AutoID → 将 NewAddr 写入 Flash → 回复 B0。

### 6.3 更新地址 (0xA6, 无响应)

发送帧 (10 字节):
```
CC 0A 00 A6 [NewAddr:4] [XOR] EE
```

**无响应**。设备直接将新地址写入 Flash，仅用于一对一通信。

### 6.4 设置型号 (0xC7, 无响应)

发送帧 (11 字节):
```
CC 0B 00 C7 [FixedAddr:4] [Model:1] [XOR] EE
```

**无响应**。设备匹配地址后将型号值写入 Flash。

### 6.5 设置 Modbus ID (0xAB → 0xBA)

发送帧 (11 字节):
```
CC 0B 00 AB [FixedAddr:4] [ModbusID:1] [XOR] EE
```

响应帧:
```
DD [Len] 00 BA [FixedAddr:4] [ModbusID:1] [XOR] EE
```

### 6.6 重新获取 AutoID (0xA1, 无响应)

发送帧 (6 字节):
```
CC 04 00 A1 [XOR] EE
```

广播命令，**无响应**。所有设备重新计算 AutoID。

---

## 七、CircuitPython 固件移植清单

设备端固件需要实现以下模块：

### 7.1 串口帧解析器

```
输入: UART 字节流
输出: 解析后的命令结构 {cmd, payload}

状态机:
  IDLE → 收到 0xCC → READING_LEN → 按 Len 读取剩余字节
  → 校验 XOR → 校验 0xEE 帧尾 → 输出命令
```

### 7.2 命令分发器

```python
# 伪代码
def handle_command(cmd, payload):
    if cmd == 0x00A1:   reacquire_autoid()           # 广播, 无响应
    elif cmd == 0x00A2: handle_get_fixed_addr(payload) # → B2
    elif cmd == 0x005A: handle_read_data(payload, sleep=False) # → 5B
    elif cmd == 0x00A3: handle_read_data(payload, sleep=True)  # → 3B
    elif cmd == 0x00A4: handle_read_all_data()        # → 4B
    elif cmd == 0x00A6: handle_update_addr(payload)   # 无响应
    elif cmd == 0x00A7: handle_modify_addr(payload)   # → 7B
    elif cmd == 0x00A8: handle_read_temp(payload)     # → 8B
    elif cmd == 0x00A0: handle_write_addr(payload)    # → B0
    elif cmd == 0x00AB: handle_set_modbus_id(payload) # → BA
    elif cmd == 0x00C7: handle_set_model(payload)     # 无响应
    elif cmd == 0x00C8: handle_read_model(payload)    # → 8D
```

### 7.3 响应构建器

```python
def build_response(rsp_cmd: int, payload: bytes) -> bytes:
    length = 1 + 1 + 2 + len(payload) + 1 + 1
    frame = bytes([0xDD, length, (rsp_cmd >> 8) & 0xFF, rsp_cmd & 0xFF]) + payload
    checksum = xor_checksum(frame)
    frame += bytes([checksum, 0xEE])
    return frame
```

### 7.4 需要持久化存储的参数

| 参数 | 大小 | 默认值 | 说明 |
|------|------|--------|------|
| FixedAddr | 4B | 0x00000000 | 设备固定地址 |
| AutoID | 2B | 计算值 | 根据地址哈希 |
| Model | 1B | 0 | 型号/量程 |
| ModbusID | 1B | 1 | Modbus 从机地址 |
| SensorType | 1B | 自动检测 | 1/2/3 |

### 7.5 命令→响应 速查

| 发送命令 | 响应码 | 有无响应 | 超时(ms) | 用途 |
|----------|--------|----------|----------|------|
| 0xA0 | 0xB0 | ✅ | 300 | AutoID写地址 |
| 0xA1 | — | ❌ | 500 | 重算AutoID |
| 0xA2 | 0xB2 | ✅ | 300 | 查固定地址 |
| 0xA3 | 0x3B | ✅ | 3500 | 读数据+休眠 |
| 0x5A | 0x5B | ✅ | 5000 | 读数据不休眠 |
| 0xA4 | 0x4B | ✅ | 3500 | 读全部(1V1) |
| 0xA6 | — | ❌ | 500 | 更新地址(1V1) |
| 0xA7 | 0x7B | ✅ | 1000 | 修改地址 |
| 0xA8 | 0x8B | ✅ | 3500 | 读温度+休眠 |
| 0xAB | 0xBA | ✅ | 1000 | 设Modbus ID |
| 0xC7 | — | ❌ | 500 | 设型号 |
| 0xC8 | 0x8D | ✅ | 2000 | 读型号 |

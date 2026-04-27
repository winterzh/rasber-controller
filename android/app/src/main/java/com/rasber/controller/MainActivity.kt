package com.rasber.controller

import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.horizontalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import kotlinx.coroutines.launch
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.material3.LocalTextStyle
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import com.rasber.controller.ble.BleManager
import org.json.JSONObject

/**
 * MainActivity - ESP32 控制器配置和参数设置
 * by dztdash
 */
@OptIn(ExperimentalMaterial3Api::class)
class MainActivity : ComponentActivity() {

    private lateinit var bleManager: BleManager

    // 状态变量 - Activity 级别
    private var _connected = mutableStateOf(false)
    private var _scanning = mutableStateOf(false)
    private var _devices = mutableStateOf<List<android.bluetooth.BluetoothDevice>>(emptyList())
    private var _lastData = mutableStateOf("")
    
    // 设备状态
    private var _deviceId = mutableStateOf("")
    private var _firmwareVersion = mutableStateOf("")
    private var _freeMemory = mutableStateOf(0)
    private var _config = mutableStateOf<JSONObject?>(null)
    
    // 传感器数据
    private var _sensorData = mutableStateOf<Map<Int, SensorReading>>(emptyMap())
    private var _sensorAddresses = mutableStateOf<Map<String, List<Int>>>(emptyMap())
    private var _scanProgress = mutableStateOf(0)
    private var _readSensorsStatus = mutableStateOf("")

    // 协议元数据 (从设备 list_protocols 拉取)
    data class ProtocolMeta(val name: String, val addrMin: Long, val addrMax: Long, val scanMax: Int)
    private var _protocols = mutableStateOf<List<ProtocolMeta>>(emptyList())
    private var _channelProtocol = mutableStateOf<Map<String, String>>(emptyMap())  // com -> proto name
    private var _addressDirty = mutableStateOf(false)
    private var _writeConfigPending = mutableStateOf(false)
    // 保存并离开: 收到 write_config ack 后跳到此 tab; -1 = 不跳
    private var _pendingTabAfterSave = mutableStateOf(-1)
    
    // ConfigTab 状态
    data class A4Result(val autoId: Int, val addr: Long, val a: Double, val b: Double, val z: Double)
    data class BatchResult(val autoId: Int, val addr: Long, val model: String = "", val status: String)
    private var _a4Results = mutableStateOf<List<A4Result>>(emptyList())
    private var _a4SingleResult = mutableStateOf<A4Result?>(null)
    private var _batchResults = mutableStateOf<List<BatchResult>>(emptyList())
    private var _configStatus = mutableStateOf("")
    private var _batchRunning = mutableStateOf(false)
    private var _a4Running = mutableStateOf(false)
    private var _a7Status = mutableStateOf("")
    private var _configProgress = mutableStateOf(0f)
    
    // 配置段名称列表
    private var _configSections = mutableStateOf<List<String>>(emptyList())

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val allGranted = permissions.all { it.value }
        if (allGranted) {
            bleManager.startScan()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        try {
            bleManager = BleManager(this).apply {
                onConnectionChanged = { connected ->
                    _connected.value = connected
                    if (connected) {
                        // 连接后自动获取状态
                        sendCommand("{\"cmd\":\"status\"}")
                    }
                }
                onScanningChanged = { scanning ->
                    _scanning.value = scanning
                }
                onDevicesChanged = { devices ->
                    _devices.value = devices
                }
                onDataReceived = { data ->
                    _lastData.value = data
                    handleBleData(data)
                }
            }
        } catch (e: Exception) {
            Toast.makeText(this, "BLE 初始化失败: ${e.message}", Toast.LENGTH_LONG).show()
        }

        setContent {
            MaterialTheme {
                MainApp()
            }
        }
    }

    private fun handleBleData(data: String) {
        android.util.Log.d("MainActivity", "handleBleData called, data length: ${data.length}")
        android.util.Log.d("MainActivity", "Data preview: ${data.take(200)}...")
        try {
            val json = JSONObject(data)
            android.util.Log.d("MainActivity", "JSON parsed successfully, keys: ${json.keys().asSequence().toList()}")
            
            // 检查是否有 type 字段 (流式数据)
            when (json.optString("type")) {
                "read_start" -> {
                    _sensorData.value = emptyMap()
                }
                "data" -> {
                    val addr = json.getInt("addr")
                    val reading = SensorReading(
                        addr = addr,
                        channel = json.optInt("channel", 1),
                        a = json.optDouble("a", 0.0),
                        b = json.optDouble("b", 0.0),
                        z = json.optDouble("z", 0.0),
                        status = json.optString("status", "ok")
                    )
                    _sensorData.value = _sensorData.value + (addr to reading)
                }
                "read_complete" -> {
                    // 读取完成
                }
                "config_section" -> {
                    // 分段配置数据
                    val section = json.optString("section")
                    val data = json.optJSONObject("data")
                    android.util.Log.d("MainActivity", "Config section received: $section")
                    if (section.isNotEmpty() && data != null) {
                        // 组装配置
                        val currentConfig = _config.value ?: JSONObject()
                        currentConfig.put(section, data)
                        _config.value = currentConfig
                    }
                }
                "config_complete" -> {
                    // 配置发送完成
                    android.util.Log.d("MainActivity", "Config complete, sections: ${_config.value?.keys()?.asSequence()?.toList()}")
                }
                "error" -> {
                    val addr = json.optInt("addr", -1)
                    if (addr >= 0) {
                        _sensorData.value = _sensorData.value + (addr to SensorReading(addr, status = "error"))
                    }
                }
            }
            
            // 检查是否有 cmd 字段 (命令响应)
            when (json.optString("cmd")) {
                "status" -> {
                    // 新格式：字段直接在顶层
                    _deviceId.value = json.optString("id", "")
                    _freeMemory.value = json.optInt("free_mem", 0)
                    android.util.Log.d("MainActivity", "Status: id=${_deviceId.value}, free_mem=${_freeMemory.value}")
                }
                "read", "config" -> {
                    android.util.Log.d("MainActivity", "Handling config response")
                    // 新格式：完整配置直接返回
                    _config.value = json
                    android.util.Log.d("MainActivity", "Config received: ${json.keys().asSequence().toList()}")
                }
                "set_id", "set_interval", "set_sleep", "set_mqtt", "set_wifi", "set_4g",
                "enable_wifi", "disable_wifi", "enable_4g", "disable_4g", "save",
                "set_storage", "set_usb_rw", "set_rs485_ext", "set_merge_segments" -> {
                    // 设置成功，刷新配置
                    val ok = json.optBoolean("ok", false)
                    android.util.Log.d("MainActivity", "Set command result: ok=$ok")
                    if (ok) {
                        // 刷新配置
                        bleManager.sendCommand("{\"cmd\":\"read\"}")
                    }
                }
                "reboot" -> {
                    android.util.Log.d("MainActivity", "Device rebooting...")
                }
                "read_sensors" -> {
                    val ok = json.optBoolean("ok", false)
                    _readSensorsStatus.value = if (ok) "✓ 已触发, 准备采集..." else "✗ 采集失败"
                }
                "read_sensors_start" -> {
                    val total = json.optInt("total", 0)
                    val cycle = json.optInt("cycle", 0)
                    _readSensorsStatus.value = "采集中... (周期 $cycle, 共 $total 颗)"
                }
                "upload_start" -> {
                    val segs = json.optInt("segments", 0)
                    _readSensorsStatus.value = "采集完成, 上传中... ($segs 段)"
                }
                "upload_done" -> {
                    _readSensorsStatus.value = "上传完成"
                }
                "read_sensors_complete" -> {
                    val cycle = json.optInt("cycle", 0)
                    _readSensorsStatus.value = "✓ 周期 $cycle 完成"
                }
                // 数据读取相关命令
                "get_sensors" -> {
                    val com = json.optString("com", "1")
                    val addrsArray = json.optJSONArray("addrs")
                    val proto = json.optString("protocol", "PRIVATE_V2026")
                    if (addrsArray != null) {
                        val addrs = (0 until addrsArray.length()).map { addrsArray.getInt(it) }
                        _sensorAddresses.value = _sensorAddresses.value + (com to addrs)
                        _channelProtocol.value = _channelProtocol.value + (com to proto)
                        _addressDirty.value = false  // 刚从设备拉的, 视为干净
                        addrs.forEach { addr ->
                            if (!_sensorData.value.containsKey(addr)) {
                                _sensorData.value = _sensorData.value + (addr to SensorReading(addr, com.toIntOrNull() ?: 1, status = "pending"))
                            }
                        }
                        android.util.Log.d("MainActivity", "Got sensors for COM$com: ${addrs.size} addrs, proto=$proto")
                    }
                }
                "list_protocols" -> {
                    val arr = json.optJSONArray("protocols")
                    if (arr != null) {
                        val list = (0 until arr.length()).map { i ->
                            val o = arr.getJSONObject(i)
                            ProtocolMeta(
                                name = o.optString("name"),
                                addrMin = o.optLong("addr_min", 0),
                                addrMax = o.optLong("addr_max", 0xFFFFFFFFL),
                                scanMax = o.optInt("scan_max", 0)
                            )
                        }
                        _protocols.value = list
                        android.util.Log.d("MainActivity", "list_protocols: ${list.size}")
                    }
                }
                "write_config" -> {
                    val ok = json.optBoolean("ok", false)
                    _writeConfigPending.value = false
                    if (ok) {
                        _addressDirty.value = false
                        Toast.makeText(this@MainActivity, "已保存到设备", Toast.LENGTH_SHORT).show()
                    } else {
                        val err = json.optString("error", "未知错误")
                        Toast.makeText(this@MainActivity, "保存失败: $err", Toast.LENGTH_LONG).show()
                        // 失败时取消挂起的 tab 切换
                        _pendingTabAfterSave.value = -1
                    }
                }
                "scan_start" -> {
                    android.util.Log.d("MainActivity", "Scan started for COM${json.optString("com")}")
                    _scanProgress.value = 0
                }
                "scan_result" -> {
                    val com = json.optString("com", "1")
                    val addr = json.optInt("addr")
                    val autoId = json.optInt("auto_id", -1)
                    android.util.Log.d("MainActivity", "Scan result: COM$com AutoID $autoId -> addr $addr")
                    // 添加到地址列表
                    val currentAddrs = _sensorAddresses.value[com] ?: emptyList()
                    _sensorAddresses.value = _sensorAddresses.value + (com to (currentAddrs + addr))
                    // 添加传感器占位，包含 autoId
                    _sensorData.value = _sensorData.value + (addr to SensorReading(addr = addr, channel = com.toIntOrNull() ?: 1, autoId = autoId, status = "found"))
                }
                "scan_progress" -> {
                    _scanProgress.value = json.optInt("progress")
                }
                "scan_complete" -> {
                    val count = json.optInt("count")
                    android.util.Log.d("MainActivity", "Scan complete: $count sensors found")
                    _scanProgress.value = 1024
                }
                "read_start" -> {
                    android.util.Log.d("MainActivity", "Read started for COM${json.optString("com")}")
                }
                "sensor_data" -> {
                    val addr = json.optInt("addr")
                    val ok = json.optBoolean("ok")
                    val com = json.optString("com", "1").toIntOrNull() ?: 1
                    if (ok) {
                        val a = json.optDouble("a", 0.0)
                        val b = json.optDouble("b", 0.0)
                        val z = json.optDouble("z", 0.0)
                        _sensorData.value = _sensorData.value + (addr to SensorReading(addr = addr, channel = com, a = a, b = b, z = z, status = "ok"))
                    } else {
                        _sensorData.value = _sensorData.value + (addr to SensorReading(addr = addr, channel = com, status = "error"))
                    }
                }
                "read_complete" -> {
                    android.util.Log.d("MainActivity", "Read complete for COM${json.optString("com")}")
                }
                // 型号读取/设置
                "model_data" -> {
                    val addr = json.optInt("addr")
                    val ok = json.optBoolean("ok")
                    val com = json.optString("com", "1").toIntOrNull() ?: 1
                    if (ok) {
                        val model = json.optInt("model", -1)
                        val temp = json.optDouble("temp", 0.0)
                        val existing = _sensorData.value[addr]
                        if (existing != null) {
                            _sensorData.value = _sensorData.value + (addr to existing.copy(model = model, temp = temp, status = "model_ok"))
                        } else {
                            _sensorData.value = _sensorData.value + (addr to SensorReading(addr, com, model = model, temp = temp, status = "model_ok"))
                        }
                    }
                    android.util.Log.d("MainActivity", "Model data: addr=$addr, ok=$ok")
                }
                "read_model_complete" -> {
                    android.util.Log.d("MainActivity", "Read model complete for COM${json.optString("com")}")
                }
                "set_model_result" -> {
                    val addr = json.optInt("addr")
                    val model = json.optInt("model")
                    android.util.Log.d("MainActivity", "Set model result: addr=$addr, model=$model")
                }
                "set_model_complete" -> {
                    val count = json.optInt("count")
                    android.util.Log.d("MainActivity", "Set model complete: $count sensors")
                }
                // ConfigTab 响应
                "a4_single_result" -> {
                    val ok = json.optBoolean("ok")
                    if (ok) {
                        val autoId = json.optInt("auto_id")
                        val addr = json.optLong("addr")
                        val a = json.optDouble("a", 0.0)
                        val b = json.optDouble("b", 0.0)
                        val z = json.optDouble("z", 0.0)
                        _a4SingleResult.value = A4Result(autoId, addr, a, b, z)
                        _configStatus.value = "A4 读取成功: AutoID=$autoId 地址=$addr"
                    } else {
                        _a4SingleResult.value = null
                        _configStatus.value = "A4 无响应"
                    }
                    _a4Running.value = false
                }
                "a4_start" -> {
                    _a4Results.value = emptyList()
                    _a4Running.value = true
                    _configStatus.value = "A4 扫描中..."
                }
                "a4_result" -> {
                    val autoId = json.optInt("auto_id")
                    val addr = json.optLong("addr")
                    val a = json.optDouble("a", 0.0)
                    val b = json.optDouble("b", 0.0)
                    val z = json.optDouble("z", 0.0)
                    _a4Results.value = _a4Results.value + A4Result(autoId, addr, a, b, z)
                    _configStatus.value = "已找到 ${_a4Results.value.size} 个传感器"
                }
                "a4_progress" -> {
                    val current = json.optInt("current")
                    val total = json.optInt("total", 961)
                    _configProgress.value = current.toFloat() / total
                }
                "a4_complete" -> {
                    val count = json.optInt("count", 0)
                    _a4Running.value = false
                    _configStatus.value = "A4 扫描完成，找到 $count 个传感器"
                    _configProgress.value = 0f
                }
                "update_addr_result" -> {
                    val ok = json.optBoolean("ok")
                    val newAddr = json.optLong("new_addr")
                    val modelOk = json.opt("model_ok")
                    val model = json.optInt("model", -1)
                    val readModel = json.optInt("read_model", -1)
                    _configStatus.value = if (ok) {
                        var msg = "地址已更新: $newAddr"
                        if (model >= 0) {
                            msg += if (modelOk == true) " | 型号=$model 验证成功" else " | 型号验证失败(期望$model 读取$readModel)"
                        }
                        msg
                    } else "地址更新失败"
                }
                "write_addr_result" -> {
                    val ok = json.optBoolean("ok")
                    val oldAddr = json.optLong("old_addr")
                    val newAddr = json.optLong("new_addr")
                    _configStatus.value = if (ok) "地址修改成功: $oldAddr → $newAddr" else "地址修改失败"
                }
                "write_model_result" -> {
                    val ok = json.optBoolean("ok")
                    val addr = json.optLong("addr")
                    val model = json.optInt("model")
                    _configStatus.value = if (ok) "型号写入成功: addr=$addr model=$model" else "型号写入失败"
                }
                "set_modbus_result" -> {
                    val ok = json.optBoolean("ok")
                    val addr = json.optLong("addr")
                    val modbusId = json.optInt("modbus_id")
                    _configStatus.value = if (ok) "Modbus ID 设置成功: addr=$addr id=$modbusId" else "Modbus ID 设置失败"
                }
                "modify_addr_a7_result" -> {
                    val ok = json.optBoolean("ok")
                    val oldAddr = json.optLong("old_addr")
                    val newAddr = json.optLong("new_addr")
                    val verifyOk = json.optBoolean("verify_ok")
                    val verifyAddr = json.optLong("verify_addr")
                    _a7Status.value = if (ok) {
                        if (verifyOk) {
                            "✅ 修改成功: $oldAddr → $newAddr，验证通过"
                        } else {
                            "✅ 修改成功: $oldAddr → $newAddr"
                        }
                    } else "❌ 修改失败"
                    _configStatus.value = _a7Status.value
                }
                "batch_start" -> {
                    _batchResults.value = emptyList()
                    _batchRunning.value = true
                    _configStatus.value = "批量写入中..."
                }
                "batch_result" -> {
                    val autoId = json.optInt("auto_id")
                    val addr = json.optLong("addr")
                    _batchResults.value = _batchResults.value + BatchResult(autoId, addr, status = "成功")
                    _configStatus.value = "已写入 ${_batchResults.value.size} 个"
                }
                "batch_progress" -> {
                    val current = json.optInt("current")
                    val total = json.optInt("total", 961)
                    _configProgress.value = current.toFloat() / total
                }
                "batch_complete" -> {
                    val success = json.optInt("success", 0)
                    _batchRunning.value = false
                    _configStatus.value = "批量写入完成，成功 $success 个"
                    _configProgress.value = 0f
                }
            }
        } catch (e: Exception) {
            android.util.Log.e("MainActivity", "handleBleData error: ${e.message}", e)
        }
    }

    @Composable
    fun MainApp() {
        var selectedTab by remember { mutableIntStateOf(0) }
        var pendingSwitch by remember { mutableIntStateOf(-1) }
        var showLeaveDialog by remember { mutableStateOf(false) }
        val pendingTabAfterSave = _pendingTabAfterSave.value

        // 收到 write_config ack 成功后, 自动切到挂起的 tab
        LaunchedEffect(pendingTabAfterSave, _addressDirty.value, _writeConfigPending.value) {
            if (pendingTabAfterSave >= 0 && !_addressDirty.value && !_writeConfigPending.value) {
                selectedTab = pendingTabAfterSave
                _pendingTabAfterSave.value = -1
            }
        }

        // 统一拦截切 tab: 离开 Tab2 (数据) 且有未保存修改 → 弹 dialog
        val requestSwitch: (Int) -> Unit = { target ->
            if (_addressDirty.value && selectedTab == 2 && target != 2) {
                pendingSwitch = target
                showLeaveDialog = true
            } else {
                selectedTab = target
            }
        }

        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text("控制器配置和参数设置") },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = MaterialTheme.colorScheme.primary,
                        titleContentColor = Color.White
                    )
                )
            },
            bottomBar = {
                NavigationBar {
                    NavigationBarItem(
                        selected = selectedTab == 0,
                        onClick = { requestSwitch(0) },
                        icon = { Icon(Icons.Default.Bluetooth, "连接") },
                        label = { Text("连接") }
                    )
                    NavigationBarItem(
                        selected = selectedTab == 1,
                        onClick = { requestSwitch(1) },
                        icon = { Icon(Icons.Default.Build, "配置") },
                        label = { Text("配置") }
                    )
                    NavigationBarItem(
                        selected = selectedTab == 2,
                        onClick = { requestSwitch(2) },
                        icon = { Icon(Icons.Default.List, "数据") },
                        label = { Text("数据") }
                    )
                    NavigationBarItem(
                        selected = selectedTab == 3,
                        onClick = { requestSwitch(3) },
                        icon = { Icon(Icons.Default.Settings, "设置") },
                        label = { Text("设置") }
                    )
                }
            }
        ) { padding ->
            Column(modifier = Modifier.padding(padding)) {
                // 蓝牙未连接提示横幅
                if (!_connected.value) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(Color(0xFFE53935))
                            .padding(horizontal = 16.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(
                            Icons.Default.Warning,
                            contentDescription = null,
                            tint = Color.White,
                            modifier = Modifier.size(18.dp)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            "蓝牙未连接 — 请在连接页面连接设备",
                            color = Color.White,
                            fontSize = 13.sp
                        )
                    }
                }
                Box(modifier = Modifier.weight(1f)) {
                    when (selectedTab) {
                        0 -> ConnectTab()
                        1 -> ConfigTab()
                        2 -> DataTab()
                        3 -> SettingsTab()
                    }
                }
            }
        }

        if (showLeaveDialog) {
            AlertDialog(
                onDismissRequest = {
                    showLeaveDialog = false
                    pendingSwitch = -1
                },
                title = { Text("有未保存的修改") },
                text = { Text("地址列表/协议有修改未保存到设备. 离开后修改将丢失.") },
                confirmButton = {
                    TextButton(
                        onClick = {
                            // 保存并离开: 立即发 write_config; LaunchedEffect 等 ack 后切 tab
                            showLeaveDialog = false
                            val target = pendingSwitch
                            pendingSwitch = -1
                            _pendingTabAfterSave.value = target
                            saveAddressConfigToDevice()
                        },
                        enabled = !_writeConfigPending.value
                    ) { Text("保存并离开") }
                },
                dismissButton = {
                    Row {
                        TextButton(onClick = {
                            // 放弃修改: 重新拉取设备数据 + 切 tab
                            showLeaveDialog = false
                            val target = pendingSwitch
                            pendingSwitch = -1
                            _addressDirty.value = false
                            // 重新拉两个 COM 的最新地址列表
                            bleManager.sendCommand("{\"cmd\":\"get_sensors\",\"com\":\"1\"}")
                            bleManager.sendCommand("{\"cmd\":\"get_sensors\",\"com\":\"2\"}")
                            selectedTab = target
                        }) { Text("放弃修改") }
                        TextButton(onClick = {
                            showLeaveDialog = false
                            pendingSwitch = -1
                        }) { Text("取消") }
                    }
                }
            )
        }
    }

    // 把当前 _sensorAddresses + _channelProtocol 打包成 write_config 并下发 (等 ack 才清 dirty)
    private fun saveAddressConfigToDevice() {
        _writeConfigPending.value = true
        val cfg = JSONObject()
        for ((com, addrs) in _sensorAddresses.value) {
            val sub = JSONObject()
            val arr = org.json.JSONArray()
            addrs.forEach { addr ->
                arr.put(JSONObject().put("addr", addr))
            }
            sub.put("sensors", arr)
            _channelProtocol.value[com]?.let { sub.put("protocol", it) }
            cfg.put("rs485_$com", sub)
        }
        val payload = JSONObject().put("cmd", "write_config").put("config", cfg)
        bleManager.sendCommand(payload.toString())
    }

    @Composable
    fun ConnectTab() {
        val connected = _connected.value
        val scanning = _scanning.value
        val devices = _devices.value

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp)
        ) {
            // 连接状态
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = if (connected) Color(0xFF4CAF50) else Color(0xFFE0E0E0)
                )
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(
                        if (connected) Icons.Default.BluetoothConnected else Icons.Default.BluetoothDisabled,
                        contentDescription = null,
                        tint = if (connected) Color.White else Color.Gray
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        if (connected) "已连接" else "未连接",
                        color = if (connected) Color.White else Color.Gray,
                        fontWeight = FontWeight.Bold
                    )
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            // 扫描按钮
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Button(
                    onClick = {
                        if (!scanning) {
                            permissionLauncher.launch(
                                arrayOf(
                                    android.Manifest.permission.BLUETOOTH_SCAN,
                                    android.Manifest.permission.BLUETOOTH_CONNECT,
                                    android.Manifest.permission.ACCESS_FINE_LOCATION
                                )
                            )
                        } else {
                            bleManager.stopScan()
                        }
                    },
                    enabled = !connected
                ) {
                    Text(if (scanning) "停止扫描" else "扫描设备")
                }

                if (connected) {
                    Button(
                        onClick = {
                            val utcMs = System.currentTimeMillis()
                            val tzOffsetMs = java.util.TimeZone.getDefault().getOffset(utcMs)
                            val localTimestamp = utcMs / 1000 + tzOffsetMs / 1000
                            bleManager.sendCommand("{\"cmd\":\"set_time\",\"timestamp\":$localTimestamp}")
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF2196F3))
                    ) {
                        Text("同步时间")
                    }
                    
                    Button(
                        onClick = { bleManager.disconnect() },
                        colors = ButtonDefaults.buttonColors(containerColor = Color.Red)
                    ) {
                        Text("断开连接")
                    }
                }
            }

            if (scanning) {
                Spacer(modifier = Modifier.height(8.dp))
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
            }

            Spacer(modifier = Modifier.height(16.dp))

            // 设备列表
            Text("发现的设备:", fontWeight = FontWeight.Bold)
            Spacer(modifier = Modifier.height(8.dp))

            LazyColumn(modifier = Modifier.weight(1f)) {
                items(devices, key = { it.address }) { device ->
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 4.dp)
                            .clickable { bleManager.connect(device) }
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(16.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(Icons.Default.Bluetooth, contentDescription = null)
                            Spacer(modifier = Modifier.width(8.dp))
                            Column {
                                Text(device.name ?: "未知设备", fontWeight = FontWeight.Bold)
                                Text(device.address, color = Color.Gray)
                            }
                        }
                    }
                }
            }
        }
    }

    @Composable
    fun ConfigTab() {

        val a4SingleResult = _a4SingleResult.value
        val batchResults = _batchResults.value
        val configStatus = _configStatus.value
        val batchRunning = _batchRunning.value
        val a4Running = _a4Running.value
        val progress = _configProgress.value
        var selectedCom by remember { mutableStateOf("1") }

        // 跨 section 共享的状态（A4 结果自动填充到其他区域）
        var a4Addr by remember { mutableStateOf("") }
        var newAddr by remember { mutableStateOf("") }
        var modbusAddr by remember { mutableStateOf("") }

        // A4 结果自动填充
        LaunchedEffect(a4SingleResult) {
            if (a4SingleResult != null) {
                val addrStr = a4SingleResult.addr.toString()
                a4Addr = addrStr
                newAddr = addrStr
                modbusAddr = addrStr
            }
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(12.dp)
                .verticalScroll(rememberScrollState())
        ) {

            // COM 选择
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("COM口:", fontWeight = FontWeight.Bold)
                Spacer(modifier = Modifier.width(8.dp))
                listOf("1", "2").forEach { com ->
                    FilterChip(
                        selected = selectedCom == com,
                        onClick = { selectedCom = com },
                        label = { Text("COM$com") },
                        modifier = Modifier.padding(end = 4.dp)
                    )
                }
            }

            // 状态 + 进度
            if (configStatus.isNotEmpty()) {
                Spacer(modifier = Modifier.height(4.dp))
                Text(configStatus, color = Color(0xFF1976D2), fontSize = 13.sp)
            }
            if (progress > 0f) {
                LinearProgressIndicator(
                    progress = progress,
                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)
                )
            }

            Spacer(modifier = Modifier.height(8.dp))

            // ===== Section 1: A4 读取 (单次) =====
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text("A4 读取", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleSmall)
                    Text("广播读取 — 不需要地址，自动返回 AutoID 和轴数据，填充到下方各区域", fontSize = 12.sp, color = Color.Gray)
                    Spacer(modifier = Modifier.height(8.dp))

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        OutlinedTextField(
                            value = a4Addr,
                            onValueChange = { a4Addr = it },
                            label = { Text("返回地址 (自动填充)", fontSize = 10.sp) },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            readOnly = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
                        )
                        Button(
                            onClick = {
                                _a4Running.value = true
                                _a4SingleResult.value = null
                                bleManager.sendCommand("{\"cmd\":\"read_all_a4\",\"com\":\"$selectedCom\"}")
                            },
                            enabled = !a4Running
                        ) {
                            Text(if (a4Running) "读取中..." else "A4 读取")
                        }
                    }

                    // 单条结果显示
                    if (a4SingleResult != null) {
                        Spacer(modifier = Modifier.height(8.dp))
                        Row(modifier = Modifier.fillMaxWidth().background(Color(0xFFE3F2FD)).padding(8.dp)) {
                            Column {
                                Text("AutoID: ${a4SingleResult.autoId}  |  地址: ${a4SingleResult.addr}", fontWeight = FontWeight.Bold, fontSize = 13.sp)
                                Text("A=${a4SingleResult.a}  B=${a4SingleResult.b}  Z=${a4SingleResult.z}", fontSize = 12.sp, color = Color.Gray)
                            }
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // ===== Section 2: A6 一对一更新地址 =====
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text("一对一更新地址 (A6)", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleSmall)
                    Text("单对单通信，只需填新地址。勾选可同时修改型号并读回验证", fontSize = 12.sp, color = Color.Gray)
                    Spacer(modifier = Modifier.height(8.dp))

                    var updateModel by remember { mutableStateOf(false) }
                    var modelValue by remember { mutableStateOf("0") }

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        OutlinedTextField(
                            value = newAddr,
                            onValueChange = { newAddr = it },
                            label = { Text("新地址", fontSize = 10.sp) },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
                        )
                    }
                    Spacer(modifier = Modifier.height(4.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = updateModel, onCheckedChange = { updateModel = it })
                        Text("同时修改型号", fontSize = 13.sp)
                        if (updateModel) {
                            Spacer(modifier = Modifier.width(8.dp))
                            Box {
                                var modelExpanded by remember { mutableStateOf(false) }
                                OutlinedButton(onClick = { modelExpanded = true }) {
                                    Text("型号: $modelValue", fontSize = 12.sp)
                                }
                                DropdownMenu(expanded = modelExpanded, onDismissRequest = { modelExpanded = false }) {
                                    listOf(
                                        "0" to "三轴阵列(Z=g)", "1" to "三轴阵列(水平mm)", "2" to "三轴阵列(垂直Z=1000)",
                                        "6" to "双轴固定(Z=g)", "7" to "双轴固定(mm)",
                                        "10" to "三轴固定(Z=g)", "11" to "三轴固定(水平mm)", "12" to "三轴固定(垂直Z=1000)"
                                    ).forEach { (v, label) ->
                                        DropdownMenuItem(
                                            text = { Text("$v - $label", fontSize = 12.sp) },
                                            onClick = { modelValue = v; modelExpanded = false }
                                        )
                                    }
                                }
                            }
                        }
                    }
                    Spacer(modifier = Modifier.height(4.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Button(
                            onClick = {
                                val n = newAddr.toLongOrNull() ?: 0L
                                if (n > 0) {
                                    val m = if (updateModel) modelValue.toIntOrNull() ?: -1 else -1
                                    val modelParam = if (m >= 0) ",\"model\":$m" else ""
                                    bleManager.sendCommand("{\"cmd\":\"update_addr_a6\",\"com\":\"$selectedCom\",\"new_addr\":$n$modelParam}")
                                }
                            },
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("更新地址")
                        }
                        Button(
                            onClick = {
                                // 更新地址并自动+1
                                val n = newAddr.toLongOrNull() ?: 0L
                                if (n > 0) {
                                    val m = if (updateModel) modelValue.toIntOrNull() ?: -1 else -1
                                    val modelParam = if (m >= 0) ",\"model\":$m" else ""
                                    bleManager.sendCommand("{\"cmd\":\"update_addr_a6\",\"com\":\"$selectedCom\",\"new_addr\":$n$modelParam}")
                                    newAddr = (n + 1).toString()
                                }
                            },
                            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF7B1FA2)),
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("更新地址+1")
                        }
                    }
                    Text("⚠️ 会修改设备地址，仅生产配置用！", color = Color.Red, fontSize = 11.sp)
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // ===== Section 2.5: A7 单点修改编号 =====
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text("单点修改编号 (A7)", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleSmall)
                    Text("指定旧地址和新地址，修改后自动验证", fontSize = 12.sp, color = Color.Gray)
                    Spacer(modifier = Modifier.height(8.dp))

                    var a7OldAddr by remember { mutableStateOf("") }
                    var a7NewAddr by remember { mutableStateOf("") }
                    val a7Status = _a7Status.value

                    // A4 结果自动填充旧地址
                    LaunchedEffect(a4SingleResult) {
                        if (a4SingleResult != null) {
                            a7OldAddr = a4SingleResult.addr.toString()
                        }
                    }

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        OutlinedTextField(
                            value = a7OldAddr,
                            onValueChange = { a7OldAddr = it },
                            label = { Text("旧地址", fontSize = 10.sp) },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
                        )
                        OutlinedTextField(
                            value = a7NewAddr,
                            onValueChange = { a7NewAddr = it },
                            label = { Text("新地址", fontSize = 10.sp) },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
                        )
                    }
                    Spacer(modifier = Modifier.height(4.dp))
                    Button(
                        onClick = {
                            val o = a7OldAddr.toLongOrNull() ?: 0L
                            val n = a7NewAddr.toLongOrNull() ?: 0L
                            if (o > 0 && n > 0) {
                                _a7Status.value = "执行中..."
                                bleManager.sendCommand("{\"cmd\":\"modify_addr_a7\",\"com\":\"$selectedCom\",\"old_addr\":$o,\"new_addr\":$n}")
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFFF6F00))
                    ) {
                        Text("修改地址并验证")
                    }
                    // 结果显示
                    if (a7Status.isNotEmpty()) {
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            a7Status,
                            fontSize = 13.sp,
                            color = if (a7Status.startsWith("✅")) Color(0xFF2E7D32) else if (a7Status.startsWith("❌")) Color.Red else Color(0xFF1565C0)
                        )
                    }
                    Text("⚠️ 会修改设备地址，仅生产配置用！", color = Color.Red, fontSize = 11.sp)
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // ===== Section 3: 设置 Modbus ID =====
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text("设置 Modbus ID", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleSmall)
                    Spacer(modifier = Modifier.height(8.dp))

                    var modbusId by remember { mutableStateOf("") }

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        OutlinedTextField(
                            value = modbusAddr,
                            onValueChange = { modbusAddr = it },
                            label = { Text("传感器地址", fontSize = 10.sp) },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
                        )
                        OutlinedTextField(
                            value = modbusId,
                            onValueChange = { modbusId = it },
                            label = { Text("Modbus ID", fontSize = 10.sp) },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
                        )
                    }
                    Spacer(modifier = Modifier.height(4.dp))
                    Button(
                        onClick = {
                            val a = modbusAddr.toLongOrNull() ?: 0L
                            val id = modbusId.toIntOrNull() ?: 0
                            if (a > 0 && id > 0) {
                                bleManager.sendCommand("{\"cmd\":\"set_modbus_id\",\"com\":\"$selectedCom\",\"addr\":$a,\"modbus_id\":$id}")
                            }
                        },
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("设置 Modbus ID")
                    }
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // ===== Section 4: 批量地址写入 =====
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text("批量地址写入", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleSmall)
                    Text("扫描 AutoID 范围，匹配的设备写入固定地址（从最大地址递减）", fontSize = 12.sp, color = Color.Gray)
                    Spacer(modifier = Modifier.height(8.dp))

                    var startAutoId by remember { mutableStateOf("0") }
                    var endAutoId by remember { mutableStateOf("960") }
                    var maxAddr by remember { mutableStateOf("") }
                    var delayMs by remember { mutableStateOf("300") }

                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        OutlinedTextField(
                            value = startAutoId,
                            onValueChange = { startAutoId = it },
                            label = { Text("起始AutoID", fontSize = 10.sp) },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
                        )
                        OutlinedTextField(
                            value = endAutoId,
                            onValueChange = { endAutoId = it },
                            label = { Text("结束AutoID", fontSize = 10.sp) },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
                        )
                    }
                    Spacer(modifier = Modifier.height(4.dp))
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        OutlinedTextField(
                            value = maxAddr,
                            onValueChange = { maxAddr = it },
                            label = { Text("最大地址(十进制)", fontSize = 10.sp) },
                            placeholder = { Text("如 2334000001", fontSize = 10.sp) },
                            modifier = Modifier.weight(2f),
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
                        )
                        OutlinedTextField(
                            value = delayMs,
                            onValueChange = { delayMs = it },
                            label = { Text("延时ms", fontSize = 10.sp) },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
                        )
                    }
                    Spacer(modifier = Modifier.height(4.dp))
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        Button(
                            onClick = {
                                val s = startAutoId.toIntOrNull() ?: 0
                                val e = endAutoId.toIntOrNull() ?: 960
                                val m = maxAddr.toLongOrNull() ?: 0L
                                val d = delayMs.toIntOrNull() ?: 300
                                if (m > 0) {
                                    bleManager.sendCommand("{\"cmd\":\"batch_addr_write\",\"com\":\"$selectedCom\",\"start_autoid\":$s,\"end_autoid\":$e,\"max_addr\":$m,\"delay\":$d}")
                                }
                            },
                            enabled = !batchRunning,
                            modifier = Modifier.weight(1f)
                        ) {
                            Text(if (batchRunning) "写入中..." else "开始扫描写入")
                        }
                        OutlinedButton(
                            onClick = { _batchResults.value = emptyList() },
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("清空列表")
                        }
                    }

                    // 批量结果
                    if (batchResults.isNotEmpty()) {
                        Spacer(modifier = Modifier.height(8.dp))
                        Text("成功: ${batchResults.size}", fontWeight = FontWeight.Bold, fontSize = 13.sp)
                        Row(modifier = Modifier.fillMaxWidth().background(Color(0xFFE8F5E9)).padding(4.dp)) {
                            Text("AutoID", modifier = Modifier.width(60.dp), fontWeight = FontWeight.Bold, fontSize = 12.sp)
                            Text("写入地址", modifier = Modifier.width(110.dp), fontWeight = FontWeight.Bold, fontSize = 12.sp)
                            Text("型号", modifier = Modifier.width(50.dp), fontWeight = FontWeight.Bold, fontSize = 12.sp)
                            Text("状态", modifier = Modifier.weight(1f), fontWeight = FontWeight.Bold, fontSize = 12.sp)
                        }
                        batchResults.takeLast(20).forEach { r ->
                            Row(modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp, horizontal = 4.dp)) {
                                Text("${r.autoId}", modifier = Modifier.width(60.dp), fontSize = 12.sp)
                                Text("${r.addr}", modifier = Modifier.width(110.dp), fontSize = 12.sp)
                                Text(r.model, modifier = Modifier.width(50.dp), fontSize = 12.sp)
                                Text(r.status, modifier = Modifier.weight(1f), fontSize = 12.sp, color = Color(0xFF4CAF50))
                            }
                            Divider()
                        }
                    }

                    // 型号操作
                    Spacer(modifier = Modifier.height(8.dp))
                    var batchModel by remember { mutableStateOf("0") }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(4.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Box {
                            var batchModelExpanded by remember { mutableStateOf(false) }
                            OutlinedButton(onClick = { batchModelExpanded = true }) {
                                Text("型号: $batchModel", fontSize = 12.sp)
                            }
                            DropdownMenu(expanded = batchModelExpanded, onDismissRequest = { batchModelExpanded = false }) {
                                listOf(
                                    "0" to "三轴阵列(Z=g)", "1" to "三轴阵列(水平mm)", "2" to "三轴阵列(垂直Z=1000)",
                                    "6" to "双轴固定(Z=g)", "7" to "双轴固定(mm)",
                                    "10" to "三轴固定(Z=g)", "11" to "三轴固定(水平mm)", "12" to "三轴固定(垂直Z=1000)"
                                ).forEach { (v, label) ->
                                    DropdownMenuItem(
                                        text = { Text("$v - $label", fontSize = 12.sp) },
                                        onClick = { batchModel = v; batchModelExpanded = false }
                                    )
                                }
                            }
                        }
                        Button(
                            onClick = {
                                // 只发一条 read_model 命令，固件内部串行读取所有传感器
                                bleManager.sendCommand("{\"cmd\":\"read_model\",\"com\":\"$selectedCom\"}")
                            },
                            enabled = batchResults.isNotEmpty(),
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("读取型号", fontSize = 12.sp)
                        }
                        Button(
                            onClick = {
                                // 使用批量 set_model 命令，固件内部串行设置（每个传感器间隔1s等待Flash写入）
                                val m = batchModel.toIntOrNull() ?: 0
                                bleManager.sendCommand("{\"cmd\":\"set_model\",\"com\":\"$selectedCom\",\"model\":$m}")
                            },
                            enabled = batchResults.isNotEmpty(),
                            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFE91E63)),
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("批量写型号", fontSize = 12.sp)
                        }
                    }
                }
            }
        }
    }

    @Composable
    fun DataTab() {

        val sensorData = _sensorData.value
        val sensorAddresses = _sensorAddresses.value
        val scanProgress = _scanProgress.value
        val protocols = _protocols.value
        val channelProtocol = _channelProtocol.value
        val dirty = _addressDirty.value
        val pending = _writeConfigPending.value
        var selectedCom by remember { mutableStateOf("1") }
        var protoExpanded by remember { mutableStateOf(false) }
        // 添加/编辑 dialog: null = 关闭; (oldAddr, isEdit) - oldAddr 在 edit 模式下是被替换的原值
        var addrDialogState by remember { mutableStateOf<Pair<Int?, Boolean>?>(null) }
        // 进入 tab 时拉一次协议列表 (动态填下拉)
        LaunchedEffect(Unit) {
            if (_protocols.value.isEmpty()) {
                bleManager.sendCommand("{\"cmd\":\"list_protocols\"}")
            }
        }

        val currentProto = channelProtocol[selectedCom] ?: protocols.firstOrNull()?.name ?: "PRIVATE_V2026"
        val currentMeta = protocols.find { it.name == currentProto }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp)
        ) {


            // 单行: COM 选择 + 协议 + 保存 (压缩节省竖向空间)
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                listOf("1" to "COM1", "2" to "COM2").forEach { (value, label) ->
                    FilterChip(
                        selected = selectedCom == value,
                        onClick = {
                            selectedCom = value
                            _sensorData.value = emptyMap()
                        },
                        label = { Text(label, fontSize = 12.sp) }
                    )
                }
                Spacer(modifier = Modifier.weight(1f))
                Box {
                    AssistChip(
                        onClick = { protoExpanded = true },
                        label = { Text(currentProto, fontSize = 11.sp, maxLines = 1) },
                        trailingIcon = { Icon(Icons.Default.ArrowDropDown, contentDescription = "协议", modifier = Modifier.size(18.dp)) }
                    )
                    DropdownMenu(
                        expanded = protoExpanded,
                        onDismissRequest = { protoExpanded = false }
                    ) {
                        if (protocols.isEmpty()) {
                            DropdownMenuItem(
                                text = { Text("(未拉到协议列表)", color = Color.Gray) },
                                onClick = { protoExpanded = false }
                            )
                        } else {
                            protocols.forEach { meta ->
                                DropdownMenuItem(
                                    text = { Text("${meta.name}  [${meta.addrMin}~${meta.addrMax}]", fontSize = 12.sp) },
                                    onClick = {
                                        if (meta.name != currentProto) {
                                            _channelProtocol.value = _channelProtocol.value + (selectedCom to meta.name)
                                            _addressDirty.value = true
                                        }
                                        protoExpanded = false
                                    }
                                )
                            }
                        }
                    }
                }
                Button(
                    onClick = { saveAddressConfigToDevice() },
                    enabled = dirty && !pending,
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF1976D2)),
                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp)
                ) {
                    if (pending) {
                        CircularProgressIndicator(modifier = Modifier.size(14.dp), strokeWidth = 2.dp, color = Color.White)
                    } else {
                        Icon(Icons.Default.Save, contentDescription = null, modifier = Modifier.size(14.dp))
                    }
                    Spacer(modifier = Modifier.width(2.dp))
                    Text(if (dirty) "保存" else "已存", fontSize = 11.sp)
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // 操作按钮 (压缩字号 + padding)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(4.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Button(
                    onClick = {
                        bleManager.sendCommand("{\"cmd\":\"get_sensors\",\"com\":\"$selectedCom\"}")
                    },
                    modifier = Modifier.weight(1f),
                    contentPadding = PaddingValues(vertical = 6.dp)
                ) { Text("读取地址", fontSize = 12.sp) }
                Button(
                    onClick = {
                        _sensorAddresses.value = _sensorAddresses.value + (selectedCom to emptyList())
                        _sensorData.value = emptyMap()
                        _scanProgress.value = 0
                        _addressDirty.value = true
                        bleManager.sendCommand("{\"cmd\":\"scan\",\"com\":\"$selectedCom\"}")
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFFF9800)),
                    modifier = Modifier.weight(1f),
                    contentPadding = PaddingValues(vertical = 6.dp)
                ) { Text("扫地址", fontSize = 12.sp) }
                Button(
                    onClick = {
                        bleManager.sendCommand("{\"cmd\":\"read_data\",\"com\":\"$selectedCom\"}")
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF4CAF50)),
                    modifier = Modifier.weight(1f),
                    contentPadding = PaddingValues(vertical = 6.dp)
                ) { Text("读取数据", fontSize = 12.sp) }
            }

            Spacer(modifier = Modifier.height(4.dp))

            // 读取数据并上发 (触发设备完整采集 + MQTT 上传, 顺序: 4G → WiFi → Ethernet)
            val ctx = LocalContext.current
            val readSensorsStatus = _readSensorsStatus.value
            Button(
                onClick = {
                    _readSensorsStatus.value = "发送中..."
                    bleManager.sendCommand("{\"cmd\":\"read_sensors\"}")
                    Toast.makeText(ctx, "已发送 (light sleep 才生效)", Toast.LENGTH_SHORT).show()
                },
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF1976D2)),
                modifier = Modifier.fillMaxWidth()
            ) {
                Icon(Icons.Default.Send, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(modifier = Modifier.width(4.dp))
                Text("读取数据并上发")
            }
            if (readSensorsStatus.isNotEmpty()) {
                Text(
                    readSensorsStatus,
                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                    style = MaterialTheme.typography.bodySmall,
                    color = if (readSensorsStatus.startsWith("✓")) Color(0xFF4CAF50)
                            else if (readSensorsStatus.startsWith("✗")) Color.Red
                            else MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center
                )
            }

            // 型号操作 (默认折叠, 点击展开)
            var targetModel by remember { mutableStateOf(0) }
            var modelExpanded by remember { mutableStateOf(false) }
            var modelOpsExpanded by remember { mutableStateOf(false) }
            val modelOptions = listOf(
                0 to "0 - 三轴阵列(Z=g)",
                1 to "1 - 三轴阵列(水平mm)",
                2 to "2 - 三轴阵列(垂直Z=1000)",
                6 to "6 - 双轴固定(Z=g)",
                7 to "7 - 双轴固定(mm)",
                10 to "10 - 三轴固定(Z=g)",
                11 to "11 - 三轴固定(水平mm)",
                12 to "12 - 三轴固定(垂直Z=1000)"
            )
            val selectedModelLabel = modelOptions.find { it.first == targetModel }?.second ?: "0 - 三轴阵列(Z=g)"

            TextButton(
                onClick = { modelOpsExpanded = !modelOpsExpanded },
                modifier = Modifier.fillMaxWidth(),
                contentPadding = PaddingValues(vertical = 2.dp)
            ) {
                Text(
                    "型号操作 ${if (modelOpsExpanded) "▲" else "▼"}",
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (modelOpsExpanded) Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(4.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Button(
                    onClick = { 
                        bleManager.sendCommand("{\"cmd\":\"read_model\",\"com\":\"$selectedCom\"}") 
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF9C27B0)),
                    modifier = Modifier.weight(1f),
                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                ) {
                    Text("读取型号", fontSize = 12.sp)
                }
                
                Button(
                    onClick = { 
                        bleManager.sendCommand("{\"cmd\":\"set_model\",\"com\":\"$selectedCom\",\"model\":$targetModel}") 
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFE91E63)),
                    modifier = Modifier.weight(1f),
                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
                ) {
                    Text("设置型号", fontSize = 12.sp)
                }
                
                // 型号下拉选择
                Box(modifier = Modifier.weight(1f)) {
                    OutlinedTextField(
                        value = selectedModelLabel,
                        onValueChange = {},
                        readOnly = true,
                        modifier = Modifier.fillMaxWidth(),
                        textStyle = LocalTextStyle.current.copy(fontSize = 14.sp),
                        label = { Text("型号", fontSize = 10.sp) },
                        trailingIcon = {
                            IconButton(onClick = { modelExpanded = true }) {
                                Icon(Icons.Default.ArrowDropDown, contentDescription = "展开")
                            }
                        },
                        singleLine = true
                    )
                    DropdownMenu(
                        expanded = modelExpanded,
                        onDismissRequest = { modelExpanded = false }
                    ) {
                        modelOptions.forEach { (value, label) ->
                            DropdownMenuItem(
                                text = { Text(label) },
                                onClick = {
                                    targetModel = value
                                    modelExpanded = false
                                }
                            )
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(8.dp))
            
            // 扫描进度
            if (scanProgress in 1..1023) {
                LinearProgressIndicator(
                    progress = scanProgress / 1024f,
                    modifier = Modifier.fillMaxWidth()
                )
                Text("扫描中... $scanProgress/1024", style = MaterialTheme.typography.bodySmall)
                Spacer(modifier = Modifier.height(8.dp))
            }

            // 表格区域 - 可水平滚动
            val scrollState = rememberScrollState()
            
            Column(modifier = Modifier.weight(1f)) {
                // 表头
                Row(
                    modifier = Modifier
                        .background(MaterialTheme.colorScheme.primaryContainer)
                        .padding(vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    // 固定列: 地址 (含状态 emoji 前缀) + 操作
                    Text("地址", modifier = Modifier.width(120.dp).padding(start = 8.dp), fontWeight = FontWeight.Bold)
                    Text("操作", modifier = Modifier.width(72.dp), fontWeight = FontWeight.Bold)
                    // 可滚动列
                    Row(modifier = Modifier.horizontalScroll(scrollState).padding(end = 8.dp)) {
                        Text("AutoID", modifier = Modifier.width(60.dp), fontWeight = FontWeight.Bold)
                        Text("A(X)", modifier = Modifier.width(80.dp), fontWeight = FontWeight.Bold)
                        Text("B(Y)", modifier = Modifier.width(80.dp), fontWeight = FontWeight.Bold)
                        Text("Z", modifier = Modifier.width(80.dp), fontWeight = FontWeight.Bold)
                        Text("型号", modifier = Modifier.width(50.dp), fontWeight = FontWeight.Bold)
                    }
                }

                // 传感器列表
                val addresses = sensorAddresses[selectedCom] ?: emptyList()
                
                LazyColumn(modifier = Modifier.weight(1f)) {
                    if (addresses.isEmpty()) {
                        item {
                            Text("COM$selectedCom 暂无传感器配置, 点击\"读取地址\"/\"扫地址\"或下方\"+ 添加地址\"",
                                modifier = Modifier.padding(16.dp),
                                color = Color.Gray)
                        }
                    } else {
                        items(addresses) { addr ->
                            val reading = sensorData[addr]
                            val statusIcon = when (reading?.status) {
                                "ok" -> "✅"
                                "found" -> "📍"
                                "error" -> "❌"
                                "model_ok" -> "🔧"
                                else -> "⏳"
                            }

                            Row(
                                modifier = Modifier.padding(vertical = 4.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                // 固定列: 状态 emoji 前缀 + 地址 (点击 poll) + 编辑/删除
                                Text(
                                    "$statusIcon $addr",
                                    modifier = Modifier
                                        .width(120.dp)
                                        .padding(start = 8.dp)
                                        .clickable {
                                            bleManager.sendCommand("{\"cmd\":\"poll\",\"com\":\"$selectedCom\",\"addr\":$addr}")
                                            _sensorData.value = _sensorData.value + (addr to SensorReading(addr, selectedCom.toIntOrNull() ?: 1, status = "pending"))
                                        },
                                    color = MaterialTheme.colorScheme.primary,
                                    textDecoration = androidx.compose.ui.text.style.TextDecoration.Underline
                                )
                                Row(modifier = Modifier.width(72.dp)) {
                                    IconButton(
                                        onClick = { addrDialogState = addr to true },
                                        modifier = Modifier.size(32.dp)
                                    ) {
                                        Icon(Icons.Default.Edit, "编辑", modifier = Modifier.size(18.dp), tint = Color(0xFF1976D2))
                                    }
                                    IconButton(
                                        onClick = {
                                            val cur = _sensorAddresses.value[selectedCom] ?: emptyList()
                                            _sensorAddresses.value = _sensorAddresses.value + (selectedCom to cur.filter { it != addr })
                                            _addressDirty.value = true
                                        },
                                        modifier = Modifier.size(32.dp)
                                    ) {
                                        Icon(Icons.Default.Delete, "删除", modifier = Modifier.size(18.dp), tint = Color(0xFFE53935))
                                    }
                                }
                                // 可滚动列
                                Row(modifier = Modifier.horizontalScroll(scrollState).padding(end = 8.dp)) {
                                    Text(if (reading?.autoId ?: -1 >= 0) "${reading?.autoId}" else "--", modifier = Modifier.width(60.dp))
                                    Text(reading?.let { String.format("%.2f", it.a) } ?: "--", modifier = Modifier.width(80.dp))
                                    Text(reading?.let { String.format("%.2f", it.b) } ?: "--", modifier = Modifier.width(80.dp))
                                    Text(reading?.let { String.format("%.2f", it.z) } ?: "--", modifier = Modifier.width(80.dp))
                                    Text(if (reading?.model ?: -1 >= 0) "${reading?.model}" else "--", modifier = Modifier.width(50.dp))
                                }
                            }
                            Divider()
                        }
                    }
                    item {
                        OutlinedButton(
                            onClick = { addrDialogState = null to false },
                            modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp)
                        ) {
                            Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(modifier = Modifier.width(4.dp))
                            Text("添加地址")
                        }
                    }
                }
            }
        }

        // 添加 / 编辑地址 dialog
        addrDialogState?.let { (oldAddr, isEdit) ->
            AddressEditDialog(
                oldAddr = oldAddr,
                isEdit = isEdit,
                meta = currentMeta,
                existingAddrs = sensorAddresses[selectedCom] ?: emptyList(),
                onDismiss = { addrDialogState = null },
                onConfirm = { newAddr ->
                    val cur = _sensorAddresses.value[selectedCom] ?: emptyList()
                    val next = if (isEdit && oldAddr != null) {
                        cur.map { if (it == oldAddr) newAddr else it }
                    } else {
                        cur + newAddr
                    }
                    _sensorAddresses.value = _sensorAddresses.value + (selectedCom to next)
                    _addressDirty.value = true
                    addrDialogState = null
                }
            )
        }
    }

    @Composable
    fun AddressEditDialog(
        oldAddr: Int?,
        isEdit: Boolean,
        meta: ProtocolMeta?,
        existingAddrs: List<Int>,
        onDismiss: () -> Unit,
        onConfirm: (Int) -> Unit
    ) {
        var input by remember { mutableStateOf(oldAddr?.toString() ?: "") }
        var error by remember { mutableStateOf("") }
        val rangeHint = meta?.let { "范围 ${it.addrMin} ~ ${it.addrMax}" } ?: "(协议元数据未拉到)"

        AlertDialog(
            onDismissRequest = onDismiss,
            title = { Text(if (isEdit) "编辑地址" else "添加地址") },
            text = {
                Column {
                    OutlinedTextField(
                        value = input,
                        onValueChange = {
                            input = it.filter { c -> c.isDigit() }
                            error = ""
                        },
                        label = { Text("地址") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        isError = error.isNotEmpty()
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(rangeHint, fontSize = 11.sp, color = Color.Gray)
                    if (error.isNotEmpty()) {
                        Text(error, fontSize = 12.sp, color = Color.Red)
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    val v = input.toLongOrNull()
                    when {
                        v == null -> error = "必须是数字"
                        meta != null && (v < meta.addrMin || v > meta.addrMax) ->
                            error = "超出范围 ${meta.addrMin}~${meta.addrMax}"
                        v > Int.MAX_VALUE -> error = "地址过大"
                        existingAddrs.contains(v.toInt()) && (!isEdit || v.toInt() != oldAddr) ->
                            error = "地址已存在"
                        else -> onConfirm(v.toInt())
                    }
                }) { Text("确定") }
            },
            dismissButton = {
                TextButton(onClick = onDismiss) { Text("取消") }
            }
        )
    }

    @Composable
    fun SettingsTab() {
        val config = _config.value
        
        // 编辑状态
        var editDeviceId by remember { mutableStateOf("") }
        var editInterval by remember { mutableStateOf("5") }
        var editSleepMode by remember { mutableStateOf("idle") }
        var editWifiSsid by remember { mutableStateOf("") }
        var editWifiPassword by remember { mutableStateOf("") }
        var editMqttBroker by remember { mutableStateOf("") }
        var editMqttPort by remember { mutableStateOf("1883") }
        var editMqttTopic by remember { mutableStateOf("") }
        var editMqttUser by remember { mutableStateOf("") }
        var editMqttPass by remember { mutableStateOf("") }
        var edit4gApn by remember { mutableStateOf("cmnet") }
        var edit4gCops by remember { mutableStateOf("0") }
        var edit4gModem by remember { mutableStateOf("A7670C_yundtu") }
        var wifiEnabled by remember { mutableStateOf(false) }
        var g4Enabled by remember { mutableStateOf(false) }
        var storageEnabled by remember { mutableStateOf(false) }
        var storagePeriod by remember { mutableStateOf("month") }
        var customIntervalMin by remember { mutableStateOf("60") }
        var rs485ExtEnabled by remember { mutableStateOf(false) }
        var mergeSegmentsEnabled by remember { mutableStateOf(false) }
        var saveStatus by remember { mutableStateOf("") }
        var usbRwEnabled by remember { mutableStateOf(false) }
        var configLoaded by remember { mutableStateOf(false) }
        var isReading by remember { mutableStateOf(false) }

        // 从配置同步编辑值
        LaunchedEffect(config) {
            config?.let { cfg ->
                if (isReading) {
                    configLoaded = true
                    isReading = false
                    saveStatus = "读取完成"
                }
                cfg.optJSONObject("system")?.let { sys ->
                    editDeviceId = sys.optString("id", "")
                    editInterval = sys.optInt("interval_preset", 5).toString()
                    editSleepMode = sys.optString("sleep_mode", "idle")
                    customIntervalMin = sys.optInt("interval_custom_min", 60).toString()
                    rs485ExtEnabled = sys.optBoolean("rs485_ext", false)
                    mergeSegmentsEnabled = sys.optBoolean("merge_segments", false)
                }
                cfg.optJSONObject("network")?.let { net ->
                    editMqttBroker = net.optString("mqtt_broker", "")
                    editMqttPort = net.optInt("mqtt_port", 1883).toString()
                    editMqttTopic = net.optString("mqtt_topic", "")
                    editMqttUser = net.optString("mqtt_user", "")
                    editMqttPass = net.optString("mqtt_pass", "")
                    net.optJSONObject("wifi")?.let { wifi ->
                        wifiEnabled = wifi.optBoolean("enabled", false)
                        editWifiSsid = wifi.optString("ssid", "")
                        editWifiPassword = wifi.optString("password", "")
                    }
                    net.optJSONObject("4g")?.let { g4 ->
                        g4Enabled = g4.optBoolean("enabled", false)
                        edit4gApn = g4.optString("apn", "cmnet")
                        edit4gCops = g4.optInt("cops", 0).toString()
                        edit4gModem = g4.optString("modem", "A7670C_yundtu")
                    }
                }
                cfg.optJSONObject("local_storage")?.let { storage ->
                    storageEnabled = storage.optBoolean("enabled", false)
                    storagePeriod = storage.optString("period", "month")
                }
                // USB 模式从 _usb_rw 字段读取（实际 NVM 标志）
                if (cfg.has("_usb_rw")) {
                    usbRwEnabled = cfg.optBoolean("_usb_rw", false)
                }
            }
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp)
                .verticalScroll(rememberScrollState())
        ) {

            // ===== 顶部按钮栏：读取 / 保存 =====
            val scope = rememberCoroutineScope()
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Button(
                    onClick = {
                        isReading = true
                        bleManager.sendCommand("{\"cmd\":\"read\"}")
                        saveStatus = "读取中..."
                    },
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF1976D2))
                ) {
                    Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("读取配置")
                }
                Button(
                    enabled = configLoaded,
                    onClick = {
                        saveStatus = "保存中..."
                        scope.launch {
                            val intervalValue = editInterval.toIntOrNull() ?: 5
                            val customMin = customIntervalMin.toIntOrNull() ?: 60
                            val configJson = org.json.JSONObject().apply {
                                put("system", org.json.JSONObject().apply {
                                    put("id", editDeviceId)
                                    put("interval_preset", intervalValue)
                                    put("interval_custom_min", customMin)
                                    put("sleep_mode", editSleepMode)
                                    put("rs485_ext", rs485ExtEnabled)
                                    put("merge_segments", mergeSegmentsEnabled)
                                })
                                put("local_storage", org.json.JSONObject().apply {
                                    put("enabled", storageEnabled)
                                    put("period", storagePeriod)
                                })
                                put("network", org.json.JSONObject().apply {
                                    put("mqtt_broker", editMqttBroker)
                                    put("mqtt_port", editMqttPort.toIntOrNull() ?: 1883)
                                    put("mqtt_topic", editMqttTopic)
                                    put("mqtt_user", editMqttUser)
                                    put("mqtt_pass", editMqttPass)
                                    put("wifi", org.json.JSONObject().apply {
                                        put("enabled", wifiEnabled)
                                        put("ssid", editWifiSsid)
                                        put("password", editWifiPassword)
                                    })
                                    put("4g", org.json.JSONObject().apply {
                                        put("enabled", g4Enabled)
                                        put("apn", edit4gApn)
                                        put("cops", edit4gCops)
                                        put("modem", edit4gModem)
                                    })
                                })
                            }
                            bleManager.sendCommand("{\"cmd\":\"write_config\",\"config\":$configJson}")
                            saveStatus = "已保存"
                        }
                    },
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF4CAF50))
                ) {
                    Icon(Icons.Default.Check, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("保存配置")
                }
            }

            if (saveStatus.isNotEmpty()) {
                Text(saveStatus, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
            }

            Spacer(modifier = Modifier.height(12.dp))

            // ===== 系统配置 =====
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("系统配置", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
                    Spacer(modifier = Modifier.height(12.dp))
                    
                    OutlinedTextField(value = editDeviceId, onValueChange = { editDeviceId = it }, label = { Text("设备编号") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    var intervalExpanded by remember { mutableStateOf(false) }
                    val intervalOptions = listOf("0" to "不休眠", "1" to "5分钟", "2" to "10分钟", "3" to "15分钟", "4" to "30分钟", "5" to "1小时", "6" to "2小时", "7" to "4小时", "8" to "8小时", "9" to "12小时", "10" to "24小时", "99" to "自定义")
                    val selectedIntervalLabel = intervalOptions.find { it.first == editInterval }?.second ?: "1小时"
                    
                    Box(modifier = Modifier.fillMaxWidth()) {
                        OutlinedTextField(value = selectedIntervalLabel, onValueChange = {}, label = { Text("采集间隔") }, readOnly = true, modifier = Modifier.fillMaxWidth(), trailingIcon = { IconButton(onClick = { intervalExpanded = true }) { Icon(Icons.Default.ArrowDropDown, "展开") } })
                        DropdownMenu(expanded = intervalExpanded, onDismissRequest = { intervalExpanded = false }, modifier = Modifier.fillMaxWidth(0.9f)) {
                            intervalOptions.forEach { (value, label) -> DropdownMenuItem(text = { Text(label) }, onClick = { editInterval = value; intervalExpanded = false }) }
                        }
                    }
                    
                    if (editInterval == "99") {
                        Spacer(modifier = Modifier.height(8.dp))
                        OutlinedTextField(value = customIntervalMin, onValueChange = { customIntervalMin = it }, label = { Text("自定义间隔（分钟）") }, modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                    }
                    
                    Spacer(modifier = Modifier.height(8.dp))
                    var sleepExpanded by remember { mutableStateOf(false) }
                    val sleepOptions = listOf("light" to "轻休眠", "deep" to "深休眠")
                    val selectedSleepLabel = sleepOptions.find { it.first == editSleepMode }?.second ?: "轻休眠"
                    Box(modifier = Modifier.fillMaxWidth()) {
                        OutlinedTextField(value = selectedSleepLabel, onValueChange = {}, label = { Text("休眠模式") }, readOnly = true, modifier = Modifier.fillMaxWidth(), trailingIcon = { IconButton(onClick = { sleepExpanded = true }) { Icon(Icons.Default.ArrowDropDown, "展开") } })
                        DropdownMenu(expanded = sleepExpanded, onDismissRequest = { sleepExpanded = false }, modifier = Modifier.fillMaxWidth(0.9f)) {
                            sleepOptions.forEach { (value, label) -> DropdownMenuItem(text = { Text(label) }, onClick = { editSleepMode = value; sleepExpanded = false }) }
                        }
                    }
                }
            }
            
            Spacer(modifier = Modifier.height(12.dp))

            // ===== MQTT =====
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("MQTT", fontWeight = FontWeight.Bold)
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedTextField(value = editMqttBroker, onValueChange = { editMqttBroker = it }, label = { Text("服务器") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                    Spacer(modifier = Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(value = editMqttPort, onValueChange = { editMqttPort = it }, label = { Text("端口") }, modifier = Modifier.weight(1f), singleLine = true)
                        OutlinedTextField(value = editMqttTopic, onValueChange = { editMqttTopic = it }, label = { Text("主题") }, modifier = Modifier.weight(2f), singleLine = true)
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = editMqttUser,
                            onValueChange = { editMqttUser = it },
                            label = { Text("用户名") },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            visualTransformation = PasswordVisualTransformation()
                        )
                        OutlinedTextField(
                            value = editMqttPass,
                            onValueChange = { editMqttPass = it },
                            label = { Text("密码") },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            visualTransformation = PasswordVisualTransformation()
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            // ===== 4G =====
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("4G", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                        Switch(checked = g4Enabled, onCheckedChange = { g4Enabled = it })
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    // Modem 型号选择
                    var modemExpanded by remember { mutableStateOf(false) }
                    val modemOptions = listOf("A7670C_yundtu", "A7670G")
                    Box(modifier = Modifier.fillMaxWidth()) {
                        OutlinedTextField(value = edit4gModem, onValueChange = {}, label = { Text("Modem 型号") }, readOnly = true, modifier = Modifier.fillMaxWidth(), trailingIcon = { IconButton(onClick = { modemExpanded = true }) { Icon(Icons.Default.ArrowDropDown, "展开") } }, singleLine = true)
                        DropdownMenu(expanded = modemExpanded, onDismissRequest = { modemExpanded = false }, modifier = Modifier.fillMaxWidth(0.9f)) {
                            modemOptions.forEach { model -> DropdownMenuItem(text = { Text(model) }, onClick = { edit4gModem = model; modemExpanded = false }) }
                        }
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(value = edit4gApn, onValueChange = { edit4gApn = it }, label = { Text("APN") }, modifier = Modifier.weight(2f), singleLine = true)
                        OutlinedTextField(value = edit4gCops, onValueChange = { edit4gCops = it }, label = { Text("运营商") }, modifier = Modifier.weight(1f), singleLine = true)
                    }
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            // ===== 本地存储 =====
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("本地存储", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                        Switch(checked = storageEnabled, onCheckedChange = { storageEnabled = it })
                    }
                    if (storageEnabled) {
                        Spacer(modifier = Modifier.height(8.dp))
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                            listOf("month" to "按月", "day" to "按日").forEach { (value, label) ->
                                FilterChip(selected = storagePeriod == value, onClick = { storagePeriod = value }, label = { Text(label) }, leadingIcon = if (storagePeriod == value) {{ Icon(Icons.Default.Check, null, Modifier.size(16.dp)) }} else null)
                            }
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            // ===== WiFi =====
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("WiFi", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                        Switch(checked = wifiEnabled, onCheckedChange = { wifiEnabled = it })
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedTextField(value = editWifiSsid, onValueChange = { editWifiSsid = it }, label = { Text("SSID") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedTextField(
                        value = editWifiPassword,
                        onValueChange = { editWifiPassword = it },
                        label = { Text("密码") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation()
                    )
                }
            }

            Spacer(modifier = Modifier.height(12.dp))
            
            // ===== 高级设置 =====
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("高级设置", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
                    Spacer(modifier = Modifier.height(12.dp))
                    Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("485扩展", style = MaterialTheme.typography.bodyMedium)
                            Text(if (rs485ExtEnabled) "4通道模式" else "2通道模式", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Switch(checked = rs485ExtEnabled, onCheckedChange = { rs485ExtEnabled = it })
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("合并报文", style = MaterialTheme.typography.bodyMedium)
                            Text("全通道数据合并到一段报文", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Switch(checked = mergeSegmentsEnabled, onCheckedChange = { mergeSegmentsEnabled = it })
                    }
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            // ===== 导入地址表 =====
            OutlinedButton(onClick = { bleManager.sendCommand("{\"cmd\":\"import_address_list\"}"); saveStatus = "正在导入地址表..." }, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(modifier = Modifier.width(4.dp))
                Text("导入地址表 (address_list.csv)")
            }

            Spacer(modifier = Modifier.height(8.dp))

            // ===== 导入配置 (下拉选源) =====
            val configSources = listOf(
                "出厂配置 (config.default)" to "load_default",
                "同步配置文件 (config.json)" to "sync_config"
            )
            var configSrcIdx by remember { mutableStateOf(0) }
            var configSrcExpanded by remember { mutableStateOf(false) }
            var showImportDialog by remember { mutableStateOf(false) }

            Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Box(modifier = Modifier.weight(1f)) {
                    OutlinedTextField(
                        value = configSources[configSrcIdx].first,
                        onValueChange = {},
                        label = { Text("配置来源") },
                        readOnly = true,
                        modifier = Modifier.fillMaxWidth(),
                        trailingIcon = { IconButton(onClick = { configSrcExpanded = true }) { Icon(Icons.Default.ArrowDropDown, "展开") } },
                        singleLine = true
                    )
                    DropdownMenu(expanded = configSrcExpanded, onDismissRequest = { configSrcExpanded = false }, modifier = Modifier.fillMaxWidth(0.9f)) {
                        configSources.forEachIndexed { idx, (label, _) ->
                            DropdownMenuItem(text = { Text(label) }, onClick = { configSrcIdx = idx; configSrcExpanded = false })
                        }
                    }
                }
                Spacer(modifier = Modifier.width(8.dp))
                OutlinedButton(
                    onClick = { showImportDialog = true },
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Color(0xFFFF9800))
                ) {
                    Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("导入")
                }
            }
            if (showImportDialog) {
                val (label, cmd) = configSources[configSrcIdx]
                val isFactory = cmd == "load_default"
                androidx.compose.material3.AlertDialog(
                    onDismissRequest = { showImportDialog = false },
                    title = { Text(if (isFactory) "恢复出厂配置" else "同步配置文件") },
                    text = {
                        Text(
                            if (isFactory)
                                "将从设备 /config.default 文件整体覆盖 NVM（不含地址表）。\n\n确定执行？"
                            else
                                "将从设备 /config.json 文件合并进 NVM（增量更新，文件没写的字段保留旧值）。\n\n确定执行？"
                        )
                    },
                    confirmButton = {
                        Button(onClick = {
                            bleManager.sendCommand("{\"cmd\":\"$cmd\"}")
                            saveStatus = "正在执行: $label ..."
                            showImportDialog = false
                        }, colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFFF9800))) { Text("确定") }
                    },
                    dismissButton = {
                        androidx.compose.material3.TextButton(onClick = { showImportDialog = false }) { Text("取消") }
                    }
                )
            }

            Spacer(modifier = Modifier.height(12.dp))

            // ===== U盘模式 =====
            var showRebootDialog by remember { mutableStateOf(false) }
            var pendingUsbRwValue by remember { mutableStateOf(false) }
            
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("U盘模式可读写", fontWeight = FontWeight.Bold)
                            Text(if (usbRwEnabled) "开启 - 电脑可读写" else "关闭 - 设备可保存", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Switch(checked = usbRwEnabled, onCheckedChange = { pendingUsbRwValue = it; showRebootDialog = true })
                    }
                }
            }
            
            if (showRebootDialog) {
                androidx.compose.material3.AlertDialog(
                    onDismissRequest = { showRebootDialog = false },
                    title = { Text("需要重启") },
                    text = { Text("切换需要重启设备才能生效。") },
                    confirmButton = {
                        Button(onClick = {
                            usbRwEnabled = pendingUsbRwValue
                            bleManager.sendCommand("{\"cmd\":\"set_usb_rw\",\"enabled\":$pendingUsbRwValue}")
                            android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({ bleManager.sendCommand("{\"cmd\":\"reboot\"}") }, 500)
                            showRebootDialog = false
                        }) { Text("重启") }
                    },
                    dismissButton = {
                        androidx.compose.material3.TextButton(onClick = { usbRwEnabled = pendingUsbRwValue; bleManager.sendCommand("{\"cmd\":\"set_usb_rw\",\"enabled\":$pendingUsbRwValue}"); showRebootDialog = false }) { Text("稍后重启") }
                    }
                )
            }

            Spacer(modifier = Modifier.height(16.dp))

            // ===== 控制按钮 =====
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                Button(onClick = { bleManager.sendCommand("{\"cmd\":\"read_sensors\"}") }, colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF4CAF50))) { Text("采集") }
                Button(onClick = { bleManager.sendCommand("{\"cmd\":\"reboot\"}") }, colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFFF9800))) { Text("重启") }
                Button(onClick = { bleManager.disconnect() }, colors = ButtonDefaults.buttonColors(containerColor = Color.Gray)) { Text("断开") }
            }

            Spacer(modifier = Modifier.height(8.dp))
            Text("v1.1.0-nvm", modifier = Modifier.fillMaxWidth(), style = MaterialTheme.typography.bodySmall, color = Color.Gray, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        if (::bleManager.isInitialized) {
            bleManager.cleanup()
        }
    }
}

data class SensorReading(
    val addr: Int,
    val channel: Int = 1,
    val autoId: Int = -1,
    val a: Double = 0.0,
    val b: Double = 0.0,
    val z: Double = 0.0,
    val model: Int = -1,
    val temp: Double = 0.0,
    val status: String = "pending"
)

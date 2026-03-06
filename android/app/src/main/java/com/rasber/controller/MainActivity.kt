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
    
    // ConfigTab 状态
    data class A4Result(val autoId: Int, val addr: Long, val a: Double, val b: Double, val z: Double)
    data class BatchResult(val autoId: Int, val addr: Long, val model: String = "", val status: String)
    private var _a4Results = mutableStateOf<List<A4Result>>(emptyList())
    private var _a4SingleResult = mutableStateOf<A4Result?>(null)
    private var _batchResults = mutableStateOf<List<BatchResult>>(emptyList())
    private var _configStatus = mutableStateOf("")
    private var _batchRunning = mutableStateOf(false)
    private var _a4Running = mutableStateOf(false)
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
                // 数据读取相关命令
                "get_sensors" -> {
                    val com = json.optString("com", "1")
                    val addrsArray = json.optJSONArray("addrs")
                    if (addrsArray != null) {
                        val addrs = (0 until addrsArray.length()).map { addrsArray.getInt(it) }
                        _sensorAddresses.value = _sensorAddresses.value + (com to addrs)
                        // 初始化传感器数据占位
                        addrs.forEach { addr ->
                            if (!_sensorData.value.containsKey(addr)) {
                                _sensorData.value = _sensorData.value + (addr to SensorReading(addr, com.toIntOrNull() ?: 1, status = "pending"))
                            }
                        }
                        android.util.Log.d("MainActivity", "Got sensors for COM$com: ${addrs.size} addrs")
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
                        onClick = { selectedTab = 0 },
                        icon = { Icon(Icons.Default.Bluetooth, "连接") },
                        label = { Text("连接") }
                    )
                    NavigationBarItem(
                        selected = selectedTab == 1,
                        onClick = { selectedTab = 1 },
                        icon = { Icon(Icons.Default.Build, "配置") },
                        label = { Text("配置") }
                    )
                    NavigationBarItem(
                        selected = selectedTab == 2,
                        onClick = { selectedTab = 2 },
                        icon = { Icon(Icons.Default.List, "数据") },
                        label = { Text("数据") }
                    )
                    NavigationBarItem(
                        selected = selectedTab == 3,
                        onClick = { selectedTab = 3 },
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
                                batchResults.forEach { r ->
                                    bleManager.sendCommand("{\"cmd\":\"read_model\",\"com\":\"$selectedCom\",\"addr\":${r.addr}}")
                                }
                            },
                            enabled = batchResults.isNotEmpty(),
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("读取型号", fontSize = 12.sp)
                        }
                        Button(
                            onClick = {
                                val m = batchModel.toIntOrNull() ?: 0
                                batchResults.forEach { r ->
                                    bleManager.sendCommand("{\"cmd\":\"write_model_single\",\"com\":\"$selectedCom\",\"addr\":${r.addr},\"model\":$m}")
                                }
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
        var selectedCom by remember { mutableStateOf("1") }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp)
        ) {


            // COM 口选择
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceEvenly
            ) {
                listOf("1" to "COM1", "2" to "COM2").forEach { (value, label) ->
                    FilterChip(
                        selected = selectedCom == value,
                        onClick = { 
                            selectedCom = value
                            // 清空当前数据，准备加载新COM的数据
                            _sensorData.value = emptyMap()
                        },
                        label = { Text(label) }
                    )
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // 操作按钮
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(4.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Button(
                    onClick = { 
                        bleManager.sendCommand("{\"cmd\":\"get_sensors\",\"com\":\"$selectedCom\"}")
                    },
                    modifier = Modifier.weight(1f)
                ) {
                    Text("读取地址")
                }
                Button(
                    onClick = { 
                        _sensorAddresses.value = _sensorAddresses.value + (selectedCom to emptyList())
                        _sensorData.value = emptyMap()
                        _scanProgress.value = 0
                        bleManager.sendCommand("{\"cmd\":\"scan\",\"com\":\"$selectedCom\"}") 
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFFF9800)),
                    modifier = Modifier.weight(1f)
                ) {
                    Text("扫地址")
                }
                Button(
                    onClick = { 
                        bleManager.sendCommand("{\"cmd\":\"read_data\",\"com\":\"$selectedCom\"}") 
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF4CAF50)),
                    modifier = Modifier.weight(1f)
                ) {
                    Text("读取数据")
                }
            }

            // 型号操作按钮
            var targetModel by remember { mutableStateOf(0) }
            var modelExpanded by remember { mutableStateOf(false) }
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
            
            // 第三行：读取型号 + 设置型号 + 型号下拉框（同一行）
            Row(
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
                        .padding(vertical = 8.dp)
                ) {
                    // 固定列：地址 + 状态
                    Text("地址", modifier = Modifier.width(100.dp).padding(start = 8.dp), fontWeight = FontWeight.Bold)
                    Text("状态", modifier = Modifier.width(40.dp), fontWeight = FontWeight.Bold)
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
                            Text("COM$selectedCom 暂无传感器配置，点击\"读取地址\"或\"扫地址\"", 
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
                                // 固定列：地址（可点击读取单个传感器）+ 状态
                                Text(
                                    "$addr",
                                    modifier = Modifier
                                        .width(100.dp)
                                        .padding(start = 8.dp)
                                        .clickable {
                                            bleManager.sendCommand("{\"cmd\":\"poll\",\"com\":\"$selectedCom\",\"addr\":$addr}")
                                            _sensorData.value = _sensorData.value + (addr to SensorReading(addr, selectedCom.toIntOrNull() ?: 1, status = "pending"))
                                        },
                                    color = MaterialTheme.colorScheme.primary,
                                    textDecoration = androidx.compose.ui.text.style.TextDecoration.Underline
                                )
                                Text(statusIcon, modifier = Modifier.width(40.dp))
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
                }
            }
        }
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
        var edit4gApn by remember { mutableStateOf("cmnet") }
        var edit4gCops by remember { mutableStateOf("0") }
        var wifiEnabled by remember { mutableStateOf(false) }
        var g4Enabled by remember { mutableStateOf(false) }
        // 本地存储和U盘模式
        var storageEnabled by remember { mutableStateOf(false) }
        var storagePeriod by remember { mutableStateOf("month") }
        var usbRwEnabled by remember { mutableStateOf(false) }
        var customIntervalMin by remember { mutableStateOf("60") }
        // 高级设置
        var rs485ExtEnabled by remember { mutableStateOf(false) }
        var mergeSegmentsEnabled by remember { mutableStateOf(false) }
        
        // 从配置同步编辑值
        LaunchedEffect(config) {
            config?.let { cfg ->
                cfg.optJSONObject("system")?.let { sys ->
                    editDeviceId = sys.optString("id", "")
                    editInterval = sys.optInt("interval", 5).toString()
                    editSleepMode = sys.optString("sleep_mode", "idle")
                }
                cfg.optJSONObject("wifi")?.let { wifi ->
                    wifiEnabled = wifi.optBoolean("enabled", false)
                    editWifiSsid = wifi.optString("ssid", "")
                    editWifiPassword = wifi.optString("password", "")
                }
                cfg.optJSONObject("mqtt")?.let { mqtt ->
                    editMqttBroker = mqtt.optString("broker", "")
                    editMqttPort = mqtt.optInt("port", 1883).toString()
                    editMqttTopic = mqtt.optString("topic", "")
                }
                cfg.optJSONObject("4g")?.let { g4 ->
                    g4Enabled = g4.optBoolean("enabled", false)
                    edit4gApn = g4.optString("apn", "cmnet")
                    edit4gCops = g4.optInt("cops", 0).toString()
                }
                // 本地存储配置
                cfg.optJSONObject("local_storage")?.let { storage ->
                    storageEnabled = storage.optBoolean("enabled", false)
                    storagePeriod = storage.optString("period", "month")
                }
                // U盘模式配置
                cfg.optJSONObject("system")?.let { sys ->
                    usbRwEnabled = sys.optBoolean("usb_rw", false)
                    rs485ExtEnabled = sys.optBoolean("rs485_ext", false)
                    mergeSegmentsEnabled = sys.optBoolean("merge_segments", false)
                }
            }
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp)
                .verticalScroll(rememberScrollState())
        ) {


            // 读取配置按钮
            Button(
                onClick = { bleManager.sendCommand("{\"cmd\":\"read\"}") },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("获取全部配置")
            }

            Spacer(modifier = Modifier.height(12.dp))

            // 系统配置编辑
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("系统配置", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
                    Spacer(modifier = Modifier.height(12.dp))
                    
                    // 设备 ID
                    OutlinedTextField(
                        value = editDeviceId,
                        onValueChange = { editDeviceId = it },
                        label = { Text("设备编号") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true
                    )
                    
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    // 采集间隔 - 下拉选择
                    var intervalExpanded by remember { mutableStateOf(false) }
                    val intervalOptions = listOf(
                        "0" to "0 - 不休眠", "1" to "1 - 5分钟", "2" to "2 - 10分钟", "3" to "3 - 15分钟",
                        "4" to "4 - 30分钟", "5" to "5 - 1小时", "6" to "6 - 2小时", "7" to "7 - 4小时",
                        "8" to "8 - 8小时", "9" to "9 - 12小时", "10" to "10 - 24小时", "99" to "99 - 自定义"
                    )
                    val selectedIntervalLabel = intervalOptions.find { it.first == editInterval }?.second ?: "1 - 5分钟"
                    
                    Box(modifier = Modifier.fillMaxWidth()) {
                        OutlinedTextField(
                            value = selectedIntervalLabel,
                            onValueChange = {},
                            label = { Text("采集间隔") },
                            readOnly = true,
                            modifier = Modifier.fillMaxWidth(),
                            trailingIcon = {
                                IconButton(onClick = { intervalExpanded = true }) {
                                    Icon(Icons.Default.ArrowDropDown, contentDescription = "展开")
                                }
                            }
                        )
                        DropdownMenu(
                            expanded = intervalExpanded,
                            onDismissRequest = { intervalExpanded = false },
                            modifier = Modifier.fillMaxWidth(0.9f)
                        ) {
                            intervalOptions.forEach { (value, label) ->
                                DropdownMenuItem(
                                    text = { Text(label) },
                                    onClick = {
                                        editInterval = value
                                        intervalExpanded = false
                                    }
                                )
                            }
                        }
                    }
                    
                    // 自定义间隔输入框 (仅当选择自定义时显示)
                    if (editInterval == "99") {
                        Spacer(modifier = Modifier.height(8.dp))
                        OutlinedTextField(
                            value = customIntervalMin,
                            onValueChange = { customIntervalMin = it },
                            label = { Text("自定义间隔（分钟）") },
                            modifier = Modifier.fillMaxWidth(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
                        )
                    }
                    
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    // 休眠模式 - 下拉选择
                    var sleepExpanded by remember { mutableStateOf(false) }
                    val sleepOptions = listOf("light" to "轻休眠", "deep" to "深休眠")
                    val selectedSleepLabel = sleepOptions.find { it.first == editSleepMode }?.second ?: "轻休眠"
                    
                    Box(modifier = Modifier.fillMaxWidth()) {
                        OutlinedTextField(
                            value = selectedSleepLabel,
                            onValueChange = {},
                            label = { Text("休眠模式") },
                            readOnly = true,
                            modifier = Modifier.fillMaxWidth(),
                            trailingIcon = {
                                IconButton(onClick = { sleepExpanded = true }) {
                                    Icon(Icons.Default.ArrowDropDown, contentDescription = "展开")
                                }
                            }
                        )
                        DropdownMenu(
                            expanded = sleepExpanded,
                            onDismissRequest = { sleepExpanded = false },
                            modifier = Modifier.fillMaxWidth(0.9f)
                        ) {
                            sleepOptions.forEach { (value, label) ->
                                DropdownMenuItem(
                                    text = { Text(label) },
                                    onClick = {
                                        editSleepMode = value
                                        sleepExpanded = false
                                    }
                                )
                            }
                        }
                    }
                    
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    Spacer(modifier = Modifier.height(16.dp))
                    
                    // 保存按钮
                    val scope = rememberCoroutineScope()
                    Button(
                        onClick = {
                            scope.launch {
                                if (editDeviceId.isNotEmpty()) {
                                    bleManager.sendCommand("{\"cmd\":\"set_id\",\"value\":\"$editDeviceId\"}")
                                    kotlinx.coroutines.delay(200)
                                }
                                // 发送间隔设置，如果是自定义还需发送自定义分钟数
                                val intervalValue = editInterval.toIntOrNull() ?: 5
                                if (intervalValue == 99) {
                                    val customMin = customIntervalMin.toIntOrNull() ?: 60
                                    bleManager.sendCommand("{\"cmd\":\"set_interval\",\"value\":99,\"custom_min\":$customMin}")
                                } else {
                                    bleManager.sendCommand("{\"cmd\":\"set_interval\",\"value\":$intervalValue}")
                                }
                                kotlinx.coroutines.delay(200)
                                bleManager.sendCommand("{\"cmd\":\"set_sleep\",\"value\":\"$editSleepMode\"}")
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF2196F3))
                    ) {
                        Text("保存配置")
                    }
                }
            }
            Spacer(modifier = Modifier.height(16.dp))

            // ===== MQTT 配置 =====
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("🌐 MQTT", fontWeight = FontWeight.Bold)
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedTextField(value = editMqttBroker, onValueChange = { editMqttBroker = it }, label = { Text("服务器") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                    Spacer(modifier = Modifier.height(8.dp))
                    Row {
                        OutlinedTextField(value = editMqttPort, onValueChange = { editMqttPort = it }, label = { Text("端口") }, modifier = Modifier.weight(1f), singleLine = true)
                        Spacer(modifier = Modifier.width(8.dp))
                        OutlinedTextField(value = editMqttTopic, onValueChange = { editMqttTopic = it }, label = { Text("主题") }, modifier = Modifier.weight(2f), singleLine = true)
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    Button(onClick = { bleManager.sendCommand("{\"cmd\":\"set_mqtt\",\"broker\":\"$editMqttBroker\",\"port\":${editMqttPort.toIntOrNull() ?: 1883},\"topic\":\"$editMqttTopic\"}") }, modifier = Modifier.fillMaxWidth()) { Text("保存 MQTT") }
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            // ===== 4G 配置 =====
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("📡 4G", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                        Switch(checked = g4Enabled, onCheckedChange = { 
                            g4Enabled = it
                            bleManager.sendCommand(if (it) "{\"cmd\":\"enable_4g\"}" else "{\"cmd\":\"disable_4g\"}")
                        })
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    Row {
                        OutlinedTextField(value = edit4gApn, onValueChange = { edit4gApn = it }, label = { Text("APN") }, modifier = Modifier.weight(2f), singleLine = true)
                        Spacer(modifier = Modifier.width(8.dp))
                        OutlinedTextField(value = edit4gCops, onValueChange = { edit4gCops = it }, label = { Text("运营商") }, modifier = Modifier.weight(1f), singleLine = true)
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    Button(onClick = { bleManager.sendCommand("{\"cmd\":\"set_4g\",\"apn\":\"$edit4gApn\",\"cops\":${edit4gCops.toIntOrNull() ?: 0}}") }, modifier = Modifier.fillMaxWidth()) { Text("保存 4G") }
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            // ===== 本地存储 =====
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("💾 本地存储", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                        Switch(checked = storageEnabled, onCheckedChange = { 
                            storageEnabled = it
                            bleManager.sendCommand("{\"cmd\":\"set_storage\",\"enabled\":$it}")
                        })
                    }
                    if (storageEnabled) {
                        Spacer(modifier = Modifier.height(8.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceEvenly
                        ) {
                            listOf("month" to "按月分文件存储", "day" to "按日分文件存储").forEach { (value, label) ->
                                val isSelected = storagePeriod == value
                                FilterChip(
                                    selected = isSelected,
                                    onClick = { 
                                        storagePeriod = value
                                        bleManager.sendCommand("{\"cmd\":\"set_storage\",\"period\":\"$value\"}")
                                    },
                                    label = { Text(label, fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal) },
                                    leadingIcon = if (isSelected) {{ Icon(Icons.Default.Check, contentDescription = null, modifier = Modifier.size(16.dp)) }} else null,
                                    colors = FilterChipDefaults.filterChipColors(
                                        selectedContainerColor = Color(0xFF1976D2),
                                        selectedLabelColor = Color.White,
                                        selectedLeadingIconColor = Color.White
                                    ),
                                    border = FilterChipDefaults.filterChipBorder(
                                        borderColor = Color.Gray,
                                        selectedBorderColor = Color(0xFF1976D2),
                                        enabled = true,
                                        selected = isSelected
                                    )
                                )
                            }
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            // ===== WiFi 配置 =====
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("📶 WiFi", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                        Switch(checked = wifiEnabled, onCheckedChange = { 
                            wifiEnabled = it
                            bleManager.sendCommand(if (it) "{\"cmd\":\"enable_wifi\"}" else "{\"cmd\":\"disable_wifi\"}")
                        })
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedTextField(value = editWifiSsid, onValueChange = { editWifiSsid = it }, label = { Text("SSID") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedTextField(value = editWifiPassword, onValueChange = { editWifiPassword = it }, label = { Text("密码") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                    Spacer(modifier = Modifier.height(8.dp))
                    Button(onClick = { bleManager.sendCommand("{\"cmd\":\"set_wifi\",\"ssid\":\"$editWifiSsid\",\"password\":\"$editWifiPassword\"}") }, modifier = Modifier.fillMaxWidth()) { Text("保存 WiFi") }
                }
            }

            Spacer(modifier = Modifier.height(16.dp))
            
            // 高级设置卡片
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("⚙️ 高级设置", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
                    Spacer(modifier = Modifier.height(12.dp))
                    
                    // 485扩展开关
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("485扩展", style = MaterialTheme.typography.bodyMedium)
                            Text(
                                if (rs485ExtEnabled) "4通道模式" else "2通道模式",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Switch(checked = rs485ExtEnabled, onCheckedChange = { 
                            rs485ExtEnabled = it
                            bleManager.sendCommand("{\"cmd\":\"set_rs485_ext\",\"enabled\":$it}")
                        })
                    }
                    
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    // 合并报文开关
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("合并报文", style = MaterialTheme.typography.bodyMedium)
                            Text(
                                "全通道数据合并到一段报文",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Switch(checked = mergeSegmentsEnabled, onCheckedChange = { 
                            mergeSegmentsEnabled = it
                            bleManager.sendCommand("{\"cmd\":\"set_merge_segments\",\"enabled\":$it}")
                        })
                    }
                }
            }

            Spacer(modifier = Modifier.height(16.dp))
            // U盘模式可读写（放在最后）
            var showRebootDialog by remember { mutableStateOf(false) }
            var pendingUsbRwValue by remember { mutableStateOf(false) }
            
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("U盘模式可读写", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
                            Text(
                                if (usbRwEnabled) "开启 - 电脑可读写，设备不可保存" else "关闭 - 设备可保存，电脑只读",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Switch(
                            checked = usbRwEnabled, 
                            onCheckedChange = { 
                                pendingUsbRwValue = it
                                showRebootDialog = true
                            }
                        )
                    }
                }
            }
            
            // 重启确认对话框
            if (showRebootDialog) {
                androidx.compose.material3.AlertDialog(
                    onDismissRequest = { showRebootDialog = false },
                    title = { Text("需要重启") },
                    text = { Text("切换需要重启设备才能生效。\n${if (pendingUsbRwValue) "开启后电脑可以读写文件" else "关闭后设备可以保存配置"}\n\n是否立即重启？") },
                    confirmButton = {
                        Button(onClick = {
                            usbRwEnabled = pendingUsbRwValue
                            bleManager.sendCommand("{\"cmd\":\"set_usb_rw\",\"enabled\":$pendingUsbRwValue}")
                            android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
                                bleManager.sendCommand("{\"cmd\":\"reboot\"}")
                            }, 500)
                            showRebootDialog = false
                        }) {
                            Text("重启")
                        }
                    },
                    dismissButton = {
                        androidx.compose.material3.TextButton(onClick = { 
                            usbRwEnabled = pendingUsbRwValue
                            bleManager.sendCommand("{\"cmd\":\"set_usb_rw\",\"enabled\":$pendingUsbRwValue}")
                            showRebootDialog = false
                        }) {
                            Text("稍后重启")
                        }
                    }
                )
            }

            Spacer(modifier = Modifier.height(16.dp))

            // 控制按钮
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                Button(onClick = { bleManager.sendCommand("{\"cmd\":\"read_sensors\"}") }, colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF4CAF50))) { Text("采集") }
                Button(onClick = { bleManager.sendCommand("{\"cmd\":\"reboot\"}") }, colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFFF9800))) { Text("重启") }
                Button(onClick = { bleManager.disconnect() }, colors = ButtonDefaults.buttonColors(containerColor = Color.Gray)) { Text("断开") }
            }

            Spacer(modifier = Modifier.height(8.dp))
            Text("v1.0.3", modifier = Modifier.fillMaxWidth(), style = MaterialTheme.typography.bodySmall, color = Color.Gray)
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

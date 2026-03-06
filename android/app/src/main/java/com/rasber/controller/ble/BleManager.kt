package com.rasber.controller.ble

import android.annotation.SuppressLint
import android.bluetooth.*
import android.bluetooth.le.*
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import java.util.UUID
import java.util.concurrent.CopyOnWriteArrayList

/**
 * BLE 管理器 - 使用回调模式代替 StateFlow 避免 Compose recomposition 问题
 */
@SuppressLint("MissingPermission")
class BleManager(private val context: Context) {
    
    companion object {
        private const val TAG = "BleManager"
        val NUS_SERVICE_UUID: UUID = UUID.fromString("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
        val NUS_RX_UUID: UUID = UUID.fromString("6E400002-B5A3-F393-E0A9-E50E24DCCA9E")
        val NUS_TX_UUID: UUID = UUID.fromString("6E400003-B5A3-F393-E0A9-E50E24DCCA9E")
        val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
    }
    
    private val bluetoothAdapter: BluetoothAdapter? by lazy {
        try {
            val manager = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
            manager?.adapter
        } catch (e: Exception) {
            Log.e(TAG, "Failed to get BluetoothAdapter: ${e.message}")
            null
        }
    }
    
    private val scanner: BluetoothLeScanner? get() = bluetoothAdapter?.bluetoothLeScanner
    
    private var gatt: BluetoothGatt? = null
    private var rxCharacteristic: BluetoothGattCharacteristic? = null
    private var txCharacteristic: BluetoothGattCharacteristic? = null
    private val handler = Handler(Looper.getMainLooper())
    
    // 接收缓冲区 - 用于拼接分包的 JSON 数据
    private val receiveBuffer = StringBuilder()
    
    // 使用线程安全的列表
    private val _devices = CopyOnWriteArrayList<BluetoothDevice>()
    
    // 公开的状态 (volatile 确保可见性)
    @Volatile var isConnected: Boolean = false
        private set
    
    @Volatile var isScanning: Boolean = false
        private set
    
    @Volatile var lastReceivedData: String = ""
        private set
    
    // 回调接口
    var onDevicesChanged: ((List<BluetoothDevice>) -> Unit)? = null
    var onConnectionChanged: ((Boolean) -> Unit)? = null
    var onScanningChanged: ((Boolean) -> Unit)? = null
    var onDataReceived: ((String) -> Unit)? = null
    
    fun getDevices(): List<BluetoothDevice> = _devices.toList()
    
    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            val device = result.device
            if (device.name != null && !_devices.any { it.address == device.address }) {
                Log.d(TAG, "Found device: ${device.name} - ${device.address}")
                _devices.add(device)
                handler.post { onDevicesChanged?.invoke(_devices.toList()) }
            }
        }
        
        override fun onScanFailed(errorCode: Int) {
            Log.e(TAG, "Scan failed with error: $errorCode")
            isScanning = false
            handler.post { onScanningChanged?.invoke(false) }
        }
    }
    
    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            Log.d(TAG, "Connection state changed: status=$status, newState=$newState")
            when (newState) {
                BluetoothProfile.STATE_CONNECTED -> {
                    Log.d(TAG, "Connected, discovering services...")
                    gatt.discoverServices()
                }
                BluetoothProfile.STATE_DISCONNECTED -> {
                    Log.d(TAG, "Disconnected")
                    isConnected = false
                    handler.post { onConnectionChanged?.invoke(false) }
                }
            }
        }
        
        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            Log.d(TAG, "Services discovered: status=$status")
            val service = gatt.getService(NUS_SERVICE_UUID)
            if (service != null) {
                Log.d(TAG, "NUS service found")
                rxCharacteristic = service.getCharacteristic(NUS_RX_UUID)
                txCharacteristic = service.getCharacteristic(NUS_TX_UUID)
                
                txCharacteristic?.let { tx ->
                    gatt.setCharacteristicNotification(tx, true)
                    val descriptor = tx.getDescriptor(CCCD_UUID)
                    descriptor?.let { d ->
                        @Suppress("DEPRECATION")
                        d.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                        @Suppress("DEPRECATION")
                        gatt.writeDescriptor(d)
                    }
                }
                
                isConnected = true
                // 请求更大的 MTU 以支持更长的 JSON 消息
                gatt.requestMtu(256)
                handler.post { onConnectionChanged?.invoke(true) }
            } else {
                Log.e(TAG, "NUS service not found")
            }
        }
        
        override fun onMtuChanged(gatt: BluetoothGatt, mtu: Int, status: Int) {
            Log.d(TAG, "MTU changed: mtu=$mtu, status=$status")
        }
        
        @Deprecated("Deprecated in Java")
        override fun onCharacteristicWrite(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) {
            Log.d(TAG, "Characteristic write: uuid=${characteristic.uuid}, status=$status (0=success)")
        }
        
        @Deprecated("Deprecated in Java")
        override fun onCharacteristicChanged(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic) {
            if (characteristic.uuid == NUS_TX_UUID) {
                val chunk = characteristic.value?.decodeToString() ?: ""
                Log.d(TAG, "Received chunk (${chunk.length} bytes): $chunk")
                
                receiveBuffer.append(chunk)
                
                // 方法1: 使用换行符作为消息分隔符
                val bufferStr = receiveBuffer.toString()
                Log.d(TAG, "Buffer total length: ${bufferStr.length}")
                
                // 检查是否有完整的行（以换行符结尾）
                val newlinePos = bufferStr.indexOf('\n')
                if (newlinePos >= 0) {
                    val line = bufferStr.substring(0, newlinePos).trim()
                    receiveBuffer.delete(0, newlinePos + 1)
                    
                    if (line.isNotEmpty() && line.startsWith("{")) {
                        Log.d(TAG, "Complete line received: ${line.take(100)}...")
                        lastReceivedData = line
                        handler.post { onDataReceived?.invoke(line) }
                    }
                }
            }
        }
    }
    
    fun startScan() {
        val currentScanner = scanner
        if (currentScanner == null) {
            Log.e(TAG, "BLE Scanner not available")
            return
        }
        
        Log.d(TAG, "Starting scan...")
        _devices.clear()
        isScanning = true
        onScanningChanged?.invoke(true)
        onDevicesChanged?.invoke(emptyList())
        
        try {
            currentScanner.startScan(scanCallback)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start scan: ${e.message}")
            isScanning = false
            onScanningChanged?.invoke(false)
            return
        }
        
        handler.postDelayed({ stopScan() }, 15000)
    }
    
    fun stopScan() {
        Log.d(TAG, "Stopping scan...")
        try {
            scanner?.stopScan(scanCallback)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to stop scan: ${e.message}")
        }
        isScanning = false
        handler.post { onScanningChanged?.invoke(false) }
    }
    
    fun connect(device: BluetoothDevice) {
        Log.d(TAG, "Connecting to ${device.address}...")
        stopScan()
        gatt?.close()
        gatt = device.connectGatt(context, false, gattCallback)
    }
    
    fun disconnect() {
        Log.d(TAG, "Disconnecting...")
        gatt?.disconnect()
        gatt?.close()
        gatt = null
        isConnected = false
        handler.post { onConnectionChanged?.invoke(false) }
    }
    
    fun sendCommand(cmd: String): Boolean {
        Log.d(TAG, "sendCommand called: $cmd")
        Log.d(TAG, "gatt=$gatt, rxCharacteristic=$rxCharacteristic, isConnected=$isConnected")
        
        if (gatt == null) {
            Log.e(TAG, "sendCommand failed: gatt is null")
            return false
        }
        if (rxCharacteristic == null) {
            Log.e(TAG, "sendCommand failed: rxCharacteristic is null")
            return false
        }
        
        rxCharacteristic?.let { rx ->
            @Suppress("DEPRECATION")
            // 添加换行符 - 固件需要换行符来识别完整的 JSON 消息
            rx.value = (cmd + "\n").toByteArray()
            // 显式设置写入类型为 WRITE_TYPE_DEFAULT (需要响应)
            @Suppress("DEPRECATION")
            rx.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
            @Suppress("DEPRECATION")
            val result = gatt?.writeCharacteristic(rx) ?: false
            Log.d(TAG, "Sent: $cmd, writeType=${rx.writeType}, result=$result")
            return result
        }
        return false
    }
    
    fun cleanup() {
        Log.d(TAG, "Cleanup...")
        stopScan()
        disconnect()
        onDevicesChanged = null
        onConnectionChanged = null
        onScanningChanged = null
        onDataReceived = null
    }
}

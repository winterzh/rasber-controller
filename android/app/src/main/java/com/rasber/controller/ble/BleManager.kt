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
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * BLE 管理器 - 分包发送支持，写入同步确认
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
    
    // 接收缓冲区
    private val receiveBuffer = StringBuilder()
    
    // 写入同步
    @Volatile private var writeLatch: CountDownLatch? = null
    
    // 协商的 MTU
    @Volatile private var negotiatedMtu: Int = 23
    
    private val _devices = CopyOnWriteArrayList<BluetoothDevice>()
    
    @Volatile var isConnected: Boolean = false
        private set
    
    @Volatile var isScanning: Boolean = false
        private set
    
    @Volatile var lastReceivedData: String = ""
        private set
    
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
                gatt.requestMtu(512)
                handler.post { onConnectionChanged?.invoke(true) }
            } else {
                Log.e(TAG, "NUS service not found")
            }
        }
        
        override fun onMtuChanged(gatt: BluetoothGatt, mtu: Int, status: Int) {
            Log.d(TAG, "MTU changed: mtu=$mtu, status=$status")
            if (status == BluetoothGatt.GATT_SUCCESS) {
                negotiatedMtu = mtu
            }
        }
        
        @Deprecated("Deprecated in Java")
        override fun onCharacteristicWrite(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) {
            Log.d(TAG, "Write complete: status=$status")
            writeLatch?.countDown()
        }
        
        @Deprecated("Deprecated in Java")
        override fun onCharacteristicChanged(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic) {
            if (characteristic.uuid == NUS_TX_UUID) {
                val chunk = characteristic.value?.decodeToString() ?: ""
                Log.d(TAG, "RX chunk (${chunk.length}B): $chunk")
                
                receiveBuffer.append(chunk)
                
                val bufferStr = receiveBuffer.toString()
                val newlinePos = bufferStr.indexOf('\n')
                if (newlinePos >= 0) {
                    val line = bufferStr.substring(0, newlinePos).trim()
                    receiveBuffer.delete(0, newlinePos + 1)
                    
                    if (line.isNotEmpty() && line.startsWith("{")) {
                        Log.d(TAG, "Complete msg: ${line.take(100)}...")
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
    
    /**
     * 发送命令 — 自动分包，每包等待写入确认后再发下一包
     */
    fun sendCommand(cmd: String): Boolean {
        Log.d(TAG, "sendCommand (${cmd.length}B): ${cmd.take(80)}...")
        
        if (gatt == null || rxCharacteristic == null) {
            Log.e(TAG, "sendCommand failed: not connected")
            return false
        }
        
        val data = (cmd + "\n").toByteArray()
        val chunkSize = maxOf(negotiatedMtu - 3, 20)  // ATT header 3B
        
        if (data.size <= chunkSize) {
            return writeChunkSync(data)
        }
        
        // 大消息 → 后台线程分包发送
        val totalChunks = (data.size + chunkSize - 1) / chunkSize
        Log.d(TAG, "Chunking ${data.size}B into $totalChunks pkts (chunk=$chunkSize, MTU=$negotiatedMtu)")
        Thread {
            var offset = 0
            var idx = 0
            while (offset < data.size) {
                val end = minOf(offset + chunkSize, data.size)
                val chunk = data.copyOfRange(offset, end)
                val ok = writeChunkSync(chunk)
                idx++
                Log.d(TAG, "Chunk $idx/$totalChunks (${chunk.size}B) ok=$ok")
                if (!ok) {
                    Log.e(TAG, "Chunked send FAILED at chunk $idx")
                    break
                }
                offset = end
            }
        }.start()
        return true
    }
    
    /**
     * 同步写入单个 chunk — 等待 onCharacteristicWrite 回调
     */
    private fun writeChunkSync(data: ByteArray): Boolean {
        val latch = CountDownLatch(1)
        writeLatch = latch
        
        rxCharacteristic?.let { rx ->
            @Suppress("DEPRECATION")
            rx.value = data
            @Suppress("DEPRECATION")
            rx.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
            @Suppress("DEPRECATION")
            val result = gatt?.writeCharacteristic(rx) ?: false
            if (!result) {
                writeLatch = null
                return false
            }
            return latch.await(2, TimeUnit.SECONDS)
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

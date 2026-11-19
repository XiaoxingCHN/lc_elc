package com.example.lab_inventory_client

import android.Manifest
import android.app.Activity
import android.app.Application
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.gengcon.www.jcprintersdk.JCPrintApi
import com.gengcon.www.jcprintersdk.callback.Callback
import com.gengcon.www.jcprintersdk.callback.PrintCallback
import com.gengcon.www.jcprintersdk.callback.ScanCallback
import com.gengcon.www.jcprintersdk.bean.PrinterDevice
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import org.json.JSONObject
import java.util.Collections
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 精臣 (NIIMBOT) B1 Pro 蓝牙直打桥接。
 *
 * 对应 Android SDK 4.1.1（`4.1.1-release.aar` + `image-1.9.5.aar`）。接口与参数
 * 全部来自 `Android端SDK 接口说明文档 V4.1.1`：
 *   * 2.1.2 初始化：getInstance(Callback) → initSdk(Application) →
 *     initDefaultImageLibrarySettings("", "")；
 *   * 2.2.1 蓝牙连接：connectBluetoothPrinter 是同步耗时方法，必须在子线程调用；
 *   * 2.3 / 8.2–8.6 打印：setTotalPrintQuantity(页数 × 份数) →
 *     startPrintJob(浓度, 纸张类型, 打印模式, PrintCallback) →
 *     在 onBufferFree 里逐页 draw… + generateLabelJson + commitData →
 *     onProgress 到最后一页最后一份后 endPrintJob()；
 *   * 8.4.1.2 printerInfo 的字段与顺序。
 *
 * 该类的定位是“薄桥接”：40×20 mm 的排版（二维码位置、文字行、字号下限、行数上限、
 * 截断标记）由 Dart 侧 `planThermalLabel` 计算后原样传入，保证 Android 与 Windows
 * 两条直打路径用同一份几何计划；这里只负责把计划翻译成 SDK 调用并如实回报结果。
 */
class NiimbotPrinterBridge(
    private val activity: Activity,
    private val application: Application,
    private val requestPermissions: (Array<String>, (Boolean) -> Unit) -> Unit,
) : EventChannel.StreamHandler {

    companion object {
        private const val TAG = "LabPrinter"
        private const val QR_CODE_TYPE = 31

        /** 搜索时长（秒）。SDK 的 scanBluetoothPrinter(int) 把该 int 当秒数延时。 */
        private const val SCAN_SECONDS = 12

        /** B1 Pro：浓度 1–5（默认 3）、间隙纸、热敏。 */
        private const val DENSITY = 3
        private const val PAPER_TYPE_GAP = 1
        private const val PRINT_MODE_THERMAL = 1

        /** B1 Pro 是 300 dpi，SDK 文档给出的毫米→像素倍率。 */
        private const val FALLBACK_PRINT_MULTIPLE = 11.81f

        private const val CONNECT_OK = 0
        private const val CONNECT_FAILED = -1
        private const val CONNECT_BUSY = -2
        private const val CONNECT_UNSUPPORTED = -3
    }

    private val mainHandler = Handler(Looper.getMainLooper())
    private val initExecutor = Executors.newSingleThreadExecutor()

    @Volatile
    private var initState = 0 // 0 未初始化，1 成功，2 失败
    @Volatile
    private var initError: String? = null
    private val initLock = Any()
    private val initWaiters = mutableListOf<(Boolean, String?) -> Unit>()

    private var eventSink: EventChannel.EventSink? = null
    private val discovered = Collections.synchronizedSet(mutableSetOf<String>())

    @Volatile
    private var printing = false
    private var printTimeout: Runnable? = null

    /**
     * 全局回调：SDK 只会在第一次 getInstance() 时安装它。连接结果以
     * connectBluetoothPrinter 的返回值 + isConnection() 为准，这里只记录断开，
     * 让 Dart 侧能在打印前判断。
     */
    private val callback = object : Callback {
        override fun onConnectSuccess(address: String?, type: Int) {
            Log.d(TAG, "onConnectSuccess type=$type")
        }

        override fun onDisConnect() {
            Log.d(TAG, "onDisConnect")
        }

        override fun onElectricityChange(powerLevel: Int) {}

        override fun onCoverStatus(coverStatus: Int) {}

        override fun onPaperStatus(paperStatus: Int) {}

        override fun onRfidReadStatus(status: Int) {}

        override fun onRibbonStatus(status: Int) {}

        override fun onRibbonRfidReadStatus(status: Int) {}

        override fun onFirmErrors() {}
    }

    // ------------------------------------------------------------------
    // EventChannel（扫描结果）
    // ------------------------------------------------------------------

    override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
        eventSink = events
        discovered.clear()
    }

    override fun onCancel(arguments: Any?) {
        eventSink = null
        stopScanInternal()
    }

    private fun emit(map: Map<String, Any?>) {
        mainHandler.post { eventSink?.success(map) }
    }

    private fun emitError(code: String, message: String) {
        emit(mapOf("type" to "error", "code" to code, "message" to message))
    }

    // ------------------------------------------------------------------
    // 初始化
    // ------------------------------------------------------------------

    private fun ensureInit(done: (Boolean, String?) -> Unit) {
        synchronized(initLock) {
            when (initState) {
                1 -> {
                    done(true, null)
                    return
                }
                2 -> {
                    done(false, initError)
                    return
                }
            }
            initWaiters.add(done)
            if (initWaiters.size > 1) return // 已有一个初始化任务在跑
        }
        initExecutor.execute {
            var ok = false
            var error: String? = null
            try {
                val api = JCPrintApi.getInstance(callback)
                // initSdk 会把 image AAR 里的 font/language.json 与
                // font/ZT001.ttf 复制到应用私有目录；失败即无法绘制中文。
                ok = api.initSdk(application)
                if (!ok) {
                    error = "精臣打印组件初始化失败（字体资源不可用）"
                } else if (api.initDefaultImageLibrarySettings("", "") != 0) {
                    ok = false
                    error = "精臣打印组件图像库初始化失败"
                }
            } catch (t: Throwable) {
                ok = false
                error = "精臣打印组件初始化异常：${t.message ?: t.javaClass.simpleName}"
            }
            val waiters: List<(Boolean, String?) -> Unit>
            synchronized(initLock) {
                initState = if (ok) 1 else 2
                initError = error
                waiters = initWaiters.toList()
                initWaiters.clear()
            }
            mainHandler.post { waiters.forEach { it(ok, error) } }
        }
    }

    private fun sdk(): JCPrintApi? = if (initState == 1) JCPrintApi.getInstance(callback) else null

    // ------------------------------------------------------------------
    // MethodChannel 入口
    // ------------------------------------------------------------------

    fun handle(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "available" -> ensureInit { ok, error ->
                result.success(mapOf("available" to ok, "reason" to error))
            }

            "requestPermissions" -> requestPermissions(requiredPermissions()) { granted ->
                result.success(granted)
            }

            "scan" -> startScan(result)
            "stopScan" -> {
                stopScanInternal()
                result.success(null)
            }

            "connect" -> connect(call.argument<String>("address"), result)
            "disconnect" -> {
                sdk()?.close()
                result.success(true)
            }

            "isConnected" -> result.success(isConnected())
            "paperInfo" -> paperInfo(result)
            "print" -> print(call.arguments, result)
            else -> result.notImplemented()
        }
    }

    // ------------------------------------------------------------------
    // 权限 / 蓝牙状态
    // ------------------------------------------------------------------

    /**
     * 按 doc3 第 2.1 节：
     *   * Android 12+（API 31）：BLUETOOTH_SCAN + BLUETOOTH_CONNECT；
     *   * Android 6–11：ACCESS_FINE_LOCATION；
     *   * 更早：清单里的 BLUETOOTH 即可（运行时无需请求）。
     */
    private fun requiredPermissions(): Array<String> {
        return when {
            Build.VERSION.SDK_INT >= 31 -> arrayOf(
                Manifest.permission.BLUETOOTH_SCAN,
                Manifest.permission.BLUETOOTH_CONNECT,
            )
            Build.VERSION.SDK_INT >= 23 -> arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
            else -> emptyArray()
        }
    }

    private fun hasPermissions(): Boolean = requiredPermissions().all {
        activity.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED
    }

    private fun adapter(): BluetoothAdapter? {
        val manager = activity.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
        val fromManager = manager?.adapter
        if (fromManager != null) return fromManager
        // Pre-API-18 fallback; minSdk is 23 so this is only a safety net.
        @Suppress("DEPRECATION")
        return BluetoothAdapter.getDefaultAdapter()
    }

    /** doc3 第 2.3 节：Android 10–11 搜索蓝牙必须打开系统定位服务。 */
    private fun locationEnabled(): Boolean {
        val manager = activity.getSystemService(Context.LOCATION_SERVICE) as? LocationManager
            ?: return false
        return if (Build.VERSION.SDK_INT >= 28) {
            manager.isLocationEnabled
        } else {
            @Suppress("DEPRECATION")
            manager.isProviderEnabled(LocationManager.GPS_PROVIDER) ||
                manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
        }
    }

    private fun isConnected(): Boolean = sdk()?.isConnection() == 0

    // ------------------------------------------------------------------
    // 扫描
    // ------------------------------------------------------------------

    private fun startScan(result: MethodChannel.Result) {
        ensureInit { ok, error ->
            if (!ok) {
                result.error("SDK_UNAVAILABLE", error ?: "精臣打印组件不可用", null)
                return@ensureInit
            }
            val bluetooth = adapter()
            if (bluetooth == null) {
                result.error("BLUETOOTH_UNAVAILABLE", "此设备没有蓝牙模块，无法使用蓝牙打印机。", null)
                return@ensureInit
            }
            if (!bluetooth.isEnabled) {
                result.error("BLUETOOTH_OFF", "请先打开手机蓝牙，再搜索打印机。", null)
                return@ensureInit
            }
            if (!hasPermissions()) {
                result.error("PERMISSION_DENIED", "缺少蓝牙搜索/连接权限，请允许后重试。", null)
                return@ensureInit
            }
            // Android 12+ 的 BLUETOOTH_SCAN 带 neverForLocation，不要求定位服务；
            // Android 10–11 仍必须打开定位服务（doc3 2.3）。
            if (Build.VERSION.SDK_INT in 29..30 && !locationEnabled()) {
                result.error("LOCATION_OFF", "请打开系统定位服务后再搜索蓝牙打印机（Android 10/11 的要求）。", null)
                return@ensureInit
            }
            discovered.clear()
            emitBondedDevices(bluetooth)
            try {
                sdk()?.scanBluetoothPrinter(SCAN_SECONDS, object : ScanCallback {
                    override fun onScan(device: PrinterDevice?) {
                        val address = device?.deviceAddress?.trim().orEmpty()
                        if (address.isEmpty()) return
                        if (!discovered.add(address.uppercase())) return
                        emit(
                            mapOf(
                                "type" to "device",
                                "name" to (device?.deviceName?.trim().orEmpty()),
                                "address" to address,
                            ),
                        )
                    }

                    override fun onFinish() {
                        emit(mapOf("type" to "finished"))
                    }
                })
                result.success(true)
            } catch (t: Throwable) {
                result.error("SCAN_FAILED", "启动蓝牙搜索失败：${t.message ?: t.javaClass.simpleName}", null)
            }
        }
    }

    /**
     * doc3 第 2.4.3 节建议同时列出已配对设备：广播搜索只覆盖正在广播的设备，
     * 已配对但未广播的打印机会被漏掉。只保留经典/双模设备（SPP 打印机）。
     */
    private fun emitBondedDevices(bluetooth: BluetoothAdapter) {
        val bonded = try {
            bluetooth.bondedDevices
        } catch (_: SecurityException) {
            return // Android 12+ 没有 BLUETOOTH_CONNECT 时读不到
        } catch (_: Throwable) {
            return
        }
        for (device in bonded) {
            try {
                val type = device.type
                if (type != BluetoothDevice.DEVICE_TYPE_CLASSIC &&
                    type != BluetoothDevice.DEVICE_TYPE_DUAL
                ) {
                    continue
                }
                val address = device.address?.trim().orEmpty()
                if (address.isEmpty() || !discovered.add(address.uppercase())) continue
                emit(
                    mapOf(
                        "type" to "device",
                        "name" to (device.name?.trim().orEmpty()),
                        "address" to address,
                    ),
                )
            } catch (_: SecurityException) {
                // 读不到名字就跳过，绝不让一次权限异常中断整个搜索。
            }
        }
    }

    private fun stopScanInternal() {
        try {
            // stopScanPrinter(0) = 取消蓝牙 discovery（1 才是取消 WIFI 搜索）。
            sdk()?.stopScanPrinter(0)
        } catch (_: Throwable) {
        }
    }

    // ------------------------------------------------------------------
    // 连接
    // ------------------------------------------------------------------

    private fun connect(address: String?, result: MethodChannel.Result) {
        val target = address?.trim().orEmpty()
        if (target.isEmpty()) {
            result.error("INVALID_ADDRESS", "没有选择打印机（蓝牙地址为空）。", null)
            return
        }
        ensureInit { ok, error ->
            if (!ok) {
                result.error("SDK_UNAVAILABLE", error ?: "精臣打印组件不可用", null)
                return@ensureInit
            }
            if (!hasPermissions()) {
                result.error("PERMISSION_DENIED", "缺少蓝牙连接权限，请允许后重试。", null)
                return@ensureInit
            }
            // doc3 第四节：连接前必须先取消正在进行的搜索，否则连接会失败。
            stopScanInternal()
            Thread {
                var code = CONNECT_FAILED
                var message: String? = null
                try {
                    code = sdk()?.connectBluetoothPrinter(target) ?: CONNECT_UNSUPPORTED
                } catch (t: Throwable) {
                    code = CONNECT_FAILED
                    message = t.message
                }
                mainHandler.post {
                    result.success(
                        mapOf(
                            "code" to code,
                            "connected" to (code == CONNECT_OK && isConnected()),
                            "message" to connectMessage(code, message),
                        ),
                    )
                }
            }.start()
        }
    }

    private fun connectMessage(code: Int, detail: String?): String? = when (code) {
        CONNECT_OK -> null
        CONNECT_FAILED -> "连接失败：请确认打印机已开机、未被其他手机占用，并在系统蓝牙中完成配对（配对码 0000 或 1234）。${detail.orEmpty()}"
        CONNECT_BUSY -> "打印机或蓝牙正忙，请稍候重试。"
        CONNECT_UNSUPPORTED -> "该设备不是受支持的蓝牙打印机。"
        else -> "连接失败（代码 $code）。"
    }

    // ------------------------------------------------------------------
    // 纸张信息
    // ------------------------------------------------------------------

    private fun paperInfo(result: MethodChannel.Result) {
        val info = try {
            sdk()?.paperInfo
        } catch (t: Throwable) {
            result.error("PAPER_INFO_FAILED", "读取纸张信息失败：${t.message}", null)
            return
        }
        if (info == null) {
            result.success(null)
            return
        }
        result.success(
            mapOf(
                "state" to info.state,
                "paperType" to info.paperType,
                "gapHeight" to info.gapHeight,
                "totalHeight" to info.totalHeight,
                "paperWidth" to info.paperWidth,
            ),
        )
    }

    // ------------------------------------------------------------------
    // 打印
    // ------------------------------------------------------------------

    private data class TextLine(
        val text: String,
        val x: Float,
        val y: Float,
        val width: Float,
        val height: Float,
        val fontSize: Float,
        val bold: Boolean,
    )

    private data class LabelJob(
        val payload: String,
        val lines: List<TextLine>,
    )

    private data class PrintSpec(
        val widthMm: Float,
        val heightMm: Float,
        val copies: Int,
        val density: Int,
        val paperType: Int,
        val printMode: Int,
        val printMultiple: Float,
        val qrX: Float,
        val qrY: Float,
        val qrSize: Float,
    )

    private fun print(arguments: Any?, result: MethodChannel.Result) {
        val root = arguments as? Map<*, *>
        if (root == null) {
            result.error("BAD_ARGUMENT", "打印参数为空。", null)
            return
        }
        val labels = parseJobs(root["labels"])
        val spec = parseSpec(root["spec"])
        if (labels == null || labels.isEmpty()) {
            result.error("BAD_ARGUMENT", "没有可打印的标签内容。", null)
            return
        }
        if (spec == null) {
            result.error("BAD_ARGUMENT", "打印尺寸或份数不合法。", null)
            return
        }
        if (printing) {
            result.error("BUSY", "已有打印任务正在进行，请等待完成。", null)
            return
        }
        ensureInit { ok, error ->
            if (!ok) {
                result.error("SDK_UNAVAILABLE", error ?: "精臣打印组件不可用", null)
                return@ensureInit
            }
            val api = sdk()
            if (api == null || api.isConnection() != 0) {
                result.error("NO_CONNECTION", "打印机尚未连接，请先搜索并连接蓝牙打印机。", null)
                return@ensureInit
            }
            // 文档 5.2 / getMultiple()：连接后以 SDK 根据打印机分辨率算出的倍率
            // 为准（200dpi=8，300dpi≈11.81）；拿不到才用 Dart 侧的机型提示值。
            val sdkMultiple = try {
                api.getMultiple()
            } catch (_: Throwable) {
                0f
            }
            val effective = if (sdkMultiple.isFinite() && sdkMultiple > 0f) {
                spec.copy(printMultiple = sdkMultiple)
            } else {
                spec
            }
            startJob(api, labels, effective, result)
        }
    }

    private fun parseJobs(value: Any?): List<LabelJob>? {
        val list = value as? List<*> ?: return null
        val jobs = ArrayList<LabelJob>(list.size)
        for (entry in list) {
            val map = entry as? Map<*, *> ?: return null
            val payload = (map["payload"] as? String)?.trim().orEmpty()
            if (payload.isEmpty()) return null // 没有二维码的标签绝不当成有码打印
            val rawLines = map["lines"] as? List<*> ?: emptyList<Any?>()
            val lines = ArrayList<TextLine>(rawLines.size)
            for (raw in rawLines) {
                val line = raw as? Map<*, *> ?: return null
                val text = line["text"] as? String ?: continue
                if (text.isEmpty()) continue
                val x = (line["x"] as? Number)?.toFloat() ?: return null
                val y = (line["y"] as? Number)?.toFloat() ?: return null
                val width = (line["width"] as? Number)?.toFloat() ?: return null
                val height = (line["height"] as? Number)?.toFloat() ?: return null
                val fontSize = (line["fontSize"] as? Number)?.toFloat() ?: return null
                if (!x.isFinite() || !y.isFinite() || !width.isFinite() ||
                    !height.isFinite() || !fontSize.isFinite() ||
                    width <= 0f || height <= 0f || fontSize <= 0f
                ) {
                    return null
                }
                lines.add(
                    TextLine(
                        text = text,
                        x = x,
                        y = y,
                        width = width,
                        height = height,
                        fontSize = fontSize,
                        bold = line["bold"] == true,
                    ),
                )
            }
            jobs.add(LabelJob(payload = payload, lines = lines))
        }
        return jobs
    }

    private fun parseSpec(value: Any?): PrintSpec? {
        val map = value as? Map<*, *> ?: return null
        val width = (map["widthMm"] as? Number)?.toFloat() ?: return null
        val height = (map["heightMm"] as? Number)?.toFloat() ?: return null
        val copies = (map["copies"] as? Number)?.toInt() ?: 1
        val qrX = (map["qrX"] as? Number)?.toFloat() ?: return null
        val qrY = (map["qrY"] as? Number)?.toFloat() ?: return null
        val qrSize = (map["qrSize"] as? Number)?.toFloat() ?: return null
        val density = (map["density"] as? Number)?.toInt() ?: DENSITY
        val paperType = (map["paperType"] as? Number)?.toInt() ?: PAPER_TYPE_GAP
        val printMode = (map["printMode"] as? Number)?.toInt() ?: PRINT_MODE_THERMAL
        val multiple = (map["printMultiple"] as? Number)?.toFloat() ?: 0f
        if (!width.isFinite() || !height.isFinite() || width <= 0f || height <= 0f) return null
        if (!qrX.isFinite() || !qrY.isFinite() || !qrSize.isFinite() || qrSize <= 0f) return null
        if (copies < 1) return null
        return PrintSpec(
            widthMm = width,
            heightMm = height,
            copies = copies,
            density = density.coerceIn(1, 5),
            paperType = paperType,
            printMode = printMode,
            printMultiple = if (multiple > 0f && multiple.isFinite()) multiple else FALLBACK_PRINT_MULTIPLE,
            qrX = qrX,
            qrY = qrY,
            qrSize = qrSize,
        )
    }

    private fun startJob(
        api: JCPrintApi,
        jobs: List<LabelJob>,
        spec: PrintSpec,
        result: MethodChannel.Result,
    ) {
        printing = true
        val pages = jobs.size
        val total = pages * spec.copies
        var submitted = 0
        val finished = AtomicBoolean(false)

        fun finish(payload: Map<String, Any?>) {
            if (!finished.compareAndSet(false, true)) return
            printTimeout?.let { mainHandler.removeCallbacks(it) }
            printTimeout = null
            printing = false
            mainHandler.post { result.success(payload) }
        }

        fun fail(code: String, message: String, errorCode: Int? = null, printed: Int = 0) {
            finish(
                mapOf(
                    "ok" to false,
                    "printed" to printed,
                    "truncated" to false,
                    "errorCode" to errorCode,
                    "errorMessage" to message,
                    "error" to code,
                ),
            )
        }

        // 一份计划生成失败或打印机报错后不再提交任何数据（doc 2.3 注意事项）。
        var stopped = false

        val timeoutMs = maxOf(60_000L, 4_000L * total)
        val timeout = Runnable {
            if (finished.get()) return@Runnable
            // cancelJob() 是文档标注的耗时方法：放到工作线程，避免卡住主线程。
            Thread {
                try {
                    api.cancelJob()
                } catch (_: Throwable) {
                }
            }.start()
            fail(
                "TIMEOUT",
                "打印超时（${timeoutMs / 1000} 秒内打印机未完成）。请检查打印机电源、纸张和蓝牙连接后重试。",
            )
        }
        printTimeout = timeout
        mainHandler.postDelayed(timeout, timeoutMs)

        val callback = object : PrintCallback {
            override fun onProgress(
                pageIndex: Int,
                quantityIndex: Int,
                customData: HashMap<String, Any?>?,
            ) {
                if (finished.get()) return
                if (pageIndex >= pages && quantityIndex >= spec.copies) {
                    // doc 2.3.5 / 8.6：最后一份打印完成后结束任务，退出打印状态。
                    val ended = try {
                        api.endPrintJob()
                    } catch (_: Throwable) {
                        false
                    }
                    finish(
                        mapOf(
                            "ok" to true,
                            "printed" to pages,
                            "truncated" to false,
                            "errorCode" to null,
                            "errorMessage" to null,
                            "endJobFailed" to !ended,
                        ),
                    )
                }
            }

            override fun onError(errorCode: Int) {
                // V4.1.1 保留的兼容回调，语义由双参数 onError 提供。
            }

            override fun onError(errorCode: Int, printState: Int) {
                stopped = true
                fail(
                    "PRINT_ERROR",
                    "打印机报告错误（代码 $errorCode）。",
                    errorCode = errorCode,
                    printed = submitted,
                )
            }

            override fun onCancelJob(success: Boolean) {
                stopped = true
                fail("CANCELLED", "打印已取消。", printed = submitted)
            }

            override fun onBufferFree(pageIndex: Int, bufferSize: Int) {
                if (stopped || finished.get()) return
                if (submitted >= pages || bufferSize <= 0) return
                val count = minOf(pages - submitted, bufferSize)
                val jsonList = ArrayList<String>(count)
                val infoList = ArrayList<String>(count)
                try {
                    for (index in submitted until submitted + count) {
                        jsonList.add(renderLabelJson(api, jobs[index], spec))
                        infoList.add(printerInfoJson(spec))
                    }
                    api.commitData(jsonList, infoList)
                } catch (t: Throwable) {
                    stopped = true
                    fail(
                        "RENDER_FAILED",
                        "生成打印数据失败：${t.message ?: t.javaClass.simpleName}",
                        printed = submitted,
                    )
                    return
                }
                submitted += count
            }

            override fun onPause(success: Boolean) {}

            override fun onPausing() {}

            override fun onResume(success: Boolean) {}
        }

        try {
            // doc 2.3.2：总量 = 所有页面的份数之和，必须在 startPrintJob 之前设置。
            api.setTotalPrintQuantity(total)
            api.startPrintJob(spec.density, spec.paperType, spec.printMode, callback)
        } catch (t: Throwable) {
            fail(
                "START_FAILED",
                "无法开始打印：${t.message ?: t.javaClass.simpleName}",
            )
        }
    }

    /** 绘制一页并导出 SDK 的标签 JSON（doc 2.3.3 / 8.4.1）。 */
    private fun renderLabelJson(api: JCPrintApi, job: LabelJob, spec: PrintSpec): String {
        api.drawEmptyLabel(spec.widthMm, spec.heightMm, 0, emptyList<String>())
        api.drawLabelQrCode(
            spec.qrX,
            spec.qrY,
            spec.qrSize,
            spec.qrSize,
            job.payload,
            QR_CODE_TYPE,
            0,
        )
        for (line in job.lines) {
            api.drawLabelText(
                line.x,
                line.y,
                line.width,
                line.height,
                line.text,
                "",
                line.fontSize,
                0, // rotate
                0, // 水平左对齐
                0, // 垂直顶对齐
                6, // 宽高固定，内容超出时自动缩小（不裁切、不丢字）
                0f, // letterSpace
                0.2f, // lineSpace（倍距；与 Windows 直打路径一致）
                booleanArrayOf(line.bold, false, false, false),
            )
        }
        return String(api.generateLabelJson(), Charsets.UTF_8)
    }

    /**
     * doc 8.4.1.2：printQuantity 是“当前页的份数”，printMultiple 以字符串形式
     * 序列化（200dpi = 8，300dpi = 11.81）。
     */
    private fun printerInfoJson(spec: PrintSpec): String {
        val info = JSONObject()
        val payload = JSONObject()
        payload.put("orientation", 0)
        payload.put("margin", org.json.JSONArray().apply { put(0); put(0); put(0); put(0) })
        payload.put("printQuantity", spec.copies)
        payload.put("horizontalOffset", 0)
        payload.put("verticalOffset", 0)
        payload.put("width", spec.widthMm.toDouble())
        payload.put("height", spec.heightMm.toDouble())
        payload.put("printMultiple", spec.printMultiple.toString())
        payload.put("epc", "")
        info.put("printerImageProcessingInfo", payload)
        return info.toString()
    }
}

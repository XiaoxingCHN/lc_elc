package com.example.lab_inventory_client

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel
import android.Manifest
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.location.LocationManager
import android.net.ConnectivityManager
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Build
import android.provider.Settings
import java.security.MessageDigest

class MainActivity : FlutterActivity() {
    private var installing = false
    private var pendingSsidResult: MethodChannel.Result? = null
    private var pendingPrinterPermission: ((Boolean) -> Unit)? = null
    companion object {
        var finishInstall: ((String?, String?) -> Unit)? = null
        private const val SSID_PERMISSION_REQUEST = 4701
        private const val PRINTER_PERMISSION_REQUEST = 4702
    }
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        // 精臣 B1 Pro 蓝牙直打。初始化、扫描、连接、打印都在桥接类里，这里只
        // 负责通道装配与运行时权限回调（权限请求必须由 Activity 发起）。
        val bridge = NiimbotPrinterBridge(this, application) { permissions, done ->
            requestPrinterPermissions(permissions, done)
        }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "lab/printer")
            .setMethodCallHandler { call, result -> bridge.handle(call, result) }
        EventChannel(flutterEngine.dartExecutor.binaryMessenger, "lab/printer/scan")
            .setStreamHandler(bridge)
        // Wi-Fi SSID for the in-memory LAN acceleration hint. The value is read
        // on demand and never written anywhere by this channel.
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "lab/wifi_ssid")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "currentSsid" -> reportSsid(result)
                    "requestPermission" -> requestSsidPermission(result)
                    else -> result.notImplemented()
                }
            }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "lab/client_update")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "unmetered" -> {
                        val network = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
                        result.success(!network.isActiveNetworkMetered)
                    }
                    "facts" -> result.success(mapOf("android_sdk" to Build.VERSION.SDK_INT))
                    "install" -> {
                        if (installing) { result.error("BUSY", "安装器已启动", null); return@setMethodCallHandler }
                        if (Build.VERSION.SDK_INT >= 26 && !packageManager.canRequestPackageInstalls()) {
                            try {
                                startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName")))
                                result.error("INSTALL_PERMISSION", "请在系统设置中允许此应用安装更新，再返回重试。", null)
                            } catch (_: Exception) {
                                result.error("INSTALL_PERMISSION_SETTINGS", "无法打开安装权限页，请到系统设置中允许此应用安装更新。", null)
                            }
                            return@setMethodCallHandler
                        }
                        installing = true
                        val path = call.argument<String>("path")
                        val build = call.argument<Number>("build")?.toLong()
                        val size = call.argument<Number>("size")?.toLong()
                        val hash = call.argument<String>("sha256")
                        Thread {
                            var stage = "INSTALL_ARGUMENT"
                            var message = "安装请求信息不完整，请重新下载更新。"
                            try {
                                require(path != null && build != null && size != null && hash != null)
                                stage = "INSTALL_PACKAGE_READ"; message = "无法读取已下载的更新包，请重新下载。"
                                val file = UpdatePackageFiles.verify(cacheDir, path, size, hash)
                                val flags = if (Build.VERSION.SDK_INT >= 28) PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES
                                stage = "INSTALL_PACKAGE_FORMAT"; message = "系统无法识别此APK，请重新下载完整更新包。"
                                val incoming = packageManager.getPackageArchiveInfo(file.path, flags) ?: error("Invalid APK")
                                val current = packageManager.getPackageInfo(packageName, flags)
                                fun version(info: android.content.pm.PackageInfo): Long =
                                    if (Build.VERSION.SDK_INT >= 28) info.longVersionCode else info.versionCode.toLong()
                                fun signers(info: android.content.pm.PackageInfo): Set<String> {
                                    val signatures = if (Build.VERSION.SDK_INT >= 28) info.signingInfo?.apkContentsSigners else info.signatures
                                    return signatures?.map { s -> MessageDigest.getInstance("SHA-256").digest(s.toByteArray()).joinToString("") { "%02x".format(it.toInt() and 255) } }?.toSet() ?: emptySet()
                                }
                                stage = "INSTALL_PACKAGE_VERSION"; message = "更新包的应用标识或版本与当前应用不匹配。"
                                require(incoming.packageName == packageName && version(incoming) == build && build > version(current))
                                stage = "INSTALL_PACKAGE_SIGNATURE"; message = "更新包签名与已安装应用不一致，已拒绝安装。"
                                require(signers(current).isNotEmpty() && signers(incoming) == signers(current))
                                stage = "INSTALL_SESSION"; message = "系统安装器未能创建安装任务，请检查可用空间和系统安装限制。"
                                val installer = packageManager.packageInstaller
                                val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
                                params.setAppPackageName(packageName)
                                params.setSize(size)
                                if (Build.VERSION.SDK_INT >= 31) params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_REQUIRED)
                                val id = installer.createSession(params)
                                try {
                                    finishInstall = { code, reason -> runOnUiThread {
                                        installing = false; finishInstall = null
                                        if (code == null) result.success(null)
                                        else result.error(code, reason, null)
                                    } }
                                    installer.openSession(id).use { session ->
                                        session.openWrite("update.apk", 0, size).use { output ->
                                            file.inputStream().use { it.copyTo(output) }; session.fsync(output)
                                        }
                                        val callback = Intent(this, UpdateInstallReceiver::class.java)
                                        val mutable = if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0
                                        val pending = PendingIntent.getBroadcast(this, id, callback, PendingIntent.FLAG_UPDATE_CURRENT or mutable)
                                        stage = "INSTALL_COMMIT"; message = "系统未接受安装请求，请检查系统安装限制后重试。"
                                        session.commit(pending.intentSender)
                                    }
                                } catch (e: Exception) { installer.abandonSession(id); throw e }
                            } catch (error: Exception) {
                                val code = if (error is UpdatePackageFiles.VerificationException) error.code else stage
                                val reason = if (error is UpdatePackageFiles.VerificationException) error.message else message
                                runOnUiThread { installing = false; finishInstall = null; result.error(code, reason, null) }
                            }
                        }.start()
                    }
                    else -> result.notImplemented()
                }
            }
    }

    // ------------------------------------------------------------------
    // lab/wifi_ssid
    //
    // Android only reports the SSID when the app holds the fine location
    // permission AND location services are switched on. Every other outcome is
    // reported as an error code so Dart can explain it; nothing is cached or
    // persisted here.
    // ------------------------------------------------------------------

    // minSdk is 23, so the framework's own runtime-permission API is enough
    // (no androidx dependency is added just for this).
    private fun hasSsidPermission(): Boolean =
        checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED

    private fun locationEnabled(): Boolean {
        val manager = getSystemService(Context.LOCATION_SERVICE) as? LocationManager
            ?: return false
        return if (Build.VERSION.SDK_INT >= 28) {
            manager.isLocationEnabled
        } else {
            @Suppress("DEPRECATION")
            manager.isProviderEnabled(LocationManager.GPS_PROVIDER) ||
                manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
        }
    }

    @Suppress("DEPRECATION")
    private fun reportSsid(result: MethodChannel.Result) {
        if (!hasSsidPermission()) {
            result.error("PERMISSION_DENIED", "需要位置权限才能读取 WiFi 名称", null)
            return
        }
        if (!locationEnabled()) {
            result.error("LOCATION_OFF", "请打开系统位置服务后再读取 WiFi 名称", null)
            return
        }
        val manager = applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
        if (manager == null || !manager.isWifiEnabled) {
            // Wired network or Wi-Fi switched off: unknown, not an error.
            result.success("")
            return
        }
        val info = manager.connectionInfo
        val raw = info?.ssid ?: ""
        val ssid = raw.trim().trim('"')
        // Android reports "<unknown ssid>" / "0x" when it cannot resolve it.
        result.success(if (ssid == "<unknown ssid>" || ssid == "0x") "" else ssid)
    }

    private fun requestSsidPermission(result: MethodChannel.Result) {
        if (hasSsidPermission()) {
            result.success(true)
            return
        }
        if (pendingSsidResult != null) {
            // A request is already open: do not stack dialogs.
            result.success(false)
            return
        }
        pendingSsidResult = result
        requestPermissions(
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION),
            SSID_PERMISSION_REQUEST,
        )
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == PRINTER_PERMISSION_REQUEST) {
            val done = pendingPrinterPermission ?: return
            pendingPrinterPermission = null
            done(grantResults.isNotEmpty() &&
                grantResults.all { it == PackageManager.PERMISSION_GRANTED })
            return
        }
        if (requestCode != SSID_PERMISSION_REQUEST) return
        val result = pendingSsidResult ?: return
        pendingSsidResult = null
        result.success(hasSsidPermission())
    }

    /**
     * 请求蓝牙直打所需权限（Android 12+ 的 BLUETOOTH_SCAN/CONNECT，或
     * Android 6–11 的 ACCESS_FINE_LOCATION）。不堆叠对话框：已有请求在等结果
     * 时直接回 false，由 Dart 侧提示用户稍后重试。
     */
    private fun requestPrinterPermissions(
        permissions: Array<String>,
        done: (Boolean) -> Unit,
    ) {
        if (permissions.isEmpty() ||
            permissions.all { checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED }
        ) {
            done(true)
            return
        }
        if (pendingPrinterPermission != null) {
            done(false)
            return
        }
        pendingPrinterPermission = done
        requestPermissions(permissions, PRINTER_PERMISSION_REQUEST)
    }
}

class UpdateInstallReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            @Suppress("DEPRECATION")
            val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
            confirm?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (confirm == null) {
                MainActivity.finishInstall?.invoke("INSTALL_CONFIRMATION", "系统未提供安装确认页面，请重试。")
            } else try {
                context.startActivity(confirm)
            } catch (_: Exception) {
                MainActivity.finishInstall?.invoke("INSTALL_CONFIRMATION", "无法打开系统安装确认页面，请检查系统安装限制。")
            }
        } else {
            val message = when (status) {
                PackageInstaller.STATUS_SUCCESS -> null
                PackageInstaller.STATUS_FAILURE_ABORTED -> "安装已取消，原版本保留，可稍后重试。"
                PackageInstaller.STATUS_FAILURE_STORAGE -> "系统空间不足，释放空间后重试。"
                PackageInstaller.STATUS_FAILURE_BLOCKED -> "系统阻止了安装，请检查安装权限或设备管理限制。"
                PackageInstaller.STATUS_FAILURE_CONFLICT -> "安装包与当前应用冲突，原版本保留。"
                PackageInstaller.STATUS_FAILURE_INCOMPATIBLE -> "此更新包与当前系统不兼容。"
                PackageInstaller.STATUS_FAILURE_INVALID -> "系统判定安装包无效，请重新下载。"
                else -> "系统安装未完成，原版本保留，请重试。"
            }
            MainActivity.finishInstall?.invoke(if (message == null) null else "INSTALL_SYSTEM_$status", message)
        }
    }
}

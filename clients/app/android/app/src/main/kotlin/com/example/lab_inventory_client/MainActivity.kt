package com.example.lab_inventory_client

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import java.io.File
import java.security.MessageDigest

class MainActivity : FlutterActivity() {
    private var installing = false
    companion object { var finishInstall: ((Boolean) -> Unit)? = null }
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
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
                            startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName")))
                            result.error("INSTALL_PERMISSION", "请允许此应用安装更新后重试", null)
                            return@setMethodCallHandler
                        }
                        installing = true
                        val path = call.argument<String>("path")
                        val build = call.argument<Number>("build")?.toLong()
                        val size = call.argument<Number>("size")?.toLong()
                        val hash = call.argument<String>("sha256")
                        Thread {
                            try {
                                require(path != null && build != null && size != null && hash != null)
                                val file = File(path)
                                val root = File(cacheDir, "client-updates").canonicalFile
                                require(file.absolutePath == file.canonicalPath && file.canonicalPath.startsWith(root.path + File.separator))
                                require(file.isFile && file.length() == size && size in 1..536870912L)
                                val digest = MessageDigest.getInstance("SHA-256")
                                file.inputStream().use { stream ->
                                    val buffer = ByteArray(65536)
                                    while (true) { val read = stream.read(buffer); if (read < 0) break; digest.update(buffer, 0, read) }
                                }
                                require(digest.digest().joinToString("") { "%02x".format(it.toInt() and 255) } == hash)
                                val flags = if (Build.VERSION.SDK_INT >= 28) PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES
                                val incoming = packageManager.getPackageArchiveInfo(file.path, flags) ?: error("Invalid APK")
                                val current = packageManager.getPackageInfo(packageName, flags)
                                fun version(info: android.content.pm.PackageInfo): Long =
                                    if (Build.VERSION.SDK_INT >= 28) info.longVersionCode else info.versionCode.toLong()
                                fun signers(info: android.content.pm.PackageInfo): Set<String> {
                                    val signatures = if (Build.VERSION.SDK_INT >= 28) info.signingInfo?.apkContentsSigners else info.signatures
                                    return signatures?.map { s -> MessageDigest.getInstance("SHA-256").digest(s.toByteArray()).joinToString("") { "%02x".format(it.toInt() and 255) } }?.toSet() ?: emptySet()
                                }
                                require(incoming.packageName == packageName && version(incoming) == build && build > version(current))
                                require(signers(current).isNotEmpty() && signers(incoming) == signers(current))
                                val installer = packageManager.packageInstaller
                                val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
                                params.setAppPackageName(packageName)
                                params.setSize(size)
                                if (Build.VERSION.SDK_INT >= 31) params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_REQUIRED)
                                val id = installer.createSession(params)
                                try {
                                    finishInstall = { success -> runOnUiThread {
                                        installing = false; finishInstall = null
                                        if (success) result.success(null)
                                        else result.error("INSTALL_CANCELLED", "安装未完成，原版本保留", null)
                                    } }
                                    installer.openSession(id).use { session ->
                                        session.openWrite("update.apk", 0, size).use { output ->
                                            file.inputStream().use { it.copyTo(output) }; session.fsync(output)
                                        }
                                        val callback = Intent(this, UpdateInstallReceiver::class.java)
                                        val mutable = if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0
                                        val pending = PendingIntent.getBroadcast(this, id, callback, PendingIntent.FLAG_UPDATE_CURRENT or mutable)
                                        session.commit(pending.intentSender)
                                    }
                                } catch (e: Exception) { installer.abandonSession(id); throw e }
                            } catch (_: Exception) {
                                runOnUiThread { installing = false; finishInstall = null; result.error("INSTALL_FAILED", "安装包身份或权限校验失败", null) }
                            }
                        }.start()
                    }
                    else -> result.notImplemented()
                }
            }
    }
}

class UpdateInstallReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            @Suppress("DEPRECATION")
            val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
            confirm?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (confirm != null) context.startActivity(confirm)
        } else MainActivity.finishInstall?.invoke(status == PackageInstaller.STATUS_SUCCESS)
    }
}

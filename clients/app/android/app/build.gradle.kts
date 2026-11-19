plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.example.lab_inventory_client"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.example.lab_inventory_client"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        //
        // minSdk: flutter_secure_storage - the "记住登录" key store - requires
        // Android 6.0 / API 23 or newer; it wraps the data key with an RSA key
        // held in the Android Keystore. Flutter's own default is already 24, so
        // maxOf() is a guard rather than a change.
        minSdk = maxOf(23, flutter.minSdkVersion)
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        // 精臣 Android SDK (4.1.1-release.aar) 只提供 arm64-v8a 与 armeabi-v7a
        // 的 JNI 库；保留 x86_64 会让模拟器装得上却在打印时找不到 libminilzo.so。
        // 真机均为 ARM，因此这里显式限定 ABI，与 SDK 保持一致。
        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a")
        }
    }

    // Prebuilt JNI libraries inside plugin AARs (ML Kit barcode, Flutter's own
    // util libs) ignore ndk.abiFilters, so a few x86_64 .so files still leaked
    // into the APK. The app cannot run on x86_64 at all (the NIIMBOT SDK has no
    // x86_64 slice and libflutter.so/libapp.so are not built for it), so those
    // files are dead weight - drop them explicitly.
    packaging {
        jniLibs {
            excludes += listOf("lib/x86_64/**")
        }
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

dependencies {
    // 精臣 (NIIMBOT) Android SDK 4.1.1 与图像库 1.9.5，来源与 SHA256 见
    // app/libs/README.md。文档 V4.1.1 第 1.1.2.2 节：API 31 及以上直接
    // fileTree 引入 *.jar/*.aar（不再需要 flatDir）。B1 Pro 在 V4.1.1
    // 更新记录中明确“SDK 支持 B1_Pro”。
    //
    // image-1.9.5.aar 不能省略：4.1.1-release.aar 的 JCPrintApi 全部绘图
    // 方法（drawEmptyLabel / drawLabelText / drawLabelQrCode /
    // generateLabelJson …）都是对 com.niimbot.canvas.image.NBCanvasImageApiSzwy
    // 的 native 转发，该类与 libniimbot_canvas_image.so / libskia.so 只在
    // image AAR 里；只有 LPAPI（B50/B11/T6/T7/T8 系列）才是可选的。
    implementation(fileTree(mapOf("dir" to "libs", "include" to listOf("*.jar", "*.aar"))))
}

flutter {
    source = "../.."
}

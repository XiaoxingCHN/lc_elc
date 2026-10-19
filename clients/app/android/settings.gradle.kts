// Android build configuration: Flutter standard layout + official Aliyun mirrors.
//
// NETWORK NOTE: this network cannot reach Google Maven (dl.google.com /
// maven.google.com time out on Dart and JDK17 TLS), so the AndroidX / ML Kit /
// CameraX artifacts that mobile_scanner and printing need - and the AGP/Kotlin
// plugin markers themselves - come from the official Aliyun mirror
// (https://help.aliyun.com/en/document_detail/436767.html). Verified reachable:
//   com.android.application.gradle.plugin:9.1.0            (200)
//   org.jetbrains.kotlin.android.gradle.plugin:2.4.0       (200)
//   com.android.tools.build:gradle:9.1.0                   (200)
//   com.google.mlkit:barcode-scanning:17.3.0 AAR           (200, 9.9 MB)
// The canonical repositories are KEPT as fallbacks, TLS verification is
// untouched, and nothing global (proxy / system trust store) is changed - only
// this project's repository list.
//
// Kotlin DSL note: `maven("https://...")` is not offered by this Gradle
// version's settings-script accessors (only the Closure/Action overloads are),
// so every mirror uses `maven { url = uri(...) }`.
pluginManagement {
    val flutterSdkPath =
        run {
            val properties = java.util.Properties()
            file("local.properties").inputStream().use { properties.load(it) }
            val flutterSdkPath = properties.getProperty("flutter.sdk")
            require(flutterSdkPath != null) { "flutter.sdk not set in local.properties" }
            flutterSdkPath
        }

    includeBuild("$flutterSdkPath/packages/flutter_tools/gradle")

    repositories {
        maven { url = uri("https://maven.aliyun.com/repository/gradle-plugin") }
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://maven.aliyun.com/repository/public") }
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositories {
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://repo1.maven.org/maven2") }
        maven { url = uri("https://maven.aliyun.com/repository/public") }
        // Flutter's engine repository (declared at project scope by
        // FlutterPlugin.kt; repeated here so it applies under settings-level
        // repository resolution as well).
        maven { url = uri("https://storage.googleapis.com/download.flutter.io") }
        google()
        mavenCentral()
    }
}

plugins {
    id("dev.flutter.flutter-plugin-loader") version "1.0.0"
    id("com.android.application") version "9.1.0" apply false
    id("org.jetbrains.kotlin.android") version "2.4.0" apply false
}

include(":app")

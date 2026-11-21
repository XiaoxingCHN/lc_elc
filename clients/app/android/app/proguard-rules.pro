# 精臣 (NIIMBOT) Android SDK 混淆规则。
#
# 来源：`Android端SDK 接口说明文档 V4.1.1` 第 1.3 节“混淆配置”。Flutter 的
# release 构建默认 isMinifyEnabled = true（见 flutter_tools 的
# FlutterPlugin.kt），因此这些规则是发布包能否正常打印的前提：SDK 内部大量
# 使用反射与 native 回调，被混淆后 initSdk/绘图/回调都会失败。
#
# 只保留 SDK 自己的包，不关闭本项目或 Flutter 的混淆。

-keep public class com.gengcon.www.jcprintersdk.**{*;}
-keep public class com.niimbot.canvas.image.**{*; }
-keep public class com.dothantech.**{*;}
-keep public class zpSDK.zpSDK.**{*;}
-keep public class com.snbc.sdk.**{*;}
-keep public class android_serialport_api.**{*;}

-dontwarn com.gengcon.www.jcprintersdk.**
-dontwarn com.jingchen.jcimagesdk.**
-dontwarn com.niimbot.canvas.image.**
-dontwarn com.dothantech.**
-dontwarn zpSDK.zpSDK.**
-dontwarn com.snbc.sdk.**
-dontwarn android_serialport_api.**

# 共享Flutter源码

这里是Windows/Android/Linux唯一可编辑客户端源。入口lib/main.dart；统一器件库和扫码业务lib/features/unified；业务HTTP lib/services/lab_api_client.dart；登录/安全存储lib/services；路由lib/routes。

不要把这里的build、.dart_tool、android/local.properties或flutter/ephemeral提交到Git。提交pubspec.yaml、pubspec.lock、平台runner和实际需要的.g.dart模型。具体环境和隔离构建入口见[开发说明](../../docs/development/CLIENT.md)。

原始README状态过时，已转存local/archive/docs-original，不作为当前业务事实。

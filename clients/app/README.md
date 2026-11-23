# 共享Flutter源码

这里是 Windows、Android、Linux 唯一可编辑的客户端源码。版本以 `pubspec.yaml` 为准。`1.4.0+26` 已在三端应用内 stable 发布，现行包和验证见[正式发布记录](../../maintenance/handoffs/2026-11-23-client-stable-release.md)。

仓位速览在 `lib/features/warehouse/`，使用服务端父级关系展示多级库位。作业表单仍通过原内部库位接口选库位。管理员可创建库位或更改上级，改名与停用目前由网页端提供。

入口lib/main.dart；统一器件库和扫码业务lib/features/unified；业务HTTP lib/services/lab_api_client.dart；登录/安全存储lib/services；路由lib/routes。

不要把这里的build、.dart_tool、android/local.properties或flutter/ephemeral提交到Git。提交pubspec.yaml、pubspec.lock、平台runner和实际需要的.g.dart模型。具体环境和隔离构建入口见[开发说明](../../docs/development/CLIENT.md)。

原始README状态过时，已转存local/archive/docs-original，不作为当前业务事实。

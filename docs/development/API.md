# API维护入口

[源码路由表](../../maintenance/registry/routes.json)由 `tools/generate_routes.py` 解析纳入维护的控制器生成。表中包含 URL、处理器和路由选项，动态拼接路径在登记里写作 `dynamic-route`，实际路径查对应控制器。生产是否部署某条路由以[运维状态](../operations/CURRENT_STATE.md)为准。

两阶段入库新增 pending 接口与标签类型的请求、权限、幂等和返回语义见[实现契约](TWO_STAGE_RECEIPT_IMPLEMENTATION.md)。

```sh
python tools/generate_routes.py
python tools/generate_routes.py --check
```

变更API时同时检查server方法的真实输入、返回JSON信封、权限和幂等语义，更新客户端lab_api_client.dart与EDA调用方。路由表不是完整业务schema，不会自动证明权限或库存事务正确。

旧business_api_contract.json/catalog_api_contract.json原稿保存在local/archive/docs-original，可能早于最近修复，不能用它们覆盖当前实现。确认其内容后才可作为新的契约基线。

客户端更新器新增两个普通GET接口，独立于上述库存JSON-RPC：`/lab/client/updates/manifest`为匿名最小签名清单，`/lab/client/updates/assets/{release_id}/{filename}`要求合法登录及lab角色。状态码、签名载荷、平台匹配及发布布局见[实现契约](CLIENT_UPDATE_IMPLEMENTATION.md)。三端正式 stable 的版本和候选状态见[更新通道交接](../../maintenance/handoffs/2026-11-23-client-stable-release.md)。

`/lab/api/inventory/locations` 返回 `locations`；`with_tree: true` 增加 `ancestors`，`with_stats: true` 返回本库位统计。创建库位可传 `parent_id`。移动走 `/lab/api/inventory/location_update`，发送 `update_parent: true`、`parent_id` 和 `request_key`；顶层用 `parent_id: false`。同一次移动重试复用请求号，创建端点未采用同样的重放契约。写入必须通过服务端库存管理员权限校验。EDA 扩展使用 `lab_eda` 的独立密钥接口，Web 和 Flutter 继续使用 Odoo 会话。

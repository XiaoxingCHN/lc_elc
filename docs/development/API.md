# API维护入口

当前已注册路由由tools/generate_routes.py直接解析三个Odoo模块的controller装饰器生成，见maintenance/registry/routes.json（25条注册项）。这份表记录URL、handler、源位置和显式type/auth/methods/csrf选项，不执行Odoo、不连接生产。

```sh
python tools/generate_routes.py
python tools/generate_routes.py --check
```

变更API时同时检查server方法的真实输入、返回JSON信封、权限和幂等语义，更新客户端lab_api_client.dart与EDA调用方。路由表不是完整业务schema，不会自动证明权限或库存事务正确。

旧business_api_contract.json/catalog_api_contract.json原稿保存在local/archive/docs-original，可能早于最近修复，不能用它们覆盖当前实现。确认其内容后才可作为新的契约基线。

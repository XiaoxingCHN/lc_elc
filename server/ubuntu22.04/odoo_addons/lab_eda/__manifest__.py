{
    "name": "实验室库存 EDA 插件接口",
    "version": "19.0.1.0.0",
    "summary": "嘉立创 EDA 专业版插件专用接口：API Token 认证，不依赖 Cookie 会话",
    "description": """
EDA 插件专用接口
=================

嘉立创 EDA 专业版扩展的 ``sys_ClientUrl.request()`` **无法携带 Cookie**
（``options`` 只暴露 ``headers``/``integrity``，而 ``Cookie`` 是 Fetch 规范的
禁止请求头）。所以插件不能复用网页端的会话认证。

本模块提供：

* ``lab.eda.token``：绑定到具体用户的 API Token，只存哈希，发放权锁在库存管理员；
* ``/lab/api/eda/*``：只认 ``Authorization: bearer <token>`` 的专用端点，
  内部转发到既有业务方法——**业务逻辑只有一套**，不在这里重写。

**不改动**现有 ``/lab/api/*`` 路由的认证方式，网页端零影响。

安全边界：Token 明文存在插件配置里（EDA 端无 DPAPI），与浏览器保存密码同一水位；
可随时吊销，``last_used_at`` 可用于发现异常使用。
""",
    "author": "lc_elc",
    "license": "LGPL-3",
    "category": "Inventory/Inventory",
    "depends": ["base", "web", "lab_workflow", "lab_catalog"],
    "data": [
        "security/lab_eda_security.xml",
        "security/ir.model.access.csv",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}

# 当前发布入口

| 组件 | 版本 | 本机成品目录 | 源码 |
|---|---|---|---|
| Windows客户端 | 1.0.1+2 | ../clients/windows/releases/1.0.1/ | ../clients/app/ |
| Android客户端 | 1.1.2+5 stable | ../clients/android/releases/1.1.2+5/ | ../clients/app/ |
| Linux客户端 | 1.0.1+2 | ../clients/linux/releases/1.0.1/ | ../clients/app/ |
| 嘉立创EDA专业版 | 3.0.3 | ../plugins/jlc-eda/releases/3.0.3/ | ../plugins/jlc-eda/ |
| Odoo模块当前修复包 | 2026-10-18 | ../server/releases/2026-10-18/ | ../server/ubuntu22.04/odoo_addons/ |

实际文件名、大小、SHA256、来源和已知验收限制见maintenance/registry/releases.json。旧版全部在local/archive/packages和local/archive/eda，不能用于覆盖当前服务器或客户端。

发布物由Git排除，请按dependencies/README和离线载荷流程获取。不要只取Windows exe或Linux ELF，应保留完整同目录资源。

Android stable发布与手机安装状态分开记录：build5已完成签名/HTTP下载核验，手机反馈安装入口仍失败，1.1.3+6修复见最新交接。

# 域名迁移：现有方案调研与选型

日期：2026-10-25。用户新增要求：涉及大量编码前先查 GitHub 可行方案，避免重复实现。此要求已加入开发流程，并用于本批迁移；当前仅调研/候选，无生产写入。

## 已查阅的上游

| 项目 | 维护与许可证证据 | 与本批的关系 |
|---|---|---|
| [certbot/certbot](https://github.com/certbot/certbot) | GitHub元数据未归档，最近推送2026-10-23；LICENSE.txt为Apache-2.0，Nginx插件含MIT部分 | 服务器已有1.21.0；匹配v1.21.0文档确认内置manual插件支持DNS-01，服务器也已成功import，无需另写签发或DNS API代码 |
| [go-acme/lego](https://github.com/go-acme/lego) | 未归档，最近推送2026-10-23；MIT | 已有内置alidns provider；独立二进制可作为后续自动续期候选，需单独审核版本/载荷及受限凭据，不在本批自动安装 |
| [acmesh-official/acme.sh](https://github.com/acmesh-official/acme.sh) | 未归档，最近推送2026-10-23；GPL-3.0 | 已有dns_ali实现，可作为备选；涉及账号配置与DNS凭据，不执行仓库安装命令、不复制其签名代码自行维护 |

上述维护时间来自本轮GitHub API读取，表示近期有维护活动，不等同完整安全审计。未依据star数直接选型，未下载或运行第三方安装脚本。

## 本批决定

1. 优先复用服务器现有Certbot manual DNS-01。内网Web服务无需对公网开放；域名控制权由公网TXT验证。签发成功后使用Nginx标准TLS配置和Odoo既有管理Host功能。
2. 内置manual不需要阿里云DNS插件，也不需要在聊天提供DNS API密钥；实际TXT值待订单生成后由用户添加，不使用示例值冒充真实挑战。
3. manual模式缺少自动认证hook时不能自动续期；本批不会把它写成已完成自动续期。后续若要自动化，优先评估现成alidns provider及最小范围凭据，而不是自行实现阿里云API签名或ACME协议。
4. 只保留最小配置部署、备份/回滚和参数适配。Nginx代理头继承按官方规则处理；参数使用Odoo ORM及显式跨进程信号，避免另写认证、选库或路由系统。
5. 当前阻塞属于服务器系统DNS失效及首次生产ACME账号注册，已向用户提出具体DNS修复和协议确认；未通过大量编码规避授权边界。

## 关键原始来源

- [匹配已安装版本的Certbot manual及续期说明](https://github.com/certbot/certbot/blob/v1.21.0/certbot/docs/using.rst)：支持异机/手动DNS验证；无认证hook不能自动续期。
- [Certbot许可证](https://github.com/certbot/certbot/blob/main/LICENSE.txt)。
- [lego阿里云provider配置](https://github.com/go-acme/lego/blob/main/providers/dns/alidns/alidns.toml)：原生支持RAM角色或现成凭据方式；未读取实际凭据。
- [acme.sh阿里云provider源码](https://github.com/acmesh-official/acme.sh/blob/master/dnsapi/dns_ali.sh)：已有添加/删除挑战记录实现；未复制代码。
- [Nginx proxy_set_header规则](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_set_header)：子location定义任一该指令时，父级同类指令不会自动继承。

本轮研究使用已连接GitHub只读工具与官方文档，未修改远端仓库。项目生产源175文件未因本次调研变化。

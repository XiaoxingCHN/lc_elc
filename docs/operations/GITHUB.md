# GitHub 仓库、Releases 与离线文件恢复

## 当前发布状态

2026-11-23 通过 GitHub API 核对，仓库为公开可见。[客户端 Release](https://github.com/XiaoxingCHN/lc_elc/releases/tag/client-v1.4.0%2B26) 已提供 Linux x64 安装包和 SHA-256 校验文件，标签指向实际构建提交 `d98c73a`。现有 Windows、Android 含第三方打印运行时，继续通过登录后的 stable 通道分发。EDA `4.2.0` 使用独立扩展包。 [公开发行交接](../../maintenance/handoffs/2026-11-23-client-github-release.md)安装包目录由 Git 忽略，只有明确创建 GitHub Release 并上传附件后才会显示在该入口。Odoo 的应用内更新从正式域名读取另一套已签名清单，状态见[更新通道交接](../../maintenance/handoffs/2026-11-23-client-stable-release.md)。

手动分发可将三端安装包放在客户端 Release，将 `.eext` 和发行 ZIP 放在 EDA Release。分别记录版本、精确来源和 SHA-256，公开上传前核对包内的第三方运行时及现有分发授权。Android 的 APK 签名与服务器清单签名用途不同。

## 历史设置

初始归档只建立本地Git维护仓库。后续用户已配置既有origin并授权上传；2026-10-19两阶段入库与服务端部署交接已提交到 `codex/two-stage-receipt-plan` 分支，主功能提交0716829。源码在Git，安装包/私有数据仍按载荷登记保留在Git之外；不改变仓库可见性、不强推main、不把凭据写入脚本。目录名不是GitHub仓库地址。

## 2026-10-28 P3 更新

用户已明确授权推送，目标为既有 `origin` 的 `feat/p3-web-workflows-20261028`，不改 main、不强推。提交包括完整冻结服务器源码、所需运维与验收记录；源清单为 `maintenance/registry/source-server-p3-web-20261028.json`（250 文件）。本地 repo_check 52 项通过；API 与浏览器未执行场景继续按正式交接记录，不代表云端 CI 或生产验收通过。源码候选 ZIP 与本机载荷仍在 Git 之外，生产仍 P2。

## 历史流程：新建维护仓库和第一次推送

1. 在GitHub账号下新建Private仓库，不预建README以免与本地冲突。复制其SSH或HTTPS地址。账号认证使用Git Credential Manager/SSH agent，不能把token写进URL或脚本。
2. 检查 `git status`、`git diff --cached --stat`，运行repo_check；确认local、数据库、签名、SDK和发布大文件没有被暂存。
3. 如本机未配置Git作者，由本人设置当前仓库的name/email，不借用AI身份。已有归档基线commit时直接添加远端；若无commit先 `git add .`、`git commit -m "chore: import maintainable archive baseline"`。
4. `git remote add origin <自己的私有仓库URL>`；`git push -u origin main`。若有基线tag，检查后显式 `git push origin <tag>`。

## 在另一台机器恢复

```sh
git clone <现有origin的URL> lc_elc
cd lc_elc
python tools/repo_check.py
python tools/fetch_payload.py --list
```

Git只含源码、规范、锁与登记，未提交离线载荷属正常。按dependencies/README下载锁定上游包，或者从可信备份拿到由tools/offline_bundle.py导出的载荷包，用同工具导入并核对。下载文件会对登记hash；哈希不符不得当同版本继续。

当前机器上的完整载荷路径已在maintenance/registry/payloads.json列出。要离开当前机器，必须先把载荷导出到另一块盘/受控存储；只复制Git文件不能恢复SQLite历史数据或既有安装包。

签名私钥另行受控备份，不能包含在Git、普通离线载荷或聊天附件。缺少匹配密钥不能为已安装应用延续覆盖升级。

## 对外发布前

私有仓库也要检查第三方许可证、内部域名/IP和证据中的账号标识。公开 Release 可被任何人下载。上传前核对签名公证书、许可证、包内配置以及发行说明，凭据和内部证据留在受控路径。仓库可见性由仓库拥有者管理。

## 自动检查

.github/workflows/repository.yml准备了GitHub上的源码/维护工具检查，不连接生产，不需要私有载荷或账号。各版本以对应的 GitHub Actions 记录为准。当前文档整理未触发新的云端检查。所用action入口已查官方[checkout](https://github.com/actions/checkout)与[setup-python](https://github.com/actions/setup-python)，仅contents:read并不保留checkout认证。未来升级action须复核上游要求。

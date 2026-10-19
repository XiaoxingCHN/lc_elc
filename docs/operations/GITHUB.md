# GitHub私有仓库与离线文件恢复

本次只建立本地Git维护仓库，不创建远端、不推送、不把凭据交给脚本。目录名不是GitHub仓库地址。

## 第一次推送

1. 在GitHub账号下新建Private仓库，不预建README以免与本地冲突。复制其SSH或HTTPS地址。账号认证使用Git Credential Manager/SSH agent，不能把token写进URL或脚本。
2. 检查 `git status`、`git diff --cached --stat`，运行repo_check；确认local、数据库、签名、SDK和发布大文件没有被暂存。
3. 如本机未配置Git作者，由本人设置当前仓库的name/email，不借用AI身份。已有归档基线commit时直接添加远端；若无commit先 `git add .`、`git commit -m "chore: import maintainable archive baseline"`。
4. `git remote add origin <自己的私有仓库URL>`；`git push -u origin main`。若有基线tag，检查后显式 `git push origin <tag>`。

## 在另一台机器恢复

```sh
git clone <私有仓库URL> lc_elc
cd lc_elc
python tools/repo_check.py
python tools/fetch_payload.py --list
```

Git只含源码、规范、锁与登记，未提交离线载荷属正常。按dependencies/README下载锁定上游包，或者从可信备份拿到由tools/offline_bundle.py导出的载荷包，用同工具导入并核对。下载文件会对登记hash；哈希不符不得当同版本继续。

当前机器上的完整载荷路径已在maintenance/registry/payloads.json列出。要离开当前机器，必须先把载荷导出到另一块盘/受控存储；只复制Git文件不能恢复SQLite历史数据或既有安装包。

签名私钥另行受控备份，不能包含在Git、普通离线载荷或聊天附件。缺少匹配密钥不能为已安装应用延续覆盖升级。

## 对外发布前

私有仓库也要检查第三方许可证、内部域名/IP和证据中的账号标识。当前仓库保留业务部署定位，但不含真实密码；如改为公开发布，需单独做发布审核，不能直接切换可见性。

## 自动检查

.github/workflows/repository.yml准备了GitHub上的源码/维护工具检查，不连接生产，不需要私有载荷或账号。尚未推送，不能称云端CI已通过。所用action入口已查官方[checkout](https://github.com/actions/checkout)与[setup-python](https://github.com/actions/setup-python)，仅contents:read并不保留checkout认证。未来升级action须复核上游要求。

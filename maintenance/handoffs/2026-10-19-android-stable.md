# 维护交接：Android 1.1.2+5 已发布到更新通道

## 用户目标与已确认边界

用户明确要求“你发布下”，授权将已经构建核验的Android修复包发布到现有stable更新通道。只发布Android；Windows/Linux仍为候选，未切换其通道。未安装手机应用、未重启服务、未修改库存和账号权限。

## 当前权威源码、分支和版本

client1.1.2+5，source-client-picker-fix-20261019.json，163文件，树hash f61a4733881ac4b8572b570ad3cf28781c750df7e85d32b20e440ca7fce29e2e。发布源码提交66ced7bd82d48616a34c1335f26464d6f928e1e7，分支codex/two-stage-receipt-plan；只创建本地提交，未推送GitHub。包构建先于该提交，完整冻结源与提交索引、各构建副本逐项一致，未重编或替换APK字节。服务端lab_workflow19.0.1.2.0沿用已上线版本。

## 已完成工作与实际证据

发行android-1.1.2-build5-20261019，android/universal/stable，build5、release_sequence1；Ed25519 key-id release-20261019，私钥仅本机签名，未上传。先上传包/清单、远端复验大小和SHA256、写入不可变发行目录，最后原子切换stable.json；服务持续active且未重启。

- APK 74,777,513字节，SHA256 d5e2a557f4e639dd122446dd0b3f286378947ec237e486c1a2c80e631602f152；既有Android证书8b4c2409604fcd6fdd65dc5344afca7bffb81f07df2c77c210bcef1a78a9ff43，minSdk24。
- 本轮实际使用1.1.1+4构建副本中的验签/版本判断代码验收本地及生产HTTP清单，exit0：签名有效、build4接受build5，build5不会重复升级自己。
- LAN Android清单200并验签、逐字段等同本地发行；Windows/Linux204；匿名完整包303跳登录。
- 实际受保护HTTP完整下载200、字节数与SHA256一致；真实无角色账号会话403。为验证临时创建2个文件会话，验证后移除；不输出cookie/token，数据库事务READ ONLY并回滚。
- 原有272 Flutter通过5跳过、三端构建/源码核验及公开签名证据沿用receipt-picker-fix-20261019.json，不冒称本轮重跑全量测试。

机器证据见maintenance/audit/android-stable-20261019.json及maintenance/registry/artifact-client-android-1.1.2-build5.json；本机发行文件在clients/android/releases/1.1.2+5，整个releases目录保持Git排除。

## 剩余工作与阻塞

发布完成，旧1.1.1+4可打开“关于与更新”检查并下载，Android安装仍须系统确认。计费/未知网络需要手动点下载；非计费网络后台下载。实体手机安装确认/升级后界面及数据保留仍需用户实测，本次发布授权未被当作实体验收通过。Windows/Linux原生完整升级、物理打印与断电仍未验证。

## 依赖和产物

无新增依赖，沿用client-update-dependencies-20261019.json。包名仍保留原构建文件的candidate后缀，避免改写旧产物；该后缀不影响已签名的stable通道/版本判断。包、不可变manifest.json、公钥标识、来源清单及证书见本轮审计；旧包不覆盖。

## 生产状态和回滚

分发根/opt/odoo/.local/share/Odoo/lab-client-updates；新发行releases/android-1.1.2-build5-20261019，指针android/universal/stable.json。此前Android通道为空，无旧指针可恢复；若撤回，仅将本次stable.json原子改名为同目录withdrawn-android-1.1.2-build5-20261019.json，先核对路径无符号链接及文件hash/发行身份。保留不可变包和清单，不回滚数据库、不递归删除目录。指针撤回不阻止已完整缓存包的用户确认安装。完整服务端备份继续按update-endpoint-deploy交接保管，本轮分发文件发布不触及该备份。

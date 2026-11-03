# P3 工作中交接（不是发布通过）

用户要求继续补功能，主代理省token，Qoder/WorkBuddy DeepSeek多代理不限量。当前分支feat/p3-web-workflows-20261028，既有dirty改动保留。生产仍是P2，未上传/升级本轮P3，正式域名手机无VPN验收仍待用户。

现有GUI3733的/codex-bridge已认证可用，workspace 8b11f62f-8a95-477c-afcf-39aea93c46a2。helper为已安装deepseek-harness技能bridge.py（凭据内部读取，不打印）；调用需仅进程内DSH_CODEX_BRIDGE_URL=http://127.0.0.1:3733/codex-bridge。完整调度材料在local/build/p3-web-20261028：bridge-state.json保存task/session/model/cursor，bridge-control.py读status/transcript/wait；每个key-created/status/request文件可恢复。当前全部新回合统一magpie/qoder-cn/dfmodel high：WorkBuddy实际429，提示2026-10-28 13:46:43 UTC+8恢复，未原地忙重试。早期native spawn实际GPT已中断，不能称其Qoder成果。

已交付源码：backend（workflow窄API/映射/成员/PDF/安全修复）、ui（13页外壳+LC core）、receipt（入库扫码袋标签）、issue（领用归还历史）、inventory（库位映射成员物料）、account（只读身份与退出）、gateway（精确allowlist）。各自互斥写域在对应请求与frontend-contract.md；共享core/模板只能ui作者改。security只审查，validation只写指定测试/本机runner，release目前只预检。model observed已确认，两家均有实际执行消息。

中央已有：fast-r1-results.json 108项纯测试通过+5 JS语法；p3-unit-r1-results.json新增backend逻辑25、Web静态25通过，core10/12失败和5份XML格式失败已发原作者修。不要把这些当P3全绿。

真实ORM R1：run-backend-orm.sh（私有namespace内runtime自身RO bind，不改旧脚本/旧运行时）执行exit1，输出backend-orm-r1-output.log为PS UTF16，utf8副本已另存；完整合成测试日志已拷backend-orm-r1/。55旧测试2个error都是继承HTTP_PROXY=127:7897在私有netns不可达，局部清空大小写proxy变量+NO_PROXY后再跑；旧inner test-tags硬编码**未跑新LabP3BackendTest 21项**，validation正修本地副本选择器保留旧断言并加入P3，禁止拿旧55当新P3通过。

最新待修/验收：security-round2.md指出unknown后换payload可绕锁、标签ids*copies无总量（Lead定总量200）、多公司global-role/最后manager；已派ui/backend修并加测试。receipt误称无pending/update，实际controllers/lab_inventory_api.py:38、models/lab_pending_receipt.py:202、common.py pendingUpdate均存在，已要求复用保持已印追溯码，不能新建+取消当编辑。issue/receipt需unknown锁稳定表单scope、跨刷新恢复，不能仅提示。gateway已要求旧/lab/scan固定相对303到/team/scan（不转发旧控制台）、新增catalog两POST；最终需实码对齐复核。

WSL Ubuntu-22.04 uid1000，runtime /var/tmp/lc-elc-clean-apt-20261014-082927-594/rootfs真实存在；runtime为Python3.10（日志确认），不能声称等同生产Python3.12.15。PG14与P2 Chrome资产可用。outer单UID map设计正常，PG二层userns映射101。local run-all.sh仍需审查修正（原版复用teamweb_test与W旧PG），要求默认新专用P3库/数据、仅停止自己启动的服务。所有业务测试禁止NAS/真实库存/真实凭据，子代理pwsh因grantWrite失败，主会话统一执行，不改ACL/宿主sandbox。

下一步：收原作者修复→跑core/全部XML/真实新ORM非零数→HTTP+真实DOM入库/领用/部分归还→真实Nginx/Origin/旧QR兼容→复审全候选→统一版本/route registry/冻结与不可变包→完整交接。版本/registry尚未更新。旧备份filestore一致性问题仍未关闭，不能贸然生产部署。没有相关后台命令job仍在跑（R1已collect）；桥接任务持续运行，用现有taskId续接，别创建重复对话。

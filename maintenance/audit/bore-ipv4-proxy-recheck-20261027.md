# bore IPv4 与 VPN 复核（2026-10-27）

## 结论

撤销此前“境外 IP 全封、HTTP 代理不支持裸 TCP、bore.pub 必须放弃”的判断。本轮 NAS 以真实 IPv4 159.223.110.159 建立 bore 0.5.3 隧道；Windows 经已有 HTTP 代理 127.0.0.1:7897，使用域名和真实 IPv4 均成功获得 HTTP 200 和精确诊断内容。没有修改 VPN、路由、DNS 或生产 Nginx/Odoo。

## 方法与证据

- 服务：NAS 用户目录独立 Python HTTP 服务，仅监听 127.0.0.1:38249，只返回固定诊断字符串；不访问生产 DB、文件、账号或 Odoo。
- 隧道：bore local 38249 --local-host 127.0.0.1 --to 159.223.110.159 --port 0，分配 47037；控制与转发目的地址均使用 IPv4。未探测代理供应商自身内部传输的 IP 版本。
- 诊断脚本与结果保存在忽略目录 local/build/bore-network-recheck-20261027/；payload-results-recovered.json 为六条原始测量的恢复记录（恢复来源为当时记录的测试输出，不是原JSON字节）。固定输出名的runner在后续协议探针中覆盖了原payload-results.json；后续探针另保存在local/build/bore-public-gateway-20261027/plain-protocol-results.json。原文件SHA256为c55a2d4428477213ec87f2987e8512ffe05f4778ec5cfa54ddce7256ac04c0e8，不能对恢复文件沿用该哈希。脚本 runner exit 0 只代表运行完成，业务结果按下表分别列出。
- Windows Node v24.13.0；远端 Python3；本机使用当前已启用的 7897 代理，无认证信息读取。

| 目的地址 | 访问方式 | 实际结果 |
|---|---|---|
| 159.223.110.159:47037 | 本机 IPv4 直连 | 10秒超时，未收到字节 |
| bore.pub:47037 | 本机 IPv4 直连 | 10秒超时，未收到字节 |
| 159.223.110.159:47037 | HTTP CONNECT | 200 + 精确内容，2128ms |
| bore.pub:47037 | HTTP CONNECT | 200 + 精确内容，2247ms |
| 159.223.110.159:47037 | HTTP 正向代理 | 200 + 精确内容，2273ms |
| bore.pub:47037 | HTTP 正向代理 | 200 + 精确内容，2292ms |

独立 curl 复核（exit 0）：

~~~powershell
curl.exe -4 --proxy http://127.0.0.1:7897 --connect-timeout 5 --max-time 15 --fail --silent --show-error http://159.223.110.159:47037/health
~~~

返回固定字符串 lc-bore-ipv4-diag-20261027-codex。本地址是一次性合成测试端口，测试后已关闭，不能用作生产链接。此 HTTP 测试不承载任何凭据。

## 先前判断的具体错误

1. TCP 超时只描述当时的源、目标、端口和路径，不足以推出整个网络或所有访问者都被封锁。
2. HTTP CONNECT 可以承载 TCP。控制端口 7835 不提供 HTTPS，对该端口发送 TLS 后失败，不证明 CONNECT 被拒绝。本轮 CONNECT200 后继续成功传输了实际响应，不只检查协商状态。
3. 本轮 Node resolve4 读取 bore.pub 为 198.18.0.4；NAS 为 198.18.0.34。这是 fake-IP 行为的迹象，但不能据此断言代理损坏、必然失败或所有请求被劫持。域名经代理实测同样成功。
4. 未出现 TUN 网卡也不足以推断完整路径上的防火墙/路由原因。现有证据不能确定直连超时的唯一根因。
5. 原来 /login 在未知 Host 下404而数据库页200，不能简单归因于“落到80端口的lc.rm.com server”；Nginx先按监听地址选择server，再按SNI/Host处理，Odoo本身也根据Host决定根路径。

## 清理与生产状态

按 supervisor PID230806 的完整脚本路径校验归属，再发送 SIGTERM；它终止 bore 子 PID230808。独立 ps -C bore 未见进程，未用 pkill 模糊匹配。日志与脚本保留在 NAS 用户诊断目录，没有删除证据。生产 TLS 登录复查 HTTP200、ssl_verify_result0。

## 不能混同的完成项

公网隧道经 VPN/代理可达已验证；生产 Odoo 公网安全入口尚未发布。生产原443此前存在通配代理，不能当成已部署的P1白名单入口。正式入口仍需独立默认拒绝网关、会话/业务验证、受信任的域名与证书、端口管理与服务监督。公共bore的高位端口不能靠DNS变成443；直接IP网址也不会自动匹配现有域名证书。这些是应用入口配置事项，不能再误报成bore网络不可行。

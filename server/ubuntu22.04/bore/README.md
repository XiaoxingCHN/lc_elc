# bore 公网入口（P1 本地隔离链路 / P2 隔离真实 Odoo 验收）

## Netlify HTTPS回源（2026-10-27）

`scripts/render-netlify-gateway.py`复用原白名单并区分专用回源Host、固定Odoo管理Host和精确前台Origin白名单；使用独立map/限速zone，不信任Netlify或客户端自带转发头。所有响应显式private/no-store，清除上游缓存验证器；固定诊断路径/__lc_origin_probe不访问业务数据。独立回源证书的链和域名须实测通过，不能使用-k交付。

`scripts/build-netlify-site.py`从`netlify/`模板生成可手工拖拽上传的ZIP。构建必须指定已冻结server source manifest，脚本和模板哈希不一致即拒绝；输出不可覆盖并记录来源/哈希。200强制rewrite覆盖静态占位页，正式站点内容与Cookie由白名单网关提供。Netlify有26秒代理时限，实际POST/会话/缓存和大文件下载需逐项验收。

## 公共 IPv4 中继部署工具（2026-10-27）

`scripts/render-public-gateway.py` 从既有Nginx TLS配置引用和已测allowlist生成独立回环网关；不读取证书/私钥文件内容，不改写内网vhost。Nginx1.18使用proxy_cookie_path兼容Secure/SameSite，较新版本使用proxy_cookie_flags。正式使用前必须执行Nginx语法检查和实际Cookie/头部/拒绝路径验证。

`systemd/lc-bore-public.service.template` 固定IPv4中继与端口，按普通服务用户运行、自动重连、限制地址族。公共bore不传递访客IP，网关覆盖转发头并对认证POST执行共享限速（6次/分钟，burst5）；不能冒充按真实客户端IP限速。随机端口也可用，但重连后需要更新配置和访问地址。

访问网址的主机名须匹配现有证书；DNS A记录只改IPv4，不映射端口。公共中继提供的高位端口必须写在HTTPS网址中。标准443需要可控制的公网中继。不要以HTTP传递登录凭据，也不要靠跳过证书校验交付正式入口。当前部署结果以最新审计交接为准，下方为历史隔离验收记录。

状态分两层，勿混用：

- **P1（本地隔离入口链路）**：真实 Nginx + bore 0.5.3 + 合成上游，主链路 94/0、失败路径 10/0、运行时完整性 10/0、契约 9/0；端口参数化渲染回归 **116/0**。合成上游**不是 Odoo**。
- **P2（真实Odoo隔离验收）**：P2 127/0/0/0，exit 0；浏览器28/0，P1 116/0，hook7/0；lab_team_web19.0.1.0.5、lab_catalog19.0.2.0.5候选未部署。
- **仍未验证**：真实公网节点、标准 443 公网入口、生产部署与生产升级、真机。均不构成公网开放授权。

本轮已收口。新快照：[source-server-p2-evidence-hardened-20261027.json](../../../maintenance/registry/source-server-p2-evidence-hardened-20261027.json)；详见[审计](../../../maintenance/audit/bore-p2-evidence-hardening-20261027.md)与[交接](../../../maintenance/handoffs/2026-10-27-p2-evidence-hardening.md)。

## 组件

| 文件 | 作用 |
|---|---|
| «nginx/bore-public-allowlist.conf.template» | 入口 Nginx：默认拒绝、精确路径+方法白名单、认证端点清 DB 头、限速钩子 |
| «nginx/bore-proxy-headers.conf» | 代理头：**覆盖** X-Forwarded-For/X-Real-IP，清空 Forwarded，固定 DB 头占位 |
| «nginx/bore-edge-stream.conf.template» | 受控边缘 stream 片段（可选；真实边缘建议独立 Nginx 实例） |
| «scripts/verify-local-entry.sh» | 本地一键验证：真实 Nginx + bore + 合成上游 |
| «scripts/run-p2-isolated.sh» | P2 隔离整轮 runner：真实 Odoo/Nginx/bore/Chrome，产出同轮 JSONL+summary+exit |
| «tests/browser_flow.py» | 严格浏览器真实 UI 流程（登录/检索/详情/刷新/退出，CDP 直连，不代测试 fetch） |
| «tests/test_config_contract.py» | 模板契约测试（无需运行时，含 authority/端口渲染断言） |
| «tests/synthetic_upstream.py» | 合成上游（**不是 Odoo**，只验证代理/路由边界） |

## 链路（本轮实测）

```
访客(127.0.0.3/6) --TLS--> 公开边缘 Nginx stream (127.0.0.1:9500, 不接收客户端 PROXY)
      --PROXY v1--> bore server (127.0.0.1:7835) --> bore client --> 入口 Nginx (127.0.0.1:8443, TLS + proxy_protocol)
      --HTTP--> 合成上游 (127.0.0.1:9000)
```

- 入口仅监听回环，且「set_real_ip_from 127.0.0.1」+「real_ip_header proxy_protocol」只信任 bore client 对端。
- 上游必须看到 **真实访客 IP**（实测 127.0.0.3 / 127.0.0.6 各自独立），伪造 XFF/Forwarded 被覆盖为空/真实值。

## 上游研究与许可

- **bore 0.5.3（MIT，https://github.com/ekzhang/bore）**：官方源码无 PROXY protocol 实现（main 分支 29 文件、README 无该选项）。
  → 单靠 bore 无法保留访客 IP（实测隧道后上游看到 127.0.0.1）；必须在**受控边缘**由成熟组件生成 PROXY。
- 本轮边缘使用 **Nginx stream proxy_protocol** 生成，bore 只做透明 TCP 转发，组合实测可用。
- 备选（未采用/未验证）：frp 的 proxy_protocol 能力、Cloudflare Tunnel + CF-Connecting-IP；均需另行评估许可、账号与真实网络。

## 运行时来源与复现

```bash
# 1) 下载/校验本地运行时（不安装系统包；输出 local/build/.../runtime）
bash server/ubuntu22.04/bore/scripts/fetch-runtime.sh
# 2) 校验（ok=8 bad=0）
bash server/ubuntu22.04/bore/scripts/fetch-runtime.sh --verify-only
# 3) 当前契约测试（21项）
python3 -m unittest discover -s server/ubuntu22.04/bore/tests -p "test_config_contract.py"
# 4) 运行时完整性（篡改归档拒绝/不解包、非法 deb 不通配解包，10 断言）
bash server/ubuntu22.04/bore/tests/test_fetch_integrity.sh
# 5) 真实链路（94 断言）+ 失败路径（10 断言）
NGINX_BIN="$(pwd)/local/build/bore-p1-20261026/runtime/root/usr/sbin/nginx" \
MODULE_SO="$(pwd)/local/build/bore-p1-20261026/runtime/root/usr/lib/nginx/modules/ngx_stream_module.so" \
BORE_BIN="$(pwd)/local/build/bore-p1-20261026/runtime/bore" \
  bash server/ubuntu22.04/bore/scripts/verify-local-entry.sh
NGINX_BIN="$(pwd)/local/build/bore-p1-20261026/runtime/root/usr/sbin/nginx" \
MODULE_SO="$(pwd)/local/build/bore-p1-20261026/runtime/root/usr/lib/nginx/modules/ngx_stream_module.so" \
BORE_BIN="$(pwd)/local/build/bore-p1-20261026/runtime/bore" \
  bash server/ubuntu22.04/bore/tests/test_failure_paths.sh
```

历史P1主链94/0、失败路径10/0、完整性10/0、契约9/0；本轮主链116/0、当前契约21/0。来源/许可见运行时PROVENANCE。
脚本对 NGINX_BIN/MODULE_SO/BORE_BIN 自动转绝对路径（Nginx `-p` 后相对 module 路径会错）。

## 严格 CSP 与 authority 变量（P2 修复）

- **根因**：入口曾用 `$host` 生成上游 Host/X-Forwarded-Host，**丢失外部非标准端口（如 9500）**；Werkzeug/Odoo 据此把 303 Location 绝对化成默认端口 URL，浏览器解析为**另一个 origin**，与严格 CSP 冲突。
- **修复**：authority 改用 `$http_host` 并做**精确白名单**（不接受任意 Host/X-Forwarded-Host 透传）；外部端口由模板参数 **@PUBLIC_PORT@** 显式渲染，不再从请求推断。
- **端口防呆**：生产 443 渲染时拒绝 9500（契约测试断言），避免把本地调试端口带进生产。
- **CSP**：严格策略（默认 self、`form-action 'self'`、不追加额外 connect 来源）；退出改为**原生 POST 表单 + CSRF**（/team 基址），因此不需要放宽 CSP 去兼容测试侧 fetch。
- 参考：Nginx [proxy_set_header](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_set_header)｜MDN [CSP form-action](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/form-action)。

## 真实 UI 与同轮证据（P2）

浏览器流程经 CDP 操作**真实页面**：登录页输入并点击提交 → /lab → 搜索框输入并触发检索 → 点击结果卡片进入详情 → 刷新 → 点击真实退出按钮。断言依据网络事件与 DOM，而不是由测试自行 fetch 代替 UI。

- 保留严格判定：完整 JSON 等值、布尔严格、不允许重复/控制台/安全错误、不允许静默清洗通过。
- 同轮一致：`results.jsonl` + `summary.json`（含 status/blocked/skip/pass/fail 与 results 哈希）+ 进程退出码必须指向同一 run。
- 浏览器Cookie仅内存；curl临时缓冲退出时清理。公开合成清单和公钥证据保留供独立验证。
- 更新包签名以**独立公钥**验证（测试用专用 key），不是生产签名密钥。

最终run.cf3QjW为127/0/0/0，exit0。原IPv6首地址504已修为全部候选先过SSRF检查后的有界回退，TLS/重定向/大小边界不变。旧失败轮次保留；--check-evidence区分evidence_integrity与run_status/run_exit_code。

## WSL 测试命令

以下命令在WSL仓库根执行；载荷/日志位于忽略的local/build，隔离Odoo、字体与0600测试私钥在专属WSL原生运行时目录。

```bash
# 运行时准备与校验（不安装系统包）
bash server/ubuntu22.04/bore/scripts/fetch-runtime.sh
bash server/ubuntu22.04/bore/scripts/fetch-runtime.sh --verify-only

# 契约测试（含 authority/端口渲染断言）
python3 -m unittest discover -s server/ubuntu22.04/bore/tests -p "test_config_contract.py"

# 运行时完整性与失败路径
bash server/ubuntu22.04/bore/tests/test_fetch_integrity.sh
NGINX_BIN="$(pwd)/local/build/bore-p1-20261026/runtime/root/usr/sbin/nginx" \
MODULE_SO="$(pwd)/local/build/bore-p1-20261026/runtime/root/usr/lib/nginx/modules/ngx_stream_module.so" \
BORE_BIN="$(pwd)/local/build/bore-p1-20261026/runtime/bore" \
  bash server/ubuntu22.04/bore/tests/test_failure_paths.sh

# P1 链路（合成上游，不是 Odoo）
NGINX_BIN="$(pwd)/local/build/bore-p1-20261026/runtime/root/usr/sbin/nginx" \
MODULE_SO="$(pwd)/local/build/bore-p1-20261026/runtime/root/usr/lib/nginx/modules/ngx_stream_module.so" \
BORE_BIN="$(pwd)/local/build/bore-p1-20261026/runtime/bore" \
  bash server/ubuntu22.04/bore/scripts/verify-local-entry.sh

# P2 整轮（真实隔离 Odoo 19 + Chrome；需本地合成账号，见脚本环境变量说明）
bash server/ubuntu22.04/bore/scripts/run-p2-isolated.sh

# 单元/逻辑测试（浏览器流、runner、签名夹具、契约）
python3 -m unittest discover -s server/ubuntu22.04/bore/tests -p "test_*.py"
```

本轮已收口。新快照：[source-server-p2-evidence-hardened-20261027.json](../../../maintenance/registry/source-server-p2-evidence-hardened-20261027.json)；详见[审计](../../../maintenance/audit/bore-p2-evidence-hardening-20261027.md)与[交接](../../../maintenance/handoffs/2026-10-27-p2-evidence-hardening.md)。

## 使用

```bash
# 需要 nginx（含 ngx_stream_module.so）与 bore 可执行文件
NGINX_BIN=/path/to/nginx MODULE_SO=/path/to/ngx_stream_module.so BORE_BIN=/path/to/bore \
  bash server/ubuntu22.04/bore/scripts/verify-local-entry.sh
```

输出：`local/build/bore-p1-20261026/run/`（证书/日志/结果，Git 忽略）。

## 明确边界

- 合成 DB 名 «bore_p1_synth_db»，不是生产库；合成上游不验证真实 Odoo 会话、权限或库存。
- 未实现：真实公网节点与标准 443、真实访客网络、自动续期、**生产部署**、EDA/Flutter 旧调用迁移。
- 已在**隔离真实 Odoo 19** 上验证（P2）：登录、检索、详情、刷新、退出（原生 POST+CSRF→303 同源）、匿名 `/lab` 303 保护、旧会话失效、严格 CSP 下零控制台/安全错误。这不等于生产已应用或公网可用。
- 未验证：生产 Odoo 上的同轮流程（生产只读、未部署）、真实公网/标准 443、真机、以及限速与 Odoo 冷却的最终一致性（Odoo workers 间不共享计数）。
- 生产运行时差异：生产 **Nginx 1.18.0 不支持 `proxy_cookie_flags`**，本地测试用的 1.30.6 **不能直接当作线上版本**；生产还需单独授权与兼容方案。

## 本轮测试资产

[签名夹具](tests/fixtures/signed_update_fixture.py)生成明确test-only身份，合成APK不可安装；verify子命令独立验证下载清单。私钥应在可执行0600权限的私有原生文件系统。
中文字体采用[官方Noto CJK来源登记](../../../maintenance/registry/bore-p2-fonts-20261027.json)，使用 `python tools/fetch_payload.py --id bore-p2-noto-cjk --download` 恢复已校验deb，仅私有解包；提供专属FONTCONFIG_FILE/FONTCONFIG_PATH和缓存，不安装系统字体。

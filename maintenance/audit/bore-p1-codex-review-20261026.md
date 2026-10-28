# bore P1 本地隔离实现：Codex 最终审查

日期：2026-10-26。分工：DSH 实施，Codex 提出审查意见、独立复跑并作最终判断。

## 结论与范围

接受 **P1 本地隔离实现**。不代表真实公网或生产环境验收通过，不授权部署、开放隧道、修改 DNS 或卸载模块。

审核对象为 `maintenance/registry/source-server-bore-p1-local-review2-20261026.json`，186 文件，tree SHA256 `0455170e3cc3b677700dfa21d8020d7f27afb2a38a72724f22baca8bbd50543d`。基于分支 `codex/two-stage-receipt-plan`、HEAD `14cf1ef44c6da1a1c1e4a77bbe51c446023a1e71` 的未提交工作区；原有未提交材料保留，未提交或推送 Git。源冻结不等于发布。

## 审查后完成的修正

- 白名单按真实控制器与前端端点补齐 `/lab`、详情、会话别名、登录表单和退出方法；动态详情 key 限单路径段。
- 转发头覆盖不可信 XFF/X-Real-IP，清除 Forwarded；认证精确端点清空选库头。
- 正式边缘模板公开侧不接受访客 PROXY 前缀，由 Nginx 生成来源信息，经 bore 透传至回环 TLS+PROXY 入口；运行测试直接渲染正式模板。
- 拒绝测试使用正确 CA/SNI、原样路径、上游请求计数与错误证据；区分协议拒绝、证书失败和一般连接失败。
- 验证使用独占运行目录；进程清理核对 PID、启动时间和身份，预检含 bore 控制端口，验证占用者不受影响。
- 运行时归档在解包前验证固定 SHA256，仅解包清单内载荷；实际可执行文件/模块另验固定哈希。篡改归档必须拒绝且不解包。

## Codex 独立验证

Windows Python 3.15.0；链路运行于本机 WSL2 Ubuntu 22.04，Nginx 1.18.0、bore 0.5.3、OpenSSL 3.0.2、Python 3.10.12。运行时通过项目脚本非 root 解包；测试证书、合成账号数据与日志不进入 Git。

| 检查 | 实际结果 | 退出码 | 证据 |
|---|---|---|---|
| `python -m unittest discover -s server/ubuntu22.04/bore/tests -p test_config_contract.py -v` | 9 通过，0 失败 | 0 | 本轮工具输出 |
| `bash server/ubuntu22.04/bore/scripts/verify-local-entry.sh`，配置绝对运行时路径 | 94 通过，0 失败 | 0 | `local/build/bore-dsh-resume-20261026/codex-chain-final.log` |
| `bash server/ubuntu22.04/bore/tests/test_failure_paths.sh`，相同运行时环境 | 10 通过，0 失败 | 0 | `local/build/bore-dsh-resume-20261026/codex-failure-paths-final.log` |
| `bash server/ubuntu22.04/bore/tests/test_fetch_integrity.sh` | 10 通过，0 失败 | 0 | `local/build/bore-dsh-resume-20261026/codex-fetch-integrity.log` |
| `python tools/repo_check.py --output local/build/bore-dsh-resume-20261026/codex-final-repo-check.json` | 50 检查通过，0 错误 | 0 | 对应 JSON |
| `git diff --check` | 无差异格式错误 | 0 | 本轮工具输出 |

组件验证合计 123 项，仓库 50 项另计；没有将旧版失败运行或未执行检查计为通过。仓库检查保留既有 `production-py312-rebuild` 离线载荷未构建警告；本轮未执行全量 `--verify-payloads`。

## 后续与未测边界

P1 上游为合成 HTTP 服务，不能验证真实 Odoo 的认证、Cookie、角色、库存事务或资源访问规则。真实公网节点、标准 443、移动网络表现、自动续期与生产上线均未测。本次没有生产操作，无生产回滚动作。

用户恢复内网后已交原 DSH 会话开展 P2：生产只读核对；真实 Odoo 合成隔离环境验证会话、权限与只读 UI。不得复制真实库/凭据至测试，不把“连上内网”当作生产写入授权。

DSH 继续沿用 task `task-codex-team-web-phase1-1a236b6b-505a-46ed-95be-a8df122ee26c` / session `session-979373c3-4290-414f-af00-cd63e7d177bf`；已观察模型 `ali/deepseek-v4.1-flash-1017/high`。详细实施交接见 `maintenance/handoffs/2026-10-26-bore-p1-local-isolated-entry.md`。

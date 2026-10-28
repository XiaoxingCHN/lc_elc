# 维护交接：2026-10-27 bore IPv4 与代理复核

## 用户目标与已确认边界

用户要求纠正 DeepSeek 的网络误判并验证挂 VPN 时访问 bore；只使用 IPv4，不改客户端/插件。沿用既有公网任务授权，但生产开放必须有独立白名单边界。

## 当前权威源码、分支和版本

分支 codex/two-stage-receipt-plan；server 当前 source-server-production-p2-20261027.json，业务源码与版本未改。工作区包含既有未提交修改，未覆盖。

## 已完成工作与实际证据

详见[审计](../audit/bore-ipv4-proxy-recheck-20261027.md)。同一合成隧道6种路径：代理4种成功200+精确内容（2.1～2.3秒），直连2种10秒超时。独立curl显式HTTP代理复核exit0。HTTP CONNECT支持TCP且本轮已完成实际数据传输，撤销“bore必须放弃”的错误结论。

## 剩余工作与阻塞

本轮没有证明直连超时的唯一根因；没有变更VPN/路由/DNS。正式Odoo公网入口还未部署：复用已测模板时仍要独立loopback listener、适配Nginx1.18、严格Host/Origin、Cookie、限速及域名证书。不要转发现有无白名单443/原始8069，也不要通过证书警告当作安全上线。

## 依赖和产物

bore0.5.3、NAS Python3、Windows Node24.13.0/curl；证据在local/build/bore-network-recheck-20261027，NAS在/home/hbut/bore/diag-codex-20261027。没有新增凭据或载荷，没有保存聊天到TOMC。

## 生产状态和回滚

本轮只在NAS普通用户目录运行合成服务，已按完整路径核对PID后停止隧道。无生产配置/服务重启，生产TLS登录200且证书信任检查0。此前其他模型改过的lc.rm.com/Nginx配置不属于本轮变更；不执行其不完整回滚说明，避免与独立upstream定义重复。

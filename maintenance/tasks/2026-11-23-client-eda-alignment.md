# 任务：客户端库位树与 EDA 界面对齐

- Status: ready-for-human
- Category: enhancement
- 目标：落实审查报告的 12 项修改，并把 15 项验收用例变成可重复执行的检查。
- 范围：`clients/app`（三端共用）与 `plugins/jlc-eda`。服务端不改。
- 验收：见 [审查报告](../audit/2026-11-23-client-eda-alignment.md) 的验收矩阵与本轮实施记录。
- 已完成：核心源码修改、自动化测试、三端原生包和 EDA 4.2.0 候选、源清单冻结、repo_check。Windows 和 Linux 通道包另行打包并验证首帧。
- 未完成：真实 EDA 宿主、Android 覆盖安装、完整升级与回退、客户端连生产。正式 stable 已上线 `1.4.0+26`。[正式发布交接](../handoffs/2026-11-23-client-stable-release.md)。
- 版本：客户端 `1.4.0+26`，EDA `4.2.0`。
- 交接：[2026-11-23 客户端与 EDA 对齐](../handoffs/2026-11-23-client-eda-alignment.md)。

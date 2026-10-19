# 数据保存与恢复

数据不进Git。当前本机完整历史快照在catalog/checkpoint-20261015，来源原linux_serve/lcsc_deployment/checkpoint；SQLite3547037696字节，中文cn662768条、cn_excluded56条。预期SHA256 `ac536621032c6028b708847b4ee0d74669008c9dfd2dee480991dfa11ad60823`，迁移会实际重算来源和目标hash确认。

这是旧一致性快照，不是当前服务器695217器件/4110477参数的最新数据库。生产完整备份仍只在服务器；路径/hash见SERVER.md。不要把本目录直接恢复到生产。

旧Windows中文JSONL/CSV导出、状态和日志在local/archive/data/lcsc_cn_archive，国际发现历史在local/archive/data/international；相同大库经全量hash确认后只保存一个新副本并建立来源别名，原文件没有删除。

## 怎样获得这些文件

- 精确历史副本：在当前机器用tools/offline_bundle.py导出data/catalog和离线依赖载荷；将载荷和.sha256一起转到新机器，用同工具import并逐文件核对。数据库是自行采集产物，不能从PyPI/GitHub包名下载。
- 新的合法快照：先在已授权采集机暂停采集，然后运行 `python server/ubuntu22.04/crawler/snapshot_catalog.py --source <采集数据>/components.sqlite3 --destination <新快照>/components.sqlite3`。工具拒绝覆盖目标，并检查暂停状态/SQLite完整性。
- 将同一采集点的categories_cn.json放到快照目录，再 `python server/ubuntu22.04/verify_checkpoint.py <新快照目录>`。保留manifest、记录计数和SHA。
- 只有需要导入Odoo时才按运维流程执行导入器；本归档任务不执行导入，不修改业务数量。

复制Git仓库不会带来数据库。离开当前机器前需另作可信离机备份，导出的历史资料不得与签名私钥/账号cookie混装。

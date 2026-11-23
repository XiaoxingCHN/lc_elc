# 历史资料入口

历史实物保存在Git排除的 local/archive/；原 F:/lc_elc_workspace 已于 2026-11-14 审核补档后删除，未替换其junction，未启动任何旧任务。

- local/archive/packages：旧版客户端、Ubuntu离线包和最初SDK整包；不是当前发布入口。
- local/archive/legacy-workspace：旧服务端/手机端/Flutter原型/早期Linux方案与原始根说明。
- local/archive/eda：EDA2.x和3.0.0–3.0.2、引用资料与旧验收。
- local/archive/data：旧中文导出/国际发现库/日志；相同 SQLite 经全量哈希核对后引用 `data/catalog` 的副本。旧工作区的重复文件已退役，`local/archive/data/lcsc_cn_archive` 的另存归档原库仍保留。
- local/archive/docs-original：原文档，可能有过时计数、状态和路径；不得作为当前部署事实。
- local/archive/evidence：历史实际测试记录和真实构建配方；一次性补丁和聊天记录不作为正式维护工具。
- local/archive/workspace-candidates：旧工作区退役前补档的570个未发布构建候选（含560 MiB服务端离线重建包和两个Linux客户端tar.gz）；不是当前发布入口。
- local/archive/eda/workspace-intermediates：EDA 3.x只留原件的30个构建产物，仓库内无对应源码。
- local/archive/evidence/analysis-workspace-20261014：旧工作区 _analysis 的2219个WorkBuddy记录，不作为正式维护工具。
- local/archive/source-import-before-format：补档51个不在Git的旧修订（该目录原有4个），来源为旧工作区中迁移后已演进的文件。

原始178156文件的体积盘点、复制映射和排除原因见local/manifests；缓存/临时构建目录不迁入当前源码，原件已随2026-11-14退役删除。历史资料可能包含环境信息，不能批量加入Git。

2026-11-14审核：138294个已迁移目标中138107个仍在（缺失187个全为dependencies/sdk/windows/flutter/.pub-preload-cache/*.tar.gz），820个抽查哈希中51个因迁移后源码继续演进而不同、旧修订已补档；退役前共补档2870文件/1402575621 B，逐文件来源与哈希见local/manifests/workspace-retirement-20261114.json，复核报告见merge-recheck-20261114.json。

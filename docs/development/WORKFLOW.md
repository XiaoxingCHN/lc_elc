# 人与AI共同维护流程

## 首次接手

读README → AGENTS → CURRENT_STATE → 对应组件README → registry。运行仓库检查，确认源码、载荷和当前包。生成文件不改，历史副本不作为起点。

## 做一项修改

涉及大量编码前，先在 GitHub 查找可复用的成熟实现，记录来源、维护状态、许可证和与现有环境的兼容性。优先复用，只补必要的适配与集成；没有采用现成方案时，说明具体原因，再交给实现者开发。

1. `git switch -c fix/<短名称>` 或 `feat/<短名称>`；新需求用TASK模板说明用户场景和通过条件。
2. 明确只改哪个组件；API变更要同步服务端、客户端和插件契约，兼容旧客户端或说明升级顺序。
3. 小步修改，业务权限、库存权威、幂等、离线只读等不变量需要重点验证。团队同时工作时分配不同目录，不覆盖对方产物。
4. 执行组件测试，再运行 `python tools/repo_check.py`；检查 `git diff --check`、差异及无凭据/载荷混入。
5. 保存实际测试命令、工具版本、退出码、通过/跳过数量和未验证项。构建产物标记为candidate，不能仅凭exit0叫最终验收。
6. 修改CHANGELOG、相应版本/文档；用release工具冻结来源。人工检查后提交，生产变更另有授权、备份、变更和回滚记录。
7. 交接写明下一步、当前源manifest和已知限制，不把完整聊天拷入仓库。

## 版本与分支

main保持能解释、能验证的维护基线。功能/修复分支通过检查后合入；Git tag标识基线或组件发布。客户端pubspec版本、Odoo各manifest版本、EDA package/extension版本独立，release registry将它们组成一次交付。

当前历史安装包不能直接视为新Git commit编译所得：来源关联是从原工作区hash及既有构建证据重建的，记录为imported。后续新构建必须用Git commit和完整源manifest关联。

## 机密与大文件

Git私有不代表可放密钥。密码/会话/签名材料只在OS凭据存储或local/private；日志不输出值。离线大文件要登记来源、获取方法和hash，不能只留下‘需要SDK’。原始数据库和历史聊天不用于PR展示。

## 当前源码与历史冻结的区别

maintenance/registry/active-sources.json指向当前代码的完整manifest；老manifest和已发布包保持不可变。正常功能修改后，不要改写旧baseline来凑检查：在测试并确认要冻结时创建新的源快照，例如 `python tools/release.py snapshot --component client --output maintenance/registry/source-client-task-<日期>.json --activate`。--activate只切换当前源码指针，不替旧安装包改变来源，也不代表已发布/已验收。未切换之前checker会指出代码相对当前快照的差异，这是需要补齐交接的明确状态。

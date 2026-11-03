# 维护交接：仓库路径与调用关系图

## 用户目标和边界

用户要求用Project Graph梳理现有路径和调用关系，选择仓库专用画布。无生产、DNS、路由修改授权，本轮没有执行这些变更。

## 实施与纠正

通过本机Canvas MCP适配器绘制61节点/92边，布局API成功但51组多行节点重叠。用户反馈后先改短标题消除重叠，但用户再次指出关系仍然不可读，说明“不重叠”不能作为可读性通过。

最终另做三个独立原生.prg文档，业务节点分别9/8/10，连线8/8/10，分别表达现有页面、新域名规划、业务调用。文件位于docs/architecture/warehouse-readable；相同布局PNG已查看，结构、引用及不重叠校验通过。原总图保留。新文件通过本项目原生序列化模板生成并逐文件回读，没有声称已在Project Graph桌面逐张打开。建议用户打开新三张小图，不再用初版总图作解释。

## 来源与限制

本地lab_inventory/lab_catalog/lab_workflow菜单、JS、接口、模型及Flutter服务源码，非生产实时检查。规划域名team.l-creation.club及/login、/lab等尚未实现。原生后台动作数字ID不从源码编造。网页入库直接receipt、Flutter两阶段pending的差异保留于完整源数据。

本机MCP仅--project由无线JLink图改为用户保存的仓库图，其他配置核对未变；图的首次实时修改前有本机备份。因当前原生工具实例可能保留旧参数，绘制使用相同适配器的新stdio会话。没有写入无线JLink硬件图。

## 检查

三个新原生文档ZIP/msgpack回读和边端点检查通过，节点无重叠；PNG逐张目测。整仓repo_check先前exit1、46通过，原因包括旧lab_portal登记/冻结与现源码不一致以及本机Python3.15目录语法问题，不因绘图擅改。工具和画布完整数据在local/build/projectgraph-20261025；图稿说明和验证在docs/architecture/warehouse-readable。

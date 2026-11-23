# 新维护机器从零开始

## 基础工具

1. 安装Git：Windows用[Git官方Windows入口](https://git-scm.com/downloads/win)，Linux使用发行版Git包。安装后确认`git --version`，把克隆目录设为工作根。
2. 安装Python3.10以上：从[Python官方下载入口](https://www.python.org/downloads/)选择适合自己系统的受支持版本，安装时使`python`或`python3`可运行。仓库工具为标准库，不要求先pip install一堆包；GitHub源码检查固定Python3.12。它不同于Odoo生产venv的完整依赖环境。
3. 先读README、AGENTS和CURRENT_STATE，运行`python tools/repo_check.py`。只克隆Git时缺少离线载荷警告属于预期，按dependencies/README补齐；已知完整cp312闭包未构建是单独缺口，不应静默忽略。

## 客户端维护

从payloads.json下载或离线恢复FlutterSDK、AndroidJDK/SDK、pub/Gradle缓存。Windows还需官方VS C++桌面工具；Linux需平台README列出的开发包。不要拿Windows Flutter/Node exe在Linux直接运行。

现成客户端可以直接按各端安装说明使用，修改源码则从clients/app开始。第一次构建先dry-run，工具不存在应按登记获取，不能让AI猜一个旧临时目录。

## EDA维护

安装 EDA 4.x 时导入 `.eext` 并在「连接设置」填入 EDA 密钥，按[现行插件入口](../../plugins/README.md)操作。Node 和 npm 用于源码构建，安装扩展无需再装本机网桥。旧 3.x 包的 Node 运行时只用于恢复对应历史环境。

## Odoo维护

开发机用独立Odoo/PostgreSQL测试库；不要直接在生产账号下练习升级或恢复。新装Ubuntu22.04走cp310离线安装路径，既有生产cp312按SERVER.md和生产70包版本锁准备同ABI依赖。全新机器不应把一份Python3.12条码wheel当完整生产环境。

## 私有材料与版本

Android匹配key单独受控恢复到local/private/signing，公证书对照registry；无key时不要生成一个新的冒充可更新包。真实登录密码由OS安全存储或管理员交付，不放Git/说明/聊天。首次Git提交作者由维护者本人配置，已有项目从登记的 `origin` 克隆即可。仓库和 Release 的实际可见性见 [GitHub 维护指南](../operations/GITHUB.md)。

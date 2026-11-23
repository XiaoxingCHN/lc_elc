# Windows客户端

本机成品为 `releases/1.4.0+26/LC_ELC-Windows-1.4.0+26-x64.zip`。解压整个 ZIP，在完整目录内运行 `lab_inventory_client.exe`。更新通道候选包已通过解包和首帧启动。 正式应用内 stable 为 `1.4.0+26`。走查和更新状态见[交接](../../maintenance/handoffs/2026-11-23-client-stable-release.md)。

## 开发环境与既有构建说明

共享源在../app。工具为Flutter3.47.7/Dart3.13.5、Windows C++桌面编译工具；MSVC不在本仓库离线包，原机D:/VS2026是未注册的便携布局，不可当通用VS安装。按官方[安装说明](https://learn.microsoft.com/en-us/cpp/build/vscpp-step-0-installation?view=msvc-170)安装“使用C++的桌面开发”、Windows SDK、对应v143工具集；本机原工具集14.44.35207。

从根目录运行 `python tools/build_client.py --platform windows --dry-run` 检查计划；恢复工具链后加--test进行构建。便携VS可能仍需私有环境适配，历史真实wrapper在local/archive/recipes/windows-native及原工作区，不要改全局注册表来凑构建。

插件符号链接错误时，使用dependencies/ensure_plugin_junctions.ps1并显式传-Project（当前新构建worktree）和-PubCache，不能无视pubget失败。PDF打印需要同包插件DLL/Pdfium/CRT，不能按‘附件’删除。

`1.4.0+26` 的完整构建与首帧证据见[正式发布交接](../../maintenance/handoffs/2026-11-23-client-stable-release.md)。精臣实物打印和完整升级待复测。完整构建说明见[客户端开发](../../docs/development/CLIENT.md)。

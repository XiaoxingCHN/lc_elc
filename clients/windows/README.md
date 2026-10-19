# Windows客户端

当前现成版：releases/1.0.1/LC_ELC-Windows-1.0.1.zip，以及同目录展开bundle。必须完整分发，不能只拿lab_inventory_client.exe。

共享源在../app。工具为Flutter3.47.7/Dart3.13.5、Windows C++桌面编译工具；MSVC不在本仓库离线包，原机D:/VS2026是未注册的便携布局，不可当通用VS安装。按官方[安装说明](https://learn.microsoft.com/en-us/cpp/build/vscpp-step-0-installation?view=msvc-170)安装“使用C++的桌面开发”、Windows SDK、对应v143工具集；本机原工具集14.44.35207。

从根目录运行 `python tools/build_client.py --platform windows --dry-run` 检查计划；恢复工具链后加--test进行构建。便携VS可能仍需私有环境适配，历史真实wrapper在local/archive/recipes/windows-native及原工作区，不要改全局注册表来凑构建。

插件符号链接错误时，使用dependencies/ensure_plugin_junctions.ps1并显式传-Project（当前新构建worktree）和-PubCache，不能无视pubget失败。PDF打印需要同包插件DLL/Pdfium/CRT，不能按‘附件’删除。

本次仅重新核对既有成品hash和归档源，没有重新编译或实体打印。完整步骤见docs/development/CLIENT.md。

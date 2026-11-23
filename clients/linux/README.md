# Linux客户端

本机成品为 `releases/1.4.0+26/LC_ELC-Linux-1.4.0+26.tar.gz`。解压后保留整个目录及执行权限。更新通道候选包已通过解包和 WSLg 首帧启动。桌面密钥存储、打印及完整升级仍待验收。 正式应用内 stable 为 `1.4.0+26`。手动包可从 [GitHub Release](https://github.com/XiaoxingCHN/lc_elc/releases/tag/client-v1.4.0%2B26) 公开下载。走查和更新状态见[交接](../../maintenance/handoffs/2026-11-23-client-stable-release.md)。

## 开发环境与既有构建说明

Linux原生构建应在Linux/WSL执行，不是PowerShell。Flutter3.47.7/Dart3.13.5，Ubuntu开发环境需要clang、cmake、ninja-build、pkg-config、libgtk-3-dev、libsecret-1-dev、libcups2-dev及C++编译工具。可在联网开发机用apt安装这些明确包；本次归档不安装宿主apt。

先按dependencies/README恢复LinuxFlutter和pub-cache-linux，然后在仓库根：

```sh
python3 tools/build_client.py --platform linux --dry-run
python3 tools/build_client.py --platform linux --test
```

打印插件CMake会取上游Pdfium；完整离线时应复用已核验预置库/历史构建配方，不能认为pubcache已含所有原生二进制。原WSL构建私有目录、PKG_CONFIG/sysroot/Pdfium适配路径在local/archive/evidence/ui-repair-20261018/build-linux.sh，不是跨机器有效的固定地址。

运行时需要GTK、libsecret以及真实SecretService（GNOME Keyring等）、CUPS/Pdfium。199 个 DEB 随历史离线归档保留，`1.4.0+26` 发布的是应用 bundle，不附该套 DEB。无桌面密钥服务时不允许明文密码回退。

历史 1.0.1 的构建与验证见其归档交接。当前 Linux 版本的登录记忆和实体打印均待复测。

# Linux客户端

当前成品releases/1.0.1/LC_ELC-Linux-1.0.1.tar.gz，以及同目录完整bundle。共享源../app，不能只分发ELF。

Linux原生构建应在Linux/WSL执行，不是PowerShell。Flutter3.47.7/Dart3.13.5，Ubuntu开发环境需要clang、cmake、ninja-build、pkg-config、libgtk-3-dev、libsecret-1-dev、libcups2-dev及C++编译工具。可在联网开发机用apt安装这些明确包；本次归档不安装宿主apt。

先按dependencies/README恢复LinuxFlutter和pub-cache-linux，然后在仓库根：

```sh
python3 tools/build_client.py --platform linux --dry-run
python3 tools/build_client.py --platform linux --test
```

打印插件CMake会取上游Pdfium；完整离线时应复用已核验预置库/历史构建配方，不能认为pubcache已含所有原生二进制。原WSL构建私有目录、PKG_CONFIG/sysroot/Pdfium适配路径在local/archive/evidence/ui-repair-20261018/build-linux.sh，不是跨机器有效的固定地址。

运行时需要GTK、libsecret以及真实SecretService（GNOME Keyring等）、CUPS/Pdfium。最新成品随包199 DEB保留；无桌面密钥服务时不允许明文密码回退。

1.0.1构建已有exit0，归档重新核对hash；旧版有SecretService/CUPS验收，1.0.1没有重新完整做这些原生验收和实体打印，不能把旧报告冒充新测试。

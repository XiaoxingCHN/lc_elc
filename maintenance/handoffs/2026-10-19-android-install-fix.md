# 维护交接：Android安装入口修复

## 用户目标与已确认边界

Android1.1.2+5已按用户明确授权发布到更新通道，用户随后反馈旧版1.1.1+4允许未知来源安装后仍显示通用失败。继续修复客户端，沿当前更新发布授权发布递增的新版本；不修改业务库存、账号权限、网络或其他服务，不覆盖已发布build5。

## 当前权威源码、分支和版本

客户端1.1.3+6，clients/app；完整清单source-client-android-install-fix-final-20261019.json，166文件。前一份source-client-android-install-fix-20261019.json保留为测试开发中的快照，不改写历史manifest。分支codex/two-stage-receipt-plan；最终来源提交和产物记录见本轮审计。

## 已完成工作与实际证据

旧Java/Kotlin实现要求absolutePath==canonicalPath，会拒绝指向合法私有更新缓存的系统路径别名。现在先解析文件和cacheDir的canonical路径，再执行目录包含、文件/长度、SHA256以及原有APK包名/版本/签名检查。仍拒绝跳出缓存的符号链接或同前缀兄弟目录。依据[Android File API](https://developer.android.com/reference/java/io/File#getCanonicalPath())，canonical路径会解析符号链接，因此绝对路径文本不必与canonical路径文本相同。

这是一处已通过真实文件系统复现的确定缺陷；尚无该手机的原生日志，不能断言它就是用户设备当前失败的唯一原因。旧版统一提示确实隐藏了实际失败环节。

原生按权限/缓存/文件长度/hash/APK格式/版本/签名/安装会话/提交/确认页面/系统结果返回具体错误码及可读原因；Flutter保留该原因，失败后解除业务请求保护。处理缺少系统确认Intent或系统拒绝启动确认页，避免无限等待或崩溃。PackageInstaller仍要求用户确认，不卸载旧版。

- 真实JDK17文件系统测试9项通过、exit0：标准文件、合法缓存别名、越界/逃逸链接/兄弟目录、长度/hash/缺文件等；旧absolute==canonical检查对别名明确失败，新边界通过。
- Flutter全量275通过5跳过、exit0；3项新回归实际操作确认安装并验证权限/缓存/取消原因呈现及业务保护解除。测试使用内存流隔离假时钟，真实包完整性由既有更新测试和JVM测试覆盖。最初真实IO widget fixture等待挂起，诊断与失败日志保留，未算PASS。
- 静态分析0错误0警告119提示、exit0。Android构建/最终签名、源一致性、发布与HTTP结果见本轮审计；未执行的内容不得计通过。

## 剩余工作与阻塞

旧版正在运行的安装入口不能被服务器发来的新APK直接修正。用户目前从旧入口安装已失败，需要手动覆盖修复APK一次；保留原应用数据，不先卸载。手机实际安装、升级后交互和下一次应用内更新仍需用户验证。如修复后仍失败，界面会显示具体INSTALL_*错误码和原因，可据此继续定位。未将本次原生编译或路径测试当实机安装验收。

## 依赖和产物

无新增运行依赖，新增纯Java缓存校验类和不依赖Android mock的JVM回归。复用原签名、私有缓存和现有PackageInstaller。Android新包及公开证书/hash见maintenance/audit/android-install-fix-20261019.json；Windows/Linux未重新构建，保留之前1.1.2+5候选，不宣称已经产出桌面1.1.3+6。

## 生产状态和回滚

Odoo19.0.1.2.0服务保持当前版本。本轮仅客户端包与递增发行清单；build5的包和签名清单必须保留。最终通道切换结果、旧指针保存位置、下载校验和撤回操作见android-install-fix审计；不恢复数据库、不递归删除发行目录。

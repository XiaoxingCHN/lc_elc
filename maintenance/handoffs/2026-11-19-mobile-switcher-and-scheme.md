# 维护交接：手机切换器撑满整屏 + 内网 https 手误

- 分支：`feat/receipt-param-search`（工作树 `.claude/worktrees/read-tomc-memory-56e7a2`）
- 客户端 `1.3.5+20 → 1.3.5+21`；未提交；未接触生产。

## 用户反馈

两张截图：

1. 手机上分区切换器渲染成**占满整屏的绿色胶囊**，四个分区标签挤在屏幕中间一行。
2. 采购入库页底部：「登录失败：无法连接 https://192.168.31.105:8069。无法连接服务器。」
   （同屏还有 `is_storable=False` 那条——那是服务端未部署的旧行为，见
   `2026-11-19-pending-storable-and-finish.md`。）

## 一、手机切换器撑满整屏（真 bug，且是我交付时漏测的）

`GlassSegmentedControl` 的 `_Segment` 里用 `Center(child: text)` 居中标签。`Center`
在没有 factor 的情况下会**扩张到父级允许的最大尺寸**：

- 桌面：切换器放在 `Column` 里，高度约束是无界的 → `Center` 缩到内容大小，看不出问题；
- 手机：切换器放在 `Scaffold.bottomNavigationBar` 里，高度约束是**有界**的
  （整个屏幕高）→ `Center` 撑满 → 每个 segment 变成整屏高。

实测（`tester.getSize`，412×915 屏幕）：修前 **412×907**，修后 **412×52**。

修法：两处 `Center` 都加 `widthFactor: 1, heightFactor: 1`。这不是针对手机的特例——
一个 segment 本来就该缩到标签大小。

回归测试：`warehouse_shell_test.dart` 的
「in a bottom bar it stays a thin strip, not a full-screen pill」，
断言切换器高度 < 120 且正文仍可见。

**教训**：`Scaffold.bottomNavigationBar` 给的是有界高度，和 `Column` 的无界高度行为相反。
任何"能放进底部栏"的组件都必须在有界高度下测一次。

## 二、内网 https 手误

截图里 `https://192.168.31.105:8069`。实测该服务器：

```
http://192.168.31.105:8069/web/health  -> 200
https://192.168.31.105:8069/web/health -> 连接失败
```

8069 是 Odoo 的明文 HTTP 端口，内网部署没有证书。所以这个地址**必然**失败，而错误信息
只写「无法连接」，读起来像服务器挂了。

修法：`OdooConfig.intranetSchemeHint(raw)`（纯函数）—— 私有网段 + `https` + 端口在
`intranetPlainHttpPorts`（目前只有 8069）时返回一句可操作的话：

> 内网 8069 端口是明文 HTTP，没有证书。请把地址改成 http://192.168.31.105:8069

登录页 `_validate()` 在**发请求之前**调用它。

**没有拦的情况**（有测试钉住）：
- `https://<内网>:18443` —— 那是网关自己终结 TLS 的端口，https 正确；
- 公网地址（`https://team.l-creation.club`）；
- 正确的 `http://…:8069`。

## 实测

- `flutter test --no-pub` → **509 passed / 5 skipped / 0 failed**。
- `flutter analyze --no-pub lib test` → 0 error / 0 warning。
- Windows 1.3.5+21 三步 exit 0；Android 1.3.5+21 构建中。

## 产物

- Windows：`clients/windows/releases/1.3.5+21/LC_ELC-Windows-1.3.5+21-x64.zip`，
  37,733,627 B，sha256 `b3faba35…a60e7c3`，30 文件，exe sha256 `f49251f4…b1fb2`。
- 清单 `source-client-1.3.5-21-20261119.json`（220 文件，已 `--activate`）。

## 未验证

- 手机上的实际观感（只有 widget 测试的尺寸断言，没有真机截图）。
- 服务端 `is_storable` 修复仍未部署——截图里那条报错在部署前会继续出现。
- 未 commit / 未 push。

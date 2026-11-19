# 维护交接：对比度修复 + 库位标签版式

- 分支：`feat/receipt-param-search`（工作树 `.claude/worktrees/read-tomc-memory-56e7a2`）
- 未提交；未接触生产。

## 用户反馈（两条）

1. 「三端都要更新，你这个色调的对比度完全看不清好吧」——截图里库存管理五张卡片是整片荧光绿，
   文字几乎不可见。
2. 「我们在做库位码的时候可以把库码放在二维码下面，然后库的名称放大放在左边要能看得见」。

## 对比度：根因与修法

`NavCard` 把 `prominent: true` 传给了 `GlassPanel`，`GlassSurface` 于是用
`palette.accent`（`#C9FF3F`）@ `glassFillProminent`（0.94）铺满整张卡，
而标题用 `colorScheme.onSurface`、说明用 `palette.muted`。

实测对比度（WCAG 相对亮度，对着合成后的实际填充色算）：

| 组合 | 对比度 |
|---|---|
| `onAccent` on accent | 16.6:1 ✅ |
| **`onSurface` on prominent fill（旧）** | **1.2:1** ❌ |
| **`muted` on prominent fill（旧）** | **2.0:1** ❌ |

`GlassSurface` 自己的文档写着「The stronger variant … At most one per screen」——
五张并列本来就违背了它。修法：卡片改中性玻璃面板，荧光绿只留给 44×44 的图标底和图标本身。

新增 `test/features/warehouse/warehouse_contrast_test.dart`（11 条）：
- 深浅两套色板分别断言 正文 / textSoft / muted / onAccent 在各自实际合成色上 ≥ 4.5:1；
- **反向**断言 `onSurface` 压在 accent 上 < 4.5:1 —— 把错误组合本身钉住，防止有人再把
  prominent 和 onSurface 配到一起；
- `NavCard` 层面断言它**从不**产出 `prominent: true` 的面板，且标题/说明/禁用原因都 ≥ 4.5:1。

## 桌面切换器

宽度 ≥900 时 `GlassSegmentedControl` 原本拉满整行，看起来像第二条工具栏。改为左侧紧凑胶囊
（`WarehouseSectionSwitcher(expanded: false)`，最大宽 520）。窄屏底部栏仍是拉满。

## 库位标签版式

`planThermalLabel` 为 `content.kind == 'location'` 单独走 `_planLocationLabel`：

| 元素 | 位置 | 字号 |
|---|---|---|
| 二维码 | 11 mm @ (1, 1) | — |
| **库码** | QR 正下方，y = 12 mm，宽度严格限制在 11 mm 码列内 | 6 pt（实测宽 8.3 mm） |
| **名称** | 右侧列 x = 13.5 mm，宽 24.5 mm | 17 pt（`kThermalMaxLocationNameFontMm`） |

两个必须记住的坑：

1. **名称不能取 `title`**。服务端 `lab_labels.py:118-127` 给库位标签的
   `title` 是 `location.lab_code or location.name` —— 也就是**库码**。照抄会把编码打成
   17 pt 大标题、名称反而消失。改为从 `名称：` 那一行取值（正则兼容 `名称/库位名称/name`），
   取不到才回退到首个正文值，最后才回退 title。
2. **库码取自 `payload`**（`LABL:K000003` → `K000003`），不是正文行。这样打出来的字和
   二维码编码的串一定是同一个，不会因为服务端正文行不同步而错位。

器件袋标签的几何完全没动（有测试 `bag labels are unchanged by the location path` 钉住）。
Windows FFI 与 Android 桥接都按「caption 用自己的 x/width」绘制，Kotlin 侧逐行读 x/width，
无需改动。

## 实测

- `flutter test --no-pub` → **504 passed / 5 skipped / 0 failed**。
- `flutter analyze --no-pub lib test` → 0 error / 0 warning。
- 真实 Windows 进程启动 + 截图：库存管理卡片文字清晰，顶部切换器为紧凑胶囊。
- 库位标签几何 dump（服务端真实形状的 `LabelContent`）：
  `QR x=1.0 y=1.0 size=11.0` / `CAPTION "K000003" @y=12.00 6.0pt w=8.3mm` /
  `NAME "电阻货架" @x=13.5 y=1.00 17.0pt`。

## 产物

- Windows：`clients/windows/releases/1.3.5+19/LC_ELC-Windows-1.3.5+19-x64.zip`，
  37,734,213 B，sha256 `249c90e8…891a5e89`，30 文件，exe sha256 `aa50f5b6…78ccee3`。
  清单 `source-client-1.3.5-19-20261119.json`（220 文件，已 `--activate`）。
- Android：构建中（本工作树没有 `dependencies/android`，用主仓 `F:\lc_elc\dependencies\android`
  与 `local/private/signing/windows-debug.keystore`）。

### Android 构建的跨盘坑（必读）

`--work-root C:/lcw` 会让 Android 构建**必然失败**，报：

```
Could not close incremental caches in ...\mobile_scanner\kotlin\compileReleaseKotlin\...
Suppressed: java.lang.IllegalArgumentException: this and base files have different roots:
  F:\lc_elc\dependencies\pub-cache-windows\...\BarcodeHandler.kt
  C:\lcw\client-android-...\source\android
```

Kotlin 增量编译器要算相对路径，pub 缓存在 `F:` 而工作根在 `C:` 就跨盘报错。
**Android 的 `--work-root` 必须与 pub 缓存同盘**（本机用 `--work-root F:/lcw`）。
Windows 构建不受影响（没有 Kotlin 编译）。这个错误看起来像「Kotlin 缓存损坏」，
重试一次也不会好，别浪费时间。

## 未验证

- 真实打印库位标签的观感与扫码（尤其 6 pt 库码在 300 dpi 下的清晰度）。
- Android 实机布局与蓝牙出纸。
- 未 commit / 未 push。

## 附：AAR 不入库

`clients/app/android/app/libs/.gitignore`（本轮新增）只跟踪 `README.md`，两个厂商 AAR
（0.8 MB + 28.7 MB）不入 Git，与 Windows 端 `windows/niimbot/runtime/.gitignore` 的做法一致。
构建前需从 `F:\lc_elc\Android-4.1.1-20261117.zip` 的 `SDK接入包/` 解出并核对 README 里的 SHA256。

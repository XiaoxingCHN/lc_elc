# 标签字体说明

## 为什么要有这个目录

器件/库位标签要打印中文（型号、参数、库位名、中文提示），
reportlab 内置字体没有中文字形；如果「只换字体名」，实际 PDF 会显示成方块或空白。
所以本模块会**真实检测字形**（cmap 查 ``charToGlyph``），缺字形就换字体，
所有候选都缺字形就直接报错、拒绝生成，绝不静默丢字。

## 字体候选顺序

1. 环境变量 ``LAB_WORKFLOW_LABEL_FONT`` 指向的字体文件
2. 系统参数 ``lab_workflow.label_font`` 指向的字体文件
3. 本目录下的 ``NotoSansSC-Regular.ttf`` / ``NotoSansSC-VF.ttf``
4. 系统已安装的 CJK 字体（Ubuntu: ``fonts-noto-cjk`` / ``fonts-wqy-microhei``）

## 随包字体与许可证

* 文件名：``NotoSansSC-VF.ttf``（Noto Sans SC，Google / Adobe 出品）
* 许可证：**SIL Open Font License 1.1**，全文见本目录 ``OFL.txt``
* 归属：``Copyright 2012 Google Inc. All Rights Reserved.``
* 允许随软件一起打包、嵌入 PDF、再分发（OFL 1.1 第 2 条），
  唯一限制是不得单独售卖字体本身，且衍生字体不得使用保留字体名。

> 说明：本字体取自本机已安装的 Noto Sans SC 文件（Google 官方 OFL 字体），
> 只做随包分发与嵌入打印用途。**未使用任何 Windows 商业字体**
> （微软雅黑/宋体等不在此目录，也不随包分发）。

## 运维可选：换成体积更小的字体

完整 Noto Sans SC 约 17MB。如需精简体积，可以：

1. 使用 ``fonttools`` 抽取子集（例如常用 3500 汉字 + 拉丁 + 数字 + 标点），
   生成的静态 TTF 放到本目录并保留 ``OFL.txt``；
2. 或安装系统字体包（``sudo apt-get install -y fonts-noto-cjk``），
   并把本目录字体删除，模块会自动回退到系统字体。

## 字体接入必须实测

新增字体后请务必真实生成一次 PDF 并**目视/OCR 检查中文是否正常**，
不能只确认「文件存在」或「注册成功」。模块里的自动检测只能保证「字形存在」，
最终打印效果仍需人工确认（安装说明见 ``__manifest__`` 与验收文档）。

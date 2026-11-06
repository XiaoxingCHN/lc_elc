# 领域文档

工程技能探索代码库时应如何读取本仓库的领域文档。

## 探索前先读

- 根目录 `GLOSSARY.md`；或
- 若存在根目录 `GLOSSARY-MAP.md`，按其中指向逐个读取相关上下文的 `GLOSSARY.md`。
- `docs/adr/`：读取涉及当前工作区域的 ADR。多上下文仓库还要检查 `src/<context>/docs/adr/`。

如果这些文件不存在，静默继续：不要提示缺失，也不要主动创建。`/domain-modeling` 技能（通过 `/grill-with-docs` 和 `/improve-codebase-architecture` 进入）会在术语或决策真正确定时按需创建。

## 文件结构

本仓库是 single-context：

```text
/
├── GLOSSARY.md
├── docs/adr/
│   ├── 0001-....md
│   └── 0002-....md
└── clients/ server/ ...
```

当前已有 `GLOSSARY.md` 和 `docs/adr/`（第 1 条为 `0001-parameter-keyword-search.md`）；新增决策按顺序编号。

## 使用词汇表

输出中命名领域概念时（issue 标题、重构提案、假设、测试名），使用 `GLOSSARY.md` 定义的术语，不要漂移到词汇表明确避免的同义词。

如果需要的概念还不在词汇表中，这是一个信号：要么你在发明项目不用的语言（重新考虑），要么确实存在缺口（记录给 `/domain-modeling`）。

## 标记 ADR 冲突

如果输出与现有 ADR 冲突，明确指出来，不要静默覆盖：

> _与 ADR-0007（event-sourced orders）冲突，但值得重新讨论，因为……_

# skill-context-slide

> **SCS** — 当 agent 调 tool 加载外部知识后，压缩时用 LRU 滑动窗口 + stub 替换来管理上下文。

**核心口诀：满了就踢，要了再装。**

## 解决的问题

Agent 调用 `skill_view(name)` 加载技能内容后，即使话题已经切换，这些内容仍占据 token 预算。SCS 在 context compression 触发时，只保留最近 N 个不同技能名的完整内容，窗口外的替换为 `[已卸载]` stub。

## 设计层次

```
┌─────────────────────────────────────┐
│  A: 设计模式（docs/pattern.md）       │ ← 通用思路
│  适用于任何 agent 的知识加载管理       │
├─────────────────────────────────────┤
│  B: Hermes 补丁路径                  │ ← 具体实现
│  两条 patch + 一键 revert            │
├─────────────────────────────────────┤
│  C: test_skill_view_lru_pruning.py   │ ← 验证
│  11个用例覆盖正常+边界+异常           │
└─────────────────────────────────────┘
```

## Hermes Agent 安装

### 补丁内容

1. 在 `agent/context_compressor.py` 的 `_sanitize_tool_pairs` 和 `_align_boundary_forward` 之间插入 `SKILL_VIEW_LRU_WINDOW` 常量和 `_prune_skill_view_results` 方法
2. 在 `compress()` 的 `_strip_historical_media` 之后添加调用 `compressed = self._prune_skill_view_results(compressed)`

### 还原

```bash
python scripts/revert.py --backup
python scripts/revert.py --dry-run   # 预览
```

### 验证

```bash
cd <hermes-agent-root>
python -m pytest tests/agent/test_skill_view_lru_pruning.py -v
```

## 测试覆盖

| 类别 | 用例数 | 覆盖点 |
|------|--------|--------|
| 正常路径 | 6 | 空输入、无调用、保留、淘汰、去重、交替完整 |
| 边界条件 | 5 | 批量加载、混合工具、孤立 call_id、窗口=0、重载 |
| **合计** | **11** | **全部通过 ✅** |

完整报告：`docs/verification-report.md`

## License

MIT

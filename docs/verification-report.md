# SCS — Skill-Context-Slide 验证报告

> 2026-07-03 · 全闭环测试

## 概述

SCS 在 Hermes Agent 的 `ContextCompressor.compress()` 中维护一个 LRU 滑动窗口。
compression 触发时，窗口外的 `skill_view` tool result 被 stub 替换，释放 token 预算。
窗口默认大小 = 3，可配置。

## 被测组件

| 项目 | 值 |
|------|-----|
| 模块 | `agent/context_compressor.py` |
| 方法 | `ContextCompressor._prune_skill_view_results()` |
| 常量 | `SKILL_VIEW_LRU_WINDOW: int = 3` |
| 调用点 | `compress()` Phase 5，`_strip_historical_media` 之后 |
| 测试文件 | `tests/agent/test_skill_view_lru_pruning.py` |
| 行数（核心逻辑） | ~80 行 |
| 行数（测试） | ~335 行 |

## 算法（4 Pass）

1. **收集** — 遍历 assistant 消息，找到 `function.name == "skill_view"` 的 tool_calls
2. **LRU 窗口** — 从后往前扫描，取最近 N 个不同 skill_name（窗口 ≤ 0 时全部卸载）
3. **标记** — 窗口外的 call_id 加入 `outside_cids`
4. **替换** — 匹配的 tool result content 替换为 `{"success":true,"name":"...","content":"[已卸载]"}`

## 测试矩阵

### 正常路径

| # | 测试 | 预期 | 结果 |
|---|------|------|------|
| 1 | 空输入 | `[]` 原样返回 | ✅ |
| 2 | 无 skill_view 调用 | 消息列表不变 | ✅ |
| 3 | 1 个技能（≤窗口） | 内容保留 | ✅ |
| 4 | 4 个技能（>窗口） | 最早 1 个被 stub 替换 | ✅ |
| 5 | 同名技能重复加载 | 去重，只占 1 个窗口位 | ✅ |
| 6 | 消息交替完整 | stub 不改变消息总数 | ✅ |

### 边界条件

| # | 测试 | 预期 | 结果 |
|---|------|------|------|
| 7 | 同一条消息批量调 skill_view | 每个独立计入窗口 | ✅ |
| 8 | 混合其他 tool（web_search 等） | 非 skill_view 不受影响 | ✅ |
| 9 | 孤立 tool_call_id | 不崩溃，安全忽略 | ✅ |
| 10 | 窗口=0 边缘情况 | 全部卸载 | ✅ |
| 11 | 卸载后重载同名技能 | 新内容保留，LRU 重算 | ✅ |

## 全闭环往返测试

| 步骤 | 操作 | 测试结果 | 耗时 |
|------|------|----------|------|
| ① | 安装 patch | 11/11 ✅ | 0.52s |
| ② | `revert.py` 还原 | 3 处改动全部回滚 | — |
| ③ | 还原后验证 | 11/11 ❌（方法不存在，正确行为） | 0.66s |
| ④ | 重新应用 patch | 2 次 patch 无冲突 | — |
| ⑤ | 重装后验证 | 11/11 ✅ | 0.54s |

## 修复记录

### Bug: 窗口=0 时 `>=` 条件兜底

**症状**：`SKILL_VIEW_LRU_WINDOW=0` 时，Pass 2 的 `if len(lru_skills) >= 0: break` 条件在 append 之后才断，导致始终保留至少 1 个技能。

**修复**：增加显式守卫：

```python
if self.SKILL_VIEW_LRU_WINDOW <= 0:
    lru_set: set[str] = set()  # window=0 or negative → evict all
else:
    # 原有 LRU 构建逻辑
```

## 环境

| 项目 | 值 |
|------|-----|
| Python | 3.11.15 |
| pytest | 9.0.2 |
| Hermes Agent | commit 2ecb6f7fe (main) |
| 测试运行 | `cd ~/.hermes/hermes-agent && python -m pytest tests/agent/test_skill_view_lru_pruning.py -v` |

## 还原工具

```bash
# 查看改动
python scripts/revert.py --dry-run

# 一键还原（含备份）
python scripts/revert.py --backup

# 指定 Hermes 路径
python scripts/revert.py --hermes-path /opt/hermes-agent
```

支持自动检测常见路径：`cwd` → `cwd/hermes-agent` → `~/.hermes/hermes-agent` → `~/hermes-agent` → `/opt/hermes-agent`。

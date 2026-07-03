# SCS — Skill-Context-Slide: Verification Report

> 2026-07-03 · Full round-trip test

## Overview

SCS maintains an LRU sliding window inside Hermes Agent's `ContextCompressor.compress()`. When compression fires, `skill_view` tool results outside the window are replaced with a stub, freeing token budget. Default window size = 3, configurable via `SKILL_VIEW_LRU_WINDOW`.

## Components Under Test

| Item | Value |
|------|-------|
| Module | `agent/context_compressor.py` |
| Method | `ContextCompressor._prune_skill_view_results()` |
| Constant | `SKILL_VIEW_LRU_WINDOW: int = 3` |
| Call site | `compress()` Phase 5, after `_strip_historical_media` |
| Test file | `tests/agent/test_skill_view_lru_pruning.py` |
| Core logic | ~80 lines |
| Tests | ~335 lines |

## Algorithm (4 Pass)

1. **Collect** — iterate assistant messages, find `function.name == "skill_view"` tool_calls
2. **LRU window** — walk in reverse, keep N distinct skill names (≤ 0 → evict all)
3. **Mark** — call_ids outside window → `outside_cids` set
4. **Replace** — matching tool result content → `{"success":true,"name":"...","content":"[已卸载]"}`

## Test Matrix

### Normal Path

| # | Test | Expectation | Result |
|---|------|-------------|--------|
| 1 | Empty input | `[]` returned as-is | ✅ |
| 2 | No skill_view calls | Messages unchanged | ✅ |
| 3 | 1 skill (≤ window) | Content preserved | ✅ |
| 4 | 4 skills (> window) | Earliest 1 gets stubbed | ✅ |
| 5 | Same skill loaded multiple times | Deduped, 1 window slot | ✅ |
| 6 | Message alternation preserved | Stub doesn't change message count | ✅ |

### Edge Cases

| # | Test | Expectation | Result |
|---|------|-------------|--------|
| 7 | Batch skill_view in one assistant msg | Each counted independently | ✅ |
| 8 | Mixed with other tools (web_search) | Non-skill_view untouched | ✅ |
| 9 | Orphan tool_call_id | Silent ignore, no crash | ✅ |
| 10 | Window = 0 | Everything evicted | ✅ |
| 11 | Reload after eviction | New content preserved, LRU recalculated | ✅ |

## Full Round-Trip

| Step | Action | Test result | Time |
|------|--------|-------------|------|
| ① | Apply patch | 11/11 ✅ | 0.52s |
| ② | `revert.py` rollback | All 3 changes reverted | — |
| ③ | Verify after revert | 11/11 ❌ (method gone — correct) | 0.66s |
| ④ | Re-apply patch | 0 conflicts | — |
| ⑤ | Verify after re-apply | 11/11 ✅ | 0.54s |

## Bug Fix Record

### Bug: window=0 kept 1 skill due to `>=` guard ordering

**Symptom:** With `SKILL_VIEW_LRU_WINDOW=0`, the condition `if len(lru_skills) >= 0: break` fired *after* appending, so at least 1 skill always survived.

**Fix:** Added explicit guard:

```python
if self.SKILL_VIEW_LRU_WINDOW <= 0:
    lru_set: set[str] = set()  # window=0 or negative → evict all
else:
    # original LRU-building logic
```

## Environment

| Item | Value |
|------|-------|
| Python | 3.11.15 |
| pytest | 9.0.2 |
| Hermes Agent | commit 2ecb6f7fe (main) |
| Runner | `cd ~/.hermes/hermes-agent && python -m pytest tests/agent/test_skill_view_lru_pruning.py -v` |

## Revert Tool

```bash
# Preview changes
python scripts/revert.py --dry-run

# Revert with automatic backup
python scripts/revert.py --backup

# Specify Hermes path
python scripts/revert.py --hermes-path /opt/hermes-agent
```

Auto-discovers Hermes at: `cwd` → `cwd/hermes-agent` → `~/.hermes/hermes-agent` → `~/hermes-agent` → `/opt/hermes-agent`.

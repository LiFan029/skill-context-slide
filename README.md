# skill-context-slide (SCS)

> **LRU sliding window + stub eviction for agent-loaded external knowledge.**  
> When compression fires, only the last N distinct skill results survive; older ones get stubbed. Reload on demand is free.

**Core mantra: evict when full, reload when needed.**

---

## The Problem

An agent calls `skill_view(name)` (or any knowledge-loading tool) to fetch external content into conversation context. After the topic shifts, that content becomes stale but keeps consuming token budget, diluting the agent's attention and degrading independent reasoning.

SCS solves this by maintaining a **Least Recently Used (LRU) sliding window** over loaded knowledge. During context compression, only the most recent N distinct items are kept intact; everything outside the window is replaced with a lightweight stub (`[已卸载]` / `[evicted]`).

## Design Layers

```
┌──────────────────────────────────────┐
│ A: Design Pattern (docs/pattern.md)  │ ← universal idea
│ Applicable to any agent architecture │
├──────────────────────────────────────┤
│ B: Hermes Agent patch + revert tool  │ ← concrete implementation
│ Two precise patches + revert.py      │
├──────────────────────────────────────┤
│ C: Test suite (tests/)               │ ← verification
│ 11 test cases: normal + edge + error │
└──────────────────────────────────────┘
```

## Hermes Agent Installation

### What the patch does

Two changes to `agent/context_compressor.py`:

1. Insert the `SKILL_VIEW_LRU_WINDOW` constant and `_prune_skill_view_results()` method between `_sanitize_tool_pairs` and `_align_boundary_forward`
2. Add the call `compressed = self._prune_skill_view_results(compressed)` inside `compress()`, right after `_strip_historical_media`

### Revert

```bash
python scripts/revert.py --backup       # backup + revert
python scripts/revert.py --dry-run      # preview only
```

### Verify

```bash
cd <hermes-agent-root>
python -m pytest tests/agent/test_skill_view_lru_pruning.py -v
```

## Test Coverage

| Category     | Cases | What it covers                              |
|-------------|-------|---------------------------------------------|
| Normal path | 6     | empty input, no-op, keep, evict, dedup, alternation |
| Edge cases  | 5     | batch load, mixed tools, orphan call_id, window=0, reload |
| **Total**   | **11**| **100% passing**                             |

Full report: `docs/verification-report.md`

## Full Round-Trip Verification

```
  State              Test result
┌─────────────┬────────────────────────────┐
│ Patched     │ 11/11 passed (0.52s)       │
├─────────────┼────────────────────────────┤
│ Reverted    │ 11/11 failed (correct)     │
├─────────────┼────────────────────────────┤
│ Re-applied  │ 11/11 passed (0.54s)       │
└─────────────┴────────────────────────────┘
```

## License

MIT

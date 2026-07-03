# skill-context-slide (SCS)

> **LRU sliding window + stub eviction for agent-loaded external knowledge.**  
> When compression fires, only the last N distinct skill results survive; older ones get stubbed. Reload on demand is free.

**Core mantra: evict when full, reload when needed.**

<p align="center">
  <img src="https://img.shields.io/badge/Hermes%20Agent-4A00FF?style=flat-square" alt="Hermes Agent"/>
  <img src="https://img.shields.io/badge/Claude%20Code-CC7832?style=flat-square" alt="Claude Code"/>
  <img src="https://img.shields.io/badge/OpenAI%20Codex-412991?style=flat-square" alt="OpenAI Codex"/>
  <img src="https://img.shields.io/badge/Cline-00A67E?style=flat-square" alt="Cline"/>
  <img src="https://img.shields.io/badge/Continue-000000?style=flat-square" alt="Continue"/>
  <img src="https://img.shields.io/badge/Cursor-6C47FF?style=flat-square" alt="Cursor"/>
</p>

---

## The Problem

An agent calls `skill_view(name)` (or any knowledge-loading tool) to fetch external content into conversation context. After the topic shifts, that content becomes stale but keeps consuming token budget, diluting the agent's attention and degrading independent reasoning.

SCS solves this by maintaining a **Least Recently Used (LRU) sliding window** over loaded knowledge. During context compression, only the most recent N distinct items are kept intact; everything outside the window is replaced with a lightweight stub (`[已卸载]` / `[evicted]`).

## Quick Start

```bash
# 1. Clone this repo
git clone https://github.com/LiFan029/skill-context-slide.git
cd skill-context-slide

# 2. Locate your Hermes Agent installation
#    (mine is at /opt/hermes-agent or ~/.hermes/hermes-agent)
ls agent/context_compressor.py    # if you're inside the Hermes root
ls ~/.hermes/hermes-agent/agent/context_compressor.py  # common install path

# 3. Apply the patch
cd /path/to/hermes-agent
git apply /path/to/skill-context-slide/patches/scs-hermes.patch

# 4. Run the tests (from Hermes root)
python -m pytest tests/agent/test_skill_view_lru_pruning.py -v
# Expected: 11 passed

# 5. Done! Next time compression fires, skill_view results outside the
#    LRU window will be stubbed automatically.
```

## ⚠️ Restart Required After Patching

SCS lives in Python source code that is loaded into memory when a process starts. Whether you need to restart depends on **how** you run Hermes:

| Deployment | Behavior | Restart needed? |
|---|---|---|
| **CLI** (`hermes chat`) | Every invocation is a **fresh Python process**. The patched `.py` is read from disk each time. | **No** ✅ — next `hermes chat` picks it up automatically. |
| **Gateway** (`hermes gateway`) | A single long-lived Python process that caches all imports in memory on startup. | **Yes** 🔄 — run `hermes gateway restart` (or `/restart` in-session if you have admin rights). |
| **Desktop** (`hermes desktop`) | The Electron app embeds a gateway process in the background. | **Yes** 🔄 — quit the app (`Cmd+Q` / `Ctrl+Q`) and relaunch it. On Linux, also check the background gateway with `hermes gateway restart`. |

### How to verify it's active

After restarting, check the gateway logs for the SCS pruning message:

```bash
# Wait for a compression to occur (usually when the session hits ~850K tokens),
# then search the log
grep "Pruned.*skill_view.*LRU" ~/.hermes/logs/gateway.log
# Expected: "Pruned N skill_view tool result(s) outside LRU window"
```

Or run the test suite to confirm the code is wired correctly:

```bash
python -m pytest tests/agent/test_skill_view_lru_pruning.py -v
# Expected: 11/11 passed
```

## What the Patch Changes

**Single file:** `agent/context_compressor.py`, two insertion points (107 lines added, 0 removed):

### Change 1 — New method (inserted after `_sanitize_tool_pairs`)

```python
SKILL_VIEW_LRU_WINDOW: int = 3  # class constant, configurable

def _prune_skill_view_results(self, messages):
    """4-pass algorithm: collect skill_view calls → build LRU window →
    mark outsiders → replace with stub."""
    ...
```

### Change 2 — Call site (inserted inside `compress()`, after `_strip_historical_media`)

```python
# Phase 5: Prune skill_view tool results outside the LRU window
compressed = self._prune_skill_view_results(compressed)
```

### To verify what changed:

```bash
cd /path/to/hermes-agent
git diff agent/context_compressor.py    # show the patch diff
grep -n "SKILL_VIEW_LRU_WINDOW\|_prune_skill_view" agent/context_compressor.py
# Expected output: multiple lines with method definition and call site
```

## Revert

```bash
cd /path/to/skill-context-slide
python scripts/revert.py --dry-run      # preview what will be removed
python scripts/revert.py --backup       # backup + revert
```

`revert.py` auto-detects Hermes Agent at `cwd`, `cwd/hermes-agent`, `~/.hermes/hermes-agent`, `~/hermes-agent`, or `/opt/hermes-agent`.

Expected output after revert:
```bash
cd /path/to/hermes-agent
grep -c "_prune_skill_view_results" agent/context_compressor.py
# Exit code 1, no output — method is gone
```

## AI Agent Setup Instructions

If you (an AI assistant) are reading this and want to apply SCS for your user:

1. **Find Hermes Agent.** Check common locations in order:
   - `./agent/context_compressor.py` (in cwd)
   - `./hermes-agent/agent/context_compressor.py`
   - `~/.hermes/hermes-agent/agent/context_compressor.py`
   - `~/hermes-agent/agent/context_compressor.py`
   - `/opt/hermes-agent/agent/context_compressor.py`

2. **Verify it's uncompromised:** run `grep -c "_prune_skill_view_results"` on the file. If 0, it's clean.

3. **Apply the patch:** `git apply /path/to/scs-hermes.patch` from Hermes root. If git isn't available, use `patch -p1 < /path/to/scs-hermes.patch`.

4. **Verify the patch applied:** run `grep -c "_prune_skill_view_results"` again — should return ≥ 1.

5. **Copy the test file** `tests/test_skill_view_lru_pruning.py` into `tests/agent/` under Hermes root.

6. **Run tests:** `python -m pytest tests/agent/test_skill_view_lru_pruning.py -v`. Expect 11/11 passed.

7. **If tests fail**, run `python scripts/revert.py` to restore original state, then check Hermes version compatibility.

## Test Coverage

| Category     | Cases | What it covers                              |
|-------------|-------|---------------------------------------------|
| Normal path | 6     | empty input, no-op, keep, evict, dedup, alternation |
| Edge cases  | 5     | batch load, mixed tools, orphan call_id, window=0, reload |
| **Total**   | **11**| **100% passing**                             |

Full verification report: `docs/verification-report.md`

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

## Files

```
skill-context-slide/
├── patches/
│   └── scs-hermes.patch         ← git-apply ready patch for Hermes Agent
├── scripts/
│   └── revert.py                ← auto-detecting revert tool
├── tests/
│   └── test_skill_view_lru_pruning.py  ← 11-test suite (copy to Hermes)
├── docs/
│   ├── pattern.md               ← generic design pattern (any agent)
│   └── verification-report.md   ← full test report
├── README.md
└── LICENSE
```

## Design Layers

```
┌──────────────────────────────────────┐
│ A: Design Pattern (docs/pattern.md)  │ ← universal idea
│ Applicable to any agent architecture │
├──────────────────────────────────────┤
│ B: Hermes Agent patch + revert tool  │ ← concrete implementation
│ patches/scs-hermes.patch + revert.py │
├──────────────────────────────────────┤
│ C: Test suite (tests/)               │ ← verification
│ 11 test cases: normal + edge + error │
└──────────────────────────────────────┘
```

## License

MIT

# Design Pattern: LRU Context Window for Agent-Loaded Knowledge

> A simple, composable pattern for managing external knowledge loaded into
> conversation context via tool calls. **Evict when full, reload when needed.**

---

## Problem

An agent loads external knowledge (skill docs, API references, codebase context)
into conversation context via tool calls. Each load may consume hundreds to
thousands of tokens. When the topic shifts, that content becomes stale but
remains in context — silently consuming token budget and diluting the agent's
attention, degrading independent reasoning.

## Constraints

- **Don't prefetch** — never anticipate what the user will need
- **Don't hide** — keep the index/search surface transparent and complete
- **Don't intercept** — only act at natural context-reduction points (compression)
- **Don't delete messages** — preserve strict message role alternation for LLM API
- **Reload must be cheap** — one tool call, no side effects

## Solution

**LRU sliding window + stub replacement.**

### Four passes

1. **Collect** — scan assistant messages for the target tool (e.g. `skill_view`)
2. **LRU window** — walk in reverse, keep the most recent N distinct names (dedup)
3. **Mark** — call_ids outside the window → eviction set
4. **Replace** — matched tool-result content → stub (`[evicted]`)

```
Pass 1                         Pass 2
┌───┐                          ┌───┐
│skill_view("stock")          │  Newest: creative  ← kept
│skill_view("trpg")           │         devops    ← kept
│skill_view("devops")         │         trpg      ← kept
│skill_view("creative")       │  Oldest: stock    ← evicted
└───┘                          └───┘
                                    ↓
                               Pass 3 & 4
                               ┌──────────────────────┐
                               │ stock content → stub │
                               │ others unchanged     │
                               └──────────────────────┘
```

### Key decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Window size | Fixed (e.g. 3) | Simple, predictable, configurable |
| Eviction policy | LRU | Semantic relevance is unreliable and expensive |
| Replacement | Stub, not delete | Preserves `assistant → tool → assistant` alternation chain |
| Trigger | Only at compression | Never intercepts live conversation flow |

### Safety properties

- **False eviction** → next use reloads it. Cost: one tool call. Zero net loss.
- **Dedup** → same knowledge loaded multiple times = 1 window slot
- **Window = 0** → evict everything (trivial but safe edge case)

## Portability

Any agent architecture with a "compression post-processing" hook can adopt this pattern:

| Agent | Hook point | Adaptation |
|-------|-----------|------------|
| Hermes Agent | `ContextCompressor.compress()` tail | Patch or `post_compress` plugin |
| Claude Code | Post-`/compact` | Custom hook |
| Codex | Context management middleware | Middleware |
| Others | Message-list reduction path | Analogous approach |

## Reference Implementation

The `skill-context-slide` repo provides:

- `scripts/revert.py` — apply/revert the Hermes Agent patch
- `tests/` — 11-assertion test suite (normal paths + edge cases)
- `docs/verification-report.md` — full round-trip verification results

## See Also

- [Dynamic Prompt Architecture](../idea/dynamic-prompt-architecture.md) —
  solves the complementary problem: not loading unused tool definitions
  in the first place

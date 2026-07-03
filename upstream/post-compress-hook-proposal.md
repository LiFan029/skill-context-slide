# Upstream PR Proposal: post_compress hook for ContextEngine

## Summary

Add an optional `post_compress()` hook to the `ContextEngine` ABC so third-party
engines and plugins can post-process compressed messages without patching core
files.

**Author:** LiFan029  
**PR target:** NousResearch/hermes-agent  
**Consumer proof:** https://github.com/LiFan029/skill-context-slide

---

## Changes

### File 1: `agent/context_engine.py`

Add after `should_defer_preflight_to_real_usage` (before `has_content_to_compress`):

```python
# -- Optional: post-compression hook ------------------------------------

def post_compress(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Post-process compressed messages before they are returned.

    Called at the end of ``compress()`` for engines that need to
    transform or annotate messages after compaction — for example,
    pruning stale tool results, reordering, or injecting metadata.

    The default implementation is a no-op (returns messages unchanged).
    Override in subclasses to add behavior.

    Args:
        messages: The compressed message list returned by ``compress()``.

    Returns:
        The (possibly modified) message list. Must preserve valid
        OpenAI-format message alternation (assistant → tool → assistant).
    """
    return messages
```

### File 2: `agent/context_compressor.py`

In `compress()`, change the return statement from:

```python
return compressed
```

to:

```python
return self.post_compress(compressed)
```

Insertion point: end of `compress()` (line ~2771 in current main), which is
right after the compression logging block.

No other changes needed — no new imports, no new dependencies.

---

## Why

1. **SCS (Skill-Context-Slide)** — a plugin that prunes stale ``skill_view``
   tool results using an LRU sliding window. Currently requires patching
   ``context_compressor.py``; with ``post_compress`` it becomes a 20-line
   subclass.

2. **LCM engine** — could use ``post_compress`` to re-index DAG nodes after
   compaction, or inject summary pointers.

3. **Memory providers** — the existing ``on_pre_compress`` memory hook runs
   *before* compression; ``post_compress`` completes the lifecycle with an
   after-compression hook.

4. **Third-party engines** — any custom ``ContextEngine`` implementation that
   needs to post-process its own output without forking core.

---

## Non-breaking

- The default `post_compress()` is a no-op → all existing engines unaffected.
- `ContextCompressor` behaviour is identical (calls `post_compress` which
  returns messages unchanged by default).
- The ABC method is non-abstract (optional override) → no existing subclasses
  break.

---

## Consumer Usage Example

```python
# plugins/my_compressor.py
from agent.context_compressor import ContextCompressor

class LRUSkillCompressor(ContextCompressor):
    """ContextCompressor that prunes stale skill_view results."""

    SKILL_VIEW_LRU_WINDOW: int = 3

    def post_compress(self, messages):
        return self._prune_skill_view_results(messages)

    def _prune_skill_view_results(self, messages):
        # ... 4-pass algorithm (see patches/scs-hermes.patch)
```

Then configure in `config.yaml`:
```yaml
context:
  engine: my_compressor.LRUSkillCompressor
```

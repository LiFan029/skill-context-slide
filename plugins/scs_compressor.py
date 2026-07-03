"""
SCS plugin for Hermes Agent — ContextCompressor with LRU skill_view pruning.

Requires: Hermes Agent with ``post_compress`` hook (PR pending).
Without the hook, use the invasive patch at ``patches/scs-hermes.patch``.

Usage in config.yaml:
    context:
        engine: plugins.scs_compressor.SCSCompressor
"""

import json
import logging
from typing import Any, Dict, List

from agent.context_compressor import ContextCompressor

logger = logging.getLogger(__name__)


class SCSCompressor(ContextCompressor):
    """ContextCompressor with LRU sliding window for skill_view results.

    During compression, only the most recent ``SKILL_VIEW_LRU_WINDOW``
    distinct skill_view results survive; older ones are replaced with a
    lightweight stub. Reload on demand is free.
    """

    SKILL_VIEW_LRU_WINDOW: int = 3

    def post_compress(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Prune skill_view tool results outside the LRU window."""
        return self._prune_skill_view_results(messages)

    # ------------------------------------------------------------------
    # 4-pass LRU pruning algorithm
    # ------------------------------------------------------------------

    def _prune_skill_view_results(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Prune skill_view tool results outside the LRU window.

        Keeps the most recent ``SKILL_VIEW_LRU_WINDOW`` distinct skill names
        and replaces their tool-result content with a stub ``[已卸载]``
        JSON payload. Stub (not delete) preserves message role alternation;
        a re-load is a single ``skill_view()`` call, effectively free.
        """
        # Pass 1: collect every skill_view call_id + skill_name + index
        sv_calls: list[tuple[str, str, int]] = []
        for i, msg in enumerate(messages):
            if msg.get("role") != "assistant":
                continue
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                if fn.get("name") != "skill_view":
                    continue
                cid = self._get_tool_call_id(tc)
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                    skill_name = args.get("name", "")
                except (json.JSONDecodeError, TypeError):
                    skill_name = ""
                if cid and skill_name:
                    sv_calls.append((cid, skill_name, i))

        if not sv_calls:
            return messages

        # Pass 2: build LRU window (last N distinct = most recent first)
        if self.SKILL_VIEW_LRU_WINDOW <= 0:
            lru_set: set[str] = set()
        else:
            lru_skills: list[str] = []
            for _cid, skill_name, _idx in reversed(sv_calls):
                if skill_name not in lru_skills:
                    lru_skills.append(skill_name)
                    if len(lru_skills) >= self.SKILL_VIEW_LRU_WINDOW:
                        break
            lru_set = set(lru_skills)

        # Pass 3: find call_ids that fall outside the window
        outside_cids: set[str] = set()
        for cid, skill_name, _idx in sv_calls:
            if skill_name not in lru_set:
                outside_cids.add(cid)

        if not outside_cids:
            return messages

        # Pass 4: replace the tool-result content with a stub
        n_pruned = 0
        patched: list[Dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "tool" and msg.get("tool_call_id") in outside_cids:
                orig = msg.get("content", "")
                stub_name = "unknown"
                try:
                    stub_name = json.loads(orig).get("name", "unknown")
                except (json.JSONDecodeError, TypeError):
                    pass
                patched.append({
                    "role": "tool",
                    "tool_call_id": msg["tool_call_id"],
                    "content": json.dumps({
                        "success": True,
                        "name": stub_name,
                        "content": "[已卸载]",
                    }),
                })
                n_pruned += 1
            else:
                patched.append(msg)

        if n_pruned and not self.quiet_mode:
            logger.info("Pruned %d skill_view tool result(s) outside LRU window", n_pruned)

        return patched

"""Tests for skill_view LRU window pruning in context compression.

``_prune_skill_view_results`` runs inside ``compress()`` after
``_sanitize_tool_pairs`` and ``_strip_historical_media``.  These tests exercise
it in isolation over synthetic message lists.
"""

import json

import pytest
from unittest.mock import MagicMock, patch

from agent.context_compressor import ContextCompressor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compressor() -> ContextCompressor:
    with patch("agent.context_compressor.get_model_context_length",
               return_value=100000):
        return ContextCompressor(
            model="test/model",
            threshold_percent=0.85,
            protect_first_n=1,
            protect_last_n=1,
            quiet_mode=True,
        )


def _skill_tool_call(skill_name: str, call_id: str) -> dict:
    """Build a single tool-call entry for skill_view."""
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "skill_view",
            "arguments": json.dumps({"name": skill_name}),
        },
    }


def _skill_view_result(skill_name: str, call_id: str,
                       content: str = "FULL_SKILL_CONTENT_XXXX") -> dict:
    """Build a tool-role message that is the result of a skill_view call."""
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps({"success": True, "name": skill_name,
                               "content": content}),
    }


def _assistant_with_tool_calls(tool_calls: list[dict],
                                reply: str = "") -> dict:
    """Assistant message that issued tool_calls."""
    return {
        "role": "assistant",
        "content": reply,
        "tool_calls": tool_calls,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSkillViewLRUPruning:

    def test_empty_messages_unchanged(self):
        """No messages → no-op."""
        c = _compressor()
        assert c._prune_skill_view_results([]) == []

    def test_no_skill_view_calls_unchanged(self):
        """No skill_view tool_calls → no-op."""
        c = _compressor()
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        assert c._prune_skill_view_results(msgs) == msgs

    def test_single_skill_is_kept(self):
        """1 skill → kept (within window of 3)."""
        c = _compressor()
        msgs = [
            _assistant_with_tool_calls([_skill_tool_call("stock", "call_1")]),
            _skill_view_result("stock", "call_1"),
        ]
        result = c._prune_skill_view_results(msgs)
        # The skill_view result should NOT be pruned
        content = json.loads(result[1]["content"])
        assert content["content"] == "FULL_SKILL_CONTENT_XXXX"

    def test_four_skills_only_last_three_survive(self):
        """4 skills → only the last 3 distinct survive."""
        c = _compressor()
        msgs = [
            # Round 1: stock
            _assistant_with_tool_calls(
                [_skill_tool_call("stock", "call_1")], "stock data"),
            _skill_view_result("stock", "call_1", content="STOCK_MD"),
            # Round 2: TRPG
            _assistant_with_tool_calls(
                [_skill_tool_call("trpg", "call_2")], "trpg rules"),
            _skill_view_result("trpg", "call_2", content="TRPG_MD"),
            # Round 3: devops
            _assistant_with_tool_calls(
                [_skill_tool_call("devops", "call_3")], "devops cmds"),
            _skill_view_result("devops", "call_3", content="DEVOPS_MD"),
            # Round 4: creative
            _assistant_with_tool_calls(
                [_skill_tool_call("creative", "call_4")], "creative stuff"),
            _skill_view_result("creative", "call_4", content="CREATIVE_MD"),
            # Final user question
            {"role": "user", "content": "what's next?"},
        ]
        result = c._prune_skill_view_results(msgs)

        # Extract final content from each tool result
        survivals = {}
        for msg in result:
            if msg.get("role") == "tool":
                c_json = json.loads(msg["content"])
                survivals[c_json["name"]] = c_json["content"]

        # stock should be pruned (window of 3: creative, devops, trpg)
        assert survivals["stock"] == "[已卸载]", \
            "stock should have been pruned"
        # The last 3 should survive intact
        assert survivals["trpg"] == "TRPG_MD"
        assert survivals["devops"] == "DEVOPS_MD"
        assert survivals["creative"] == "CREATIVE_MD"

    def test_same_skill_reused_only_counts_once(self):
        """Loading the same skill 3 times → still counts as 1 in LRU."""
        c = _compressor()
        msgs = [
            # stock loaded twice (should count once in LRU)
            _assistant_with_tool_calls(
                [_skill_tool_call("stock", "call_1")], "stock a"),
            _skill_view_result("stock", "call_1", content="STOCK_A"),
            _assistant_with_tool_calls(
                [_skill_tool_call("stock", "call_2")], "stock b"),
            _skill_view_result("stock", "call_2", content="STOCK_B"),
            # Then 3 other distinct skills
            _assistant_with_tool_calls(
                [_skill_tool_call("trpg", "call_3")], "trpg"),
            _skill_view_result("trpg", "call_3", content="TRPG_MD"),
            _assistant_with_tool_calls(
                [_skill_tool_call("devops", "call_4")], "devops"),
            _skill_view_result("devops", "call_4", content="DEVOPS_MD"),
            _assistant_with_tool_calls(
                [_skill_tool_call("creative", "call_5")], "creative"),
            _skill_view_result("creative", "call_5", content="CREATIVE_MD"),
        ]
        result = c._prune_skill_view_results(msgs)

        survivals = {}
        for msg in result:
            if msg.get("role") == "tool":
                c_json = json.loads(msg["content"])
                survivals[c_json["name"]] = c_json["content"]

        # LRU window = creative, devops, trpg (3 distinct's).
        # stock appears only twice (both instances counted once in LRU).
        # Since stock < window, it should be pruned.
        # But wait, stock was loaded before trpg, devops, creative.
        # LRU from most recent: creative, devops, trpg → stock outside.
        assert survivals["stock"] == "[已卸载]"
        assert survivals["stock"] == "[已卸载]"
        assert survivals["trpg"] == "TRPG_MD"
        assert survivals["devops"] == "DEVOPS_MD"
        assert survivals["creative"] == "CREATIVE_MD"

    def test_message_role_alternation_preserved(self):
        """Stub replace must not change number of messages."""
        c = _compressor()
        msgs = [
            _assistant_with_tool_calls(
                [_skill_tool_call("stock", "call_1")], "stock"),
            _skill_view_result("stock", "call_1", content="STOCK_MD"),
            _assistant_with_tool_calls(
                [_skill_tool_call("trpg", "call_2")], "trpg"),
            _skill_view_result("trpg", "call_2", content="TRPG_MD"),
            _assistant_with_tool_calls(
                [_skill_tool_call("devops", "call_3")], "devops"),
            _skill_view_result("devops", "call_3", content="DEVOPS_MD"),
            _assistant_with_tool_calls(
                [_skill_tool_call("creative", "call_4")], "creative"),
            _skill_view_result("creative", "call_4", content="CREATIVE_MD"),
        ]
        result = c._prune_skill_view_results(msgs)
        assert len(result) == len(msgs), \
            f"Message count changed: {len(result)} vs {len(msgs)}"

    # ------------------------------------------------------------------
    # Edge case tests
    # ------------------------------------------------------------------

    def test_batch_skill_view_in_one_assistant_message(self):
        """Multiple skill_view calls in one assistant message."""
        c = _compressor()
        msgs = [
            _assistant_with_tool_calls([
                _skill_tool_call("stock", "call_1"),
                _skill_tool_call("trpg", "call_2"),
            ], "loading multiple"),
            _skill_view_result("stock", "call_1", content="STOCK_MD"),
            _skill_view_result("trpg", "call_2", content="TRPG_MD"),
        ]
        result = c._prune_skill_view_results(msgs)
        survivals = {}
        for msg in result:
            if msg.get("role") == "tool":
                c_json = json.loads(msg["content"])
                survivals[c_json["name"]] = c_json["content"]
        # Both within window of 3 — both survive
        assert survivals["stock"] == "STOCK_MD"
        assert survivals["trpg"] == "TRPG_MD"

    def test_mixed_other_tool_unchanged(self):
        """Non-skill_view tool calls must not be affected."""
        c = _compressor()
        msgs = [
            # skill_view calls
            _assistant_with_tool_calls(
                [_skill_tool_call("stock", "call_1")], "stock"),
            _skill_view_result("stock", "call_1", content="STOCK_MD"),
            _assistant_with_tool_calls(
                [_skill_tool_call("trpg", "call_2")], "trpg"),
            _skill_view_result("trpg", "call_2", content="TRPG_MD"),
            _assistant_with_tool_calls(
                [_skill_tool_call("devops", "call_3")], "devops"),
            _skill_view_result("devops", "call_3", content="DEVOPS_MD"),
            _assistant_with_tool_calls(
                [_skill_tool_call("creative", "call_4")], "creative"),
            _skill_view_result("creative", "call_4", content="CREATIVE_MD"),
            # A different tool (e.g. web_search) must be untouched
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_5",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": '{"query": "weather"}',
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_5",
                "content": "weather: sunny",
            },
        ]
        result = c._prune_skill_view_results(msgs)
        # web_search result must survive unchanged
        last_tool = result[-1]
        assert last_tool["role"] == "tool"
        assert last_tool["tool_call_id"] == "call_5"
        assert last_tool["content"] == "weather: sunny"

    def test_orphan_tool_call_id_no_crash(self):
        """Tool result with unmatched call_id must not crash."""
        c = _compressor()
        msgs = [
            _assistant_with_tool_calls(
                [_skill_tool_call("stock", "call_1")], "stock"),
            _skill_view_result("stock", "call_1", content="STOCK_MD"),
            # Orphan result with no matching tool_call
            {
                "role": "tool",
                "tool_call_id": "nonexistent",
                "content": json.dumps({"success": True, "name": "ghost",
                                       "content": "GHOST_MD"}),
            },
        ]
        try:
            c._prune_skill_view_results(msgs)
        except Exception as e:
            pytest.fail(f"Orphan call_id caused exception: {e}")

    def test_window_size_zero_evicts_all(self):
        """SKILL_VIEW_LRU_WINDOW=0 → all skill_view results pruned."""
        c = _compressor()
        c.SKILL_VIEW_LRU_WINDOW = 0
        msgs = [
            _assistant_with_tool_calls(
                [_skill_tool_call("stock", "call_1")], "stock"),
            _skill_view_result("stock", "call_1", content="STOCK_MD"),
        ]
        result = c._prune_skill_view_results(msgs)
        content = json.loads(result[1]["content"])
        assert content["content"] == "[已卸载]", \
            f"Expected '[已卸载]', got '{content['content']}'"

    def test_reload_after_eviction_keeps_new(self):
        """Skill evicted then reloaded → new content stays intact."""
        c = _compressor()
        msgs = [
            # stock evicted
            _assistant_with_tool_calls(
                [_skill_tool_call("stock", "call_1")], "stock"),
            _skill_view_result("stock", "call_1", content="STOCK_MD"),
            _assistant_with_tool_calls(
                [_skill_tool_call("trpg", "call_2")], "trpg"),
            _skill_view_result("trpg", "call_2", content="TRPG_MD"),
            _assistant_with_tool_calls(
                [_skill_tool_call("devops", "call_3")], "devops"),
            _skill_view_result("devops", "call_3", content="DEVOPS_MD"),
            _assistant_with_tool_calls(
                [_skill_tool_call("creative", "call_4")], "creative"),
            _skill_view_result("creative", "call_4", content="CREATIVE_MD"),
            # stock reloaded (now in window again)
            _assistant_with_tool_calls(
                [_skill_tool_call("stock", "call_5")], "stock again"),
            _skill_view_result("stock", "call_5", content="STOCK_MD_V2"),
        ]
        result = c._prune_skill_view_results(msgs)
        survivals = {}
        for msg in result:
            if msg.get("role") == "tool":
                c_json = json.loads(msg["content"])
                survivals[c_json["name"]] = c_json["content"]
        # creative should be evicted (LRU from back: stock, creative, devops → trpg out)
        assert survivals["stock"] == "STOCK_MD_V2", \
            "Reloaded stock content must be kept"
        assert survivals["creative"] == "CREATIVE_MD"
        assert survivals["devops"] == "DEVOPS_MD"
        assert survivals["trpg"] == "[已卸载]", \
            "trpg is 4th distinct from back → evicted"

#!/usr/bin/env python3
"""
revert.py — Revert SCS (Skill-Context-Slide) changes from Hermes Agent.

Removes the three modifications that SCS makes to
``agent/context_compressor.py``:

  1. The ``SKILL_VIEW_LRU_WINDOW`` class constant
  2. The ``_prune_skill_view_results()`` method
  3. The call to it inside ``compress()``
  4. The modified Pass 2 LRU-building block

Usage:
    python revert.py                          # auto-detect Hermes path
    python revert.py --hermes-path /path/to/hermes-agent
    python revert.py --dry-run                 # preview only, no changes
    python revert.py --backup                  # create .bak before reverting

Exit codes:
    0  — reverted successfully (or nothing to revert)
    1  — file not found or not patched
    2  — write error
"""

import argparse
import os
import shutil
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Markers that identify each SCS change — exact strings from the patched file.
# The revert script finds these and removes/reverts them.
# ---------------------------------------------------------------------------

# Change 1: call site inside compress() — delete both lines + blank
_CALL_SITE_MARKER = (
    '        # Phase 5: Prune skill_view tool results outside the LRU window\n'
    '        compressed = self._prune_skill_view_results(compressed)\n'
    '\n'
)

# Change 2: the Pass 2 block (we added the ≤0 guard) — replace with original
_NEW_PASS2 = (
    '        # Pass 2: build LRU window (last N distinct = most recent first)\n'
    '        if self.SKILL_VIEW_LRU_WINDOW <= 0:\n'
    '            lru_set: set[str] = set()  # window=0 or negative → evict all\n'
    '        else:\n'
    '            lru_skills: list[str] = []\n'
    '            for _cid, skill_name, _idx in reversed(sv_calls):\n'
    '                if skill_name not in lru_skills:\n'
    '                    lru_skills.append(skill_name)\n'
    '                    if len(lru_skills) >= self.SKILL_VIEW_LRU_WINDOW:\n'
    '                        break\n'
    '            lru_set = set(lru_skills)\n'
)

_ORIG_PASS2 = (
    '        # Pass 2: build LRU window (last N distinct = most recent first)\n'
    '        lru_skills: list[str] = []\n'
    '        for _cid, skill_name, _idx in reversed(sv_calls):\n'
    '            if skill_name not in lru_skills:\n'
    '                lru_skills.append(skill_name)\n'
    '                if len(lru_skills) >= self.SKILL_VIEW_LRU_WINDOW:\n'
    '                    break\n'
    '        lru_set: set[str] = set(lru_skills)\n'
)

# Change 3: the whole method + constant — from comment separator to return
_METHOD_MARKER = (
    '    # ------------------------------------------------------------------\n'
    '\n'
    '    SKILL_VIEW_LRU_WINDOW: int = 3\n'
    '\n'
    '    def _prune_skill_view_results(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:\n'
)

_METHOD_END = '        return patched\n'

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def _hermes_default_paths():
    """Common places Hermes Agent might be installed."""
    return [
        Path.cwd(),
        Path.cwd() / "hermes-agent",
        Path.home() / ".hermes" / "hermes-agent",
        Path.home() / "hermes-agent",
        Path("/opt/hermes-agent"),
    ]


def find_compressor(hermes_path: Path | None) -> Path | None:
    """Locate ``agent/context_compressor.py`` under *hermes_path*."""
    candidates = [Path(hermes_path)] if hermes_path else _hermes_default_paths()
    for base in candidates:
        p = base / "agent" / "context_compressor.py"
        if p.is_file():
            return p
    return None


def is_patched(filepath: Path) -> bool:
    """Return True if the file contains SCS changes."""
    try:
        content = filepath.read_text(encoding="utf-8")
        return ("_prune_skill_view_results" in content
                and "SKILL_VIEW_LRU_WINDOW" in content)
    except Exception:
        return False


def _count_occurrences(text: str, needle: str) -> int:
    """Number of non-overlapping occurrences of *needle* in *text*."""
    return text.count(needle)


# ---------------------------------------------------------------------------
# Revert logic
# ---------------------------------------------------------------------------

def revert(filepath: Path, dry_run: bool = False, backup: bool = False) -> int:
    """Apply all revert operations. Return number of changes made."""
    original = filepath.read_text(encoding="utf-8")
    current = original
    changes = 0

    # --- Change A: Remove call site ---
    cnt = current.count(_CALL_SITE_MARKER)
    if cnt == 0:
        print("  [SKIP] call site not found (already reverted?)")
    elif cnt > 1:
        print(f"  [WARN] call site appears {cnt} times — ambiguous, skipping")
    else:
        current = current.replace(_CALL_SITE_MARKER, "", 1)
        print("  [OK]   removed call site in compress()")
        changes += 1

    # --- Change B: Restore original Pass 2 block ---
    cnt = current.count(_NEW_PASS2)
    if cnt == 0:
        print("  [SKIP] modified Pass 2 block not found (already reverted?)")
    elif cnt > 1:
        print(f"  [WARN] modified Pass 2 block appears {cnt} times — ambiguous, skipping")
    else:
        current = current.replace(_NEW_PASS2, _ORIG_PASS2, 1)
        print("  [OK]   restored original Pass 2 LRU-building block")
        changes += 1

    # --- Change C: Remove method body ---
    start_idx = current.find(_METHOD_MARKER)
    if start_idx == -1:
        print("  [SKIP] method marker not found (already reverted?)")
    else:
        # Find the end — scan from start_idx for the return statement line
        search_from = start_idx + len(_METHOD_MARKER)
        end_idx = current.find("\n" + _METHOD_END, search_from)
        if end_idx == -1:
            print("  [WARN] method start found but cannot find return — manual check needed")
        else:
            # Include the return line + trailing blank line
            method_end = end_idx + 1 + len(_METHOD_END)  # +1 for the \n
            # Consume any trailing blank lines
            while method_end < len(current) and current[method_end] in ('\n', '\r'):
                method_end += 1
            removed = current[start_idx:method_end]
            current = current[:start_idx] + current[method_end:]
            print(f"  [OK]   removed method & constant ({len(removed)} chars)")
            changes += 1

    if changes == 0:
        print("  Nothing to revert — file appears clean.")
        return 0

    if dry_run:
        print(f"\n  [DRY-RUN] Would apply {changes} change(s). File NOT modified.")
        return 0

    # Write backup if requested
    if backup:
        bak_path = filepath.with_suffix(".py.bak.scs")
        shutil.copy2(filepath, bak_path)
        print(f"  [BACKUP] saved to {bak_path}")

    # Write new content
    filepath.write_text(current, encoding="utf-8")
    print(f"\n  ✅ Reverted {changes} change(s) in {filepath}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Revert SCS (Skill-Context-Slide) patches from Hermes Agent",
    )
    ap.add_argument("--hermes-path", "-p", type=str, default=None,
                    help="Path to Hermes Agent root (auto-detected if omitted)")
    ap.add_argument("--dry-run", "-n", action="store_true",
                    help="Preview changes without modifying the file")
    ap.add_argument("--backup", "-b", action="store_true",
                    help="Create .bak.scs backup before reverting")
    args = ap.parse_args()

    hermes_path = Path(args.hermes_path) if args.hermes_path else None
    filepath = find_compressor(hermes_path)

    if not filepath:
        print("ERROR: agent/context_compressor.py not found.", file=sys.stderr)
        if not hermes_path:
            print("      Tried:", file=sys.stderr)
            for p in _hermes_default_paths():
                print(f"        {p / 'agent' / 'context_compressor.py'}", file=sys.stderr)
        else:
            print(f"      Tried: {hermes_path / 'agent' / 'context_compressor.py'}", file=sys.stderr)
        sys.exit(1)

    print(f"Found: {filepath}")

    if not is_patched(filepath):
        print("  File does not contain SCS patches — nothing to revert.")
        sys.exit(0)

    try:
        rc = revert(filepath, dry_run=args.dry_run, backup=args.backup)
    except PermissionError:
        print(f"ERROR: Permission denied writing {filepath}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    sys.exit(rc)


if __name__ == "__main__":
    main()

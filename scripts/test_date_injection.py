"""
Ani Zeo — Date Injection Test
==============================
Tests that build_system_prompt() injects the current date into every AI
system prompt at runtime.

  No Telegram.  No bot.  No AI calls.  No network.

Run:
    python scripts/test_date_injection.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from unittest.mock import patch

# ── Bootstrap path so we can run from project root ────────────────────────────
sys.path.insert(0, ".")

from ai.prompts import SYSTEM_PROMPT, build_system_prompt

# ── Test harness ──────────────────────────────────────────────────────────────

_passed = 0
_failed = 0


def _ok(label: str) -> None:
    global _passed
    _passed += 1
    print(f"  PASS \u2713  {label}")


def _fail(label: str, detail: str = "") -> None:
    global _failed
    _failed += 1
    msg = f"  FAIL \u2717  {label}"
    if detail:
        msg += f"\n         {detail}"
    print(msg)


def _section(title: str) -> None:
    print(f"\n{'─' * 90}")
    print(f"  {title}")
    print(f"{'─' * 90}")


# ── A — build_system_prompt() returns a string ────────────────────────────────

_section("A — build_system_prompt() basic contract")

result = build_system_prompt()

if isinstance(result, str):
    _ok("returns a string")
else:
    _fail("returns a string", f"got {type(result)}")

if result:
    _ok("string is non-empty")
else:
    _fail("string is non-empty")

if SYSTEM_PROMPT in result:
    _ok("SYSTEM_PROMPT content preserved verbatim")
else:
    _fail("SYSTEM_PROMPT content preserved verbatim")

if len(result) > len(SYSTEM_PROMPT):
    _ok("date block added (result longer than bare SYSTEM_PROMPT)")
else:
    _fail("date block added (result longer than bare SYSTEM_PROMPT)",
          f"len(result)={len(result)}, len(SYSTEM_PROMPT)={len(SYSTEM_PROMPT)}")

# ── B — date values match current date ────────────────────────────────────────

_section("B — date values match current datetime")

now = datetime.now()

if str(now.year) in result:
    _ok(f"current year {now.year} present")
else:
    _fail(f"current year {now.year} present", "not found in system prompt")

month_name = now.strftime("%B")
if month_name in result:
    _ok(f"current month name '{month_name}' present")
else:
    _fail(f"current month name '{month_name}' present")

day_str = str(now.day)
if day_str in result:
    _ok(f"current day '{day_str}' present")
else:
    _fail(f"current day '{day_str}' present")

weekday_name = now.strftime("%A")
if weekday_name in result:
    _ok(f"current weekday '{weekday_name}' present")
else:
    _fail(f"current weekday '{weekday_name}' present")

# ── C — date is injected dynamically (not hardcoded) ─────────────────────────

_section("C — date is generated dynamically at call time")

FAKE_DATE = datetime(2099, 12, 31)

with patch("ai.prompts.datetime") as mock_dt:
    mock_dt.now.return_value = FAKE_DATE
    patched_result = build_system_prompt()

if "2099" in patched_result:
    _ok("mocked year 2099 appears in patched result")
else:
    _fail("mocked year 2099 appears in patched result",
          "date appears to be hardcoded or not using datetime.now()")

if "December" in patched_result:
    _ok("mocked month 'December' appears in patched result")
else:
    _fail("mocked month 'December' appears in patched result")

if "31" in patched_result:
    _ok("mocked day '31' appears in patched result")
else:
    _fail("mocked day '31' appears in patched result")

if str(now.year) not in patched_result.split(SYSTEM_PROMPT)[-1]:
    _ok("real year absent from patched result (not a static string)")
else:
    _fail("real year absent from patched result (not a static string)",
          "the date block still contains the real year when mocked")

# ── D — each call generates a fresh date ─────────────────────────────────────

_section("D — two consecutive calls both embed a date")

call1 = build_system_prompt()
call2 = build_system_prompt()

if str(datetime.now().year) in call1 and str(datetime.now().year) in call2:
    _ok("both calls embed current year")
else:
    _fail("both calls embed current year")

if SYSTEM_PROMPT in call1 and SYSTEM_PROMPT in call2:
    _ok("both calls preserve SYSTEM_PROMPT")
else:
    _fail("both calls preserve SYSTEM_PROMPT")

# ── E — message_handler imports build_system_prompt ──────────────────────────

_section("E — message_handler.py uses build_system_prompt")

import importlib, ast, pathlib

src = pathlib.Path("ai/message_handler.py").read_text()
tree = ast.parse(src)

imports_it = False
for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom):
        if node.module == "ai.prompts":
            names = [alias.name for alias in node.names]
            if "build_system_prompt" in names:
                imports_it = True

if imports_it:
    _ok("ai/message_handler.py imports build_system_prompt from ai.prompts")
else:
    _fail("ai/message_handler.py imports build_system_prompt from ai.prompts")

uses_it = "build_system_prompt" in src
if uses_it:
    _ok("ai/message_handler.py calls build_system_prompt()")
else:
    _fail("ai/message_handler.py calls build_system_prompt()")

bare_prompt_return = "return SYSTEM_PROMPT + context_block" in src
if not bare_prompt_return:
    _ok("bare 'SYSTEM_PROMPT + context_block' return replaced")
else:
    _fail("bare 'SYSTEM_PROMPT + context_block' return replaced",
          "date is not injected into the context path")

# ── F — date block appears before context block ───────────────────────────────

_section("F — date block position in prompt")

# Build with a known context suffix to verify ordering
date_pos = result.find(str(now.year))
sys_end  = len(SYSTEM_PROMPT)

if date_pos >= sys_end:
    _ok("date block comes after SYSTEM_PROMPT body (not prepended before it)")
else:
    _fail("date block comes after SYSTEM_PROMPT body",
          f"date found at pos {date_pos}, SYSTEM_PROMPT ends at {sys_end}")

# ── Summary ───────────────────────────────────────────────────────────────────

total = _passed + _failed
print(f"\n{'=' * 90}")
if _failed == 0:
    print(f"  {total}/{total} passed — all tests passed \u2713")
else:
    print(f"  {_passed}/{total} passed — {_failed} FAILED \u2717")
print(f"{'=' * 90}\n")

sys.exit(0 if _failed == 0 else 1)

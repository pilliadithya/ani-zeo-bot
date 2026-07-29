"""
test_fallback.py — Fallback chain smoke test for Ani Zeo.

What it tests
─────────────
1. Configuration check  — which providers have API keys set
2. Individual providers — call each configured provider directly
3. Fallback simulation  — disable Gemini via ProviderHealth, confirm the
                          router falls through to the next live provider
4. Full chain           — run a real route() call and show which provider
                          actually answered

Run:
    python scripts/test_fallback.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

# ── Path fix so imports resolve from project root ─────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.ai_config import PROVIDER_PRIORITY, PROVIDER_MODELS
from ai.router import AIRouter, PROVIDER_REGISTRY
from ai.providers.base_provider import ERR_PERMANENT

PROMPT = "Reply with exactly one sentence: confirm you are working."

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}✓{RESET} {msg}")
def fail(msg): print(f"  {RED}✗{RESET} {msg}")
def info(msg): print(f"  {YELLOW}→{RESET} {msg}")
def head(msg): print(f"\n{CYAN}{'─'*60}{RESET}\n{CYAN}{msg}{RESET}\n{'─'*60}")


# ── 1. Configuration check ────────────────────────────────────────────────────

def test_configuration():
    head("1 · Configuration — API keys present?")
    key_map = {
        "gemini":     "GEMINI_API_KEY",
        "groq":       "GROQ_API_KEY",
        "nvidia_nim": "NVIDIA_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }
    results = {}
    for name, env_var in key_map.items():
        present = bool(os.environ.get(env_var))
        in_chain = name in PROVIDER_PRIORITY
        model = PROVIDER_MODELS.get(name, "—")
        tag = "[chain]" if in_chain else "[manual]"
        if present:
            ok(f"{name:<12} {tag}  key=SET   model={model}")
        else:
            info(f"{name:<12} {tag}  key=MISSING (will be skipped)")
        results[name] = present
    return results


# ── 2. Individual provider calls ──────────────────────────────────────────────

async def test_individual_providers(configured: dict[str, bool]):
    head("2 · Individual providers — direct call to each")
    results = {}
    for name in PROVIDER_REGISTRY:
        if not configured.get(name):
            info(f"{name:<12} skipped (no API key)")
            results[name] = None
            continue

        router = AIRouter()
        t0 = time.monotonic()
        try:
            response = await asyncio.wait_for(
                router.route(PROMPT, provider=name),
                timeout=30,
            )
            elapsed = (time.monotonic() - t0) * 1000
            if response.success:
                snippet = response.text[:80].replace("\n", " ")
                ok(f"{name:<12} {elapsed:.0f}ms — \"{snippet}\"")
                results[name] = True
            else:
                fail(f"{name:<12} returned success=False — {response.error}")
                results[name] = False
        except asyncio.TimeoutError:
            fail(f"{name:<12} timed out after 30 s")
            results[name] = False
        except Exception as exc:
            fail(f"{name:<12} exception: {exc}")
            results[name] = False
    return results


# ── 3. Fallback simulation ────────────────────────────────────────────────────

async def test_fallback_simulation():
    head("3 · Fallback simulation — disable Gemini, expect next provider")
    router = AIRouter()

    # Disable Gemini permanently so the router skips it immediately
    router._health.mark_failed("gemini", ERR_PERMANENT, "simulated failure for test")
    info("Gemini marked as failed (simulated). Chain is now: " +
         " → ".join(p for p in PROVIDER_PRIORITY if p != "gemini"))

    t0 = time.monotonic()
    response = await router.route(PROMPT)
    elapsed = (time.monotonic() - t0) * 1000

    if response.success:
        ok(f"Got response from '{response.provider}' in {elapsed:.0f}ms")
        snippet = response.text[:80].replace("\n", " ")
        ok(f"Reply: \"{snippet}\"")
        return True
    else:
        fail(f"All fallback providers failed — {response.error}")
        return False


# ── 4. Full chain route() ─────────────────────────────────────────────────────

async def test_full_route():
    head("4 · Full chain — normal route() call (Gemini first)")
    router = AIRouter()
    t0 = time.monotonic()
    response = await router.route(PROMPT)
    elapsed = (time.monotonic() - t0) * 1000

    if response.success:
        ok(f"Provider used: {response.provider}  ({elapsed:.0f}ms)")
        ok(f"Model:         {response.model}")
        snippet = response.text[:120].replace("\n", " ")
        ok(f"Reply:         \"{snippet}\"")
    else:
        fail(f"route() failed — {response.error}")
    return response.success


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    print(f"\n{CYAN}Ani Zeo — Fallback Chain Test{RESET}")
    print(f"Priority chain: {' → '.join(PROVIDER_PRIORITY)}\n")

    configured   = test_configuration()
    ind_results  = await test_individual_providers(configured)
    fallback_ok  = await test_fallback_simulation()
    route_ok     = await test_full_route()

    head("Summary")
    passed = 0
    total  = 0

    # Individual
    for name, result in ind_results.items():
        if result is None:
            continue
        total += 1
        if result:
            ok(f"Individual / {name}")
            passed += 1
        else:
            fail(f"Individual / {name}")

    # Fallback sim
    total += 1
    if fallback_ok:
        ok("Fallback simulation")
        passed += 1
    else:
        fail("Fallback simulation")

    # Full route
    total += 1
    if route_ok:
        ok("Full route()")
        passed += 1
    else:
        fail("Full route()")

    print(f"\n  Result: {passed}/{total} passed\n")
    return 0 if passed == total else 1


if __name__ == "__main__":
    exit(asyncio.run(main()))

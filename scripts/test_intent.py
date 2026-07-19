"""
Intent detection test — scripts/test_intent.py

Run from the project root:
    python scripts/test_intent.py

Tests every required display category with representative phrases,
edge cases, and ambiguous inputs.  No external dependencies needed.
"""
from __future__ import annotations

import sys
import os

# Make sure project root is on the path when run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.intent import Intent, IntentClassifier, DISPLAY_NAMES

classifier = IntentClassifier()

# ── Test cases ────────────────────────────────────────────────────────────────
# Each entry: (input_text, expected_display_label)
# The 12 required display categories are exercised below.

TEST_CASES: list[tuple[str, str]] = [

    # ── Anime Recommendation ──────────────────────────────────────────────────
    ("recommend me some good anime",         "Anime Recommendation"),
    ("suggest anime similar to Attack on Titan", "Anime Recommendation"),
    ("what should I watch next?",            "Anime Recommendation"),
    ("anime like Naruto",                    "Anime Recommendation"),

    # ── Anime Information ─────────────────────────────────────────────────────
    ("search for Demon Slayer",              "Anime Information"),
    ("find anime about samurai",             "Anime Information"),
    ("tell me about One Piece",              "Anime Information"),
    ("what is Fullmetal Alchemist?",         "Anime Information"),
    ("best anime of all time",               "Anime Information"),
    ("top anime list",                       "Anime Information"),
    ("is there a dub for Jujutsu Kaisen?",   "Anime Information"),
    ("English dubbed version of Re:Zero",    "Anime Information"),

    # ── Character Information ─────────────────────────────────────────────────
    ("who is Gojo Satoru?",                  "Character Information"),
    ("tell me about the protagonist of AOT", "Character Information"),
    ("voice actor for Naruto",               "Character Information"),
    ("who is the antagonist in Death Note?", "Character Information"),

    # ── Manga Information ─────────────────────────────────────────────────────
    ("find manga about ninjas",              "Manga Information"),
    ("top manga of all time",                "Manga Information"),
    ("best manga recommendations",           "Manga Information"),
    ("random manga suggestion",              "Manga Information"),
    ("manga genre action",                   "Manga Information"),

    # ── Watch Order ───────────────────────────────────────────────────────────
    ("what is the watch order for Fate?",    "Watch Order"),
    ("where do I start with Gundam?",        "Watch Order"),
    ("which to watch first in Monogatari?",  "Watch Order"),
    ("in what order should I watch Bleach?", "Watch Order"),

    # ── Watchlist ─────────────────────────────────────────────────────────────
    ("add Naruto to my watchlist",           "Watchlist"),
    ("mark One Piece as finished",           "Watchlist"),
    ("show my watchlist",                    "Watchlist"),
    ("I finished watching Steins;Gate",      "Watchlist"),

    # ── Anime News ────────────────────────────────────────────────────────────
    ("latest anime news",                    "Anime News"),
    ("any anime updates this week?",         "Anime News"),
    ("what's new in anime?",                 "Anime News"),
    ("anime news today",                     "Anime News"),

    # ── Seasonal Anime ────────────────────────────────────────────────────────
    ("what anime is airing this season?",    "Seasonal Anime"),
    ("currently airing shows",               "Seasonal Anime"),
    ("what's coming next season?",           "Seasonal Anime"),
    ("upcoming anime 2025",                  "Seasonal Anime"),

    # ── Compare Anime ─────────────────────────────────────────────────────────
    ("compare Naruto vs Bleach",             "Compare Anime"),
    ("Death Note versus Code Geass",         "Compare Anime"),
    ("compare One Piece and HxH",            "Compare Anime"),

    # ── Greeting ──────────────────────────────────────────────────────────────
    ("hi",                                   "Greeting"),
    ("hello",                                "Greeting"),
    ("hey!",                                 "Greeting"),
    ("good morning",                         "Greeting"),
    ("konnichiwa",                           "Greeting"),
    ("yo",                                   "Greeting"),
    ("what's up",                            "Greeting"),

    # ── Help ──────────────────────────────────────────────────────────────────
    ("help",                                 "Help"),
    ("what can you do?",                     "Help"),
    ("show me the commands",                 "Help"),
    ("how do I use this bot?",               "Help"),

    # ── Unknown ───────────────────────────────────────────────────────────────
    ("asdfghjkl",                            "Unknown"),
    ("I like pizza",                         "Unknown"),
    ("the weather is nice today",            "Unknown"),
]

# ── Runner ────────────────────────────────────────────────────────────────────

def run_tests() -> None:
    passed = 0
    failed = 0
    failures: list[str] = []

    col_input   = 45
    col_expected = 24
    col_got      = 24

    header = (
        f"{'INPUT':<{col_input}} "
        f"{'EXPECTED':<{col_expected}} "
        f"{'GOT':<{col_got}} "
        f"RESULT"
    )
    print("=" * len(header))
    print(header)
    print("=" * len(header))

    for text, expected_label in TEST_CASES:
        intent, confidence = classifier.classify_with_confidence(text)
        got_label = classifier.display_name(intent)
        ok = got_label == expected_label
        mark = "✓" if ok else "✗"

        display_text = text if len(text) <= col_input else text[:col_input - 1] + "…"
        print(
            f"{display_text:<{col_input}} "
            f"{expected_label:<{col_expected}} "
            f"{got_label:<{col_got}} "
            f"{mark}"
        )

        if ok:
            passed += 1
        else:
            failed += 1
            failures.append(
                f"  INPUT    : {text!r}\n"
                f"  EXPECTED : {expected_label}\n"
                f"  GOT      : {got_label}  (intent={intent.name}, confidence={confidence})"
            )

    total = passed + failed
    print("=" * len(header))
    print(f"\nResults: {passed}/{total} passed", end="")
    if failed:
        print(f"  |  {failed} failed")
        print("\nFailures:")
        for f in failures:
            print(f)
    else:
        print("  — all tests passed ✓")

    # ── Confidence gate demo ──────────────────────────────────────────────────
    print("\n── Confidence gate (Unknown examples) ─────────────────────────────")
    low_confidence_inputs = ["asdfghjkl", "I like pizza", "the weather is nice today"]
    for t in low_confidence_inputs:
        intent, conf = classifier.classify_with_confidence(t)
        label = classifier.display_name(intent)
        print(f"  {t!r:<40} → {label}  (confidence={conf})")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    run_tests()

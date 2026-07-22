"""
LanguageDetector — runtime detection of Tenglish / Hinglish / Tamilish.

The user's onboarding profile stores their *preferred* language.
This module detects the *actual* language used in each message, which may
differ when users mix languages mid-conversation or haven't updated their
preference after switching.

Detected language takes priority over profile preference when injected into
the AI context, so responses always feel natural to the user's current mode.

Design
──────
- Lightweight: word-set lookup only, no ML, no network calls.
- Conservative: only triggers on unambiguous romanised marker words.
  A single strong marker is sufficient — requires no minimum count.
- Falls back gracefully: returns None when the message is plain English
  or undetectable, leaving the profile language untouched.

Supported modes
───────────────
  "Tenglish"  — Telugu + English romanised mix
  "Hinglish"  — Hindi + English romanised mix
  "Tamilish"  — Tamil + English romanised mix
  None        — English or undetectable

Usage
─────
  from services.language_detector import detect_language
  lang = detect_language("bhai ye naruto kaisa hai yaar")
  # → "Hinglish"
"""
from __future__ import annotations

import re

# ── Marker word sets ──────────────────────────────────────────────────────────
# Only unambiguous romanised words that almost never appear in plain English.
# Avoid short / common English words (e.g. "da", "la", "na") that could
# appear accidentally in anime titles or English sentences.

_TELUGU_MARKERS: frozenset[str] = frozenset({
    # Core vocabulary
    "oka", "chinna", "baaga", "manchidi", "chala", "chesthe",
    "chudu", "cheppu", "thappa", "nijam", "aipoindhi", "vachindha",
    "emiti", "enduku", "ekkadiki", "chusthe", "aipoyindhi",
    # Common colloquials
    "ante", "anthe", "kaadu", "ledhu", "telugulo", "okasari",
    "chaala", "konchem", "ekkado", "ikkade", "akkade", "evaru",
    "mee", "meeru", "nenu", "mana", "vallu", "naaku", "niku",
})

_HINDI_MARKERS: frozenset[str] = frozenset({
    # Core vocabulary
    "bhai", "yaar", "kya", "bohot", "matlab", "bilkul",
    "accha", "mast", "ekdum", "toh", "kaisa", "kaisi",
    "nahi", "haan", "tha", "aur", "bhi", "sirf",
    # Common colloquials
    "abhi", "phir", "lekin", "kyun", "kuch", "sab",
    "dekho", "suno", "batao", "samajh", "dhakad", "bindaas",
    "gazab", "zabardast", "kamaal", "bekar", "mera", "tera",
    "yeh", "woh", "iska", "uska", "tum", "hum", "apna",
    "dono", "bahut", "thoda", "poora", "kab", "kidhar",
})

_TAMIL_MARKERS: frozenset[str] = frozenset({
    # Core vocabulary
    "machan", "machi", "romba", "seri", "enna", "epdi",
    "theriyum", "mokka", "illaya", "thambi", "akka",
    # Common colloquials
    "paaru", "sollu", "theriyuma", "puriyuma", "puriyudhu",
    "onnum", "ellam", "konjam", "theriyadhu", "varuma",
    "poguma", "nadakudhu", "pannuvom", "paakalaam", "parkalaam",
    "romba", "idhuku", "adhuku", "avanga", "ivanga",
    "naan", "nee", "neenga", "avan", "aval", "avar",
})

# ── Tokeniser ─────────────────────────────────────────────────────────────────

_WORD_RE = re.compile(r"\b[a-z]+\b")


def detect_language(text: str) -> str | None:
    """
    Detect the romanised Indian language used in *text*.

    Returns
    -------
    "Tenglish" | "Hinglish" | "Tamilish" | None

    None means the message is plain English or the language could not
    be determined with confidence.  Callers should keep the profile
    language unchanged when None is returned.

    Algorithm
    ---------
    1. Tokenise the text into lowercase words.
    2. Score each language by counting its marker words present in the text.
    3. Return the highest-scoring language if its score ≥ 1.
    4. On a tie, pick the one whose markers appeared first in the text.
    """
    if not text or not text.strip():
        return None

    words = set(_WORD_RE.findall(text.lower()))

    te_score = len(words & _TELUGU_MARKERS)
    hi_score = len(words & _HINDI_MARKERS)
    ta_score = len(words & _TAMIL_MARKERS)

    best = max(te_score, hi_score, ta_score)
    if best == 0:
        return None

    if hi_score == best:
        return "Hinglish"
    if te_score == best:
        return "Tenglish"
    return "Tamilish"


def describe(text: str) -> dict:
    """
    Debug helper — returns all scores and the detected language.
    Not called in production; useful for unit tests.
    """
    words = set(_WORD_RE.findall(text.lower()))
    return {
        "telugu_score": len(words & _TELUGU_MARKERS),
        "hindi_score":  len(words & _HINDI_MARKERS),
        "tamil_score":  len(words & _TAMIL_MARKERS),
        "detected":     detect_language(text),
        "markers_found": {
            "telugu": sorted(words & _TELUGU_MARKERS),
            "hindi":  sorted(words & _HINDI_MARKERS),
            "tamil":  sorted(words & _TAMIL_MARKERS),
        },
    }

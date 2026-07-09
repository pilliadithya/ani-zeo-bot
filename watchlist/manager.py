"""
WatchlistManager — business logic for all watchlist operations.

Depends only on WatchlistStore (injected), so storage can be swapped without
touching this file.  Every mutating method returns (success: bool, message: str)
so callers can forward the message to the user without knowing storage details.
"""
from __future__ import annotations

from watchlist.store import WatchlistStore, VALID_STATUSES

STATUS_LABELS: dict[str, str] = {
    "watching":  "📺 Watching",
    "completed": "✅ Completed",
    "planned":   "📝 Planned",
    "dropped":   "❌ Dropped",
}


class WatchlistManager:
    """
    Manages add / remove / mark / show operations for a user's watchlist.

    Usage:
        mgr = WatchlistManager()
        ok, msg = mgr.add(user_id=123, anime="Naruto", status="planned")
    """

    def __init__(self, store: WatchlistStore | None = None) -> None:
        self._store = store or WatchlistStore()

    # ── Public operations ──────────────────────────────────────────────────────

    def add(
        self,
        user_id: int,
        anime: str,
        status: str = "planned",
    ) -> tuple[bool, str]:
        """
        Add anime to the user's watchlist.

        Returns (False, message) if the anime is already present anywhere,
        suggesting how to move it instead.
        """
        status = normalise_status(status)
        user_data = self._store.load(user_id)

        # Duplicate check — case-insensitive across all statuses
        for s in VALID_STATUSES:
            for existing in user_data[s]:
                if existing.lower() == anime.lower():
                    if s == status:
                        return False, (
                            f"*{existing}* is already in your "
                            f"{STATUS_LABELS[s]} list."
                        )
                    return False, (
                        f"*{existing}* is already in your "
                        f"{STATUS_LABELS[s]} list.\n"
                        f"Say _Mark {existing} as {status}_ to move it."
                    )

        user_data[status].append(anime)
        self._store.save(user_id, user_data)
        return True, f"Added *{anime}* to {STATUS_LABELS[status]}. ✓"

    def remove(self, user_id: int, anime: str) -> tuple[bool, str]:
        """Remove anime from the user's watchlist regardless of its current status."""
        user_data = self._store.load(user_id)
        for s in VALID_STATUSES:
            for existing in list(user_data[s]):
                if existing.lower() == anime.lower():
                    user_data[s].remove(existing)
                    self._store.save(user_id, user_data)
                    return True, f"Removed *{existing}* from {STATUS_LABELS[s]}. ✓"
        return False, f"*{anime}* wasn't found in your watchlist."

    def update_status(
        self,
        user_id: int,
        anime: str,
        new_status: str,
    ) -> tuple[bool, str]:
        """
        Move anime to a different status bucket.

        If the anime isn't on the watchlist yet, adds it directly.
        """
        new_status = normalise_status(new_status)
        user_data = self._store.load(user_id)

        found_title: str | None = None
        old_status: str | None = None
        for s in VALID_STATUSES:
            for existing in list(user_data[s]):
                if existing.lower() == anime.lower():
                    user_data[s].remove(existing)
                    found_title = existing
                    old_status = s
                    break
            if found_title:
                break

        title = found_title or anime
        user_data[new_status].append(title)
        self._store.save(user_id, user_data)

        if found_title and old_status and old_status != new_status:
            return True, (
                f"Moved *{title}* from {STATUS_LABELS[old_status]} "
                f"to {STATUS_LABELS[new_status]}. ✓"
            )
        return True, f"*{title}* marked as {STATUS_LABELS[new_status]}. ✓"

    def show(self, user_id: int) -> str:
        """Return a formatted Markdown string of the user's full watchlist."""
        user_data = self._store.load(user_id)
        total = sum(len(v) for v in user_data.values())

        if total == 0:
            return (
                "Your watchlist is empty!\n\n"
                "Try:\n"
                "• _Add Naruto to my watchlist_\n"
                "• _I finished Attack on Titan_\n"
                "• _I'm watching One Piece_"
            )

        lines = ["📋 *Your Watchlist*\n"]
        for status, label in STATUS_LABELS.items():
            entries = user_data.get(status, [])
            if not entries:
                continue
            lines.append(f"{label} ({len(entries)})")
            for e in entries[:10]:
                lines.append(f"  • {e}")
            if len(entries) > 10:
                lines.append(f"  … and {len(entries) - 10} more")
            lines.append("")

        return "\n".join(lines).rstrip()

    def show_by_status(self, user_id: int, status: str) -> str:
        """Return a formatted list for a single status bucket."""
        status = normalise_status(status)
        user_data = self._store.load(user_id)
        entries = user_data.get(status, [])
        label = STATUS_LABELS.get(status, status.title())

        if not entries:
            return f"{label}: Nothing here yet."

        lines = [f"{label} ({len(entries)})\n"]
        for i, e in enumerate(entries, 1):
            lines.append(f"{i}. {e}")
        return "\n".join(lines)


# ── Helpers ────────────────────────────────────────────────────────────────────

def normalise_status(status: str) -> str:
    """Map common synonyms to one of the four canonical status values."""
    s = status.lower().strip()
    _MAP = {
        "watch": "watching", "watching": "watching",
        "currently watching": "watching",
        "done": "completed", "finished": "completed",
        "complete": "completed", "completed": "completed", "watched": "completed",
        "plan": "planned", "planned": "planned",
        "plan to watch": "planned", "to watch": "planned",
        "want to watch": "planned",
        "drop": "dropped", "dropped": "dropped",
    }
    return _MAP.get(s, "planned" if s not in VALID_STATUSES else s)

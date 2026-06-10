# ── Game-feel tuning ───────────────────────────────────────────────────
# Default round length in seconds. Tuned for a 4-player lobby: ~2 minutes
# keeps real pressure on the murderer while leaving innocents a fighting
# chance to stall out the clock.
DEFAULT_ROUND_SECONDS = 120


class RoundManager:
    """
    Manages the round timer and win-condition checking.

    Win conditions (checked every frame):
      - "murderer"   → all non-Murderer players are dead (and the Murderer lives)
      - "innocents"  → the Murderer is dead
      - "innocents"  → timer reaches 0 and at least one non-Murderer is alive
      - None         → round is still in progress

    Edge case — everyone dies on the same frame (e.g. the sheriff's bullet
    lands as the murderer stabs the last innocent): the murderer is dead,
    so the innocents win the trade. The murderer must SURVIVE to win.
    """

    def __init__(self, duration_seconds=DEFAULT_ROUND_SECONDS):
        """Set the round timer (default DEFAULT_ROUND_SECONDS)."""
        self.total_seconds = duration_seconds
        self.remaining = float(duration_seconds)

    def tick(self, dt):
        """
        Count the timer down by *dt* seconds.

        Args:
            dt: delta time in seconds (usually ~0.016 at 60 FPS)
        """
        self.remaining -= dt
        if self.remaining < 0:
            self.remaining = 0.0

    def check_win_conditions(self, players):
        """
        Evaluate whether the round is over.

        Returns:
            "murderer"  — Murderer killed everyone (and is still alive)
            "innocents" — Murderer is dead, OR timer expired with non-Murderers alive
            None        — round still active
        """
        murderer_alive = any(p.is_alive and p.role == "murderer" for p in players)

        # Anyone still alive who ISN'T the Murderer?
        non_murderer_alive = any(
            p.is_alive and p.role != "murderer" for p in players
        )

        # --- Murderer killed everyone → Murderer wins ---
        if murderer_alive and not non_murderer_alive:
            return "murderer"

        # --- Murderer is dead (covers "everyone dead") → innocents win ---
        if not murderer_alive:
            return "innocents"

        # --- Timer expired with non-Murderer(s) alive → innocents win ---
        if self.remaining <= 0 and non_murderer_alive:
            return "innocents"

        return None

    def get_time_string(self):
        """Return the remaining time as 'M:SS'."""
        m = int(self.remaining // 60)
        s = int(self.remaining % 60)
        return f"{m}:{s:02d}"

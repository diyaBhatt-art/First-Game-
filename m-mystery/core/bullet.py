from core.rect import Rect

# ── Game-feel tuning ───────────────────────────────────────────────────
# Bullet speed in px per frame (~720 px/s at 60 fps). Raised from 8 so the
# sheriff's shot feels snappy. Must stay below ~20 (thinnest wall) so a
# bullet can never tunnel through a wall in a single step.
BULLET_SPEED = 12

# Default map bounds used when the caller doesn't supply any.
DEFAULT_BOUNDS = (0, 0, 800, 600)


class Bullet:
    """
    A projectile fired by a player who has a gun.

    The gun (whether held by the Sheriff or an Innocent who picks it up)
    can ONLY damage a player whose role is "murderer".  It does nothing
    to Innocents or the Sheriff — the bullet harmlessly disappears.
    """

    def __init__(self, x, y, dx, dy, shooter_role, shooter_id=None, shooter_name=None):
        """
        Args:
            x, y: spawn position (centre)
            dx, dy: normalised direction vector
            shooter_role: "murderer", "sheriff", or "innocent" (for tracking origin)
            shooter_id, shooter_name: optional identity of the shooter so
                kills can be attributed to the right player by name.
        """
        self.x = x
        self.y = y
        self.dx = dx
        self.dy = dy
        self.speed = BULLET_SPEED

        # Who fired this bullet (informational — rule is based on the *target's* role)
        self.shooter_role = shooter_role
        self.shooter_id = shooter_id
        self.shooter_name = shooter_name

        self.is_active = True

    def get_rect(self):
        """Small rect for wall-collision checks."""
        return Rect(self.x - 3, self.y - 3, 6, 6)

    def update(self, bounds=None):
        """Move the bullet. Deactivate if it leaves the map.

        Args:
            bounds: optional (x, y, w, h) map bounds; defaults to 800x600
                for backwards compatibility with callers that pass nothing.
        """
        self.x += self.dx * self.speed
        self.y += self.dy * self.speed

        bx, by, bw, bh = bounds or DEFAULT_BOUNDS
        if self.x < bx or self.x > bx + bw or self.y < by or self.y > by + bh:
            self.is_active = False

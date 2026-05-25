import pygame


class Bullet:
    """
    A projectile fired by a player who has a gun.

    The gun (whether held by the Sheriff or an Innocent who picks it up)
    can ONLY damage a player whose role is "murderer".  It does nothing
    to Innocents or the Sheriff — the bullet harmlessly disappears.
    """

    def __init__(self, x, y, dx, dy, shooter_role):
        """
        Args:
            x, y: spawn position (centre)
            dx, dy: normalised direction vector
            shooter_role: "murderer", "sheriff", or "innocent" (for tracking origin)
        """
        self.x = x
        self.y = y
        self.dx = dx
        self.dy = dy
        self.speed = 8

        # Who fired this bullet (informational — rule is based on the *target's* role)
        self.shooter_role = shooter_role

        self.is_active = True

    def get_rect(self):
        """Small rect for wall-collision checks."""
        return pygame.Rect(self.x - 3, self.y - 3, 6, 6)

    def update(self):
        """Move the bullet. Deactivate if it leaves the map."""
        self.x += self.dx * self.speed
        self.y += self.dy * self.speed

        # Off-screen check
        if self.x < 0 or self.x > 800 or self.y < 0 or self.y > 600:
            self.is_active = False

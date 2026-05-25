import pygame
import math

from core.bullet import Bullet

# Size of the player's collision box (width and height in pixels)
PLAYER_SIZE = 20


class Player:
    """Represents a player (human or bot) with position, movement and collision."""

    def __init__(self, pid, name, color, is_bot=False, is_alive=True):
        """
        Set up a new player.

        Args:
            pid: unique string id
            name: display name
            color: RGB tuple e.g. (44, 181, 232)
            is_bot: True if this is an AI bot
            is_alive: whether the player is still alive
        """
        self.id = pid
        self.name = name
        self.color = color
        self.is_bot = is_bot
        self.is_alive = is_alive

        # Position (centre of the player rectangle)
        self.x = 0.0
        self.y = 0.0

        # Movement speed in pixels per frame
        self.speed = 3

        # Role-related flags
        self.has_knife = False
        self.has_gun = False
        self.role = ""

        # Frames until the player can attack again (0 = ready)
        self.attack_cooldown = 0

        # M Bucks collected this round (resets each round, max 50)
        self.m_bucks_this_round = 0

    def get_rect(self):
        """Return a pygame.Rect representing the player's collision box."""
        half = PLAYER_SIZE // 2
        return pygame.Rect(self.x - half, self.y - half, PLAYER_SIZE, PLAYER_SIZE)

    def move(self, dx, dy, walls):
        """
        Move the player by (dx, dy) while colliding with wall rectangles.

        X and Y movement are checked separately so the player can slide
        along walls (simple AABB collision).
        """
        size = PLAYER_SIZE
        half = size // 2

        # --- Try moving on the X axis ---
        new_x = self.x + dx
        test_rect = pygame.Rect(new_x - half, self.y - half, size, size)
        if not any(test_rect.colliderect(w) for w in walls):
            self.x = new_x

        # --- Try moving on the Y axis ---
        new_y = self.y + dy
        test_rect = pygame.Rect(self.x - half, new_y - half, size, size)
        if not any(test_rect.colliderect(w) for w in walls):
            self.y = new_y

    def try_kill(self, target):
        """
        Knife attack.

        Only works if:
          - The attacker has a knife (has_knife == True)
          - The attacker's cooldown is 0
          - The target is within 40 pixels

        On success the target dies and the attacker's cooldown resets to 60 frames.

        Returns True if the kill happened, False otherwise.
        """
        if not self.has_knife or self.attack_cooldown > 0:
            return False

        dx = self.x - target.x
        dy = self.y - target.y
        dist = math.sqrt(dx * dx + dy * dy)

        if dist <= 40:
            target.is_alive = False
            self.attack_cooldown = 60
            print(f"[COMBAT] {self.name} killed {target.name} with a knife!")
            return True

        return False

    def try_shoot(self, direction):
        """
        Fire a bullet in the given (dx, dy) direction.

        Only works if has_gun == True.
        The bullet stores the shooter's role so the game knows the gun's origin.
        The gun is consumed after firing (has_gun set to False).

        Returns the Bullet object, or None if the player can't shoot.
        """
        if not self.has_gun:
            return None

        # Normalise the direction vector
        dx, dy = direction
        length = math.sqrt(dx * dx + dy * dy)
        if length == 0:
            dx, dy = 0, -1  # default: shoot upward
            length = 1

        norm_dx = dx / length
        norm_dy = dy / length

        # Create a bullet at the player's position
        bullet = Bullet(self.x, self.y, norm_dx, norm_dy, self.role)
        self.has_gun = False
        print(f"[COMBAT] {self.name} fired a bullet")
        return bullet

    def collect_buck(self, amount):
        """
        Collect M Bucks, capping at the round maximum of 50.

        Args:
            amount: how many bucks the pickup is worth

        Returns:
            The number of bucks actually collected (0 if already at cap).
        """
        space = 50 - self.m_bucks_this_round
        if space <= 0:
            return 0
        actual = min(amount, space)
        self.m_bucks_this_round += actual
        return actual

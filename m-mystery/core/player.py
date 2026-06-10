import math

from core.bullet import Bullet
from core.rect import Rect

# ── Game-feel tuning ───────────────────────────────────────────────────
# Size of the player's collision box (width and height in pixels)
PLAYER_SIZE = 20

# Knife reach for a direct stab (px). The human attack additionally gets a
# short lunge-assist up to KNIFE_LUNGE_RANGE — see RoundSession._human_attack.
KNIFE_RANGE = 40

# Frames between knife swings (60 fps → 1.0 s). Gives victims a real window
# to break away after a swing.
KNIFE_COOLDOWN_FRAMES = 60


class Player:
    """Represents a player (human or bot) with position, movement and collision."""

    def __init__(self, pid, name, color, is_bot=False, is_alive=True,
                 body_color=None, shirt_color=None, pants_color=None, skin_color=None):
        """
        Set up a new player.

        Args:
            pid: unique string id
            name: display name
            color: RGB tuple e.g. (44, 181, 232) — accent / legacy
            is_bot: True if this is an AI bot
            is_alive: whether the player is still alive
        """
        self.id = pid
        self.name = name
        self.color = color
        self.is_bot = is_bot
        self.is_alive = is_alive

        # Roblox-style avatar colors
        self.body_color = body_color or color
        self.shirt_color = shirt_color or _shade_color(color, 20)
        self.pants_color = pants_color or _shade_color(color, -40)
        self.skin_color = skin_color or (255, 204, 153)

        # Position (centre of the player rectangle)
        self.x = 0.0
        self.y = 0.0

        # Facing & animation
        self.facing = (0.0, -1.0)
        self.anim_phase = 0.0
        self.is_moving = False

        # Movement speed in pixels per frame
        self.speed = 3
        self.sprint_speed = 5
        self.stamina = 100.0
        self.max_stamina = 100.0

        # Role-related flags
        self.has_knife = False
        self.has_gun = False
        self.role = ""

        # Frames until the player can attack again (0 = ready)
        self.attack_cooldown = 0

        # M Bucks collected this round (resets each round, max 50)
        self.m_bucks_this_round = 0

        # ── Witness / attribution state (additive) ─────────────────────
        # True while the knife is visibly out (murderer stalking). Nearby
        # bots that see a drawn knife learn who the murderer is.
        self.knife_drawn = False
        # Who killed this player (set on death; used for the kill feed and
        # witness logic so kills are never misattributed).
        self.last_killer_id = None
        self.last_killer_name = None
        self.last_death_weapon = None

    def get_rect(self):
        """Return a Rect representing the player's collision box."""
        half = PLAYER_SIZE // 2
        return Rect(self.x - half, self.y - half, PLAYER_SIZE, PLAYER_SIZE)

    def move(self, dx, dy, walls):
        """
        Move the player by (dx, dy) while colliding with wall rectangles.

        X and Y movement are checked separately so the player can slide
        along walls (simple AABB collision). Wall rects may be core Rect
        or pygame.Rect objects — anything with x/y/w/h attributes.
        """
        size = PLAYER_SIZE
        half = size // 2

        moved = False
        # --- Try moving on the X axis ---
        new_x = self.x + dx
        test_rect = Rect(new_x - half, self.y - half, size, size)
        if not any(test_rect.colliderect(w) for w in walls):
            self.x = new_x
            moved = True

        # --- Try moving on the Y axis ---
        new_y = self.y + dy
        test_rect = Rect(self.x - half, new_y - half, size, size)
        if not any(test_rect.colliderect(w) for w in walls):
            self.y = new_y
            moved = True

        if moved and (dx != 0 or dy != 0):
            length = math.sqrt(dx * dx + dy * dy)
            self.facing = (dx / length, dy / length)
            self.is_moving = True
            self.anim_phase += 0.25
        else:
            self.is_moving = False

    def try_kill(self, target):
        """
        Knife attack.

        Only works if:
          - The attacker has a knife (has_knife == True)
          - The attacker's cooldown is 0
          - The target is within KNIFE_RANGE pixels

        On success the target dies (with killer attribution recorded on the
        victim) and the attacker's cooldown resets to KNIFE_COOLDOWN_FRAMES.

        Returns True if the kill happened, False otherwise.
        """
        if not self.has_knife or self.attack_cooldown > 0:
            return False

        dx = self.x - target.x
        dy = self.y - target.y
        dist = math.sqrt(dx * dx + dy * dy)

        if dist <= KNIFE_RANGE:
            target.is_alive = False
            target.last_killer_id = self.id
            target.last_killer_name = self.name
            target.last_death_weapon = "knife"
            self.attack_cooldown = KNIFE_COOLDOWN_FRAMES
            print(f"[COMBAT] {self.name} killed {target.name} with a knife!")
            return True

        return False

    def try_shoot(self, direction):
        """
        Fire a bullet in the given (dx, dy) direction.

        Only works if has_gun == True.
        The bullet stores the shooter's role, id and name (for accurate
        kill-feed attribution). The gun is consumed after firing
        (has_gun set to False).

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
        bullet = Bullet(
            self.x, self.y, norm_dx, norm_dy, self.role,
            shooter_id=self.id, shooter_name=self.name,
        )
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


def _shade_color(rgb, delta):
    return tuple(max(0, min(255, c + delta)) for c in rgb)

import json
import math
import random

from core.player import Player
from core.bot_ai import BotBrain

# ── Game-feel tuning ───────────────────────────────────────────────────
# Frames between committed direction changes (lower = twitchier).
BOT_DECISION_INTERVAL = 6
# While panicking (fleeing a known murderer) bots re-steer faster.
BOT_PANIC_INTERVAL = 3
# Bot sprint stamina economy (per frame at 60 fps): a full bar buys about
# 3 s of sprinting and refills in roughly 5.5 s of walking.
BOT_SPRINT_DRAIN_PER_FRAME = 0.55
BOT_STAMINA_REGEN_PER_FRAME = 0.30


class Bot(Player):
    """AI-controlled player with human-like utility AI."""

    _CONFIG_BY_ROLE = {}
    _PERSONALITIES = {}

    @classmethod
    def _ensure_configs_loaded(cls):
        if not cls._CONFIG_BY_ROLE:
            with open("data/bots.json") as f:
                data = json.load(f)
            for entry in data["bots"]:
                cls._CONFIG_BY_ROLE[entry["role"]] = entry
            cls._PERSONALITIES = data.get("personalities", {})

    def __init__(self, pid, name, color, x, y, personality_id=None,
                 body_color=None, shirt_color=None, pants_color=None):
        super().__init__(
            pid, name, color, is_bot=True,
            body_color=body_color, shirt_color=shirt_color, pants_color=pants_color,
        )
        self.x = x
        self.y = y

        self.direction_ticks = 90
        self.ticks_left = 0
        self.dx = 0.0
        self.dy = 0.0

        self.shoot_range = 150
        self.flee_range = 200

        self._ensure_configs_loaded()
        pers = self._PERSONALITIES.get(
            personality_id or "balanced",
            self._PERSONALITIES.get("balanced", {}),
        )
        self.brain = BotBrain(self, pers)

        # Human-like movement smoothing
        self.move_jitter = 0.0

    def _apply_role_config(self):
        cfg = self._CONFIG_BY_ROLE.get(self.role, {})
        self.speed = cfg.get("speed", self.speed)
        self.shoot_range = cfg.get("shoot_range", self.shoot_range)
        self.flee_range = cfg.get("flee_range", self.flee_range)

    def find_nearest(self, players, filter_fn=None):
        nearest = None
        nearest_sq = float("inf")
        for p in players:
            if p is self or not p.is_alive:
                continue
            if filter_fn and not filter_fn(p):
                continue
            dx = self.x - p.x
            dy = self.y - p.y
            dist_sq = dx * dx + dy * dy
            if dist_sq < nearest_sq:
                nearest_sq = dist_sq
                nearest = p
        return nearest

    def _set_move_dir(self, dx, dy, interval=BOT_DECISION_INTERVAL):
        self.dx, self.dy = dx, dy
        self.ticks_left = interval

    def update(self, all_players, walls, dropped_gun_pos=None, bucks=None):
        if not self.is_alive:
            return None

        self._apply_role_config()
        self.brain.tick_memory(all_players, walls)

        bucks = bucks or []
        nearest_buck = self.brain.nearest_buck(bucks)
        buck_xy = nearest_buck

        dx, dy, shoot_dir = self.brain.choose_direction(
            all_players, walls, dropped_gun_pos, buck_xy
        )

        # Slight movement imperfection
        if random.random() < 0.08:
            self.move_jitter = random.uniform(-0.15, 0.15)
        dx += math.cos(self.anim_phase) * self.move_jitter * 0.3
        dy += math.sin(self.anim_phase) * self.move_jitter * 0.3

        # Sprint multiplier from the brain (fleeing / murder burst), paid
        # for with the bot's own stamina bar so chases can't last forever.
        mult = self.brain.move_speed_mult
        if mult > 1.0:
            if self.stamina > 0:
                self.stamina = max(0.0, self.stamina - BOT_SPRINT_DRAIN_PER_FRAME)
            else:
                mult = 1.0
        else:
            self.stamina = min(self.max_stamina,
                               self.stamina + BOT_STAMINA_REGEN_PER_FRAME)
        speed = self.speed * mult

        if self.ticks_left > 0:
            self.ticks_left -= 1
        else:
            interval = (BOT_PANIC_INTERVAL if self.brain.panic_ticks > 0
                        else BOT_DECISION_INTERVAL)
            self._set_move_dir(dx, dy, interval)

        self.move(self.dx * speed, self.dy * speed, walls)

        bullet = None
        if shoot_dir and self.has_gun:
            bullet = self.try_shoot(shoot_dir)

        return bullet

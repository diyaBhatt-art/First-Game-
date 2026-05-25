import json
import math
import random
import pygame

from core.player import Player
from core.bullet import Bullet


class Bot(Player):
    """AI-controlled player whose behavior depends on its role."""

    # Class-level cache loaded once from data/bots.json
    _CONFIG_BY_ROLE = {}

    @classmethod
    def _ensure_configs_loaded(cls):
        if not cls._CONFIG_BY_ROLE:
            with open("data/bots.json") as f:
                for entry in json.load(f)["bots"]:
                    cls._CONFIG_BY_ROLE[entry["role"]] = entry

    def __init__(self, pid, name, color, x, y):
        super().__init__(pid, name, color, is_bot=True)
        self.x = x
        self.y = y

        # Wandering state (used by Innocent and fallback)
        self.direction_ticks = 90
        self.ticks_left = 0
        self.dx = 0.0
        self.dy = 0.0

        # Config-dependent fields (set from bots.json in update())
        self.shoot_range = 150
        self.flee_range = 200

        self._ensure_configs_loaded()

    # ------------------------------------------------------------------
    # Config lookup (by current role, set at runtime by assign_roles)
    # ------------------------------------------------------------------

    def _apply_role_config(self):
        """Override speed / range values from bots.json for the current role."""
        cfg = self._CONFIG_BY_ROLE.get(self.role, {})
        self.speed = cfg.get("speed", self.speed)
        self.shoot_range = cfg.get("shoot_range", self.shoot_range)
        self.flee_range = cfg.get("flee_range", self.flee_range)

    # ------------------------------------------------------------------
    # Helper: find nearest living player
    # ------------------------------------------------------------------

    def find_nearest(self, players, filter_fn=None):
        """
        Return the nearest *living* player (other than self) that
        optionally passes *filter_fn(player) -> bool*.

        Returns None if no matching player is found.
        """
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

    # ------------------------------------------------------------------
    # Direction helpers (set dx/dy toward or away from a point)
    # ------------------------------------------------------------------

    def _set_dir_toward(self, tx, ty):
        """Set movement vector toward (tx, ty). Re-evaluates every 10 frames."""
        dx = tx - self.x
        dy = ty - self.y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist > 0:
            self.dx = dx / dist
            self.dy = dy / dist
        self.ticks_left = 10

    def _set_dir_away(self, tx, ty):
        """Set movement vector directly away from (tx, ty)."""
        dx = self.x - tx
        dy = self.y - ty
        dist = math.sqrt(dx * dx + dy * dy)
        if dist > 0:
            self.dx = dx / dist
            self.dy = dy / dist
        self.ticks_left = 10

    def _pick_direction(self):
        """Random cardinal direction; used as fallback wander behaviour."""
        self.dx, self.dy = random.choice([
            (0, -1), (0, 1), (-1, 0), (1, 0),
        ])
        self.ticks_left = self.direction_ticks

    # ------------------------------------------------------------------
    # Main update  (called every frame)
    # ------------------------------------------------------------------

    def update(self, all_players, walls, dropped_gun_pos=None):
        """
        One AI tick.  Behaviour is dispatched by self.role.

        Returns:
            A Bullet object if this bot fired this frame, otherwise None.
        """
        if not self.is_alive:
            return None

        self._apply_role_config()

        if self.role == "murderer":
            return self._update_murderer(all_players, walls)
        elif self.role == "sheriff":
            return self._update_sheriff(all_players, walls, dropped_gun_pos)
        else:  # innocent (or fallback)
            return self._update_innocent(all_players, walls, dropped_gun_pos)

    # ------------------------------------------------------------------
    # Murderer bot  —  chase and stab the nearest player
    # ------------------------------------------------------------------

    def _update_murderer(self, all_players, walls):
        target = self.find_nearest(
            all_players,
            filter_fn=lambda p: not getattr(p, "ghost", False),
        )
        if target:
            dist = math.sqrt(
                (self.x - target.x) ** 2 + (self.y - target.y) ** 2
            )
            if dist <= 40:
                self.try_kill(target)
            self._set_dir_toward(target.x, target.y)
        elif self.ticks_left <= 0:
            self._pick_direction()

        self.move(self.dx * self.speed, self.dy * self.speed, walls)
        return None

    # ------------------------------------------------------------------
    # Sheriff bot  —  shoot the Murderer on sight, then flee
    # ------------------------------------------------------------------

    def _update_sheriff(self, all_players, walls, dropped_gun_pos):
        bullet = None

        if self.has_gun:
            murderer = self.find_nearest(
                all_players, lambda p: p.role == "murderer"
            )
            if murderer:
                dx = self.x - murderer.x
                dy = self.y - murderer.y
                dist = math.sqrt(dx * dx + dy * dy)

                if dist <= self.shoot_range:
                    dir_x = murderer.x - self.x
                    dir_y = murderer.y - self.y
                    bullet = self.try_shoot((dir_x, dir_y))

        # Flee from the nearest living player (Murderer or anyone close)
        nearest = self.find_nearest(all_players)
        if nearest:
            self._set_dir_away(nearest.x, nearest.y)
        elif self.ticks_left <= 0:
            self._pick_direction()

        self.move(self.dx * self.speed, self.dy * self.speed, walls)
        return bullet

    # ------------------------------------------------------------------
    # Innocent bot  —  flee from Murderer, seek the dropped gun
    # ------------------------------------------------------------------

    def _update_innocent(self, all_players, walls, dropped_gun_pos):
        murderer = self.find_nearest(
            all_players, lambda p: p.role == "murderer"
        )

        # Flee if Murderer is close
        if murderer:
            dx = self.x - murderer.x
            dy = self.y - murderer.y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist <= self.flee_range:
                self._set_dir_away(murderer.x, murderer.y)

        # Move toward the dropped gun if nobody has picked it up
        if (dropped_gun_pos is not None
                and not self.has_gun
                and self.role != "murderer"):
            gx, gy = dropped_gun_pos
            dx = gx - self.x
            dy = gy - self.y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < 150:
                self._set_dir_toward(gx, gy)

        # Wander if nothing is directing us
        if self.ticks_left <= 0:
            self._pick_direction()

        self.move(self.dx * self.speed, self.dy * self.speed, walls)
        return None

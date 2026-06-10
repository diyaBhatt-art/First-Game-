"""Shared round logic for 2D and 3D clients. Pure Python — no engine imports."""
import math
import random

from core.bot_ai import (
    BODY_DISCOVER_RADIUS,
    KNIFE_SPOT_RADIUS,
    SIGHT_RADIUS,
)
from core.player import KNIFE_RANGE
from core.rect import Rect, has_line_of_sight, point_in_any_rect
from core.round import RoundManager
from core.shop import ShopManager

# ── Game-feel tuning ───────────────────────────────────────────────────
# Round length for a 4-player lobby (~2 minutes of real tension).
ROUND_DURATION_SECONDS = 120

# Human attack assist: a knife swing snaps the attacker a short step toward
# a victim inside this range (line-of-sight required), then Player.try_kill
# applies the true KNIFE_RANGE check. Mirrors MM2's lunge.
KNIFE_LUNGE_RANGE = 60

# Human sprint stamina economy (per second, dt-scaled): a full bar buys
# ~3.6 s of sprinting and refills in ~5 s of walking.
SPRINT_DRAIN_PER_SEC = 28.0
STAMINA_REGEN_PER_SEC = 20.0

# Pickups
GUN_PICKUP_RADIUS = 25
BUCK_PICKUP_RADIUS = 15
BUCK_COUNT = 20
BUCK_WALL_MARGIN = 12  # bucks never spawn this close to / inside a wall

# How often (in frames) the cheap perception sweeps run.
KNIFE_SIGHT_CHECK_EVERY = 6
BODY_DISCOVER_CHECK_EVERY = 15


class RoundSession:
    """Combat, pickups, timer, and win checks — renderer-agnostic."""

    def __init__(self, players, map_data, wallet_manager, human):
        self.map_data = map_data
        self.walls = [
            Rect(w["x"], w["y"], w["w"], w["h"])
            for w in map_data["walls"]
        ]
        self.players = players
        self.human = human
        self.round_manager = RoundManager(ROUND_DURATION_SECONDS)
        self.wallet_manager = wallet_manager
        self.shop_manager = ShopManager()

        self.last_move_dir = (0, -1)
        self.bullets = []
        self.dropped_gun_pos = None
        self.bucks = self._spawn_bucks()
        self.active_effects = {}
        self.murderer_trail = []
        self.noise_traps = []
        self.screen_shake = {"frames_left": 0, "intensity": 6}
        self._prev_alive = {p.id: (p.x, p.y) for p in players if p.is_alive}
        self.shop_open = False
        self.kill_log = []   # list of (killer_name, victim_name, weapon) tuples, drained each frame

        # New (additive) round state
        self.corpses = []              # [(x, y)] — death positions this round
        self._logged_death_ids = set()  # victims already in the kill feed
        self._frame = 0
        self._bounds = (
            0, 0,
            map_data.get("width", 800),
            map_data.get("height", 600),
        )

        # Fresh attribution state and map knowledge for the new round
        for p in players:
            p.last_killer_id = None
            p.last_killer_name = None
            p.last_death_weapon = None
            p.knife_drawn = False
            brain = getattr(p, "brain", None)
            if brain is not None and hasattr(brain, "set_environment"):
                brain.set_environment(map_data)

    def _spawn_bucks(self):
        """Scatter bucks in the spawn zones, never inside or against a wall."""
        zones = self.map_data["buck_spawn_zones"]
        picks = []
        for _ in range(BUCK_COUNT):
            for _attempt in range(25):
                zone = random.choice(zones)
                x = random.randint(zone["x"], zone["x"] + zone["w"])
                y = random.randint(zone["y"], zone["y"] + zone["h"])
                if not point_in_any_rect(x, y, self.walls, margin=BUCK_WALL_MARGIN):
                    picks.append((x, y, random.randint(1, 3)))
                    break
        return picks

    @property
    def alive_count(self):
        return sum(1 for p in self.players if p.is_alive)

    def tick_human_move(self, dt, dx, dy, sprinting):
        """Apply human movement only (used when 3D computes camera-relative dx/dy)."""
        speed = self.human.sprint_speed if sprinting else self.human.speed
        if sprinting and (dx != 0 or dy != 0):
            if self.human.stamina > 0:
                self.human.stamina = max(
                    0.0, self.human.stamina - SPRINT_DRAIN_PER_SEC * dt
                )
            else:
                speed = self.human.speed
        else:
            self.human.stamina = min(
                self.human.max_stamina,
                self.human.stamina + STAMINA_REGEN_PER_SEC * dt,
            )

        if dx != 0 or dy != 0:
            length = math.sqrt(dx * dx + dy * dy)
            ndx, ndy = dx / length, dy / length
            self.last_move_dir = (ndx, ndy)
            self.human.move(ndx * speed, ndy * speed, self.walls)

    def tick_simulation(self, dt):
        """Bots, bullets, pickups — after human move."""
        if self.shop_open:
            return None

        self._frame += 1
        self.round_manager.tick(dt)
        for p in self.players:
            if p.attack_cooldown > 0:
                p.attack_cooldown -= 1

        # Feed the round clock to bot brains (murderer risk-taking ramps up
        # as the timer runs down). Cheap, so refresh twice a second.
        if self._frame % 30 == 1:
            total = max(1.0, float(self.round_manager.total_seconds))
            pressure = 1.0 - (self.round_manager.remaining / total)
            for p in self.players:
                brain = getattr(p, "brain", None)
                if brain is not None:
                    brain.time_pressure = pressure

        buck_positions = [(b[0], b[1]) for b in self.bucks]
        for p in self.players:
            if p.is_bot and p.is_alive:
                bullet = p.update(
                    self.players, self.walls, self.dropped_gun_pos, buck_positions
                )
                if bullet:
                    self.bullets.append(bullet)

        self._update_bullets()
        self._check_deaths_witness()
        self._check_dropped_gun()
        self._check_knife_sightings()
        self._discover_bodies()
        self._check_buck_collection()
        self._tick_effects()
        self._update_murderer_trail()
        self._check_noise_traps()
        self._check_alarm()
        return self.round_manager.check_win_conditions(self.players)

    def _human_attack(self):
        ghost_ids = set()
        if "ghost_mode" in self.active_effects:
            ghost_ids.add(self.active_effects["ghost_mode"]["buyer_id"])

        if self.human.has_knife:
            if self.human.attack_cooldown > 0:
                return
            nearest = None
            nearest_dist = KNIFE_LUNGE_RANGE + 1
            for p in self.players:
                if p is self.human or not p.is_alive or p.id in ghost_ids:
                    continue
                dx = self.human.x - p.x
                dy = self.human.y - p.y
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest = p
            if nearest:
                # Lunge assist: step toward the victim (walls respected, no
                # stabbing through them), then resolve the normal range check.
                if nearest_dist > KNIFE_RANGE:
                    if not has_line_of_sight(
                        self.human.x, self.human.y,
                        nearest.x, nearest.y, self.walls,
                    ):
                        return
                    self._lunge_toward(self.human, nearest,
                                       nearest_dist - KNIFE_RANGE + 2)
                self.human.try_kill(nearest)
                # Kill feed entry is added centrally in _check_deaths_witness.

        elif self.human.has_gun:
            fire_dir = self.last_move_dir
            if "dead_eye" in self.active_effects:
                murderer = next(
                    (p for p in self.players if p.role == "murderer" and p.is_alive),
                    None,
                )
                if murderer:
                    dx = murderer.x - self.human.x
                    dy = murderer.y - self.human.y
                    if math.sqrt(dx * dx + dy * dy) <= 300:
                        fire_dir = (dx, dy)
                del self.active_effects["dead_eye"]
            bullet = self.human.try_shoot(fire_dir)
            if bullet:
                self.bullets.append(bullet)

    def _lunge_toward(self, attacker, target, distance):
        """Move attacker up to *distance* px toward target, colliding with walls."""
        ndx, ndy = target.x - attacker.x, target.y - attacker.y
        length = math.sqrt(ndx * ndx + ndy * ndy)
        if length < 0.001:
            return
        ndx, ndy = ndx / length, ndy / length
        remaining = min(distance, length)
        while remaining > 0:
            step = min(8.0, remaining)
            attacker.move(ndx * step, ndy * step, self.walls)
            remaining -= step

    def _update_bullets(self):
        for bullet in self.bullets[:]:
            if not bullet.is_active:
                self.bullets.remove(bullet)
                continue

            prev_x, prev_y = bullet.x, bullet.y
            bullet.update(self._bounds)

            if not bullet.is_active:
                # Flew off the map — the gun lands where the bullet died
                self._drop_spent_gun(prev_x, prev_y)
                self.bullets.remove(bullet)
                continue

            b_rect = bullet.get_rect()
            if any(b_rect.colliderect(w) for w in self.walls):
                bullet.is_active = False
                self._drop_spent_gun(prev_x, prev_y)
                self.bullets.remove(bullet)
                continue

            shooter_id = getattr(bullet, "shooter_id", None)
            for p in self.players:
                # A bullet can never hit its own shooter — it spawns at the
                # shooter's position, so without this check every shot was
                # "stopped" by the shooter on its very first frame.
                if not p.is_alive or p.id == shooter_id:
                    continue
                # Distance from the player to the bullet's travel segment
                # this frame — a fast bullet can otherwise step past a
                # player between two frames.
                if self._segment_point_dist(
                        prev_x, prev_y, bullet.x, bullet.y, p.x, p.y) < 15:
                    if p.role == "murderer":
                        p.is_alive = False
                        p.last_killer_id = getattr(bullet, "shooter_id", None)
                        p.last_killer_name = (
                            getattr(bullet, "shooter_name", None) or "Unknown"
                        )
                        p.last_death_weapon = "gun"
                        print(f"[COMBAT] {p.name} was shot and killed!")
                        # Kill feed entry added centrally in _check_deaths_witness.
                    else:
                        # Bullet stopped by a non-murderer — gun drops there
                        self._drop_spent_gun(bullet.x, bullet.y)
                    bullet.is_active = False
                    self.bullets.remove(bullet)
                    break

    @staticmethod
    def _segment_point_dist(x1, y1, x2, y2, px, py):
        """Shortest distance from point (px, py) to segment (x1,y1)-(x2,y2)."""
        sx, sy = x2 - x1, y2 - y1
        seg_sq = sx * sx + sy * sy
        if seg_sq < 1e-9:
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
        t = ((px - x1) * sx + (py - y1) * sy) / seg_sq
        t = max(0.0, min(1.0, t))
        cx, cy = x1 + sx * t, y1 + sy * t
        return math.sqrt((px - cx) ** 2 + (py - cy) ** 2)

    def _drop_spent_gun(self, x, y):
        """Re-drop the gun where a missed bullet landed (MM2-style recovery).

        Only applies while nobody is holding a gun and none is already on
        the ground — there is exactly one gun in the economy per round.
        """
        if self.dropped_gun_pos is not None:
            return
        if any(p.has_gun for p in self.players if p.is_alive):
            return
        bx, by, bw, bh = self._bounds
        x = max(bx + 30, min(bx + bw - 30, x))
        y = max(by + 30, min(by + bh - 30, y))
        self.dropped_gun_pos = (x, y)

    def _check_deaths_witness(self):
        """Central death processing: kill feed, corpses, and bot witnesses.

        Exactly one kill-feed entry per victim (deduped via
        _logged_death_ids), attributed from the victim's last_killer_*
        fields which are stamped at the point of the kill.
        """
        current = {p.id: (p.x, p.y) for p in self.players if p.is_alive}
        for pid, pos in self._prev_alive.items():
            if pid in current:
                continue
            victim = next((x for x in self.players if x.id == pid), None)
            if victim is not None:
                death_x, death_y = victim.x, victim.y
            else:
                death_x, death_y = pos

            self.corpses.append((death_x, death_y))

            # --- Kill feed (exactly once per victim) ---
            if pid not in self._logged_death_ids and victim is not None:
                killer_name = getattr(victim, "last_killer_name", None)
                weapon = getattr(victim, "last_death_weapon", None) or "knife"
                if not killer_name:
                    murderer = next(
                        (p for p in self.players if p.role == "murderer"), None
                    )
                    killer_name = murderer.name if murderer else "Unknown"
                self.kill_log.append((killer_name, victim.name, weapon))
                self._logged_death_ids.add(pid)

            # --- Witnesses ---
            killer_id = getattr(victim, "last_killer_id", None)
            for p in self.players:
                if not p.is_bot or not p.is_alive:
                    continue
                dx = p.x - death_x
                dy = p.y - death_y
                if math.sqrt(dx * dx + dy * dy) >= SIGHT_RADIUS:
                    continue
                if not has_line_of_sight(p.x, p.y, death_x, death_y, self.walls):
                    continue
                if killer_id:
                    p.brain.on_witness_kill(killer_id, death_x, death_y)
                else:
                    p.brain.on_witness_death(self.players, death_x, death_y, pid)
        self._prev_alive = current

    def _check_dropped_gun(self):
        # Any corpse still clutching the gun drops it on the spot. (The old
        # logic re-dropped a gun at the sheriff's body every time the slot
        # emptied, duplicating guns forever.)
        for p in self.players:
            if not p.is_alive and p.has_gun:
                p.has_gun = False
                if self.dropped_gun_pos is None:
                    self.dropped_gun_pos = (p.x, p.y)

        if self.dropped_gun_pos is not None:
            gx, gy = self.dropped_gun_pos
            for p in self.players:
                if not p.is_alive or p.has_gun or p.role == "murderer":
                    continue
                dx = p.x - gx
                dy = p.y - gy
                if math.sqrt(dx * dx + dy * dy) < GUN_PICKUP_RADIUS:
                    p.has_gun = True
                    self.dropped_gun_pos = None
                    break

    def _check_knife_sightings(self):
        """Bots that see a drawn knife (or a fresh swing) learn the murderer."""
        if self._frame % KNIFE_SIGHT_CHECK_EVERY != 0:
            return
        holders = [
            p for p in self.players
            if p.is_alive and p.has_knife
            and (getattr(p, "knife_drawn", False) or p.attack_cooldown > 0)
        ]
        if not holders:
            return
        for holder in holders:
            for p in self.players:
                if not p.is_bot or not p.is_alive or p is holder:
                    continue
                dx = p.x - holder.x
                dy = p.y - holder.y
                if math.sqrt(dx * dx + dy * dy) >= KNIFE_SPOT_RADIUS:
                    continue
                if has_line_of_sight(p.x, p.y, holder.x, holder.y, self.walls):
                    p.brain.on_spot_knife(holder.id)

    def _discover_bodies(self):
        """Bots stumbling onto corpses they didn't witness learn about them."""
        if not self.corpses or self._frame % BODY_DISCOVER_CHECK_EVERY != 0:
            return
        for p in self.players:
            if not p.is_bot or not p.is_alive:
                continue
            for cx, cy in self.corpses:
                dx = p.x - cx
                dy = p.y - cy
                if math.sqrt(dx * dx + dy * dy) >= BODY_DISCOVER_RADIUS:
                    continue
                if has_line_of_sight(p.x, p.y, cx, cy, self.walls):
                    p.brain.note_body(cx, cy)

    def _check_buck_collection(self):
        for p in self.players:
            if not p.is_alive or p.m_bucks_this_round >= 50:
                continue
            for buck in self.bucks[:]:
                bx, by, value = buck
                dx = p.x - bx
                dy = p.y - by
                if math.sqrt(dx * dx + dy * dy) < BUCK_PICKUP_RADIUS:
                    if p.collect_buck(value) > 0:
                        self.bucks.remove(buck)

    def _tick_effects(self):
        expired = []
        for key, effect in self.active_effects.items():
            if effect["frames_left"] > 0:
                effect["frames_left"] -= 1
                if effect["frames_left"] == 0:
                    expired.append(key)
        for key in expired:
            if key == "ghost_mode":
                buyer_id = self.active_effects[key].get("buyer_id")
                if buyer_id:
                    for p in self.players:
                        if p.id == buyer_id:
                            p.ghost = False
            del self.active_effects[key]

    def _update_murderer_trail(self):
        for p in self.players:
            if p.role == "murderer" and p.is_alive:
                self.murderer_trail.append((p.x, p.y))
                if len(self.murderer_trail) > 20:
                    self.murderer_trail.pop(0)
                return
        self.murderer_trail.clear()

    def _check_noise_traps(self):
        if not self.noise_traps:
            return
        murderer = next(
            (p for p in self.players if p.role == "murderer" and p.is_alive), None
        )
        if not murderer:
            return
        for trap in self.noise_traps[:]:
            dx = murderer.x - trap["x"]
            dy = murderer.y - trap["y"]
            if math.sqrt(dx * dx + dy * dy) < 20:
                self.noise_traps.remove(trap)
                self.screen_shake["frames_left"] = 180

    def _check_alarm(self):
        eff = self.active_effects.get("alarm")
        if not eff:
            return
        buyer = next(
            (p for p in self.players if p.id == eff["buyer_id"] and p.is_alive), None
        )
        murderer = next(
            (p for p in self.players if p.role == "murderer" and p.is_alive), None
        )
        if buyer and murderer:
            dx = murderer.x - buyer.x
            dy = murderer.y - buyer.y
            if math.sqrt(dx * dx + dy * dy) < 100:
                self.screen_shake["frames_left"] = max(
                    self.screen_shake["frames_left"], 5
                )

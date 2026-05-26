"""Shared round logic for 2D and 3D clients."""
import math
import random
import pygame

from core.round import RoundManager
from core.shop import ShopManager


class RoundSession:
    """Combat, pickups, timer, and win checks — renderer-agnostic."""

    def __init__(self, players, map_data, wallet_manager, human):
        self.map_data = map_data
        self.walls = [
            pygame.Rect(w["x"], w["y"], w["w"], w["h"])
            for w in map_data["walls"]
        ]
        self.players = players
        self.human = human
        self.round_manager = RoundManager(180)
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

    def _spawn_bucks(self):
        zones = self.map_data["buck_spawn_zones"]
        picks = []
        for _ in range(20):
            zone = random.choice(zones)
            x = random.randint(zone["x"], zone["x"] + zone["w"])
            y = random.randint(zone["y"], zone["y"] + zone["h"])
            picks.append((x, y, random.randint(1, 3)))
        return picks

    @property
    def alive_count(self):
        return sum(1 for p in self.players if p.is_alive)

    def tick_human_move(self, dt, dx, dy, sprinting):
        """Apply human movement only (used when 3D computes camera-relative dx/dy)."""
        speed = self.human.sprint_speed if sprinting else self.human.speed
        if sprinting and (dx != 0 or dy != 0):
            if self.human.stamina > 0:
                self.human.stamina = max(0, self.human.stamina - 0.8)
            else:
                speed = self.human.speed
        else:
            self.human.stamina = min(self.human.max_stamina, self.human.stamina + 0.5)

        if dx != 0 or dy != 0:
            length = math.sqrt(dx * dx + dy * dy)
            ndx, ndy = dx / length, dy / length
            self.last_move_dir = (ndx, ndy)
            self.human.move(ndx * speed, ndy * speed, self.walls)

    def tick_simulation(self, dt):
        """Bots, bullets, pickups — after human move."""
        if self.shop_open:
            return None

        self.round_manager.tick(dt)
        for p in self.players:
            if p.attack_cooldown > 0:
                p.attack_cooldown -= 1

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
            nearest = None
            nearest_dist = 41
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
                self.human.try_kill(nearest)

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

    def _update_bullets(self):
        for bullet in self.bullets[:]:
            if not bullet.is_active:
                self.bullets.remove(bullet)
                continue
            bullet.update()
            b_rect = bullet.get_rect()
            if any(b_rect.colliderect(w) for w in self.walls):
                bullet.is_active = False
                self.bullets.remove(bullet)
                continue
            for p in self.players:
                if not p.is_alive:
                    continue
                dx = bullet.x - p.x
                dy = bullet.y - p.y
                if math.sqrt(dx * dx + dy * dy) < 15:
                    if p.role == "murderer":
                        p.is_alive = False
                        print(f"[COMBAT] {p.name} was shot and killed!")
                    bullet.is_active = False
                    self.bullets.remove(bullet)
                    break

    def _check_deaths_witness(self):
        current = {p.id: (p.x, p.y) for p in self.players if p.is_alive}
        for pid, pos in self._prev_alive.items():
            if pid not in current:
                death_x, death_y = pos
                for p in self.players:
                    if not p.is_bot or not p.is_alive:
                        continue
                    dx = p.x - death_x
                    dy = p.y - death_y
                    if math.sqrt(dx * dx + dy * dy) < 200:
                        p.brain.on_witness_death(self.players, death_x, death_y, pid)
        self._prev_alive = current

    def _check_dropped_gun(self):
        if self.dropped_gun_pos is None:
            for p in self.players:
                if p.role == "sheriff" and not p.is_alive:
                    self.dropped_gun_pos = (p.x, p.y)
                    break
        if self.dropped_gun_pos is not None:
            gx, gy = self.dropped_gun_pos
            for p in self.players:
                if not p.is_alive or p.has_gun or p.role == "murderer":
                    continue
                dx = p.x - gx
                dy = p.y - gy
                if math.sqrt(dx * dx + dy * dy) < 25:
                    p.has_gun = True
                    self.dropped_gun_pos = None
                    break

    def _check_buck_collection(self):
        for p in self.players:
            if not p.is_alive or p.m_bucks_this_round >= 50:
                continue
            for buck in self.bucks[:]:
                bx, by, value = buck
                dx = p.x - bx
                dy = p.y - by
                if math.sqrt(dx * dx + dy * dy) < 15:
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

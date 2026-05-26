"""
Utility-based bot brain — no API keys. Bots use imperfect information like real players.
"""
import math
import random

import pygame


def _dist(ax, ay, bx, by):
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


def _norm(dx, dy):
    d = math.sqrt(dx * dx + dy * dy)
    if d < 0.001:
        return 0.0, 0.0
    return dx / d, dy / d


class BotBrain:
    """Per-bot memory and decision-making."""

    def __init__(self, bot, personality=None):
        self.bot = bot
        p = personality or {}
        self.aggression = p.get("aggression", 0.5)
        self.caution = p.get("caution", 0.5)
        self.greed = p.get("greed", 0.4)
        self.accuracy = p.get("accuracy", 0.7)

        self.suspicious = {}  # player_id -> suspicion 0..1
        self.witnessed_killer_id = None
        self.last_death_pos = None
        self.reaction_delay = 0
        self.action_cooldown = 0
        self.idle_until = 0
        self.group_target_id = None
        self.wander_goal = None
        self._last_alive_count = 4

    def reset_round(self):
        """Clear per-round memory (suspicion, witnesses)."""
        self.suspicious.clear()
        self.witnessed_killer_id = None
        self.last_death_pos = None
        self.reaction_delay = 0
        self.action_cooldown = 0
        self.idle_until = 0
        self.group_target_id = None
        self.wander_goal = None
        self._last_alive_count = 4

    def on_witness_death(self, all_players, death_x, death_y, victim_id):
        """Called when this bot was near a kill — blame nearest other player."""
        bot = self.bot
        if bot.role == "murderer":
            return
        nearest = None
        best = 9999
        for p in all_players:
            if not p.is_alive or p.id == victim_id or p is bot:
                continue
            d = _dist(p.x, p.y, death_x, death_y)
            if d < best and d < 100:
                best = d
                nearest = p
        if nearest:
            self._raise_suspicion(nearest.id, 0.7)
            if best < 55:
                self.witnessed_killer_id = nearest.id
            self.reaction_delay = random.randint(8, 20)

    def tick_memory(self, all_players, walls):
        """Update suspicion from proximity / deaths (called each frame)."""
        bot = self.bot
        alive = [p for p in all_players if p.is_alive and p is not bot]
        alive_count = len(alive) + 1

        if alive_count < self._last_alive_count:
            # Someone died — if we were nearby, mark nearest other player suspicious
            nearest_other = None
            best = 9999
            for p in alive:
                d = _dist(bot.x, bot.y, p.x, p.y)
                if d < best:
                    best = d
                    nearest_other = p
            if best < 220 and nearest_other:
                self._raise_suspicion(nearest_other.id, 0.55)
                if best < 120:
                    self.witnessed_killer_id = nearest_other.id
            if self.last_death_pos is None:
                self.last_death_pos = (bot.x, bot.y)

        self._last_alive_count = alive_count

        # Decay suspicion slowly
        for pid in list(self.suspicious):
            self.suspicious[pid] *= 0.998
            if self.suspicious[pid] < 0.05:
                del self.suspicious[pid]

        # Innocents cluster: pick a "buddy" to follow sometimes
        if bot.role != "murderer" and random.random() < 0.002:
            others = [p for p in alive if p.id != bot.id]
            if others:
                self.group_target_id = random.choice(others).id

    def _raise_suspicion(self, pid, amount):
        self.suspicious[pid] = min(1.0, self.suspicious.get(pid, 0) + amount)

    def knows_murderer_identity(self, player):
        """Sheriff/innocent only 'know' murderer if witnessed or very suspicious."""
        if self.bot.role == "murderer":
            return player.role == "murderer"
        if self.witnessed_killer_id and player.id == self.witnessed_killer_id:
            return True
        return self.suspicious.get(player.id, 0) >= 0.75

    def pick_suspect(self, all_players):
        """Best guess at murderer for shooting / fleeing."""
        bot = self.bot
        candidates = []
        for p in all_players:
            if p is bot or not p.is_alive:
                continue
            if p.role == "murderer" and bot.role == "murderer":
                continue
            score = self.suspicious.get(p.id, 0)
            if self.witnessed_killer_id == p.id:
                score += 1.0
            # Murderer acts less suspicious when far — imperfect info
            if p.role == "murderer" and bot.role != "murderer":
                d = _dist(bot.x, bot.y, p.x, p.y)
                if d < 90:
                    score += 0.25 * (1 - self.caution)
            candidates.append((score, p))
        if not candidates:
            return None
        candidates.sort(key=lambda x: -x[0])
        if candidates[0][0] < 0.15:
            return None
        return candidates[0][1]

    def _ret(self, direction, shoot_dir=None):
        """Normalize to (dx, dy, shoot_dir)."""
        dx, dy = direction
        return dx, dy, shoot_dir

    def steer_clear_of_walls(self, dx, dy, walls, probe=28):
        """Nudge direction away from nearby walls."""
        bot = self.bot
        px, py = bot.x, bot.y
        for angle in (0, 0.6, -0.6, 1.2, -1.2):
            ca, sa = math.cos(angle), math.sin(angle)
            rdx = dx * ca - dy * sa
            rdy = dx * sa + dy * ca
            tx, ty = px + rdx * probe, py + rdy * probe
            test = pygame.Rect(int(tx) - 10, int(ty) - 10, 20, 20)
            if any(test.colliderect(w) for w in walls):
                dx -= rdx * 0.35
                dy -= rdy * 0.35
        return _norm(dx, dy)

    def choose_direction(self, all_players, walls, dropped_gun_pos, bucks):
        """Return (dx, dy, want_shoot_dir or None)."""
        bot = self.bot
        if self.reaction_delay > 0:
            self.reaction_delay -= 1
            return bot.facing[0], bot.facing[1], None

        if self.idle_until > 0:
            self.idle_until -= 1
            return 0, 0, None

        if random.random() < 0.003:
            self.idle_until = random.randint(15, 45)

        if bot.role == "murderer":
            return self._murderer_dir(all_players, walls, bucks)
        if bot.role == "sheriff":
            return self._sheriff_dir(all_players, walls, dropped_gun_pos, bucks)
        return self._innocent_dir(all_players, walls, dropped_gun_pos, bucks)

    def _murderer_dir(self, all_players, walls, bucks):
        bot = self.bot
        shoot = None
        targets = [
            p for p in all_players
            if p is not bot and p.is_alive and not getattr(p, "ghost", False)
        ]
        if not targets:
            return self._ret(self._wander(walls))

        # Prefer isolated victims (MM2-style stalking)
        best = None
        best_score = -1
        witnesses = len([p for p in all_players if p.is_alive and p is not bot])

        for t in targets:
            d = _dist(bot.x, bot.y, t.x, t.y)
            nearby_allies = sum(
                1 for p in all_players
                if p.is_alive and p is not t and p is not bot
                and _dist(t.x, t.y, p.x, p.y) < 100
            )
            isolation = max(0, 3 - nearby_allies)
            score = isolation * 40 - d * 0.3 + self.aggression * 30
            if d <= 40:
                score += 200
            if score > best_score:
                best_score = score
                best = t

        if best:
            d = _dist(bot.x, bot.y, best.x, best.y)
            if d <= 40:
                bot.try_kill(best)
            # Approach from behind when possible
            bx, by = best.x - bot.x, best.y - bot.y
            dx, dy = _norm(bx, by)
            if witnesses >= 2 and d > 60:
                # Blend in: sometimes move toward bucks instead
                if bucks and random.random() < 0.35 * (1 - self.aggression):
                    return self._ret(self._toward_point(bucks[0], bucks[1], walls))
            return self._ret(self.steer_clear_of_walls(dx, dy, walls))

        return self._ret(self._wander(walls))

    def _sheriff_dir(self, all_players, walls, dropped_gun_pos, bucks):
        bot = self.bot
        shoot_dir = None

        if bot.has_gun:
            suspect = self.pick_suspect(all_players)
            if suspect:
                d = _dist(bot.x, bot.y, suspect.x, suspect.y)
                in_range = d <= bot.shoot_range
                confident = (
                    self.witnessed_killer_id == suspect.id
                    or self.suspicious.get(suspect.id, 0) >= 0.6
                )
                if in_range and confident and random.random() < self.accuracy:
                    if self.action_cooldown <= 0:
                        shoot_dir = _norm(suspect.x - bot.x, suspect.y - bot.y)
                        self.action_cooldown = random.randint(8, 25)
                        self.reaction_delay = random.randint(3, 12)
                elif d < bot.shoot_range * 0.7 and not confident:
                    # Hesitate — back up like a real player
                    dx, dy = _norm(bot.x - suspect.x, bot.y - suspect.y)
                    return self._ret(self.steer_clear_of_walls(dx, dy, walls))

        if self.action_cooldown > 0:
            self.action_cooldown -= 1

        threat = self.pick_suspect(all_players)
        if threat:
            d = _dist(bot.x, bot.y, threat.x, threat.y)
            if d < 160 + self.caution * 80:
                dx, dy = _norm(bot.x - threat.x, bot.y - threat.y)
                return self._ret(self.steer_clear_of_walls(dx, dy, walls), shoot_dir)

        if dropped_gun_pos and not bot.has_gun:
            gx, gy = dropped_gun_pos
            if _dist(bot.x, bot.y, gx, gy) < 200:
                return self._ret(self._toward_point(gx, gy, walls), shoot_dir)

        if bucks and random.random() < self.greed:
            return self._ret(self._toward_point(bucks[0], bucks[1], walls), shoot_dir)

        return self._ret(self._wander(walls), shoot_dir)

    def _innocent_dir(self, all_players, walls, dropped_gun_pos, bucks):
        bot = self.bot
        threat = self.pick_suspect(all_players)

        if threat:
            d = _dist(bot.x, bot.y, threat.x, threat.y)
            flee_dist = bot.flee_range + self.caution * 60
            if d < flee_dist:
                dx, dy = _norm(bot.x - threat.x, bot.y - threat.y)
                if random.random() < 0.02:
                    self.reaction_delay = random.randint(5, 18)
                return self._ret(self.steer_clear_of_walls(dx, dy, walls))

        if dropped_gun_pos and not bot.has_gun:
            gx, gy = dropped_gun_pos
            if _dist(bot.x, bot.y, gx, gy) < 180:
                return self._ret(self._toward_point(gx, gy, walls))

        if self.group_target_id:
            buddy = next(
                (p for p in all_players if p.id == self.group_target_id and p.is_alive),
                None,
            )
            if buddy:
                d = _dist(bot.x, bot.y, buddy.x, buddy.y)
                if d > 50:
                    return self._ret(self._toward_point(buddy.x, buddy.y, walls))
                if d < 35:
                    self.group_target_id = None

        if bucks and random.random() < 0.4 + self.greed * 0.4:
            return self._ret(self._toward_point(bucks[0], bucks[1], walls))

        return self._ret(self._wander(walls))

    def _toward_point(self, tx, ty, walls):
        dx, dy = _norm(tx - self.bot.x, ty - self.bot.y)
        return self.steer_clear_of_walls(dx, dy, walls)

    def _wander(self, walls):
        bot = self.bot
        if self.wander_goal is None or random.random() < 0.01:
            self.wander_goal = (
                random.randint(60, 740),
                random.randint(60, 540),
            )
        gx, gy = self.wander_goal
        if _dist(bot.x, bot.y, gx, gy) < 30:
            self.wander_goal = None
            return _norm(random.uniform(-1, 1), random.uniform(-1, 1))
        return self._toward_point(gx, gy, walls)

    def nearest_buck(self, bucks):
        if not bucks:
            return None
        bot = self.bot
        best = None
        best_d = 9999
        for item in bucks:
            if len(item) >= 2:
                bx, by = item[0], item[1]
            else:
                continue
            d = _dist(bot.x, bot.y, bx, by)
            if d < best_d:
                best_d = d
                best = (bx, by)
        return best

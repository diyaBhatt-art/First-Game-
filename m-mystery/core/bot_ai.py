"""
Utility-based bot brain — pure Python, no engine imports, no API keys.

Bots act on imperfect information, like real players:

  * Innocents wander between map points of interest, drift toward visible
    bucks, regroup with other survivors, and flee at a sprint once they have
    actually seen the murderer kill someone or spotted a drawn knife.
  * The sheriff patrols points of interest, investigates bodies, and only
    chases/shoots once confident about the murderer's identity.
  * The murderer stalks isolated victims, avoids striking in crowds, backs
    off from anyone visibly holding the gun, and varies aggression with its
    personality (aggression/caution/greed/accuracy from data/bots.json).

All hard knowledge flows through witness events (RoundSession calls
``on_witness_kill`` / ``on_spot_knife``) or soft proximity heuristics —
bots never read another player's hidden role directly.
"""
import math
import random

from core.player import KNIFE_RANGE
from core.rect import has_line_of_sight, point_in_any_rect

# ── Perception tuning ──────────────────────────────────────────────────
SIGHT_RADIUS = 180          # px — how far a bot can witness a kill
KNIFE_SPOT_RADIUS = 140     # px — how far a drawn knife is noticed
BUCK_SIGHT_RADIUS = 160     # px — bucks farther than this are ignored
BODY_DISCOVER_RADIUS = 90   # px — walking this close reveals a corpse

# ── Behaviour tuning ───────────────────────────────────────────────────
FLEE_SPRINT_MULT = 1.5      # innocents sprint this much faster fleeing a known murderer
MURDERER_BURST_MULT = 1.35  # murderer speed burst while closing for the kill
MURDERER_ENGAGE_RADIUS = 110  # px — knife comes out and the burst begins
MURDERER_STALK_DIST = 150   # px — preferred shadowing distance before engaging
GUN_AVOID_RADIUS = 130      # px — murderer keeps away from a visible gun holder
SHERIFF_KITE_DIST = 70      # px — sheriff tries not to get closer than this
SUSPICION_FLEE_THRESHOLD = 0.55
SHERIFF_SHOOT_CONFIDENCE = 0.75  # suspicion needed to fire without a witnessed kill


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

        # Environment (overridden by RoundSession.set_environment; the
        # defaults match both shipped 800x600 maps for the legacy 2D path).
        self.map_w = 800
        self.map_h = 600
        self.pois = [
            (120, 120), (680, 120), (120, 480), (680, 480), (400, 300),
        ]

        # Knowledge / memory
        self.suspicious = {}            # player_id -> suspicion 0..1
        self.witnessed_killer_id = None  # hard knowledge of the murderer
        self.known_bodies = []          # [{"x", "y", "investigated"}]
        self.last_death_pos = None
        self._last_alive_count = None

        # Reaction / pacing state
        self.reaction_delay = 0
        self.action_cooldown = 0
        self.idle_until = 0
        self.panic_ticks = 0            # >0 while actively fleeing a known threat
        self.retreat_ticks = 0          # murderer cooling off after a kill / gun scare
        self.retreat_from = None
        self.commit_ticks = 0           # murderer committed to a chase (no dithering)

        # Goals
        self.group_target_id = None
        self.wander_goal = None
        self.buck_goal = None

        # 0..1 — how far the round clock has run down (fed by RoundSession).
        # The murderer takes bigger risks as time runs out.
        self.time_pressure = 0.0

        # Output channel read by Bot.update: >1 means "sprinting"
        self.move_speed_mult = 1.0

    # ------------------------------------------------------------------
    # Environment / lifecycle
    # ------------------------------------------------------------------

    def set_environment(self, map_data):
        """Learn map bounds and points of interest (called by RoundSession)."""
        self.map_w = map_data.get("width", 800)
        self.map_h = map_data.get("height", 600)
        pois = [(s["x"], s["y"]) for s in map_data.get("spawn_points", [])]
        for z in map_data.get("buck_spawn_zones", []):
            pois.append((z["x"] + z["w"] / 2.0, z["y"] + z["h"] / 2.0))
        if pois:
            self.pois = pois

    def reset_round(self):
        """Clear per-round memory (suspicion, witnesses, goals)."""
        self.suspicious.clear()
        self.witnessed_killer_id = None
        self.known_bodies = []
        self.last_death_pos = None
        self._last_alive_count = None
        self.reaction_delay = 0
        self.action_cooldown = 0
        self.idle_until = 0
        self.panic_ticks = 0
        self.retreat_ticks = 0
        self.retreat_from = None
        self.commit_ticks = 0
        self.group_target_id = None
        self.wander_goal = None
        self.buck_goal = None
        self.time_pressure = 0.0
        self.move_speed_mult = 1.0
        self.bot.knife_drawn = False

    # ------------------------------------------------------------------
    # Witness events (called by RoundSession / game_screen)
    # ------------------------------------------------------------------

    def on_witness_kill(self, killer_id, x, y):
        """This bot SAW the kill — it now knows who the murderer is."""
        if self.bot.role == "murderer" or killer_id == self.bot.id:
            return
        self.witnessed_killer_id = killer_id
        self._raise_suspicion(killer_id, 1.0)
        self.note_body(x, y)
        self.last_death_pos = (x, y)
        self.panic_ticks = max(self.panic_ticks, 240)
        # Human-like beat of shock before reacting
        self.reaction_delay = max(self.reaction_delay, random.randint(5, 15))

    def on_spot_knife(self, player_id):
        """This bot saw a drawn knife — knife holder is the murderer."""
        if self.bot.role == "murderer" or player_id == self.bot.id:
            return
        if self.witnessed_killer_id != player_id:
            self.reaction_delay = max(self.reaction_delay, random.randint(3, 10))
        self.witnessed_killer_id = player_id
        self._raise_suspicion(player_id, 1.0)
        self.panic_ticks = max(self.panic_ticks, 180)

    def note_body(self, x, y):
        """Remember a corpse position (sheriff investigates these)."""
        for b in self.known_bodies:
            if _dist(b["x"], b["y"], x, y) < 40:
                return
        self.known_bodies.append({"x": x, "y": y, "investigated": False})

    def on_witness_death(self, all_players, death_x, death_y, victim_id):
        """Called when this bot was near a death (legacy heuristic path).

        If the victim carries killer attribution (set by Player.try_kill)
        and this bot was close enough to see it, that becomes hard
        knowledge; otherwise fall back to blaming the nearest other player.
        """
        bot = self.bot
        if bot.role == "murderer":
            return
        self.note_body(death_x, death_y)
        self.last_death_pos = (death_x, death_y)

        victim = next((p for p in all_players if p.id == victim_id), None)
        killer_id = getattr(victim, "last_killer_id", None) if victim else None
        d_self = _dist(bot.x, bot.y, death_x, death_y)

        if killer_id and killer_id != bot.id and d_self < SIGHT_RADIUS:
            self.on_witness_kill(killer_id, death_x, death_y)
            return

        # Heuristic: blame the nearest other player to the body
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
            self._raise_suspicion(nearest.id, 0.6)
            self.reaction_delay = max(self.reaction_delay, random.randint(8, 20))

    # ------------------------------------------------------------------
    # Per-frame memory upkeep
    # ------------------------------------------------------------------

    def tick_memory(self, all_players, walls):
        """Update suspicion / pacing state (called each frame)."""
        bot = self.bot
        alive = [p for p in all_players if p.is_alive and p is not bot]
        alive_count = len(alive) + (1 if bot.is_alive else 0)

        if self._last_alive_count is None:
            self._last_alive_count = alive_count

        if alive_count < self._last_alive_count and bot.role != "murderer":
            # Someone died somewhere ("scream"). If we were close-ish but
            # didn't actually witness it, get mildly suspicious of whoever
            # is nearest — imperfect information, can be wrong.
            nearest_other = None
            best = 9999
            for p in alive:
                d = _dist(bot.x, bot.y, p.x, p.y)
                if d < best:
                    best = d
                    nearest_other = p
            if best < 220 and nearest_other:
                self._raise_suspicion(nearest_other.id, 0.3)

        self._last_alive_count = alive_count

        # Decay soft suspicion slowly; hard knowledge never decays
        for pid in list(self.suspicious):
            if pid == self.witnessed_killer_id:
                continue
            self.suspicious[pid] *= 0.998
            if self.suspicious[pid] < 0.05:
                del self.suspicious[pid]

        if self.panic_ticks > 0:
            self.panic_ticks -= 1

        # Innocents cluster: pick a "buddy" to follow sometimes
        if bot.role != "murderer" and random.random() < 0.002:
            others = [p for p in alive if p.id != bot.id]
            if others:
                self.group_target_id = random.choice(others).id

    def _raise_suspicion(self, pid, amount):
        self.suspicious[pid] = min(1.0, self.suspicious.get(pid, 0) + amount)

    # ------------------------------------------------------------------
    # Knowledge queries
    # ------------------------------------------------------------------

    def knows_murderer_identity(self, player):
        """True if this bot is confident *player* is the murderer."""
        if self.bot.role == "murderer":
            return player.role == "murderer"
        if self.witnessed_killer_id and player.id == self.witnessed_killer_id:
            return True
        return self.suspicious.get(player.id, 0) >= SHERIFF_SHOOT_CONFIDENCE

    def known_murderer(self, all_players):
        """Return the witnessed murderer Player if alive, else None."""
        if not self.witnessed_killer_id:
            return None
        return next(
            (p for p in all_players
             if p.id == self.witnessed_killer_id and p.is_alive),
            None,
        )

    def pick_suspect(self, all_players):
        """Best guess at the murderer for shooting / fleeing decisions."""
        bot = self.bot
        candidates = []
        for p in all_players:
            if p is bot or not p.is_alive:
                continue
            score = self.suspicious.get(p.id, 0)
            if self.witnessed_killer_id == p.id:
                score += 1.0
            if score > 0:
                candidates.append((score, p))
        if not candidates:
            return None
        candidates.sort(key=lambda x: -x[0])
        if candidates[0][0] < 0.15:
            return None
        return candidates[0][1]

    # ------------------------------------------------------------------
    # Steering helpers
    # ------------------------------------------------------------------

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
            if point_in_any_rect(tx, ty, walls, margin=10):
                dx -= rdx * 0.35
                dy -= rdy * 0.35
        return _norm(dx, dy)

    def _toward_point(self, tx, ty, walls):
        dx, dy = _norm(tx - self.bot.x, ty - self.bot.y)
        return self.steer_clear_of_walls(dx, dy, walls)

    def _away_from(self, tx, ty, walls):
        dx, dy = _norm(self.bot.x - tx, self.bot.y - ty)
        return self.steer_clear_of_walls(dx, dy, walls)

    def _wander(self, walls):
        """Purposeful wandering between points of interest with pauses."""
        bot = self.bot
        if self.wander_goal is None:
            if self.pois and random.random() < 0.75:
                gx, gy = random.choice(self.pois)
                # Don't pick the POI we're already standing on
                if _dist(bot.x, bot.y, gx, gy) < 60:
                    gx = random.randint(60, max(61, self.map_w - 60))
                    gy = random.randint(60, max(61, self.map_h - 60))
            else:
                gx = random.randint(60, max(61, self.map_w - 60))
                gy = random.randint(60, max(61, self.map_h - 60))
            self.wander_goal = (gx, gy)
        gx, gy = self.wander_goal
        if _dist(bot.x, bot.y, gx, gy) < 35:
            self.wander_goal = None
            # Linger at the point of interest like a player looking around
            self.idle_until = random.randint(20, 60)
            return _norm(random.uniform(-1, 1), random.uniform(-1, 1))
        return self._toward_point(gx, gy, walls)

    def nearest_buck(self, bucks):
        if not bucks:
            return None
        bot = self.bot
        best = None
        best_d = BUCK_SIGHT_RADIUS  # only "see" bucks within sight radius
        for item in bucks:
            if len(item) < 2:
                continue
            bx, by = item[0], item[1]
            d = _dist(bot.x, bot.y, bx, by)
            if d < best_d:
                best_d = d
                best = (bx, by)
        return best

    # ------------------------------------------------------------------
    # Top-level decision
    # ------------------------------------------------------------------

    def choose_direction(self, all_players, walls, dropped_gun_pos, bucks):
        """Return (dx, dy, want_shoot_dir or None)."""
        bot = self.bot
        self.move_speed_mult = 1.0

        if self.reaction_delay > 0:
            self.reaction_delay -= 1
            return bot.facing[0], bot.facing[1], None

        if self.idle_until > 0 and self.panic_ticks <= 0:
            self.idle_until -= 1
            return 0, 0, None

        if self.panic_ticks <= 0 and random.random() < 0.003:
            self.idle_until = random.randint(15, 45)

        if bot.role == "murderer":
            return self._murderer_dir(all_players, walls, bucks)
        if bot.role == "sheriff":
            return self._sheriff_dir(all_players, walls, dropped_gun_pos, bucks)
        return self._innocent_dir(all_players, walls, dropped_gun_pos, bucks)

    # ------------------------------------------------------------------
    # Murderer
    # ------------------------------------------------------------------

    def _murderer_dir(self, all_players, walls, bucks):
        bot = self.bot
        bot.knife_drawn = False

        targets = [
            p for p in all_players
            if p is not bot and p.is_alive and not getattr(p, "ghost", False)
        ]
        if not targets:
            return self._ret(self._wander(walls))

        # Back off from anyone visibly carrying the gun. This is a steering
        # response, not a hard flee — and as the clock runs down the
        # murderer accepts the risk (timer expiry means losing anyway).
        avoid_r = (GUN_AVOID_RADIUS + self.caution * 60) * (1.0 - 0.6 * self.time_pressure)
        for armed in targets:
            if not getattr(armed, "has_gun", False):
                continue
            d = _dist(bot.x, bot.y, armed.x, armed.y)
            if d < avoid_r and has_line_of_sight(bot.x, bot.y, armed.x, armed.y, walls):
                return self._ret(self._away_from(armed.x, armed.y, walls))

        # Cool off (act innocent) right after a kill or a gun scare
        if self.retreat_ticks > 0:
            self.retreat_ticks -= 1
            if self.retreat_from:
                return self._ret(self._away_from(self.retreat_from[0],
                                                 self.retreat_from[1], walls))
            return self._ret(self._wander(walls))

        # Pick the most isolated victim (MM2-style stalking)
        best = None
        best_score = -1e9
        best_witnesses = 0
        for t in targets:
            d = _dist(bot.x, bot.y, t.x, t.y)
            nearby_allies = sum(
                1 for p in targets
                if p is not t and _dist(t.x, t.y, p.x, p.y) < 130
            )
            isolation = max(0, 3 - nearby_allies)
            score = isolation * 40 - d * 0.25 + self.aggression * 30
            if d <= KNIFE_RANGE:
                score += 200
            if score > best_score:
                best_score = score
                best = t
                best_witnesses = nearby_allies

        d = _dist(bot.x, bot.y, best.x, best.y)

        # Crowd discipline: aggressive personalities tolerate one witness,
        # cautious ones want the victim completely alone. With only one
        # target left there is nothing to wait for, and as the clock runs
        # out the murderer loses (timer expiry = innocents win), so risk
        # tolerance climbs with time pressure.
        crowd_limit = 1 if self.aggression >= 0.7 else 0
        if self.time_pressure > 0.5:
            crowd_limit += 1
        if self.time_pressure > 0.8:
            crowd_limit += 2  # desperate endgame: attack regrouped survivors
        engage = best_witnesses <= crowd_limit or len(targets) == 1

        if engage:
            if d <= MURDERER_ENGAGE_RADIUS:
                # Knife out, burst in for the kill
                bot.knife_drawn = True
                self.move_speed_mult = MURDERER_BURST_MULT
                if d <= KNIFE_RANGE and bot.try_kill(best):
                    bot.knife_drawn = False
                    self.move_speed_mult = 1.0
                    # Slip away from the body — but linger less when the
                    # clock (or an aggressive streak) demands more kills.
                    cooloff = 70 + int((1 - self.aggression) * 60)
                    self.retreat_ticks = int(cooloff * (1.0 - 0.6 * self.time_pressure))
                    self.retreat_from = (best.x, best.y)
                    return self._ret(self._away_from(best.x, best.y, walls))
            return self._ret(self._toward_point(best.x, best.y, walls))

        # Too many witnesses: shadow the target from a distance and blend in
        if d > MURDERER_STALK_DIST + 40:
            return self._ret(self._toward_point(best.x, best.y, walls))
        if d < MURDERER_STALK_DIST - 30:
            return self._ret(self._away_from(best.x, best.y, walls))
        if bucks and random.random() < 0.4 * (1 - self.aggression):
            return self._ret(self._toward_point(bucks[0], bucks[1], walls))
        return self._ret(self._wander(walls))

    # ------------------------------------------------------------------
    # Sheriff
    # ------------------------------------------------------------------

    def _sheriff_dir(self, all_players, walls, dropped_gun_pos, bucks):
        bot = self.bot
        shoot_dir = None

        if self.action_cooldown > 0:
            self.action_cooldown -= 1

        # Identify the target: hard knowledge first, strong suspicion second
        target = self.known_murderer(all_players)
        confident = target is not None
        if target is None:
            suspect = self.pick_suspect(all_players)
            if suspect and self.suspicious.get(suspect.id, 0) >= SHERIFF_SHOOT_CONFIDENCE:
                target = suspect
                confident = True
            else:
                target = suspect  # low confidence — track but don't shoot

        if bot.has_gun and target:
            d = _dist(bot.x, bot.y, target.x, target.y)
            los = has_line_of_sight(bot.x, bot.y, target.x, target.y, walls)
            if confident and los and d <= bot.shoot_range and self.action_cooldown <= 0:
                self.action_cooldown = random.randint(25, 50)
                if random.random() < self.accuracy:
                    shoot_dir = _norm(target.x - bot.x, target.y - bot.y)
            if confident:
                # Chase, but kite: keep out of knife range
                self.move_speed_mult = 1.2
                if d < SHERIFF_KITE_DIST:
                    return self._ret(self._away_from(target.x, target.y, walls),
                                     shoot_dir)
                if d > bot.shoot_range * 0.75 or not los:
                    return self._ret(self._toward_point(target.x, target.y, walls),
                                     shoot_dir)
                # In the pocket — strafe sideways while lining up the shot
                fx, fy = _norm(target.x - bot.x, target.y - bot.y)
                side = 1 if (id(target) % 2 == 0) else -1
                return self._ret(
                    self.steer_clear_of_walls(-fy * side, fx * side, walls),
                    shoot_dir,
                )
            # Unconfirmed suspect close by: hold ground / back up warily
            if d < SHERIFF_KITE_DIST + 30:
                return self._ret(self._away_from(target.x, target.y, walls),
                                 shoot_dir)

        if not bot.has_gun:
            # Recover the gun — urgently if the murderer is identified
            if dropped_gun_pos:
                gx, gy = dropped_gun_pos
                if self.witnessed_killer_id:
                    self.move_speed_mult = 1.3
                return self._ret(self._toward_point(gx, gy, walls), shoot_dir)
            # Unarmed with a known murderer nearby: survive like an innocent
            threat = self.known_murderer(all_players)
            if threat:
                d = _dist(bot.x, bot.y, threat.x, threat.y)
                if d < bot.flee_range + self.caution * 60:
                    self.move_speed_mult = FLEE_SPRINT_MULT
                    return self._ret(self._away_from(threat.x, threat.y, walls))

        # Investigate the nearest unexamined body
        body = self._nearest_unexamined_body()
        if body:
            d = _dist(bot.x, bot.y, body["x"], body["y"])
            if d < 30:
                body["investigated"] = True
                self.idle_until = random.randint(25, 50)  # kneel and look around
            else:
                return self._ret(self._toward_point(body["x"], body["y"], walls),
                                 shoot_dir)

        if bucks and random.random() < self.greed * 0.5:
            return self._ret(self._toward_point(bucks[0], bucks[1], walls), shoot_dir)

        return self._ret(self._wander(walls), shoot_dir)

    def _nearest_unexamined_body(self):
        bot = self.bot
        best = None
        best_d = 1e9
        for b in self.known_bodies:
            if b["investigated"]:
                continue
            d = _dist(bot.x, bot.y, b["x"], b["y"])
            if d < best_d:
                best_d = d
                best = b
        return best

    # ------------------------------------------------------------------
    # Innocent
    # ------------------------------------------------------------------

    def _innocent_dir(self, all_players, walls, dropped_gun_pos, bucks):
        bot = self.bot

        # 1) Known murderer → sprint away, drifting toward other survivors
        known = self.known_murderer(all_players)
        if known:
            d = _dist(bot.x, bot.y, known.x, known.y)
            flee_dist = bot.flee_range + self.caution * 70
            if d < flee_dist:
                self.move_speed_mult = FLEE_SPRINT_MULT
                fx, fy = _norm(bot.x - known.x, bot.y - known.y)
                ally = self._nearest_survivor(all_players, exclude_id=known.id)
                if ally:
                    ax, ay = _norm(ally.x - bot.x, ally.y - bot.y)
                    # Only blend toward the ally if that doesn't run us
                    # back into the murderer
                    if ax * fx + ay * fy > -0.2:
                        fx, fy = _norm(fx * 0.65 + ax * 0.35, fy * 0.65 + ay * 0.35)
                return self._ret(self.steer_clear_of_walls(fx, fy, walls))
            # Out of immediate danger: regroup with the nearest survivor
            ally = self._nearest_survivor(all_players, exclude_id=known.id)
            if ally and _dist(bot.x, bot.y, ally.x, ally.y) > 70:
                return self._ret(self._toward_point(ally.x, ally.y, walls))

        # 2) Soft suspicion → keep distance, walking pace
        if not known:
            suspect = self.pick_suspect(all_players)
            if suspect and self.suspicious.get(suspect.id, 0) >= SUSPICION_FLEE_THRESHOLD:
                d = _dist(bot.x, bot.y, suspect.x, suspect.y)
                if d < bot.flee_range * 0.8:
                    return self._ret(self._away_from(suspect.x, suspect.y, walls))

        # 3) Grab the dropped gun (become the hero)
        if dropped_gun_pos and not bot.has_gun:
            gx, gy = dropped_gun_pos
            if _dist(bot.x, bot.y, gx, gy) < 180:
                return self._ret(self._toward_point(gx, gy, walls))

        # 4) Visible bucks: commit to one and collect it
        if self.buck_goal and bucks is None:
            self.buck_goal = None
        if bucks:
            if self.buck_goal is None and random.random() < 0.5 + self.greed * 0.4:
                self.buck_goal = (bucks[0], bucks[1])
            elif self.buck_goal is not None:
                self.buck_goal = (bucks[0], bucks[1])  # retarget nearest
        if self.buck_goal:
            gx, gy = self.buck_goal
            if _dist(bot.x, bot.y, gx, gy) < 12:
                self.buck_goal = None
            else:
                return self._ret(self._toward_point(gx, gy, walls))

        # 5) Follow a buddy now and then (groups read as social/alive)
        if self.group_target_id:
            buddy = next(
                (p for p in all_players
                 if p.id == self.group_target_id and p.is_alive),
                None,
            )
            if buddy:
                d = _dist(bot.x, bot.y, buddy.x, buddy.y)
                if d > 50:
                    return self._ret(self._toward_point(buddy.x, buddy.y, walls))
                if d < 35:
                    self.group_target_id = None
            else:
                self.group_target_id = None

        # 6) Default: purposeful POI wandering
        return self._ret(self._wander(walls))

    def _nearest_survivor(self, all_players, exclude_id=None):
        bot = self.bot
        best = None
        best_d = 1e9
        for p in all_players:
            if p is bot or not p.is_alive or p.id == exclude_id:
                continue
            d = _dist(bot.x, bot.y, p.x, p.y)
            if d < best_d:
                best_d = d
                best = p
        return best

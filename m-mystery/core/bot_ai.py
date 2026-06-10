"""
Utility-based bot brain — pure Python, no engine imports, no API keys.

Bots act on imperfect information, like real players:

  * Innocents wander between map points of interest, drift toward visible
    bucks, regroup with other survivors, and flee at a sprint once they have
    actually seen the murderer kill someone or spotted a drawn knife.
  * The sheriff patrols points of interest, investigates bodies, and only
    chases/shoots once confident about the murderer's identity.
  * The murderer commits to hunting one isolated victim at a time, closes
    in with a knife lunge, backs off from anyone visibly holding the gun,
    and varies aggression with its personality (aggression/caution/greed/
    accuracy from data/bots.json).

All hard knowledge flows through witness events (RoundSession calls
``on_witness_kill`` / ``on_spot_knife``) or soft proximity heuristics —
bots never read another player's hidden role directly.

Navigation: every destination is reached through ``_toward_point``, which
walks straight when there is line of sight and otherwise follows an A*
path over the cached per-map NavGrid (core/nav.py).  Local steering
(``_steer``) probes ahead and rotates to slide along walls instead of
pushing into them, and a stuck detector breaks the rare remaining pins.
"""
import math
import random

from core.bullet import BULLET_SPEED
from core.nav import get_nav_grid
from core.player import KNIFE_RANGE
from core.rect import has_line_of_sight, point_in_any_rect

# ── Perception tuning ──────────────────────────────────────────────────
SIGHT_RADIUS = 180          # px — how far a bot can witness a kill
KNIFE_SPOT_RADIUS = 140     # px — how far a drawn knife is noticed
BUCK_SIGHT_RADIUS = 160     # px — bucks farther than this are ignored
BODY_DISCOVER_RADIUS = 90   # px — walking this close reveals a corpse

# ── Behaviour tuning ───────────────────────────────────────────────────
FLEE_SPRINT_MULT = 1.5      # innocents sprint this much faster fleeing a known murderer
MURDERER_BURST_MULT = 1.45  # murderer speed burst while closing for the kill
MURDERER_ENGAGE_RADIUS = 130  # px — knife comes out and the burst begins
MURDERER_LUNGE_RANGE = 58   # px — final lunge distance before the stab
MURDERER_STALK_DIST = 150   # px — preferred shadowing distance before engaging
GUN_AVOID_RADIUS = 110      # px — murderer keeps away from a visible gun holder
SHERIFF_KITE_DIST = 70      # px — sheriff tries not to get closer than this
SUSPICION_FLEE_THRESHOLD = 0.55
SHERIFF_SHOOT_CONFIDENCE = 0.75  # suspicion needed to fire without a witnessed kill

# ── Hunting persistence / pacing ───────────────────────────────────────
HUNT_COMMIT_TICKS = 600     # ~10 s locked on one victim (no target dithering)
HUNT_FRUSTRATION_TICKS = 1100  # ~18 s without a kill -> drop crowd caution
MURDERER_OPENING_TICKS = 360   # base "blend in" period before the first strike
KILL_COOLOFF_TICKS = 240       # base time acting innocent after a kill

# ── Navigation tuning ──────────────────────────────────────────────────
REPATH_INTERVAL = 18        # min ticks between A* queries per bot (~3/sec)
GOAL_DRIFT_REPATH = 45      # px the goal may move before forcing a repath
WAYPOINT_RADIUS = 16        # px — a waypoint closer than this counts as reached
STUCK_WINDOW = 45           # ticks between stuck checks (~0.75 s)
STUCK_DIST = 8.0            # px — moving less than this per window = pinned


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
        self.hunt_target_id = None      # murderer's committed victim

        # 0..1 — how far the round clock has run down (fed by RoundSession).
        # The murderer takes bigger risks as time runs out.
        self.time_pressure = 0.0

        # Output channel read by Bot.update: >1 means "sprinting"
        self.move_speed_mult = 1.0

        # Navigation state (NavGrid is built lazily from the walls list and
        # cached globally per wall layout — see core/nav.py).
        self._nav = None
        self._nav_walls_id = None
        self._path = []                 # remaining pixel waypoints
        self._path_goal = None          # goal the current path was built for
        self._repath_timer = 0
        self._flee_goal = None
        self._flee_timer = 0
        self._ticks_since_kill = 0
        self._murderer_ticks = 0
        self._stuck_ref = None
        self._stuck_timer = 0
        self._unstick_dir = None
        self._unstick_ticks = 0
        self._aim_track = None          # (target_id, x, y, vx, vy) velocity memory
        self._was_confident = False     # sheriff: had a confirmed target last tick

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
        # New map geometry — invalidate any cached navigation state
        self._nav = None
        self._nav_walls_id = None
        self._path = []
        self._path_goal = None

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
        self.hunt_target_id = None
        self.time_pressure = 0.0
        self.move_speed_mult = 1.0
        self._path = []
        self._path_goal = None
        self._repath_timer = 0
        self._flee_goal = None
        self._flee_timer = 0
        self._ticks_since_kill = 0
        self._murderer_ticks = 0
        self._stuck_ref = None
        self._stuck_timer = 0
        self._unstick_dir = None
        self._unstick_ticks = 0
        self._aim_track = None
        self._was_confident = False
        self.bot.knife_drawn = False

    def _ensure_nav(self, walls):
        """Build / fetch the shared NavGrid for the current wall layout."""
        if self._nav is not None and self._nav_walls_id == id(walls):
            return self._nav
        self._nav = get_nav_grid(self.map_w, self.map_h, walls)
        self._nav_walls_id = id(walls)
        return self._nav

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

        self._tick_stuck()

        # Innocents cluster: pick a "buddy" to follow sometimes
        if bot.role != "murderer" and random.random() < 0.002:
            others = [p for p in alive if p.id != bot.id]
            if others:
                self.group_target_id = random.choice(others).id

    def _tick_stuck(self):
        """Detect a bot pinned against geometry and break it free."""
        bot = self.bot
        if self._unstick_ticks > 0:
            self._unstick_ticks -= 1
        if self.idle_until > 0 or self.reaction_delay > 0:
            # Standing still on purpose — not stuck
            self._stuck_ref = (bot.x, bot.y)
            self._stuck_timer = 0
            return
        if self._stuck_ref is None:
            self._stuck_ref = (bot.x, bot.y)
            self._stuck_timer = 0
            return
        self._stuck_timer += 1
        if self._stuck_timer < STUCK_WINDOW:
            return
        if _dist(bot.x, bot.y, self._stuck_ref[0], self._stuck_ref[1]) < STUCK_DIST:
            # Pinned: throw away cached goals/paths and sidestep randomly
            self._path = []
            self._path_goal = None
            self._repath_timer = 0
            self.wander_goal = None
            self._flee_goal = None
            ang = random.uniform(0, 2 * math.pi)
            self._unstick_dir = (math.cos(ang), math.sin(ang))
            self._unstick_ticks = 14
        self._stuck_ref = (bot.x, bot.y)
        self._stuck_timer = 0

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
    # Steering / navigation helpers
    # ------------------------------------------------------------------

    def _ret(self, direction, shoot_dir=None):
        """Normalize to (dx, dy, shoot_dir)."""
        dx, dy = direction
        return dx, dy, shoot_dir

    def _probe_clear(self, dx, dy, probe, walls):
        """True if walking *probe* px along (dx, dy) stays out of walls."""
        bot = self.bot
        for t in (0.5, 1.0):
            px = bot.x + dx * probe * t
            py = bot.y + dy * probe * t
            if point_in_any_rect(px, py, walls, margin=10):
                return False
        return True

    def _steer(self, dx, dy, walls, probe=26):
        """Probe ahead; when blocked, rotate to the nearest clear heading.

        This makes bots slide along walls instead of pushing into them.
        """
        dx, dy = _norm(dx, dy)
        if dx == 0 and dy == 0:
            return 0.0, 0.0
        if self._probe_clear(dx, dy, probe, walls):
            return dx, dy
        for ang in (0.45, -0.45, 0.9, -0.9, 1.4, -1.4, 2.0, -2.0, 2.6, -2.6):
            ca, sa = math.cos(ang), math.sin(ang)
            rdx = dx * ca - dy * sa
            rdy = dx * sa + dy * ca
            if self._probe_clear(rdx, rdy, probe, walls):
                return rdx, rdy
        return -dx, -dy

    def steer_clear_of_walls(self, dx, dy, walls, probe=28):
        """Back-compat wrapper around the probe-and-slide steering."""
        return self._steer(dx, dy, walls, probe)

    def _toward_point(self, tx, ty, walls):
        """Head to (tx, ty): straight when visible, A* path when not."""
        bot = self.bot
        if self._repath_timer > 0:
            self._repath_timer -= 1

        # Straight shot available — drop the path and walk direct.
        if has_line_of_sight(bot.x, bot.y, tx, ty, walls, step=10.0):
            self._path = []
            self._path_goal = None
            return self._steer(tx - bot.x, ty - bot.y, walls)

        goal_moved = (
            self._path_goal is None
            or _dist(self._path_goal[0], self._path_goal[1], tx, ty)
            > GOAL_DRIFT_REPATH
        )
        if goal_moved:
            self._path = []
        if not self._path and self._repath_timer <= 0:
            nav = self._ensure_nav(walls)
            self._path = nav.find_path(bot.x, bot.y, tx, ty)
            self._path_goal = (tx, ty)
            self._repath_timer = REPATH_INTERVAL

        while self._path and _dist(
            bot.x, bot.y, self._path[0][0], self._path[0][1]
        ) < WAYPOINT_RADIUS:
            self._path.pop(0)

        if self._path:
            wx, wy = self._path[0]
            return self._steer(wx - bot.x, wy - bot.y, walls)
        # No path yet (repath rate-limited) — steer roughly toward the goal
        return self._steer(tx - bot.x, ty - bot.y, walls)

    def _away_from(self, tx, ty, walls):
        """Local retreat: step away from a point, sliding along walls."""
        return self._steer(self.bot.x - tx, self.bot.y - ty, walls)

    def _flee_from(self, tx, ty, walls):
        """Purposeful flight: run (pathfinding) to a refuge far from the threat."""
        bot = self.bot
        if self._flee_timer > 0:
            self._flee_timer -= 1
        goal = self._flee_goal
        if goal is not None:
            reached = _dist(bot.x, bot.y, goal[0], goal[1]) < 40
            compromised = _dist(tx, ty, goal[0], goal[1]) < 120
            if reached or compromised:
                goal = None
                self._flee_goal = None
        if goal is None and self._flee_timer <= 0:
            goal = self._pick_flee_goal(tx, ty)
            self._flee_goal = goal
            self._flee_timer = 45
        if goal is not None:
            return self._toward_point(goal[0], goal[1], walls)
        return self._away_from(tx, ty, walls)

    def _pick_flee_goal(self, tx, ty):
        """Refuge point: far from the threat, not too far from the bot."""
        bot = self.bot
        w, h = self.map_w, self.map_h
        candidates = list(self.pois) + [
            (70, 70), (w - 70, 70), (70, h - 70), (w - 70, h - 70),
            (w / 2.0, h / 2.0),
        ]
        best = None
        best_score = -1e9
        for cx, cy in candidates:
            score = _dist(cx, cy, tx, ty) - 0.7 * _dist(cx, cy, bot.x, bot.y)
            if score > best_score:
                best_score = score
                best = (cx, cy)
        return best

    def _random_open_point(self, walls):
        """Random map point that is not inside (or hugging) a wall."""
        for _attempt in range(12):
            gx = random.randint(60, max(61, self.map_w - 60))
            gy = random.randint(60, max(61, self.map_h - 60))
            if not point_in_any_rect(gx, gy, walls, margin=24):
                return gx, gy
        return self.map_w / 2.0, self.map_h / 2.0

    def _wander(self, walls):
        """Purposeful wandering between points of interest with pauses."""
        bot = self.bot
        if self.wander_goal is None:
            if self.pois and random.random() < 0.75:
                gx, gy = random.choice(self.pois)
                # Don't pick the POI we're already standing on
                if _dist(bot.x, bot.y, gx, gy) < 60:
                    gx, gy = self._random_open_point(walls)
            else:
                gx, gy = self._random_open_point(walls)
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

        # Breaking out of a wall pin overrides everything for a few ticks
        if self._unstick_ticks > 0 and self._unstick_dir is not None:
            dx, dy = self._steer(
                self._unstick_dir[0], self._unstick_dir[1], walls
            )
            return dx, dy, None

        if (bot.role != "murderer" and self.panic_ticks <= 0
                and random.random() < 0.003):
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
        self._ticks_since_kill += 1
        self._murderer_ticks += 1

        targets = [
            p for p in all_players
            if p is not bot and p.is_alive and not getattr(p, "ghost", False)
        ]
        if not targets:
            return self._ret(self._wander(walls))

        # Cool off (act innocent) right after a kill or a gun scare
        if self.retreat_ticks > 0:
            self.retreat_ticks -= 1
            if self.retreat_from:
                return self._ret(self._flee_from(
                    self.retreat_from[0], self.retreat_from[1], walls))
            return self._ret(self._wander(walls))

        # Desperation: a long dry spell or the clock running down overrides
        # caution — timer expiry means the murderer loses anyway.
        desperate = (
            self.time_pressure > 0.55
            or self._ticks_since_kill > HUNT_FRUSTRATION_TICKS
            or len(targets) == 1
        )

        # Stay committed to one victim instead of dithering between targets
        target = None
        if self.hunt_target_id is not None and self.commit_ticks > 0:
            target = next(
                (p for p in targets if p.id == self.hunt_target_id), None)
        if self.commit_ticks > 0:
            self.commit_ticks -= 1
        if target is None:
            target = self._pick_victim(targets)
            self.hunt_target_id = target.id
            self.commit_ticks = HUNT_COMMIT_TICKS

        d = _dist(bot.x, bot.y, target.x, target.y)
        engage_r = MURDERER_ENGAGE_RADIUS + self.aggression * 40

        # Back off from a visible gun holder — unless desperate or already
        # closing on the victim (committed to the kill).
        if not desperate and d > engage_r * 0.6:
            avoid_r = (
                (GUN_AVOID_RADIUS + self.caution * 50)
                * (1.0 - 0.6 * self.time_pressure)
            )
            for armed in targets:
                if not getattr(armed, "has_gun", False):
                    continue
                ad = _dist(bot.x, bot.y, armed.x, armed.y)
                if ad < avoid_r and has_line_of_sight(
                        bot.x, bot.y, armed.x, armed.y, walls):
                    return self._ret(self._flee_from(armed.x, armed.y, walls))

        # Crowd discipline: aggressive personalities tolerate one witness,
        # cautious ones want the victim completely alone. Risk tolerance
        # climbs as the clock runs out; desperation drops the act entirely.
        witnesses = sum(
            1 for p in targets
            if p is not target and _dist(target.x, target.y, p.x, p.y) < 130
        )
        crowd_limit = 1 if self.aggression >= 0.7 else 0
        if self.time_pressure > 0.5:
            crowd_limit += 1
        if self.time_pressure > 0.8:
            crowd_limit += 2  # desperate endgame: attack regrouped survivors
        engage = desperate or witnesses <= crowd_limit

        # Opening act: blend in for a while before the first strike so the
        # round breathes (cautious personalities wait longer).
        opening = MURDERER_OPENING_TICKS * (0.6 + self.caution * 1.4)
        if (not desperate and self._ticks_since_kill == self._murderer_ticks
                and self._murderer_ticks < opening):
            engage = False

        if engage:
            if d <= engage_r:
                # Knife out, burst in for the kill
                bot.knife_drawn = True
                self.move_speed_mult = MURDERER_BURST_MULT
                if (d <= MURDERER_LUNGE_RANGE
                        and bot.attack_cooldown <= 0
                        and has_line_of_sight(
                            bot.x, bot.y, target.x, target.y, walls)):
                    self._lunge(target, walls)
                    if bot.try_kill(target):
                        bot.knife_drawn = False
                        self.move_speed_mult = 1.0
                        self.hunt_target_id = None
                        self.commit_ticks = 0
                        self._ticks_since_kill = 0
                        # Slip away from the body — but linger less when the
                        # clock (or an aggressive streak) demands more kills.
                        cooloff = (KILL_COOLOFF_TICKS
                                   + int((1 - self.aggression) * 240))
                        self.retreat_ticks = int(
                            cooloff * (1.0 - 0.7 * self.time_pressure))
                        self.retreat_from = (target.x, target.y)
                        return self._ret(self._flee_from(
                            target.x, target.y, walls))
                # Serpentine while charging: a straight burst is free food
                # for a leading sheriff shot.
                if d > MURDERER_LUNGE_RANGE:
                    dx, dy = self._toward_point(target.x, target.y, walls)
                    weave = 0.45 * math.sin(self._murderer_ticks * 0.18)
                    return self._ret(_norm(dx - dy * weave, dy + dx * weave))
            return self._ret(self._toward_point(target.x, target.y, walls))

        # Too many witnesses: shadow the target from a distance and blend in
        if d > MURDERER_STALK_DIST + 40:
            return self._ret(self._toward_point(target.x, target.y, walls))
        if d < MURDERER_STALK_DIST - 30:
            return self._ret(self._away_from(target.x, target.y, walls))
        if bucks and random.random() < 0.4 * (1 - self.aggression):
            return self._ret(self._toward_point(bucks[0], bucks[1], walls))
        return self._ret(self._wander(walls))

    def _pick_victim(self, targets):
        """Most isolated victim, preferring nearby ones (MM2-style stalking)."""
        bot = self.bot
        best = None
        best_score = -1e9
        for t in targets:
            d = _dist(bot.x, bot.y, t.x, t.y)
            nearby_allies = sum(
                1 for p in targets
                if p is not t and _dist(t.x, t.y, p.x, p.y) < 130
            )
            score = max(0, 3 - nearby_allies) * 40 - d * 0.3
            if d <= KNIFE_RANGE:
                score += 200
            if score > best_score:
                best_score = score
                best = t
        return best

    def _lunge(self, target, walls):
        """Close the last few pixels for the stab (mirrors the human lunge)."""
        bot = self.bot
        d = _dist(bot.x, bot.y, target.x, target.y)
        if d <= KNIFE_RANGE:
            return
        ndx, ndy = _norm(target.x - bot.x, target.y - bot.y)
        remaining = d - KNIFE_RANGE + 2
        while remaining > 0:
            step = min(8.0, remaining)
            bot.move(ndx * step, ndy * step, walls)
            remaining -= step

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

        if target is not None:
            self._track_target_velocity(target)

        # Newly confident: a "draw and aim" beat before the first shot
        if confident and not self._was_confident:
            self.action_cooldown = max(self.action_cooldown,
                                       random.randint(15, 30))
        self._was_confident = confident

        if bot.has_gun and target:
            d = _dist(bot.x, bot.y, target.x, target.y)
            los = has_line_of_sight(bot.x, bot.y, target.x, target.y, walls)
            if (confident and los and d <= bot.shoot_range
                    and self.action_cooldown <= 0
                    and self._clear_shot(target, all_players)):
                self.action_cooldown = random.randint(30, 55)
                shoot_dir = self._aim_at(target)
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
                side = 1 if (sum(ord(c) for c in target.id) % 2 == 0) else -1
                return self._ret(
                    self._steer(-fy * side, fx * side, walls),
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
                    return self._ret(self._flee_from(threat.x, threat.y, walls))

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

    def _track_target_velocity(self, target):
        """Per-tick velocity estimate of the shoot target (EMA-smoothed).

        ``facing`` flickers with steering and ignores sprint bursts, so the
        sheriff remembers where the target actually moved instead.
        """
        track = self._aim_track
        if track is None or track[0] != target.id:
            self._aim_track = (target.id, target.x, target.y, 0.0, 0.0)
            return
        _tid, px, py, vx, vy = track
        nvx = 0.65 * vx + 0.35 * (target.x - px)
        nvy = 0.65 * vy + 0.35 * (target.y - py)
        self._aim_track = (target.id, target.x, target.y, nvx, nvy)

    def _aim_at(self, target):
        """Intercept aim: fire where the target will be, with skill jitter."""
        bot = self.bot
        rx, ry = target.x - bot.x, target.y - bot.y
        vx, vy = 0.0, 0.0
        track = self._aim_track
        if track is not None and track[0] == target.id:
            vx, vy = track[3], track[4]

        # Solve |R + V t| = BULLET_SPEED * t for the flight time t (frames)
        s2 = float(BULLET_SPEED * BULLET_SPEED)
        a = vx * vx + vy * vy - s2
        b = 2.0 * (rx * vx + ry * vy)
        c = rx * rx + ry * ry
        t = None
        if abs(a) > 1e-6:
            disc = b * b - 4.0 * a * c
            if disc >= 0:
                root = math.sqrt(disc)
                for cand in ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a)):
                    if cand > 0 and (t is None or cand < t):
                        t = cand
        if t is None:
            t = math.sqrt(c) / float(BULLET_SPEED)

        ax, ay = rx + vx * t, ry + vy * t
        ang = math.atan2(ay, ax)
        ang += random.gauss(0.0, 0.03 + 0.18 * (1.0 - self.accuracy))
        return math.cos(ang), math.sin(ang)

    def _clear_shot(self, target, all_players):
        """True if no bystander stands near the firing line.

        A bullet stopped by a non-murderer is wasted (the gun drops where
        it lands), so the sheriff holds fire instead of spraying.
        """
        bot = self.bot
        sx, sy = target.x - bot.x, target.y - bot.y
        seg_len = math.sqrt(sx * sx + sy * sy)
        if seg_len < 1.0:
            return True
        ux, uy = sx / seg_len, sy / seg_len
        for p in all_players:
            if p is bot or p is target or not p.is_alive:
                continue
            px, py = p.x - bot.x, p.y - bot.y
            along = px * ux + py * uy
            if along < 0 or along > seg_len:
                continue
            if abs(px * uy - py * ux) < 18:
                return False
        return True

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

        # 1) Known murderer → sprint to a refuge on the far side of the map
        known = self.known_murderer(all_players)
        if known:
            d = _dist(bot.x, bot.y, known.x, known.y)
            flee_dist = bot.flee_range + self.caution * 70
            if d < flee_dist:
                self.move_speed_mult = FLEE_SPRINT_MULT
                return self._ret(self._flee_from(known.x, known.y, walls))
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

"""Headless simulation tests for core/ (no pygame, no ursina).

Builds the standard 1 human + 3 bots roster (mirrors main.py), loads
data/maps/map_01.json, and runs RoundSession tick-by-tick at dt=1/60 with
the human idle, for up to 3 simulated rounds.

Because the human idles, a bot is always forced to be the murderer so the
rounds can actually resolve. The three-round run asserts that:
  * at least 2 of 3 rounds end decisively BEFORE the timer expires,
  * at least 2 kills happen across the rounds,
  * bots keep moving (average displacement per second above a floor, and
    never more than ~3 consecutive near-stationary seconds — i.e. no bot
    grinds against a wall),
  * the frozen Player/Bot/RoundSession API surface is intact.

Run:
    "/Users/aritro/Downloads/Diya-Sonu Game/venv/bin/python" tests/test_core_sim.py
Also works under pytest.
"""
import json
import math
import os
import random
import sys
import tempfile

# Run from the repo root so core/ and data/ resolve
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

import core.currency as currency
from core.bot import Bot
from core.bullet import Bullet
from core.player import Player, KNIFE_RANGE
from core.rect import Rect, point_in_any_rect
from core.roles import assign_roles
from core.round import RoundManager
from core.round_session import RoundSession, ROUND_DURATION_SECONDS

DT = 1.0 / 60.0

# Keep the real saves/wallets.json untouched
currency.WALLETS_PATH = os.path.join(tempfile.gettempdir(), "mm_test_wallets.json")
if os.path.exists(currency.WALLETS_PATH):
    os.remove(currency.WALLETS_PATH)


def load_map():
    with open("data/maps/map_01.json") as f:
        return json.load(f)


def make_roster(spawns):
    """Standard roster, copied from main.py."""
    human = Player(
        "p1", "Guest_You", (44, 181, 232),
        body_color=(44, 181, 232),
        shirt_color=(30, 140, 200),
        pants_color=(35, 55, 120),
        skin_color=(255, 204, 153),
    )
    bot_roster = [
        ("bot_1", "xXShadowBladeXx", "aggressive",
         (229, 80, 120), (200, 50, 90), (60, 30, 80), (40, 20, 30)),
        ("bot_2", "CoolSheriff_Jake", "sharp",
         (244, 197, 66), (220, 170, 40), (50, 50, 90), (80, 60, 30)),
        ("bot_3", "NoobSurvivor42", "cautious",
         (100, 200, 255), (70, 160, 230), (40, 70, 110), (60, 100, 140)),
    ]
    bots = []
    for i, (bid, name, pers, accent, shirt, pants, hair) in enumerate(bot_roster):
        bots.append(Bot(
            bid, name, accent, spawns[i + 1]["x"], spawns[i + 1]["y"],
            personality_id=pers,
            body_color=hair, shirt_color=shirt, pants_color=pants,
        ))
    return human, bots


def reset_players(all_players, spawns):
    """Mirror of main.py reset_players."""
    for i, p in enumerate(all_players):
        p.is_alive = True
        p.has_knife = False
        p.has_gun = False
        p.role = ""
        p.attack_cooldown = 0
        p.m_bucks_this_round = 0
        p.x = spawns[i]["x"]
        p.y = spawns[i]["y"]
        if p.is_bot:
            p.ticks_left = 0
            p.dx = 0
            p.dy = 0
            p.brain.reset_round()
        p.stamina = p.max_stamina


FROZEN_PLAYER_FIELDS = [
    ("id", str), ("name", str), ("x", (int, float)), ("y", (int, float)),
    ("is_alive", bool), ("is_bot", bool), ("role", str),
    ("has_knife", bool), ("has_gun", bool),
    ("stamina", (int, float)), ("max_stamina", (int, float)),
    ("attack_cooldown", int), ("m_bucks_this_round", int),
    ("anim_phase", (int, float)), ("facing", tuple), ("is_moving", bool),
    ("skin_color", tuple), ("shirt_color", tuple), ("pants_color", tuple),
    ("body_color", tuple),
]


def check_frozen_player_api(p):
    for field, types in FROZEN_PLAYER_FIELDS:
        assert hasattr(p, field), "missing frozen field %s on %s" % (field, p.id)
        assert isinstance(getattr(p, field), types), (
            "frozen field %s has type %s" % (field, type(getattr(p, field))))
    if p.is_bot:
        for field in ("ticks_left", "dx", "dy", "brain"):
            assert hasattr(p, field), "missing frozen Bot field %s" % field
        assert callable(p.brain.reset_round)


def check_frozen_session_api(session):
    assert isinstance(session.kill_log, list)
    assert isinstance(session.bucks, list)
    for b in session.bucks:
        assert len(b) == 3 and all(isinstance(v, (int, float)) for v in b)
    assert session.dropped_gun_pos is None or len(session.dropped_gun_pos) == 2
    for b in session.bullets:
        assert hasattr(b, "x") and hasattr(b, "y") and hasattr(b, "is_active")
    assert "frames_left" in session.screen_shake
    assert isinstance(session.alive_count, int)
    assert isinstance(session.round_manager.remaining, float)
    assert isinstance(session.round_manager.get_time_string(), str)


def gun_economy_count(session):
    """Guns in play: held + on the ground + in flight. Must never exceed 1."""
    held = sum(1 for p in session.players if p.has_gun)
    ground = 1 if session.dropped_gun_pos is not None else 0
    flying = sum(1 for b in session.bullets if b.is_active)
    return held + ground + flying


# ─────────────────────────────────────────────────────────────────────────
# Full-round simulation
# ─────────────────────────────────────────────────────────────────────────

# Movement-health thresholds (the human idles; these apply to bots only).
MIN_AVG_DISPLACEMENT = 25.0   # px per second, averaged over the round
MAX_STUCK_SECONDS = 3         # max consecutive seconds moving < STUCK_EPS px
STUCK_EPS = 6.0


def force_bot_murderer(all_players, human):
    """The human idles in these tests, so a bot must carry the knife."""
    if human.role != "murderer":
        return
    bot = random.choice([p for p in all_players if p.is_bot])
    human.role = bot.role
    human.has_knife = bot.has_knife
    human.has_gun = bot.has_gun
    bot.role = "murderer"
    bot.has_knife = True
    bot.has_gun = False


def run_round(all_players, human, map_data, wallet, seed):
    random.seed(seed)
    reset_players(all_players, map_data["spawn_points"])
    assign_roles(all_players)
    force_bot_murderer(all_players, human)
    session = RoundSession(all_players, map_data, wallet, human)

    # Bucks must never spawn inside a wall
    for bx, by, _val in session.bucks:
        assert not point_in_any_rect(bx, by, session.walls), (
            "buck spawned inside a wall at (%s, %s)" % (bx, by))
    assert len(session.bucks) > 0

    check_frozen_session_api(session)
    for p in all_players:
        check_frozen_player_api(p)

    max_ticks = int(ROUND_DURATION_SECONDS * 60) + 20
    winner = None
    seen_victims = set()
    kill_entries = []
    names = {p.name for p in all_players}

    bots = [p for p in all_players if p.is_bot]
    last_pos = {p.id: (p.x, p.y) for p in bots}
    displacements = {p.id: [] for p in bots}  # px moved in each alive second

    for tick in range(1, max_ticks + 1):
        session.tick_human_move(DT, 0, 0, False)  # human idles
        winner = session.tick_simulation(DT)

        # Sample bot movement once per simulated second
        if tick % 60 == 0:
            for p in bots:
                lx, ly = last_pos[p.id]
                if p.is_alive:
                    displacements[p.id].append(
                        math.hypot(p.x - lx, p.y - ly))
                last_pos[p.id] = (p.x, p.y)

        # Drain the kill feed like the frontends do
        for entry in session.kill_log:
            assert isinstance(entry, tuple) and len(entry) == 3, (
                "malformed kill_log entry %r" % (entry,))
            killer, victim, weapon = entry
            assert killer in names, "unknown killer %r" % killer
            assert victim in names, "unknown victim %r" % victim
            assert weapon in ("knife", "gun"), "unknown weapon %r" % weapon
            assert victim not in seen_victims, (
                "duplicate kill_log entry for victim %r" % victim)
            seen_victims.add(victim)
            kill_entries.append(entry)
        session.kill_log.clear()

        assert gun_economy_count(session) <= 1, "gun duplicated!"

        # Stamina stays in range for everyone
        for p in all_players:
            assert 0.0 <= p.stamina <= p.max_stamina

        if winner is not None:
            break

    assert winner in ("murderer", "innocents"), (
        "no winner by timer expiry (winner=%r)" % winner)
    assert session.round_manager.remaining >= 0.0

    # Every kill-feed victim is actually dead, and every knife/gun death
    # got exactly one feed entry.
    dead = {p.name for p in all_players if not p.is_alive}
    assert set(v for (_k, v, _w) in kill_entries) <= dead
    assert len(kill_entries) == len(dead), (
        "kill feed (%d entries) does not match deaths (%d)"
        % (len(kill_entries), len(dead)))

    # --- Movement health: bots never grind against walls -----------------
    for p in bots:
        samples = displacements[p.id]
        if len(samples) < 3:
            continue  # died almost immediately — too little data to judge
        avg = sum(samples) / len(samples)
        assert avg >= MIN_AVG_DISPLACEMENT, (
            "bot %s barely moved (avg %.1f px/s < %.1f) — stuck on walls?"
            % (p.name, avg, MIN_AVG_DISPLACEMENT))
        stuck_run = 0
        for d in samples:
            stuck_run = stuck_run + 1 if d < STUCK_EPS else 0
            assert stuck_run <= MAX_STUCK_SECONDS, (
                "bot %s stood still / pushed a wall for >%d consecutive "
                "seconds" % (p.name, MAX_STUCK_SECONDS))

    decisive = session.round_manager.remaining > 0.5

    bot_bucks = sum(p.m_bucks_this_round for p in all_players if p.is_bot)
    for p in all_players:
        wallet.add_round_earnings(p.id, p.m_bucks_this_round)
    wallet.save()
    return winner, kill_entries, bot_bucks, decisive


def test_three_rounds():
    map_data = load_map()
    human, bots = make_roster(map_data["spawn_points"])
    all_players = [human] + bots
    wallet = currency.WalletManager()

    total_bot_bucks = 0
    total_kills = 0
    decisive_rounds = 0
    winners = []
    for rnd, seed in enumerate((7, 8, 9), start=1):
        winner, kills, bot_bucks, decisive = run_round(
            all_players, human, map_data, wallet, seed)
        winners.append(winner)
        total_bot_bucks += bot_bucks
        total_kills += len(kills)
        decisive_rounds += 1 if decisive else 0
        print("[TEST] round %d -> winner=%s decisive=%s kills=%s bot_bucks=%d"
              % (rnd, winner, decisive, kills, bot_bucks))

    assert decisive_rounds >= 2, (
        "only %d/3 rounds ended before the timer — bots too passive"
        % decisive_rounds)
    assert total_kills >= 2, (
        "only %d kills across 3 rounds — murderer bot is not hunting"
        % total_kills)
    assert total_bot_bucks > 0, "bots never collected any bucks across 3 rounds"
    print("[TEST] winners:", winners,
          "| decisive rounds:", decisive_rounds,
          "| total kills:", total_kills,
          "| total bot bucks:", total_bot_bucks)


# ─────────────────────────────────────────────────────────────────────────
# Win-condition edge cases
# ─────────────────────────────────────────────────────────────────────────

def _mini_players():
    ps = []
    for i, role in enumerate(["murderer", "sheriff", "innocent", "innocent"]):
        p = Player("e%d" % i, "E%d" % i, (10, 10, 10))
        p.role = role
        ps.append(p)
    return ps


def test_win_conditions():
    rm = RoundManager(120)

    # In progress
    ps = _mini_players()
    assert rm.check_win_conditions(ps) is None

    # Murderer alive, everyone else dead -> murderer
    ps = _mini_players()
    for p in ps[1:]:
        p.is_alive = False
    assert rm.check_win_conditions(ps) == "murderer"

    # Murderer dead -> innocents
    ps = _mini_players()
    ps[0].is_alive = False
    assert rm.check_win_conditions(ps) == "innocents"

    # EVERYONE dead simultaneously -> murderer didn't survive -> innocents
    ps = _mini_players()
    for p in ps:
        p.is_alive = False
    assert rm.check_win_conditions(ps) == "innocents"

    # Timer expiry with murderer + innocents alive -> innocents
    rm2 = RoundManager(0.01)
    rm2.tick(1.0)
    ps = _mini_players()
    assert rm2.remaining == 0.0
    assert rm2.check_win_conditions(ps) == "innocents"
    print("[TEST] win-condition edge cases OK")


# ─────────────────────────────────────────────────────────────────────────
# Dropped-gun regression: no infinite gun duplication at the sheriff corpse
# ─────────────────────────────────────────────────────────────────────────

def test_dropped_gun_no_duplication():
    random.seed(42)
    map_data = load_map()
    human, bots = make_roster(map_data["spawn_points"])
    all_players = [human] + bots
    wallet = currency.WalletManager()
    reset_players(all_players, map_data["spawn_points"])

    # Fixed roles for determinism
    human.role = "innocent"
    bots[0].role = "murderer"
    bots[0].has_knife = True
    bots[1].role = "sheriff"
    bots[1].has_gun = True
    bots[2].role = "innocent"

    session = RoundSession(all_players, map_data, wallet, human)

    # Sheriff dies holding the gun
    bots[1].is_alive = False
    session._check_dropped_gun()
    assert session.dropped_gun_pos is not None, "gun did not drop from corpse"
    assert bots[1].has_gun is False
    assert gun_economy_count(session) == 1

    # An innocent walks onto it
    gx, gy = session.dropped_gun_pos
    bots[2].x, bots[2].y = gx, gy
    session._check_dropped_gun()
    assert bots[2].has_gun is True
    assert session.dropped_gun_pos is None

    # Regression: the old code re-dropped a gun at the sheriff's corpse
    # every frame the slot was empty.
    for _ in range(10):
        session._check_dropped_gun()
    assert session.dropped_gun_pos is None, "gun duplicated at sheriff corpse"
    assert gun_economy_count(session) == 1

    # The innocent fires and misses: the gun lands where the bullet dies
    bullet = bots[2].try_shoot((1, 0))
    assert bullet is not None and bots[2].has_gun is False
    session.bullets.append(bullet)
    for _ in range(200):
        session._update_bullets()
        if not session.bullets:
            break
    assert not session.bullets
    assert session.dropped_gun_pos is not None, "spent gun never re-dropped"
    assert gun_economy_count(session) == 1
    print("[TEST] dropped-gun economy OK")


# ─────────────────────────────────────────────────────────────────────────
# Witness system: a bot that sees a kill knows the murderer
# ─────────────────────────────────────────────────────────────────────────

def test_witness_kill_attribution():
    random.seed(1)
    map_data = load_map()
    human, bots = make_roster(map_data["spawn_points"])
    all_players = [human] + bots
    wallet = currency.WalletManager()
    reset_players(all_players, map_data["spawn_points"])

    murderer, victim, witness = bots[0], bots[1], bots[2]
    human.role = "innocent"
    murderer.role = "murderer"
    murderer.has_knife = True
    victim.role = "innocent"
    witness.role = "innocent"

    # Stage: victim right next to the murderer, witness 100 px away in the
    # open; human far away in the opposite corner (out of sight).
    murderer.x, murderer.y = 600, 450
    victim.x, victim.y = 620, 450
    witness.x, witness.y = 620, 550
    human.x, human.y = 60, 60

    session = RoundSession(all_players, map_data, wallet, human)

    assert murderer.try_kill(victim) is True
    session._check_deaths_witness()

    assert witness.brain.witnessed_killer_id == murderer.id, (
        "witness did not identify the murderer")
    assert human_far_brainless_ok(human)
    # Kill feed: exactly one, correctly attributed
    assert session.kill_log == [(murderer.name, victim.name, "knife")]
    # Corpse recorded
    assert len(session.corpses) == 1
    print("[TEST] witness attribution OK")


def human_far_brainless_ok(human):
    return not hasattr(human, "brain") or human.brain is None


def main():
    test_win_conditions()
    test_dropped_gun_no_duplication()
    test_witness_kill_attribution()
    test_three_rounds()
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()

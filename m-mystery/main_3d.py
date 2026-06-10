"""
M Mystery — 3D mode (Roblox-style third person).
Single-file build: stylized daylight world, baked "fake" lighting, R6 rig with
limb pivots, attack/death animations, procedural sounds, particles, kill feed,
and a polished HUD.

Install: pip install ursina pygame
Run:     python main_3d.py
"""
from ursina import *
import json, os, math, random, struct, wave

from core.player import Player
from core.bot import Bot
from core.roles import assign_roles
from core.currency import WalletManager
from core.coords import pixel_to_world, PIXEL_SCALE
from core.round_session import RoundSession

SMOKE_TEST = os.environ.get("M3D_SMOKE") == "1"


# ── Colour helpers ──────────────────────────────────────────────────────
# ursina 5.2's color.rgb/rgba auto-divides by 255 only when a component
# exceeds 1, which silently breaks low/float values.  c255 is unambiguous:
# it always takes 0-255 ints.

def c255(r, g, b, a=255):
    return color.Color(r / 255, g / 255, b / 255, a / 255)


def _c(rgb):
    return c255(rgb[0], rgb[1], rgb[2])


ROLE_COLORS = {
    "murderer": (235, 64, 96),
    "sheriff":  (250, 200, 70),
    "innocent": (80, 196, 255),
}

ROLE_BLURBS = {
    "murderer": "Eliminate everyone. Don't get caught.",
    "sheriff":  "Find the murderer and take the shot.",
    "innocent": "Survive the round and collect M-Bucks.",
}

GRASS_A   = c255(124, 200, 84)
GRASS_B   = c255(108, 184, 72)
GRASS_OUT_A = c255(94, 162, 64)
GRASS_OUT_B = c255(84, 150, 58)
PATH_A    = c255(228, 206, 158)
PATH_B    = c255(214, 190, 142)
SHADOW_COL = c255(20, 30, 20, 95)


# ── Procedural sound generation (stdlib only) ───────────────────────────

SOUND_DIR = os.path.join("assets", "sounds")
_SR = 22050


def _write_wav(path, samples):
    frames = bytearray()
    for s in samples:
        if s > 1.0:
            s = 1.0
        elif s < -1.0:
            s = -1.0
        frames += struct.pack("<h", int(s * 32000))
    wf = wave.open(path, "wb")
    try:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_SR)
        wf.writeframes(bytes(frames))
    finally:
        wf.close()


def _gen_shoot():
    rng = random.Random(11)
    out = []
    for i in range(int(_SR * 0.25)):
        t = i / _SR
        noise = (rng.random() * 2 - 1) * math.exp(-t * 30)
        thump = math.sin(2 * math.pi * 95 * t) * math.exp(-t * 14)
        out.append(0.7 * noise + 0.55 * thump)
    return out


def _gen_stab():
    rng = random.Random(22)
    out = []
    dur = 0.16
    for i in range(int(_SR * dur)):
        t = i / _SR
        env = min(t * 120.0, 1.0) * math.exp(-t * 26)
        sweep = math.sin(2 * math.pi * (1100 - 3200 * t) * t)
        noise = rng.random() * 2 - 1
        out.append((0.5 * noise + 0.35 * sweep) * env)
    return out


def _gen_coin():
    out = []
    for freq, dur in ((988.0, 0.07), (1318.5, 0.17)):
        for i in range(int(_SR * dur)):
            t = i / _SR
            out.append(0.45 * math.sin(2 * math.pi * freq * t) * math.exp(-t * 13))
    return out


def _gen_death():
    out = []
    phase = 0.0
    dur = 0.5
    for i in range(int(_SR * dur)):
        t = i / _SR
        freq = 320 - 400 * t
        phase += 2 * math.pi * freq / _SR
        v = math.sin(phase) + 0.3 * math.sin(2 * phase)
        out.append(0.5 * v * math.exp(-t * 6))
    return out


def _gen_jump():
    out = []
    phase = 0.0
    dur = 0.18
    for i in range(int(_SR * dur)):
        t = i / _SR
        freq = 250 + 2200 * t
        phase += 2 * math.pi * freq / _SR
        out.append(0.4 * math.sin(phase) * math.sin(math.pi * t / dur))
    return out


def _gen_click():
    out = []
    for i in range(int(_SR * 0.05)):
        t = i / _SR
        out.append(0.5 * math.sin(2 * math.pi * 1700 * t) * math.exp(-t * 120))
    return out


def _gen_win():
    out = []
    notes = ((523.25, 0.13), (659.25, 0.13), (783.99, 0.13), (1046.5, 0.42))
    for freq, dur in notes:
        for i in range(int(_SR * dur)):
            t = i / _SR
            v = math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(4 * math.pi * freq * t)
            out.append(0.35 * v * math.exp(-t * 5))
    return out


def _gen_ambient():
    rng = random.Random(7)
    out = []
    dur = 3.0
    for i in range(int(_SR * dur)):
        t = i / _SR
        v = 0.05 * math.sin(2 * math.pi * 52 * t)
        v += 0.035 * math.sin(2 * math.pi * 87 * t + 1.7)
        v += 0.03 * (rng.random() * 2 - 1) * (0.6 + 0.4 * math.sin(2 * math.pi * 0.5 * t))
        fade = min(1.0, t / 0.2, (dur - t) / 0.2)
        out.append(v * fade)
    return out


_SOUND_BUILDERS = {
    "shoot": _gen_shoot,
    "stab": _gen_stab,
    "coin": _gen_coin,
    "death": _gen_death,
    "jump": _gen_jump,
    "click": _gen_click,
    "win": _gen_win,
    "ambient": _gen_ambient,
}


def ensure_sound_files():
    try:
        os.makedirs(SOUND_DIR, exist_ok=True)
    except OSError:
        return
    for name, builder in _SOUND_BUILDERS.items():
        path = os.path.join(SOUND_DIR, name + ".wav")
        if os.path.exists(path):
            continue
        try:
            _write_wav(path, builder())
        except Exception as exc:
            print(f"[SOUND] could not generate {name}: {exc}")


class SoundBank:
    """Tiny wrapper so audio failure can never crash the game."""

    def __init__(self):
        self.sounds = {}
        self.ambient = None

    def load(self):
        for name in _SOUND_BUILDERS:
            if name == "ambient":
                continue
            path = os.path.join(SOUND_DIR, name + ".wav")
            try:
                if os.path.exists(path):
                    self.sounds[name] = Audio(path, autoplay=False)
            except Exception as exc:
                print(f"[SOUND] could not load {name}: {exc}")

    def start_ambient(self):
        path = os.path.join(SOUND_DIR, "ambient.wav")
        try:
            if os.path.exists(path):
                self.ambient = Audio(path, loop=True, autoplay=True, volume=0.30)
        except Exception as exc:
            print(f"[SOUND] ambient failed: {exc}")

    def play(self, name, volume=1.0):
        snd = self.sounds.get(name)
        if not snd:
            return
        try:
            snd.stop(destroy=False)
            snd.volume = volume
            snd.play()
        except Exception:
            pass


# ── Particle system ─────────────────────────────────────────────────────

class Particle(Entity):
    def __init__(self, position, velocity, color_start, color_end,
                 size_start=0.15, size_end=0.02, lifetime=0.8, gravity=True, **kwargs):
        super().__init__(
            model="sphere", position=position,
            scale=size_start, color=color_start, **kwargs,
        )
        self.velocity = velocity
        self.color_start = color_start
        self.color_end = color_end
        self.size_start = size_start
        self.size_end = size_end
        self.lifetime = lifetime
        self.age = 0.0
        self.apply_gravity = gravity

    def update(self):
        dt = time.dt
        self.age += dt
        if self.age >= self.lifetime:
            destroy(self)
            return
        t = self.age / self.lifetime
        self.position += self.velocity * dt
        if self.apply_gravity:
            self.velocity.y -= 6 * dt
        self.scale = lerp(self.size_start, self.size_end, t)
        self.color = lerp(self.color_start, self.color_end, t)
        self.alpha = 1 - t


def spawn_death_particles(position):
    for _ in range(18):
        vel = Vec3(random.uniform(-4, 4), random.uniform(2, 6), random.uniform(-4, 4))
        Particle(
            position=position, velocity=vel,
            color_start=c255(255, 60, 50),
            color_end=c255(120, 16, 10),
            size_start=random.uniform(0.12, 0.25),
            size_end=0.02, lifetime=random.uniform(0.5, 1.0),
        )
    for _ in range(7):
        vel = Vec3(random.uniform(-1.5, 1.5), random.uniform(1.5, 3.5), random.uniform(-1.5, 1.5))
        Particle(
            position=position + Vec3(0, 0.3, 0), velocity=vel,
            color_start=c255(220, 220, 225),
            color_end=c255(160, 160, 170),
            size_start=random.uniform(0.3, 0.55),
            size_end=0.8, lifetime=random.uniform(0.6, 1.1),
            gravity=False,
        )


def spawn_coin_particles(position):
    for _ in range(9):
        vel = Vec3(random.uniform(-2, 2), random.uniform(3, 6), random.uniform(-2, 2))
        Particle(
            position=position, velocity=vel,
            color_start=c255(255, 220, 60),
            color_end=c255(200, 140, 20),
            size_start=random.uniform(0.08, 0.15),
            size_end=0.01, lifetime=random.uniform(0.4, 0.8),
        )


def spawn_muzzle_flash(position):
    flash = Entity(model="sphere", position=position, scale=0.32, color=c255(255, 244, 170))
    glow = Entity(
        model="quad", texture="radial_gradient", billboard=True,
        position=position, scale=1.8, color=c255(255, 210, 90, 200),
    )
    destroy(flash, delay=0.06)
    destroy(glow, delay=0.09)


def spawn_bullet_impact(position):
    for _ in range(5):
        vel = Vec3(random.uniform(-2, 2), random.uniform(0.5, 2), random.uniform(-2, 2))
        Particle(
            position=position, velocity=vel,
            color_start=c255(255, 160, 40),
            color_end=c255(130, 60, 16),
            size_start=random.uniform(0.06, 0.1),
            size_end=0.01, lifetime=random.uniform(0.2, 0.5),
        )


def spawn_jump_puff(position):
    for _ in range(6):
        vel = Vec3(random.uniform(-1.6, 1.6), random.uniform(0.3, 1.0), random.uniform(-1.6, 1.6))
        Particle(
            position=position, velocity=vel,
            color_start=c255(235, 235, 230, 220),
            color_end=c255(200, 200, 195, 0),
            size_start=random.uniform(0.15, 0.3),
            size_end=0.45, lifetime=random.uniform(0.3, 0.5),
            gravity=False,
        )


# ── Screen effects ──────────────────────────────────────────────────────

class ScreenEffects:
    def __init__(self):
        self.overlay = Entity(
            parent=camera.ui, model="quad",
            color=c255(0, 0, 0, 0), scale=(2, 2),
        )
        self.shake_intensity = 0.0
        self.shake_duration = 0.0
        self.shake_timer = 0.0
        self._blood_cooldown = 0.0

    def blood_flash(self):
        if self._blood_cooldown > 0:
            return
        self._blood_cooldown = 0.4
        self.overlay.color = c255(200, 0, 0, 110)
        self.overlay.animate("color", c255(200, 0, 0, 0), duration=0.4, curve=curve.out_expo)

    def white_flash(self):
        self.overlay.color = c255(255, 255, 255, 90)
        self.overlay.animate("color", c255(255, 255, 255, 0), duration=0.15, curve=curve.out_expo)

    def screen_shake(self, intensity, duration):
        self.shake_intensity = intensity
        self.shake_duration = duration
        self.shake_timer = duration

    def update(self):
        if self._blood_cooldown > 0:
            self._blood_cooldown -= time.dt
        if self.shake_timer > 0:
            self.shake_timer -= time.dt
            camera.position += Vec3(
                random.uniform(-self.shake_intensity, self.shake_intensity),
                random.uniform(-self.shake_intensity * 0.5, self.shake_intensity * 0.5),
                random.uniform(-self.shake_intensity, self.shake_intensity),
            )
        elif self.shake_timer < 0:
            self.shake_timer = 0


# ── Kill feed ───────────────────────────────────────────────────────────

class KillFeed:
    def __init__(self):
        self.entries = []

    def add(self, killer_name, victim_name, weapon="knife"):
        tag = "[GUN]" if weapon == "gun" else "[KNIFE]"
        col = c255(255, 196, 90) if weapon == "gun" else c255(255, 110, 110)
        t = Text(
            parent=camera.ui,
            text=f"{killer_name}  {tag}  {victim_name}",
            color=col, scale=0.95,
            position=(0.74, 0.40 - len(self.entries) * 0.045),
            origin=(0.5, 0), background=True,
        )
        try:
            t.background.color = c255(10, 12, 24, 170)
        except Exception:
            pass
        t.animate("x", 0.62, duration=0.18, curve=curve.out_quad)
        self.entries.append({"text": t, "life": 4.0})

    def update(self):
        for entry in self.entries[:]:
            entry["life"] -= time.dt
            if 0 < entry["life"] < 1.0:
                entry["text"].alpha = entry["life"]
            if entry["life"] <= 0:
                destroy(entry["text"])
                self.entries.remove(entry)

    def clear(self):
        for entry in self.entries:
            destroy(entry["text"])
        self.entries.clear()


# ── Environment helpers (baked, unlit, stylized) ────────────────────────

def _blob_shadow(pos, radius, alpha=95):
    return Entity(
        model="quad", texture="circle", rotation_x=90,
        position=Vec3(pos.x, 0.025, pos.z),
        scale=radius * 2,
        color=c255(20, 30, 20, alpha),
    )


def create_tree(pos, size=1.0):
    parts = [_blob_shadow(pos, 1.5 * size, 80)]
    trunk_h = 2.4 * size
    parts.append(Entity(
        model="cube", position=pos + Vec3(0, trunk_h / 2, 0),
        scale=(0.5 * size, trunk_h, 0.5 * size),
        color=c255(120, 78, 46), texture="white_cube",
    ))
    layers = (
        (2.6, 2.6, c255(52, 158, 62)),
        (2.0, 3.25, c255(66, 180, 72)),
        (1.35, 3.85, c255(92, 206, 88)),
    )
    for w, y_off, col in layers:
        parts.append(Entity(
            model="cube", position=pos + Vec3(0, y_off * size, 0),
            scale=(w * size, 0.55 * size, w * size),
            color=col, texture="white_cube",
        ))
    return parts


def create_lamppost(pos):
    parts = [_blob_shadow(pos, 0.55, 70)]
    parts.append(Entity(
        model="cube", position=pos + Vec3(0, 1.9, 0),
        scale=(0.14, 3.8, 0.14), color=c255(70, 78, 96), texture="white_cube",
    ))
    parts.append(Entity(
        model="cube", position=pos + Vec3(0, 3.9, 0),
        scale=(0.42, 0.34, 0.42), color=c255(255, 226, 120), texture="white_cube",
    ))
    parts.append(Entity(
        model="cube", position=pos + Vec3(0, 4.12, 0),
        scale=(0.5, 0.1, 0.5), color=c255(55, 62, 78), texture="white_cube",
    ))
    # Emissive-looking glow halo + warm light pool baked onto the ground.
    parts.append(Entity(
        model="quad", texture="radial_gradient", billboard=True,
        position=pos + Vec3(0, 3.9, 0), scale=2.4,
        color=c255(255, 214, 110, 130),
    ))
    parts.append(Entity(
        model="quad", texture="radial_gradient", rotation_x=90,
        position=pos + Vec3(0, 0.04, 0), scale=5.0,
        color=c255(255, 218, 120, 60),
    ))
    return parts


def create_barrel(pos):
    parts = [_blob_shadow(pos, 0.55, 80)]
    parts.append(Entity(
        model="cube", position=pos + Vec3(0, 0.45, 0),
        scale=(0.7, 0.9, 0.7), color=c255(168, 112, 58), texture="white_cube",
    ))
    for y in (0.22, 0.68):
        parts.append(Entity(
            model="cube", position=pos + Vec3(0, y, 0),
            scale=(0.76, 0.07, 0.76), color=c255(96, 102, 116), texture="white_cube",
        ))
    return parts


def create_crate(pos, s=1.0):
    parts = [_blob_shadow(pos, 0.75 * s, 80)]
    parts.append(Entity(
        model="cube", position=pos + Vec3(0, 0.5 * s, 0),
        scale=(1.0 * s, 1.0 * s, 1.0 * s),
        color=c255(198, 152, 92), texture="white_cube",
    ))
    parts.append(Entity(
        model="cube", position=pos + Vec3(0, 0.5 * s, 0),
        scale=(1.04 * s, 0.16 * s, 1.04 * s),
        color=c255(160, 116, 64), texture="white_cube",
    ))
    return parts


def create_rock(pos, s=1.0):
    parts = [_blob_shadow(pos, 0.7 * s, 70)]
    parts.append(Entity(
        model="sphere", position=pos + Vec3(0, 0.28 * s, 0),
        scale=(1.1 * s, 0.6 * s, 0.9 * s),
        color=c255(150, 158, 168),
    ))
    parts.append(Entity(
        model="sphere", position=pos + Vec3(0.4 * s, 0.18 * s, 0.25 * s),
        scale=(0.55 * s, 0.35 * s, 0.5 * s),
        color=c255(130, 138, 150),
    ))
    return parts


def create_bush(pos, s=1.0):
    parts = [_blob_shadow(pos, 0.6 * s, 60)]
    for off, ps, col in (
        (Vec3(0, 0.3, 0), 0.85, c255(64, 172, 70)),
        (Vec3(0.3, 0.25, 0.2), 0.6, c255(80, 192, 80)),
        (Vec3(-0.3, 0.22, -0.1), 0.55, c255(56, 158, 64)),
    ):
        parts.append(Entity(
            model="sphere", position=pos + off * s, scale=ps * s, color=col,
        ))
    return parts


def create_flower(pos, col):
    parts = [Entity(
        model="quad", texture="circle", rotation_x=90,
        position=pos + Vec3(0, 0.05, 0), scale=0.28, color=col,
    )]
    parts.append(Entity(
        model="quad", texture="circle", rotation_x=90,
        position=pos + Vec3(0, 0.06, 0), scale=0.1, color=c255(255, 240, 150),
    ))
    return parts


def create_cloud(pos, s=1.0):
    root = Entity(position=pos)
    for off, cs in (
        (Vec3(0, 0, 0), Vec3(6, 1.6, 3.4)),
        (Vec3(2.6, 0.7, 0.6), Vec3(3.6, 1.4, 2.6)),
        (Vec3(-2.4, 0.5, -0.5), Vec3(3.2, 1.2, 2.4)),
    ):
        Entity(
            parent=root, model="cube", position=off * s, scale=cs * s,
            color=c255(255, 255, 255, 235),
        )
    return root


# ── 3D Avatar ───────────────────────────────────────────────────────────

class Avatar3D(Entity):
    """R6 rig with limb pivots, walk/idle/attack/death animation and a
    blob shadow.  Root origin sits at the feet."""

    def __init__(self, player, **kwargs):
        super().__init__(**kwargs)
        self.player = player
        self.model = None
        self.collider = None

        skin  = _c(player.skin_color)
        shirt = _c(player.shirt_color)
        pants = _c(player.pants_color)
        hair  = _c(player.body_color)
        shirt_dark = _c(tuple(max(0, c - 35) for c in player.shirt_color))

        # Body group: bobs/leans without affecting root transform.
        self.body_root = Entity(parent=self)

        self.torso = self._box(self.body_root, (0, 1.15, 0), (0.9, 0.95, 0.45), shirt, "torso")
        self._box(self.torso, (0, -0.4, 0), (1.02, 0.22, 1.04), shirt_dark, "belt")
        self.head = self._box(self.body_root, (0, 1.92, 0), (0.55, 0.55, 0.55), skin, "head")
        self.hair = self._box(self.head, (0, 0.42, -0.06), (1.08, 0.45, 1.1), hair, "hair")

        # Limb pivots at shoulder / hip height so swings look natural.
        self.l_arm_pivot = Entity(parent=self.body_root, position=(-0.62, 1.58, 0))
        self.r_arm_pivot = Entity(parent=self.body_root, position=(0.62, 1.58, 0))
        self.l_leg_pivot = Entity(parent=self.body_root, position=(-0.23, 0.92, 0))
        self.r_leg_pivot = Entity(parent=self.body_root, position=(0.23, 0.92, 0))

        self.l_arm = self._box(self.l_arm_pivot, (0, -0.42, 0), (0.3, 0.85, 0.3), skin, "l_arm")
        self.r_arm = self._box(self.r_arm_pivot, (0, -0.42, 0), (0.3, 0.85, 0.3), skin, "r_arm")
        self._box(self.l_arm, (0, 0.28, 0), (1.1, 0.45, 1.1), shirt, "l_sleeve")
        self._box(self.r_arm, (0, 0.28, 0), (1.1, 0.45, 1.1), shirt, "r_sleeve")
        self.l_leg = self._box(self.l_leg_pivot, (0, -0.46, 0), (0.34, 0.92, 0.34), pants, "l_leg")
        self.r_leg = self._box(self.r_leg_pivot, (0, -0.46, 0), (0.34, 0.92, 0.34), pants, "r_leg")

        shoe_col = c255(46, 50, 60)
        self._box(self.l_leg_pivot, (0, -0.9, 0.06), (0.38, 0.18, 0.52), shoe_col, "l_shoe")
        self._box(self.r_leg_pivot, (0, -0.9, 0.06), (0.38, 0.18, 0.52), shoe_col, "r_shoe")

        # Face (positions relative to head cube).
        eye_white = c255(250, 250, 255)
        self._box(self.head, (-0.17, 0.08, 0.5), (0.2, 0.22, 0.08), eye_white, "l_eye")
        self._box(self.head, (0.17, 0.08, 0.5), (0.2, 0.22, 0.08), eye_white, "r_eye")
        self._box(self.head, (-0.17, 0.06, 0.54), (0.1, 0.12, 0.06), c255(30, 32, 40), "l_pupil")
        self._box(self.head, (0.17, 0.06, 0.54), (0.1, 0.12, 0.06), c255(30, 32, 40), "r_pupil")
        self._box(self.head, (0, -0.26, 0.5), (0.32, 0.07, 0.06), c255(200, 92, 92), "mouth")

        # Blob shadow at the feet (kept on the ground during jumps).
        self.shadow = Entity(
            parent=self, model="quad", texture="circle", rotation_x=90,
            position=(0, 0.03, 0), scale=1.5, color=SHADOW_COL,
        )

        self.nametag = Text(
            text=player.name, parent=self, y=2.55, scale=8,
            origin=(0, 0), color=color.white, billboard=True, background=True,
        )

        self.knife_entity = None
        self.gun_entity_w = None
        self.role_ring = None
        self.sync_weapons()

        self.dead_tilt = 0
        self.is_alive = True
        self._idle_t = random.uniform(0, 6.28)
        self._swing_blend = 0.0
        self._attack_anim = 0.0

    def _box(self, parent, pos, scale, col, name):
        return Entity(
            parent=parent, model="cube", color=col,
            position=pos, scale=scale, collider=None, name=name,
            texture="white_cube",
        )

    # ── Weapons ──────────────────────────────────────────────────────
    def sync_weapons(self):
        p = self.player
        if p.has_knife and not self.knife_entity:
            self.knife_entity = Entity(parent=self.r_arm_pivot, name="knife")
            Entity(parent=self.knife_entity, model="cube", color=c255(120, 86, 50),
                   position=(0, -0.85, 0.1), scale=(0.09, 0.16, 0.22), texture="white_cube")
            Entity(parent=self.knife_entity, model="cube", color=c255(225, 230, 240),
                   position=(0, -0.85, 0.5), scale=(0.05, 0.13, 0.55), texture="white_cube")
            Entity(parent=self.knife_entity, model="cube", color=c255(190, 196, 210),
                   position=(0, -0.79, 0.5), scale=(0.05, 0.05, 0.45), texture="white_cube")
        elif not p.has_knife and self.knife_entity:
            destroy(self.knife_entity)
            self.knife_entity = None

        if p.has_gun and not self.gun_entity_w:
            self.gun_entity_w = Entity(parent=self.r_arm_pivot, name="gun")
            Entity(parent=self.gun_entity_w, model="cube", color=c255(58, 60, 74),
                   position=(0, -0.8, 0.28), scale=(0.11, 0.18, 0.34), texture="white_cube")
            Entity(parent=self.gun_entity_w, model="cube", color=c255(44, 46, 58),
                   position=(0, -0.74, 0.58), scale=(0.06, 0.06, 0.3), texture="white_cube")
            Entity(parent=self.gun_entity_w, model="cube", color=c255(150, 110, 60),
                   position=(0, -0.9, 0.16), scale=(0.09, 0.16, 0.1), texture="white_cube")
        elif not p.has_gun and self.gun_entity_w:
            destroy(self.gun_entity_w)
            self.gun_entity_w = None

    # ── Animation ────────────────────────────────────────────────────
    def play_knife_swing(self):
        if not self.is_alive:
            return
        self._attack_anim = 0.4
        self.r_arm_pivot.animate("rotation_x", -130, duration=0.08, curve=curve.out_quad)
        invoke(self._relax_arm, delay=0.14)

    def play_gun_recoil(self):
        if not self.is_alive:
            return
        self._attack_anim = 0.5
        self.r_arm_pivot.animate("rotation_x", -95, duration=0.05, curve=curve.out_quad)
        invoke(self._recoil_kick, delay=0.06)

    def _recoil_kick(self):
        if self.is_alive:
            self.r_arm_pivot.animate("rotation_x", -70, duration=0.08, curve=curve.out_quad)
            invoke(self._relax_arm, delay=0.3)

    def _relax_arm(self):
        if self.is_alive:
            self.r_arm_pivot.animate("rotation_x", 0, duration=0.25, curve=curve.in_out_quad)

    def sync_alive(self, alive):
        if alive == self.is_alive:
            return
        self.is_alive = alive
        if not alive and self.dead_tilt == 0:
            self.dead_tilt = 88
            self.animate("rotation_x", -86, duration=0.5, curve=curve.out_bounce)
            self.animate("rotation_y", self.rotation_y + random.uniform(-40, 40), duration=0.5)
            self.animate("y", self.y + 0.12, duration=0.5)
            self.shadow.enabled = False
            if self.nametag:
                self.nametag.enabled = False
        elif alive:
            self.rotation_x = 0
            self.dead_tilt = 0
            self.enabled = True
            self.shadow.enabled = True
            if self.nametag:
                self.nametag.enabled = True

    def animate_walk(self, moving):
        if not self.is_alive:
            return
        dt = time.dt
        self._idle_t += dt
        if self._attack_anim > 0:
            self._attack_anim -= dt

        target = 1.0 if moving else 0.0
        self._swing_blend += (target - self._swing_blend) * min(1.0, dt * 9)
        blend = self._swing_blend
        t = self.player.anim_phase

        arm = math.sin(t) * 38 * blend
        leg = math.sin(t) * 30 * blend
        self.l_arm_pivot.rotation_x = arm
        if self._attack_anim <= 0:
            self.r_arm_pivot.rotation_x = -arm
        self.l_leg_pivot.rotation_x = -leg
        self.r_leg_pivot.rotation_x = leg

        # Walk bounce + forward lean, idle breathing when standing.
        bounce = abs(math.sin(t)) * 0.06 * blend
        breathe = math.sin(self._idle_t * 2.2) * 0.015 * (1 - blend)
        self.body_root.y = bounce + breathe
        self.body_root.rotation_x = 6 * blend
        sway = math.sin(self._idle_t * 2.2) * 2.5 * (1 - blend)
        self.l_arm_pivot.rotation_z = -sway - 2 * blend
        self.r_arm_pivot.rotation_z = sway + 2 * blend

    def face_movement(self):
        if not self.is_alive:
            return
        fx, fy = self.player.facing
        if abs(fx) + abs(fy) > 0.01:
            target = math.degrees(math.atan2(fx, fy))
            diff = (target - self.rotation_y + 180) % 360 - 180
            self.rotation_y += diff * min(1.0, time.dt * 12)

    def set_role_glow(self, role):
        if self.role_ring:
            destroy(self.role_ring)
            self.role_ring = None
        if role in ("murderer", "sheriff"):
            rc = ROLE_COLORS[role]
            self.role_ring = Entity(
                parent=self, model="quad", texture="circle_outlined",
                rotation_x=90, position=(0, 0.05, 0), scale=1.45,
                color=c255(rc[0], rc[1], rc[2], 120),
            )

    def destroy_avatar(self):
        destroy(self)


# ── 3D Map ──────────────────────────────────────────────────────────────

class Map3D:
    def __init__(self, map_data):
        self.entities = []
        self.map_data = map_data
        mw = map_data.get("width", 800)
        mh = map_data.get("height", 600)

        wall_col      = c255(206, 104, 78)   # warm brick
        wall_cap      = c255(232, 134, 102)
        perim_col     = c255(92, 182, 96)    # hedge green
        perim_cap     = c255(116, 208, 116)

        for w in map_data["walls"]:
            cx = (w["x"] + w["w"] / 2) * PIXEL_SCALE
            cz = (w["y"] + w["h"] / 2) * PIXEL_SCALE
            wx = w["w"] * PIXEL_SCALE
            wz = w["h"] * PIXEL_SCALE
            perimeter = w["w"] >= mw or w["h"] >= mh
            height = 3.2 if perimeter else 2.4
            col, cap_col = (perim_col, perim_cap) if perimeter else (wall_col, wall_cap)
            self.entities.append(Entity(
                model="cube", color=col,
                position=(cx, height / 2, cz),
                scale=(max(wx, 0.5), height, max(wz, 0.5)),
                texture="white_cube",
            ))
            self.entities.append(Entity(
                model="cube", color=cap_col,
                position=(cx, height + 0.07, cz),
                scale=(max(wx, 0.5) + 0.14, 0.16, max(wz, 0.5) + 0.14),
                texture="white_cube",
            ))

        # Crates placed off the spawn lanes.
        for px, py, s in ((250, 130, 1.2), (270, 165, 0.8), (560, 340, 1.4), (590, 370, 0.9)):
            wx, _, wz = pixel_to_world(px, py)
            self.entities.extend(create_crate(Vec3(wx, 0, wz), s))

    def destroy_map(self):
        for e in self.entities:
            destroy(e)
        self.entities.clear()


# ── Lobby helpers ───────────────────────────────────────────────────────

def _load_maps():
    map_dir = "data/maps"
    out = []
    for mf in sorted(os.listdir(map_dir)):
        if not mf.endswith(".json"):
            continue
        with open(os.path.join(map_dir, mf)) as f:
            data = json.load(f)
        out.append({"id": data["id"], "name": data["name"], "data": data})
    return out


def _make_roster(spawns):
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
    return bots


# ── Main game app ───────────────────────────────────────────────────────

class Game3DApp:
    def __init__(self):
        self.maps = _load_maps()
        self.map_index = 0
        self.round_number = 1

        self.human = Player(
            "p1", "Guest_You", (44, 181, 232),
            body_color=(44, 181, 232),
            shirt_color=(30, 140, 200),
            pants_color=(35, 55, 120),
            skin_color=(255, 204, 153),
        )
        spawns = self.maps[0]["data"]["spawn_points"]
        self.bots = _make_roster(spawns)
        self.all_players = [self.human] + self.bots
        self.wallet = WalletManager()

        self.state = "menu"
        self.session = None
        self.map3d = None
        self.avatars = {}
        self.buck_entities = {}
        self.bullet_entity_map = {}
        self.gun_entity = None
        self.ui_root = None
        self.role_panel = None
        self.human_elev = 0.0
        self.human_vy = 0.0

        # Camera
        self.cam_yaw = 0.0
        self.cam_pitch = 20.0
        self.cam_dist = 12.0
        self.mouse_sensitivity = 40
        self._cam_smooth = None

        # Effects / audio
        self.fx = None
        self.kill_feed = None
        self.sounds = SoundBank()
        self._prev_human_gun = False
        self._prev_human_bucks = 0
        self._seen_bullet_ids = set()
        self._near_murderer_timer = 0.0
        self._clock = 0.0
        self._smoke_shot_done = False

        # HUD widgets
        self.hud_root = None
        self.timer_text = None
        self.role_chip_text = None
        self.alive_text = None
        self.coin_text = None
        self.coin_icon = None
        self.stamina_fill = None
        self.cooldown_bg = None
        self.cooldown_fill = None
        self.crosshair = None

        # Environment
        self.env_entities = []
        self.clouds = []

    # ── Scene setup ─────────────────────────────────────────────────────

    def setup_scene(self):
        map_data = self.maps[0]["data"]
        mw = map_data.get("width", 800) * PIXEL_SCALE   # ~53 world units
        mh = map_data.get("height", 600) * PIXEL_SCALE  # ~40 world units
        cx, cz = mw / 2, mh / 2

        # Bright stylized sky + light haze for depth.
        # NOTE: the Sky prefab forces ursina's unlit_shader (GLSL 130/140)
        # which fails to compile on the macOS core profile, so we build the
        # dome as a plain fixed-function entity instead.
        self.env_entities.append(Entity(
            model="sky_dome", texture="sky_default", scale=600,
            position=(cx, 0, cz), color=c255(235, 245, 255),
            double_sided=True,
        ))
        scene.fog_color = c255(198, 228, 250)
        scene.fog_density = 0.0045

        # Sun: warm emissive billboard, fakes a light source.
        self.env_entities.append(Entity(
            model="quad", texture="radial_gradient", billboard=True,
            position=(cx + 70, 80, cz + 110), scale=70,
            color=c255(255, 244, 200, 235),
        ))
        self.env_entities.append(Entity(
            model="quad", texture="circle", billboard=True,
            position=(cx + 70, 80, cz + 110), scale=22,
            color=c255(255, 252, 235),
        ))

        # Drifting clouds.
        rng = random.Random(42)
        for _ in range(6):
            pos = Vec3(rng.uniform(-10, mw + 10), rng.uniform(22, 34), rng.uniform(-12, mh + 12))
            cloud = create_cloud(pos, rng.uniform(0.8, 1.6))
            self.clouds.append((cloud, rng.uniform(0.4, 1.0)))
            self.env_entities.append(cloud)

        # Base slab so the seams between tiles read as dark grout lines.
        self.env_entities.append(Entity(
            model="cube", color=c255(64, 112, 48),
            position=(cx, -0.12, cz), scale=(mw + 24, 0.06, mh + 24),
        ))

        # Vivid checkerboard ground with a sandstone path cross.
        tile = 4.0
        for ix in range(-2, int(mw // tile) + 3):
            for iz in range(-2, int(mh // tile) + 3):
                tx = ix * tile + tile / 2
                tz = iz * tile + tile / 2
                inside = 0 <= tx <= mw and 0 <= tz <= mh
                on_path = inside and (abs(tx - cx) < 2.2 or abs(tz - cz) < 2.2)
                check = (ix + iz) & 1
                if on_path:
                    col = PATH_A if check else PATH_B
                elif inside:
                    col = GRASS_A if check else GRASS_B
                else:
                    col = GRASS_OUT_A if check else GRASS_OUT_B
                self.env_entities.append(Entity(
                    model="cube", color=col,
                    position=(tx, -0.04, tz),
                    scale=(tile * 0.99, 0.08, tile * 0.99),
                    texture="white_cube",
                ))

        # Trees ring the playfield (outside the perimeter hedge).
        tree_spots = [
            (-4, -4, 1.3), (cx, -5, 1.1), (mw + 4, -4, 1.4),
            (-5, cz, 1.2), (mw + 5, cz, 1.0),
            (-4, mh + 4, 1.1), (cx, mh + 5, 1.4), (mw + 4, mh + 4, 1.2),
            (mw * 0.25, -4.5, 0.9), (mw * 0.75, mh + 4.5, 1.0),
            (-4.5, mh * 0.25, 1.0), (mw + 4.5, mh * 0.75, 0.9),
        ]
        for tx, tz, s in tree_spots:
            self.env_entities.extend(create_tree(Vec3(tx, 0, tz), s))

        # Lampposts along the paths, kept clear of the spawn points.
        for lx, lz in ((18, 10), (35, 10), (18, 30), (35, 30), (8, 20), (mw - 8, 20)):
            self.env_entities.extend(create_lamppost(Vec3(lx, 0, lz)))

        # Barrels and rocks tucked near walls / corners.
        for bx, bz in ((14.6, 8.2), (15.4, 9.6), (38.0, 33.5), (3.4, 36.4)):
            self.env_entities.extend(create_barrel(Vec3(bx, 0, bz)))
        for rx, rz, s in ((4.0, 3.6, 1.0), (mw - 4, 4.2, 0.8), (mw - 5, mh - 4, 1.2), (5, mh - 5, 0.7)):
            self.env_entities.extend(create_rock(Vec3(rx, 0, rz), s))

        # Bushes along the inside of the hedge.
        for bx, bz, s in ((8, 2.6, 1.0), (24, 2.4, 0.8), (44, 2.7, 1.1),
                          (2.6, 14, 0.9), (2.6, 26, 1.0), (mw - 2.6, 12, 0.9),
                          (mw - 2.6, 30, 1.1), (16, mh - 2.6, 1.0), (38, mh - 2.6, 0.8)):
            self.env_entities.extend(create_bush(Vec3(bx, 0, bz), s))

        # Scattered flowers for pops of colour.
        petals = [c255(255, 120, 160), c255(255, 214, 90), c255(170, 140, 255), c255(255, 250, 250)]
        frng = random.Random(9)
        placed = 0
        while placed < 26:
            fx = frng.uniform(3, mw - 3)
            fz = frng.uniform(3, mh - 3)
            if abs(fx - cx) < 3 or abs(fz - cz) < 3:
                continue
            self.env_entities.extend(create_flower(Vec3(fx, 0, fz), frng.choice(petals)))
            placed += 1

    # ── App lifecycle ───────────────────────────────────────────────────

    def run(self):
        ensure_sound_files()
        self.app = Ursina(
            title="M Mystery 3D",
            borderless=False,
            fullscreen=False,
            development_mode=False,
        )
        window.size = (1280, 720)
        window.color = c255(150, 205, 250)
        window.fps_counter.enabled = True

        self.setup_scene()
        self.fx = ScreenEffects()
        self.kill_feed = KillFeed()
        self.sounds.load()
        self.sounds.start_ambient()

        self._build_menu_ui()
        global _APP_INSTANCE
        _APP_INSTANCE = self
        self.app.run()

    def _smoke_drive(self):
        """M3D_SMOKE=1: auto-advance menu -> lobby -> round -> world, then
        screenshot and quit.  State-gated so steps can never run out of order."""
        t = self._clock
        if self.state == "menu" and t > 0.5:
            self._build_lobby_ui()
        elif self.state == "lobby" and t > 1.0:
            self._start_round()
        elif self.state == "reveal" and t > 1.5:
            self._enter_world()
        elif t > 6.5 and not self._smoke_shot_done and self.state in ("playing", "end"):
            self._smoke_shot_done = True
            self._smoke_screenshot()
        if t > 8.0:
            application.quit()

    def _smoke_screenshot(self):
        try:
            from panda3d.core import Filename
            h = self.avatars.get(self.human.id)
            print("[SMOKE] cam", camera.world_position, camera.rotation,
                  "pitch", self.cam_pitch, "yaw", self.cam_yaw,
                  "avatar", h.world_position if h else None)
            application.base.win.saveScreenshot(Filename.from_os_specific("/tmp/m3d_shot.png"))
            print("[SMOKE] screenshot saved to /tmp/m3d_shot.png")
        except Exception as exc:
            print(f"[SMOKE] screenshot failed: {exc}")

    def _clear_ui(self):
        if self.ui_root:
            destroy(self.ui_root)
            self.ui_root = None

    def _click(self, fn):
        def wrapped():
            self.sounds.play("click", 0.7)
            fn()
        return wrapped

    # ── Main menu ───────────────────────────────────────────────────────

    def _build_menu_ui(self):
        self._clear_ui()
        self.state = "menu"
        mouse.locked = False
        self.ui_root = Entity(parent=camera.ui)

        Entity(parent=self.ui_root, model="quad",
               color=c255(14, 20, 44, 235), scale=(0.66, 0.58))
        Entity(parent=self.ui_root, model="quad",
               color=c255(0, 200, 255, 60), scale=(0.66, 0.012), position=(0, 0.29))
        Entity(parent=self.ui_root, model="quad",
               color=c255(0, 200, 255, 60), scale=(0.66, 0.012), position=(0, -0.29))

        Text(parent=self.ui_root, text="M MYSTERY",
             color=c255(20, 30, 60), scale=4.8, position=(0.006, 0.144), origin=(0, 0))
        Text(parent=self.ui_root, text="M MYSTERY",
             color=c255(90, 225, 255), scale=4.8, position=(0, 0.15), origin=(0, 0))
        Text(parent=self.ui_root, text="3 D   E D I T I O N",
             color=c255(255, 214, 90), scale=1.4, position=(0, 0.07), origin=(0, 0))
        Entity(parent=self.ui_root, model="quad",
               color=c255(0, 200, 255, 80), scale=(0.5, 0.004), position=(0, 0.03))

        Button(parent=self.ui_root, text="PLAY",
               color=c255(46, 188, 90), highlight_color=c255(66, 214, 110),
               scale=(0.24, 0.075), position=(0, -0.06),
               on_click=self._click(self._build_lobby_ui))

        Text(parent=self.ui_root,
             text="[WASD] Move   [Shift] Sprint   [Q] Jump   [LMB/Space] Attack   [Scroll] Zoom",
             color=c255(150, 165, 200), scale=0.85, position=(0, -0.17), origin=(0, 0))

        Button(parent=self.ui_root, text="Quit",
               scale=(0.16, 0.055), position=(0, -0.24),
               color=c255(90, 95, 120), highlight_color=c255(120, 126, 150),
               on_click=application.quit)

    # ── Lobby ───────────────────────────────────────────────────────────

    def _build_lobby_ui(self):
        self._clear_ui()
        self.state = "lobby"
        self.ui_root = Entity(parent=camera.ui)
        m = self.maps[self.map_index]

        Entity(parent=self.ui_root, model="quad",
               color=c255(14, 20, 44, 235), scale=(0.7, 0.78))
        Text(parent=self.ui_root, text="SERVERS", y=0.32, scale=2.4, origin=(0, 0),
             color=c255(90, 225, 255))
        Text(parent=self.ui_root, text=f"< Map: {m['name']} >  (arrow keys)",
             y=0.24, scale=1.2, origin=(0, 0), color=c255(255, 214, 90))
        Text(parent=self.ui_root,
             text=f"Round {self.round_number}  -  {len(self.all_players)}/6 players",
             y=0.18, scale=0.95, origin=(0, 0), color=c255(170, 180, 210))

        y = 0.10
        for p in self.all_players:
            Entity(parent=self.ui_root, model="quad", texture="circle",
                   color=_c(p.color), scale=0.018, position=(-0.16, y))
            tag = "  (You)" if p is self.human else ""
            Text(parent=self.ui_root, text=f"{p.name}{tag}", position=(-0.13, y),
                 scale=0.95, origin=(-0.5, 0), color=color.white)
            y -= 0.055

        Button(parent=self.ui_root, text="PLAY", y=-0.2, scale=(0.3, 0.07),
               color=c255(46, 188, 90), highlight_color=c255(66, 214, 110),
               on_click=self._click(self._start_round))
        Button(parent=self.ui_root, text="Back", y=-0.3, scale=(0.2, 0.055),
               color=c255(90, 95, 120), highlight_color=c255(120, 126, 150),
               on_click=self._click(self._build_menu_ui))

    def _cycle_map(self, step):
        self.map_index = (self.map_index + step) % len(self.maps)
        self.sounds.play("click", 0.5)
        self._build_lobby_ui()

    # ── Round management ────────────────────────────────────────────────

    def _reset_players(self, spawns):
        for i, p in enumerate(self.all_players):
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
                p.dx = p.dy = 0
                p.brain.reset_round()
            p.stamina = p.max_stamina

    def _start_round(self):
        self._clear_ui()
        map_data = self.maps[self.map_index]["data"]
        spawns = map_data["spawn_points"]
        self._reset_players(spawns)
        assign_roles(self.all_players)

        if self.kill_feed:
            self.kill_feed.clear()

        self.state = "reveal"
        role = self.human.role.upper()
        rc = ROLE_COLORS.get(self.human.role, (200, 200, 200))
        role_col = _c(rc)
        self.role_panel = Entity(parent=camera.ui)
        Entity(parent=self.role_panel, model="quad",
               color=c255(14, 20, 44, 240), scale=(0.62, 0.5))
        Entity(parent=self.role_panel, model="quad",
               color=c255(rc[0], rc[1], rc[2], 70), scale=(0.62, 0.09), position=(0, 0.06))
        Text(parent=self.role_panel, text="YOUR ROLE IS", y=0.16, scale=1.6,
             origin=(0, 0), color=c255(170, 180, 210))
        Text(parent=self.role_panel, text=role, y=0.06, scale=3.2, origin=(0, 0),
             color=role_col)
        Text(parent=self.role_panel, text=ROLE_BLURBS.get(self.human.role, ""),
             y=-0.04, scale=1.0, origin=(0, 0), color=color.white)
        Text(parent=self.role_panel,
             text="LMB/Space = Attack   Shift = Sprint   Q = Jump   Mouse = Look",
             y=-0.11, scale=0.85, origin=(0, 0), color=c255(150, 165, 200))
        Button(parent=self.role_panel, text="I'm Ready", y=-0.19, scale=(0.25, 0.07),
               color=role_col, highlight_color=c255(min(rc[0] + 30, 255), min(rc[1] + 30, 255), min(rc[2] + 30, 255)),
               on_click=self._click(self._enter_world))

    def _enter_world(self):
        if self.role_panel:
            destroy(self.role_panel)
            self.role_panel = None
        self._clear_ui()

        map_data = self.maps[self.map_index]["data"]
        if self.map3d:
            self.map3d.destroy_map()
        self.map3d = Map3D(map_data)
        self._world_bounds = (
            map_data.get("width", 800) * PIXEL_SCALE,
            map_data.get("height", 600) * PIXEL_SCALE,
        )
        self.session = RoundSession(self.all_players, map_data, self.wallet, self.human)

        self.avatars = {}
        for p in self.all_players:
            wx, _, wz = pixel_to_world(p.x, p.y, 0.0)
            av = Avatar3D(p, position=(wx, 0, wz))
            av.set_role_glow(p.role)
            self.avatars[p.id] = av

        self._spawn_buck_visuals()
        self.state = "playing"
        self.human_elev = 0
        self.human_vy = 0
        self.cam_yaw = 0
        self.cam_pitch = 20
        self._cam_smooth = None

        self._prev_human_gun = self.human.has_gun
        self._prev_human_bucks = 0
        self._seen_bullet_ids = set()
        self._near_murderer_timer = 0.0

        # In smoke mode the window never has real focus, so a locked mouse
        # reports junk velocity that drives the camera into its pitch clamp.
        mouse.locked = not SMOKE_TEST
        self._build_hud()

    # ── HUD ─────────────────────────────────────────────────────────────

    def _build_hud(self):
        self.hud_root = Entity(parent=camera.ui)

        # Role chip (top-left).
        rc = ROLE_COLORS.get(self.human.role, (200, 200, 200))
        Entity(parent=self.hud_root, model="quad",
               color=c255(14, 18, 38, 200), scale=(0.24, 0.1), position=(-0.72, 0.43))
        Entity(parent=self.hud_root, model="quad",
               color=c255(rc[0], rc[1], rc[2]), scale=(0.012, 0.1), position=(-0.834, 0.43))
        self.role_chip_text = Text(
            parent=self.hud_root, text=self.human.role.upper(),
            position=(-0.71, 0.45), origin=(0, 0), scale=1.1,
            color=c255(rc[0], rc[1], rc[2]))
        self.alive_text = Text(
            parent=self.hud_root, text="ALIVE: 4",
            position=(-0.71, 0.41), origin=(0, 0), scale=0.85, color=color.white)

        # Timer (top-center).
        Entity(parent=self.hud_root, model="quad",
               color=c255(14, 18, 38, 200), scale=(0.16, 0.08), position=(0, 0.44))
        self.timer_text = Text(
            parent=self.hud_root, origin=(0, 0), position=(0, 0.44),
            scale=1.9, color=color.white)

        # Coin counter (bottom-left).
        Entity(parent=self.hud_root, model="quad",
               color=c255(14, 18, 38, 200), scale=(0.2, 0.075), position=(-0.74, -0.44))
        self.coin_icon = Entity(
            parent=self.hud_root, model="quad", texture="circle",
            color=c255(255, 214, 60), scale=0.035, position=(-0.81, -0.44))
        Entity(parent=self.hud_root, model="quad", texture="circle",
               color=c255(200, 150, 30), scale=0.022, position=(-0.81, -0.44))
        self.coin_text = Text(
            parent=self.hud_root, text="0 / 50",
            position=(-0.71, -0.44), origin=(0, 0), scale=1.2,
            color=c255(255, 224, 110))

        # Stamina bar (bottom-right).
        Text(parent=self.hud_root, text="STAMINA", scale=0.8,
             color=c255(200, 255, 200, 220), position=(0.72, -0.41), origin=(0, 0))
        Entity(parent=self.hud_root, model="quad",
               color=c255(14, 18, 38, 220), scale=(0.22, 0.03), position=(0.72, -0.45))
        self.stamina_fill = Entity(
            parent=self.hud_root, model="quad",
            color=c255(60, 210, 90), scale=(0.21, 0.022),
            position=(0.615, -0.45), origin=(-0.5, 0))

        # Crosshair + attack cooldown bar.
        self.crosshair = Entity(parent=self.hud_root)
        for s, p_off, col in (
            ((0.0026, 0.022), (0.001, -0.001), c255(0, 0, 0, 110)),
            ((0.022, 0.0026), (0.001, -0.001), c255(0, 0, 0, 110)),
            ((0.002, 0.02), (0, 0), c255(255, 255, 255, 210)),
            ((0.02, 0.002), (0, 0), c255(255, 255, 255, 210)),
        ):
            Entity(parent=self.crosshair, model="quad", color=col, scale=s, position=p_off)

        self.cooldown_bg = Entity(
            parent=self.hud_root, model="quad",
            color=c255(14, 18, 38, 180), scale=(0.07, 0.008), position=(0, -0.045))
        self.cooldown_fill = Entity(
            parent=self.hud_root, model="quad",
            color=c255(120, 230, 130), scale=(0.066, 0.005),
            position=(-0.033, -0.045), origin=(-0.5, 0))

        # Hint line.
        Text(parent=self.hud_root,
             text="WASD Move  -  Shift Sprint  -  Q Jump  -  LMB/Space Attack  -  Scroll Zoom",
             position=(0, -0.48), origin=(0, 0), scale=0.75,
             color=c255(235, 240, 255, 170))

    # ── Buck visuals ────────────────────────────────────────────────────

    def _spawn_buck_visuals(self):
        for ent, _, _ in self.buck_entities.values():
            destroy(ent)
        self.buck_entities.clear()
        for i, (bx, by, val) in enumerate(self.session.bucks):
            wx, wy, wz = pixel_to_world(bx, by, 0.85)
            coin = Entity(position=(wx, wy, wz))
            s = 0.34 + val * 0.06
            Entity(parent=coin, model="sphere", color=c255(255, 214, 60),
                   scale=(s, s, s * 0.35))
            Entity(parent=coin, model="sphere", color=c255(255, 240, 150),
                   scale=(s * 0.55, s * 0.55, s * 0.37))
            Entity(parent=coin, model="quad", texture="radial_gradient", rotation_x=90,
                   color=c255(255, 214, 80, 80), scale=s * 3.2,
                   position=(0, -wy + 0.04, 0))
            coin.spin_speed = 90 + i * 10
            coin.base_y = wy
            coin.bob_phase = i * 0.7
            self.buck_entities[(bx, by)] = (coin, bx, by)

    # ── Camera / movement ───────────────────────────────────────────────

    def _camera_relative_move(self):
        yaw = self.cam_yaw
        yr = math.radians(yaw)
        fwd = Vec3(math.sin(yr), 0, math.cos(yr))
        right = Vec3(math.cos(yr), 0, -math.sin(yr))
        dx = dy = 0.0
        if held_keys["w"]:
            dx += fwd.x; dy += fwd.z
        if held_keys["s"]:
            dx -= fwd.x; dy -= fwd.z
        if held_keys["a"]:
            dx -= right.x; dy -= right.z
        if held_keys["d"]:
            dx += right.x; dy += right.z
        if dx != 0 or dy != 0:
            length = (dx * dx + dy * dy) ** 0.5
            dx /= length; dy /= length
        return dx, dy

    def _update_camera(self):
        h = self.avatars.get(self.human.id)
        if not h:
            return
        if not self.human.is_alive:
            self.cam_yaw += time.dt * 12  # slow spectate orbit

        yr = math.radians(self.cam_yaw)
        pr = math.radians(self.cam_pitch)
        right = Vec3(math.cos(yr), 0, -math.sin(yr))

        target = Vec3(h.x, h.y + 1.9, h.z) + right * 0.8
        horiz = self.cam_dist * math.cos(pr)
        desired = Vec3(
            target.x - math.sin(yr) * horiz,
            target.y + self.cam_dist * math.sin(pr),
            target.z - math.cos(yr) * horiz,
        )
        # Keep the camera inside the perimeter hedge so it never gets
        # occluded near the map edge.  Scale the whole offset vector so the
        # camera zooms in along its own axis and the pitch is preserved.
        bw, bh = getattr(self, "_world_bounds", (53.3, 40.0))
        off = desired - target
        t = 1.0
        for axis, bound_hi in (("x", bw - 1.8), ("z", bh - 1.8)):
            o = getattr(off, axis)
            base = getattr(target, axis)
            val = base + o
            if val < 1.8 and o < 0:
                t = min(t, (1.8 - base) / o)
            elif val > bound_hi and o > 0:
                t = min(t, (bound_hi - base) / o)
        desired = target + off * max(t, 0.3)
        if desired.y < 0.6:
            desired.y = 0.6

        if self._cam_smooth is None:
            self._cam_smooth = desired
        else:
            self._cam_smooth = lerp(self._cam_smooth, desired, min(1.0, time.dt * 10))
        camera.position = self._cam_smooth

        # Aim manually — camera.look_at can introduce roll.
        d = target - self._cam_smooth
        flat = math.sqrt(d.x * d.x + d.z * d.z)
        camera.rotation = Vec3(
            math.degrees(math.atan2(-d.y, flat)),
            math.degrees(math.atan2(d.x, d.z)),
            0,
        )

    def _sync_visuals(self):
        for p in self.all_players:
            av = self.avatars.get(p.id)
            if not av:
                continue
            wx, _, wz = pixel_to_world(p.x, p.y, 0.0)
            elev = self.human_elev if p is self.human else 0
            if not av.is_alive and not p.is_alive:
                av.x, av.z = wx, wz  # keep corpse where it fell, no bobbing
            else:
                av.position = (wx, elev, wz)
            av.sync_alive(p.is_alive)
            av.sync_weapons()
            av.animate_walk(p.is_moving)
            av.face_movement()
            if p is self.human and av.is_alive:
                av.shadow.y = -elev + 0.03
                av.shadow.alpha = max(0.15, 0.37 - elev * 0.08)

        # Coins: spin + bob.
        live = {(b[0], b[1]) for b in self.session.bucks}
        for key, (ent, bx, by) in list(self.buck_entities.items()):
            if (bx, by) not in live:
                destroy(ent)
                del self.buck_entities[key]
            else:
                ent.rotation_y += time.dt * getattr(ent, "spin_speed", 60)
                ent.y = ent.base_y + math.sin(self._clock * 2.5 + ent.bob_phase) * 0.08

        # Dropped gun.
        if self.session.dropped_gun_pos:
            gx, gy = self.session.dropped_gun_pos
            wx, wy, wz = pixel_to_world(gx, gy, 0.5)
            if not self.gun_entity:
                root = Entity(position=(wx, wy, wz))
                Entity(parent=root, model="cube", color=c255(58, 60, 74),
                       scale=(0.16, 0.26, 0.6), texture="white_cube")
                Entity(parent=root, model="cube", color=c255(255, 214, 60),
                       scale=(0.2, 0.06, 0.66), position=(0, 0.14, 0), texture="white_cube")
                Entity(parent=root, model="quad", texture="radial_gradient", rotation_x=90,
                       color=c255(255, 230, 120, 90), scale=2.2, position=(0, -0.42, 0))
                self.gun_entity = root
            else:
                self.gun_entity.position = (wx, wy + math.sin(self._clock * 3) * 0.08, wz)
                self.gun_entity.rotation_y += time.dt * 120
        elif self.gun_entity:
            destroy(self.gun_entity)
            self.gun_entity = None

        # Bullets: glowing tracers.
        active_ids = {id(b) for b in self.session.bullets if b.is_active}
        for b in self.session.bullets:
            if b.is_active:
                bid = id(b)
                wx, wy, wz = pixel_to_world(b.x, b.y, 1.2)
                if bid not in self.bullet_entity_map:
                    be = Entity(position=(wx, wy, wz),
                                rotation_y=math.degrees(math.atan2(b.dx, b.dy)))
                    Entity(parent=be, model="sphere", color=c255(255, 234, 140),
                           scale=(0.14, 0.14, 0.95))
                    Entity(parent=be, model="quad", texture="radial_gradient",
                           billboard=True, color=c255(255, 200, 80, 150), scale=0.7)
                    self.bullet_entity_map[bid] = be
                else:
                    self.bullet_entity_map[bid].position = (wx, wy, wz)

        for bid in list(self.bullet_entity_map.keys()):
            if bid not in active_ids:
                spawn_bullet_impact(self.bullet_entity_map[bid].position)
                destroy(self.bullet_entity_map[bid])
                del self.bullet_entity_map[bid]

        self._update_camera()

    def _update_ui(self):
        if not self.session or self.state != "playing":
            return

        remaining = self.session.round_manager.remaining
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        if self.timer_text:
            self.timer_text.text = f"{mins}:{secs:02d}"
            if remaining < 30:
                pulse = 1.9 + math.sin(self._clock * 8) * 0.2
                self.timer_text.scale = pulse
                self.timer_text.color = c255(255, 70, 70)
            else:
                self.timer_text.scale = 1.9
                self.timer_text.color = color.white

        if self.alive_text:
            self.alive_text.text = f"ALIVE: {self.session.alive_count}"

        if self.coin_text:
            self.coin_text.text = f"{self.human.m_bucks_this_round} / 50"

        if self.stamina_fill:
            pct = self.human.stamina / self.human.max_stamina
            self.stamina_fill.scale_x = 0.21 * pct
            if pct > 0.6:
                self.stamina_fill.color = c255(60, 210, 90)
            elif pct > 0.3:
                self.stamina_fill.color = c255(225, 200, 60)
            else:
                self.stamina_fill.color = c255(225, 80, 55)

        # Attack cooldown indicator under the crosshair.
        if self.cooldown_fill and self.cooldown_bg:
            show = self.human.is_alive and (self.human.has_knife or self.human.has_gun)
            self.cooldown_bg.enabled = show
            self.cooldown_fill.enabled = show
            if show:
                if self.human.has_knife:
                    ready = 1.0 - max(0, self.human.attack_cooldown) / 60.0
                else:
                    ready = 1.0
                self.cooldown_fill.scale_x = 0.066 * ready
                self.cooldown_fill.color = (
                    c255(120, 230, 130) if ready >= 1.0 else c255(235, 180, 70))

    # ── Event reactions ─────────────────────────────────────────────────

    def _vol_at(self, px, py, base=1.0):
        d = math.hypot(self.human.x - px, self.human.y - py)
        return base * max(0.15, min(1.0, 1.0 - d / 700.0))

    def _drain_kill_log(self):
        for killer_name, victim_name, weapon in self.session.kill_log:
            if self.kill_feed:
                self.kill_feed.add(killer_name, victim_name, weapon)
            victim = next((p for p in self.all_players if p.name == victim_name), None)
            killer = next((p for p in self.all_players if p.name == killer_name), None)
            if victim:
                wx, wy, wz = pixel_to_world(victim.x, victim.y, 1.0)
                spawn_death_particles(Vec3(wx, wy, wz))
                self.sounds.play("death", self._vol_at(victim.x, victim.y, 0.9))
                if victim is self.human:
                    self.fx.blood_flash()
                    self.fx.screen_shake(0.25, 0.3)
                else:
                    d = math.hypot(self.human.x - victim.x, self.human.y - victim.y)
                    if d < 120:
                        self.fx.screen_shake(0.15, 0.2)
            if weapon == "knife" and killer:
                self.sounds.play("stab", self._vol_at(killer.x, killer.y, 0.9))
                k_av = self.avatars.get(killer.id)
                if k_av and killer is not self.human:
                    k_av.play_knife_swing()
        self.session.kill_log.clear()

    def _detect_new_bullets(self):
        active = {id(b): b for b in self.session.bullets if b.is_active}
        for bid, b in active.items():
            if bid not in self._seen_bullet_ids:
                wx, wy, wz = pixel_to_world(b.x, b.y, 1.4)
                spawn_muzzle_flash(Vec3(wx, wy, wz))
                self.sounds.play("shoot", self._vol_at(b.x, b.y, 1.0))
        self._seen_bullet_ids = set(active.keys())

    # ── Main update loop ────────────────────────────────────────────────

    def update(self):
        self._clock += time.dt
        if SMOKE_TEST:
            self._smoke_drive()

        # Cloud drift (always on — visible behind menus too).
        for cloud, speed in self.clouds:
            cloud.x += speed * time.dt
            if cloud.x > 75:
                cloud.x = -20

        if self.state != "playing" or not self.session:
            if self.fx:
                self.fx.update()
            if self.kill_feed:
                self.kill_feed.update()
            return

        if mouse.locked:
            self.cam_yaw += mouse.velocity[0] * self.mouse_sensitivity
            self.cam_pitch = clamp(
                self.cam_pitch - mouse.velocity[1] * self.mouse_sensitivity, -8, 62)

        sprinting = held_keys["shift"]
        dx, dy = self._camera_relative_move()
        self.session.tick_human_move(time.dt, dx, dy, sprinting)

        # Jump physics (jump impulse comes from input()).
        self.human_vy -= 28 * time.dt
        self.human_elev += self.human_vy * time.dt
        if self.human_elev < 0:
            self.human_elev = 0
            self.human_vy = 0

        prev_gun = self._prev_human_gun
        prev_bucks = self._prev_human_bucks

        winner = self.session.tick_simulation(time.dt)

        self._drain_kill_log()
        self._detect_new_bullets()

        # Human fired the gun this frame (recoil handled here, sound by tracer).
        if prev_gun and not self.human.has_gun:
            h_av = self.avatars.get(self.human.id)
            if h_av:
                h_av.play_gun_recoil()
            self.fx.white_flash()
            self.fx.screen_shake(0.12, 0.15)

        # Gun pickup feedback.
        if not prev_gun and self.human.has_gun and self.human.role != "sheriff":
            self.sounds.play("click", 0.9)

        # Coin collection feedback (human only).
        if self.human.m_bucks_this_round > prev_bucks:
            h_av = self.avatars.get(self.human.id)
            if h_av:
                spawn_coin_particles(h_av.world_position + Vec3(0, 1.5, 0))
            self.sounds.play("coin", 0.8)
            if self.coin_text:
                self.coin_text.scale = 1.7
                self.coin_text.animate("scale", 1.2, duration=0.25, curve=curve.out_quad)

        self._prev_human_gun = self.human.has_gun
        self._prev_human_bucks = self.human.m_bucks_this_round

        self._sync_visuals()

        # Shake requested by round_session.
        shake = self.session.screen_shake
        if shake["frames_left"] > 0:
            shake["frames_left"] -= 1
            camera.position += Vec3(
                random.uniform(-0.2, 0.2),
                random.uniform(-0.1, 0.1),
                random.uniform(-0.2, 0.2),
            )

        # Danger pulse near the murderer.
        self._near_murderer_timer += time.dt
        if self._near_murderer_timer > 1.5:
            murderer = next(
                (p for p in self.all_players if p.role == "murderer" and p.is_alive),
                None,
            )
            if murderer and self.human.is_alive and murderer is not self.human:
                ddx = self.human.x - murderer.x
                ddy = self.human.y - murderer.y
                if math.sqrt(ddx * ddx + ddy * ddy) < 60:
                    self.fx.blood_flash()
            self._near_murderer_timer = 0.0

        self._update_ui()
        self.fx.update()
        if self.kill_feed:
            self.kill_feed.update()

        if winner:
            self._end_round(winner)

    # ── Round end ──────────────────────────────────────────────────────

    def _end_round(self, winner):
        mouse.locked = False
        for p in self.all_players:
            self.wallet.add_round_earnings(p.id, p.m_bucks_this_round)
        self.wallet.save()

        if self.map3d:
            self.map3d.destroy_map()
            self.map3d = None
        for av in self.avatars.values():
            av.destroy_avatar()
        self.avatars.clear()
        self.session = None
        if self.hud_root:
            destroy(self.hud_root)
            self.hud_root = None
            self.timer_text = None
            self.alive_text = None
            self.coin_text = None
            self.stamina_fill = None
            self.cooldown_bg = None
            self.cooldown_fill = None
            self.crosshair = None
        if self.kill_feed:
            self.kill_feed.clear()
        for ent, _, _ in self.buck_entities.values():
            destroy(ent)
        self.buck_entities.clear()
        for ent in self.bullet_entity_map.values():
            destroy(ent)
        self.bullet_entity_map.clear()
        self._seen_bullet_ids = set()
        if self.gun_entity:
            destroy(self.gun_entity)
            self.gun_entity = None

        self.state = "end"
        self.sounds.play("win", 0.9)
        won = ((winner == "murderer" and self.human.role == "murderer") or
               (winner == "innocents" and self.human.role != "murderer"))
        label = "MURDERER WINS!" if winner == "murderer" else "INNOCENTS WIN!"
        lc = ROLE_COLORS["murderer"] if winner == "murderer" else ROLE_COLORS["innocent"]

        self.ui_root = Entity(parent=camera.ui)
        Entity(parent=self.ui_root, model="quad",
               color=c255(14, 20, 44, 235), scale=(0.64, 0.52))
        Entity(parent=self.ui_root, model="quad",
               color=c255(lc[0], lc[1], lc[2], 70), scale=(0.64, 0.1), position=(0, 0.17))
        Text(parent=self.ui_root, text=label, y=0.17, scale=2.6, origin=(0, 0),
             color=_c(lc))
        Text(parent=self.ui_root,
             text="VICTORY!" if won else "Better luck next round...",
             y=0.08, scale=1.2, origin=(0, 0),
             color=c255(120, 230, 130) if won else c255(170, 180, 210))
        Text(parent=self.ui_root,
             text=f"You collected {self.human.m_bucks_this_round} M-Bucks this round",
             y=0.01, scale=0.95, origin=(0, 0), color=c255(255, 224, 110))
        Button(parent=self.ui_root, text="Next Round", y=-0.08, scale=(0.3, 0.07),
               color=c255(46, 188, 90), highlight_color=c255(66, 214, 110),
               on_click=self._click(self._next_round))
        Button(parent=self.ui_root, text="Menu", y=-0.18, scale=(0.25, 0.06),
               color=c255(90, 95, 120), highlight_color=c255(120, 126, 150),
               on_click=self._click(self._build_menu_ui))

    def _next_round(self):
        self.round_number += 1
        self._build_lobby_ui()

    # ── Input ───────────────────────────────────────────────────────────

    def _try_attack(self):
        if self.state != "playing" or not self.session or not self.human.is_alive:
            return
        ready = self.human.attack_cooldown <= 0
        self.session._human_attack()
        if self.human.has_knife and ready:
            h_av = self.avatars.get(self.human.id)
            if h_av:
                h_av.play_knife_swing()
            self.sounds.play("stab", 0.35)

    def input(self, key):
        if key == "escape":
            if self.state == "playing":
                mouse.locked = False
                self._end_round("innocents")
            elif self.state == "lobby":
                self._build_menu_ui()
            else:
                application.quit()
            return

        if self.state == "lobby":
            if key == "left arrow":
                self._cycle_map(-1)
            elif key == "right arrow":
                self._cycle_map(1)
            return

        if self.state != "playing":
            return

        if key in ("left mouse down", "space"):
            self._try_attack()
        elif key == "q" and self.human.is_alive and self.human_elev <= 0.05:
            self.human_vy = 11
            self.sounds.play("jump", 0.5)
            h_av = self.avatars.get(self.human.id)
            if h_av:
                spawn_jump_puff(h_av.world_position + Vec3(0, 0.15, 0))
        elif key == "scroll up":
            self.cam_dist = clamp(self.cam_dist - 1.2, 5.0, 18.0)
        elif key == "scroll down":
            self.cam_dist = clamp(self.cam_dist + 1.2, 5.0, 18.0)


_APP_INSTANCE = None


def update():
    if _APP_INSTANCE:
        _APP_INSTANCE.update()


def input(key):
    if _APP_INSTANCE:
        _APP_INSTANCE.input(key)


def run_game():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    Game3DApp().run()


if __name__ == '__main__':
    run_game()

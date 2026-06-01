"""
M Mystery — 3D mode (Roblox-style third person).
Single-file build with particles, atmosphere, character upgrades, kill feed, and polished HUD.

Install: pip install ursina pygame
Run:     python main_3d.py
"""
from ursina import *
import json, os, math, random

from core.player import Player
from core.bot import Bot
from core.roles import assign_roles
from core.currency import WalletManager
from core.coords import pixel_to_world, PIXEL_SCALE
from core.round_session import RoundSession


# ── Colour helpers ──────────────────────────────────────────────────────

def _c(rgb):
    return color.rgb(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)


def _part(parent, pos, scale, col, name="part"):
    return Entity(
        parent=parent, model="cube", color=col,
        position=pos, scale=scale, collider=None, name=name,
        texture="white_cube",
    )


ROLE_COLORS = {
    "murderer": (229, 49, 112),
    "sheriff":  (244, 197, 66),
    "innocent": (44, 181, 232),
}


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
    for _ in range(20):
        vel = Vec3(
            random.uniform(-4, 4),
            random.uniform(2, 6),
            random.uniform(-4, 4),
        )
        Particle(
            position=position, velocity=vel,
            color_start=color.rgb(1, 0.15, 0.1),
            color_end=color.rgb(0.4, 0.05, 0.02),
            size_start=random.uniform(0.12, 0.25),
            size_end=0.02, lifetime=random.uniform(0.5, 1.0),
        )
    for _ in range(8):
        vel = Vec3(
            random.uniform(-1.5, 1.5),
            random.uniform(1.5, 3.5),
            random.uniform(-1.5, 1.5),
        )
        Particle(
            position=position + Vec3(0, 0.3, 0), velocity=vel,
            color_start=color.rgb(0.25, 0.22, 0.2),
            color_end=color.rgb(0.5, 0.5, 0.5),
            size_start=random.uniform(0.3, 0.6),
            size_end=0.8, lifetime=random.uniform(0.6, 1.2),
            gravity=False,
        )


def spawn_coin_particles(position):
    for _ in range(8):
        vel = Vec3(
            random.uniform(-2, 2),
            random.uniform(3, 6),
            random.uniform(-2, 2),
        )
        Particle(
            position=position, velocity=vel,
            color_start=color.rgb(1, 0.85, 0.1),
            color_end=color.rgb(0.6, 0.5, 0.05),
            size_start=random.uniform(0.08, 0.14),
            size_end=0.01, lifetime=random.uniform(0.4, 0.8),
        )


def spawn_muzzle_flash(position):
    flash = Entity(
        model="sphere", position=position,
        scale=0.3, color=color.rgb(1, 0.95, 0.6),
    )
    PointLight(parent=flash, color=color.rgb(1, 0.9, 0.4), range=6)
    destroy(flash, delay=0.06)


def spawn_bullet_impact(position):
    for _ in range(5):
        vel = Vec3(
            random.uniform(-2, 2),
            random.uniform(0.5, 2),
            random.uniform(-2, 2),
        )
        Particle(
            position=position, velocity=vel,
            color_start=color.rgb(1, 0.6, 0.1),
            color_end=color.rgb(0.5, 0.2, 0.05),
            size_start=random.uniform(0.06, 0.1),
            size_end=0.01, lifetime=random.uniform(0.2, 0.5),
        )


# ── Screen effects ──────────────────────────────────────────────────────

class ScreenEffects:
    def __init__(self):
        self.overlay = Entity(
            parent=camera.ui, model="quad",
            color=color.rgba(0, 0, 0, 0), scale=(2, 2),
        )
        self.shake_intensity = 0.0
        self.shake_duration = 0.0
        self.shake_timer = 0.0
        self._blood_cooldown = 0.0

    def blood_flash(self):
        if self._blood_cooldown > 0:
            return
        self._blood_cooldown = 0.4
        self.overlay.color = color.rgba(200, 0, 0, 150)
        self.overlay.animate("color", color.rgba(200, 0, 0, 0), duration=0.4, curve=curve.out_expo)

    def white_flash(self):
        self.overlay.color = color.rgba(255, 255, 255, 100)
        self.overlay.animate("color", color.rgba(255, 255, 255, 0), duration=0.15, curve=curve.out_expo)

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
        icon = "🔫" if weapon == "gun" else "⚔"
        t = Text(
            parent=camera.ui,
            text=f"{killer_name} {icon} {victim_name}",
            color=color.rgba(255, 80, 80, 255),
            scale=1.1,
            position=(0.5, 0.38 - len(self.entries) * 0.065),
            origin=(0.5, 0),
        )
        self.entries.append({"text": t, "life": 4.0})

    def update(self):
        for entry in self.entries[:]:
            entry["life"] -= time.dt
            if entry["life"] < 1.0 and entry["life"] > 0:
                entry["text"].alpha = entry["life"]
            if entry["life"] <= 0:
                destroy(entry["text"])
                self.entries.remove(entry)

    def clear(self):
        for entry in self.entries:
            destroy(entry["text"])
        self.entries.clear()


# ── Environment helpers ─────────────────────────────────────────────────

def create_tree(pos):
    trunk = Entity(
        model="cube", position=pos + Vec3(0, 1.25, 0),
        scale=(0.5, 2.5, 0.5), color=color.rgb(0.45, 0.3, 0.15),
        collider="box", texture="white_cube",
    )
    foliage = []
    for i, (w, y_off) in enumerate([(2.2, 2.8), (1.7, 3.3), (1.2, 3.7)]):
        f = Entity(
            model="cube", position=pos + Vec3(0, y_off, 0),
            scale=(w, 0.45, w),
            color=color.rgb(0.12, 0.35 + i * 0.06, 0.1),
            texture="white_cube",
        )
        foliage.append(f)
    return [trunk] + foliage


def create_lamppost(pos):
    post = Entity(
        model="cube", position=pos + Vec3(0, 2, 0),
        scale=(0.15, 4, 0.15), color=color.rgb(0.55, 0.55, 0.6),
        texture="white_cube",
    )
    lamp = Entity(
        model="cube", position=pos + Vec3(0, 4.05, 0),
        scale=(0.4, 0.2, 0.4), color=color.rgb(1, 0.85, 0.4),
        texture="white_cube",
    )
    light = PointLight(
        parent=lamp, position=Vec3(0, 0, 0),
        color=color.rgba(255, 215, 100, 200), range=10,
    )
    return [post, lamp]


def create_barrel(pos):
    body = Entity(
        model="cube", position=pos + Vec3(0, 0.45, 0),
        scale=(0.7, 0.9, 0.7), color=color.rgb(0.5, 0.35, 0.2),
        texture="white_cube",
    )
    band1 = Entity(
        model="cube", position=pos + Vec3(0, 0.25, 0),
        scale=(0.76, 0.06, 0.76), color=color.rgb(0.4, 0.4, 0.45),
        texture="white_cube",
    )
    band2 = Entity(
        model="cube", position=pos + Vec3(0, 0.7, 0),
        scale=(0.76, 0.06, 0.76), color=color.rgb(0.4, 0.4, 0.45),
        texture="white_cube",
    )
    return [body, band1, band2]


# ── 3D Avatar ───────────────────────────────────────────────────────────

class Avatar3D(Entity):
    """R6 rig with face, shoes, weapons, death animation, role glow."""

    def __init__(self, player, **kwargs):
        super().__init__(**kwargs)
        self.player = player
        self.model = None
        self.collider = None

        skin  = _c(player.skin_color)
        shirt = _c(player.shirt_color)
        pants = _c(player.pants_color)
        hair  = _c(player.body_color)

        self.torso = _part(self, (0, 1.1, 0), (0.9, 1.0, 0.45), shirt, "torso")
        self.head  = _part(self, (0, 1.85, 0), (0.55, 0.55, 0.55), skin, "head")
        self.hair  = _part(self, (0, 2.05, 0), (0.58, 0.25, 0.58), hair, "hair")
        self.l_leg = _part(self, (-0.22, 0.45, 0), (0.35, 0.9, 0.35), pants, "l_leg")
        self.r_leg = _part(self, (0.22, 0.45, 0), (0.35, 0.9, 0.35), pants, "r_leg")
        self.l_arm = _part(self, (-0.65, 1.15, 0), (0.3, 0.85, 0.3), skin, "l_arm")
        self.r_arm = _part(self, (0.65, 1.15, 0), (0.3, 0.85, 0.3), skin, "r_arm")

        s = player.speed

        # ── Shoes ────────────────────────────────────────────────────
        shoe_col = color.rgb(0.08, 0.08, 0.1)
        self._part(self, (-0.5 * s, 0.08 * s, 0.05 * s), (0.72 * s, 0.22 * s, 0.78 * s), shoe_col, "l_shoe")
        self._part(self, (0.5 * s, 0.08 * s, 0.05 * s), (0.72 * s, 0.22 * s, 0.78 * s), shoe_col, "r_shoe")

        # ── Face (on head) ───────────────────────────────────────────
        eye_col = color.rgb(0.12, 0.12, 0.7)
        self._face_part(self.head, (-0.15, 0.05, 0.5), (0.18, 0.18, 0.1), eye_col, "l_eye")
        self._face_part(self.head, (0.15, 0.05, 0.5), (0.18, 0.18, 0.1), eye_col, "r_eye")
        self._face_part(self.head, (-0.15, 0.05, 0.52), (0.09, 0.09, 0.12), color.black, "l_pupil")
        self._face_part(self.head, (0.15, 0.05, 0.52), (0.09, 0.09, 0.12), color.black, "r_pupil")
        mouth_col = color.rgb(0.75, 0.35, 0.35)
        for mx in (-0.15, 0, 0.15):
            self._face_part(self.head, (mx, -0.2, 0.5), (0.09, 0.07, 0.1), mouth_col, "mouth")

        # ── Nametag ────────────────────────────────────────────────────
        self.nametag = Text(
            text=player.name, parent=self, y=2.35, scale=8,
            origin=(0, 0), color=color.white, billboard=True, background=True,
        )

        # ── Weapon holders (attached to right arm) ─────────────────────
        self.knife_entity = None
        self.gun_entity_w = None
        self._show_weapon(player.role)

        self.dead_tilt = 0
        self.is_alive = True
        self.role_light = None

    def _part(self, parent, pos, scale, col, name):
        return Entity(
            parent=parent, model="cube", color=col,
            position=pos, scale=scale, collider=None, name=name,
            texture="white_cube",
        )

    def _face_part(self, parent, pos, scale, col, name):
        return Entity(
            parent=parent, model="cube", color=col,
            position=pos, scale=scale, collider=None, name=name,
            texture="white_cube",
        )

    def _show_weapon(self, role):
        if self.knife_entity:
            destroy(self.knife_entity)
            self.knife_entity = None
        if self.gun_entity_w:
            destroy(self.gun_entity_w)
            self.gun_entity_w = None

        if role == "murderer":
            self.knife_entity = Entity(
                parent=self.r_arm, model="cube", name="knife",
            )
            # Blade
            Entity(
                parent=self.knife_entity, model="cube",
                color=color.rgb(0.82, 0.84, 0.9),
                position=(0, -0.55, 0.28), scale=(0.07, 0.5, 0.07),
                rotation_z=12, texture="white_cube",
            )
            # Handle
            Entity(
                parent=self.knife_entity, model="cube",
                color=color.rgb(0.35, 0.22, 0.1),
                position=(0, -0.82, 0.28), scale=(0.12, 0.18, 0.12),
                texture="white_cube",
            )
        elif role == "sheriff":
            self.gun_entity_w = Entity(
                parent=self.r_arm, model="cube", name="gun",
            )
            # Body
            Entity(
                parent=self.gun_entity_w, model="cube",
                color=color.rgb(0.18, 0.18, 0.22),
                position=(0, -0.32, 0.42), scale=(0.12, 0.17, 0.36),
                texture="white_cube",
            )
            # Barrel
            Entity(
                parent=self.gun_entity_w, model="cube",
                color=color.rgb(0.14, 0.14, 0.18),
                position=(0, -0.25, 0.64), scale=(0.06, 0.06, 0.22),
                texture="white_cube",
            )
            # Grip
            Entity(
                parent=self.gun_entity_w, model="cube",
                color=color.rgb(0.3, 0.22, 0.14),
                position=(0, -0.46, -0.04), scale=(0.1, 0.22, 0.1),
                texture="white_cube",
            )

    def sync_alive(self, alive):
        if alive == self.is_alive:
            return
        self.is_alive = alive
        if not alive and self.dead_tilt == 0:
            self.animate("rotation_z", 88, duration=0.5, curve=curve.out_expo)
            self.animate("y", -0.25, duration=0.5)
            self.dead_tilt = 88
            if self.nametag:
                self.nametag.enabled = False
        elif alive:
            self.rotation_z = 0
            self.dead_tilt = 0
            self.enabled = True
            if self.nametag:
                self.nametag.enabled = True

    def animate_walk(self, moving):
        swing = 0.35 if moving else 0
        t = self.player.anim_phase
        self.l_arm.rotation_x = math.sin(t) * swing * 40
        self.r_arm.rotation_x = -math.sin(t) * swing * 40
        self.l_leg.rotation_x = -math.sin(t) * swing * 30
        self.r_leg.rotation_x = math.sin(t) * swing * 30

    def face_movement(self):
        fx, fy = self.player.facing
        if abs(fx) + abs(fy) > 0.01:
            self.rotation_y = math.degrees(math.atan2(fx, fy))

    def set_role_glow(self, role):
        if self.role_light:
            destroy(self.role_light)
            self.role_light = None
        if role == "murderer":
            self.role_light = PointLight(
                parent=self, position=(0, 2, 0),
                color=color.rgba(200, 0, 0, 120), range=3,
            )
        elif role == "sheriff":
            self.role_light = PointLight(
                parent=self, position=(0, 2, 0),
                color=color.rgba(220, 190, 0, 100), range=2,
            )

    def destroy_avatar(self):
        destroy(self)


# ── 3D Map ──────────────────────────────────────────────────────────────

class Map3D:
    def __init__(self, map_data):
        self.entities = []
        self.map_data = map_data
        mw = map_data.get("width", 800) * PIXEL_SCALE
        mh = map_data.get("height", 600) * PIXEL_SCALE

        # Perimeter + interior walls
        for w in map_data["walls"]:
            cx = (w["x"] + w["w"] / 2) * PIXEL_SCALE
            cz = (w["y"] + w["h"] / 2) * PIXEL_SCALE
            wx = w["w"] * PIXEL_SCALE
            wz = w["h"] * PIXEL_SCALE
            height = 3.5 if max(wx, wz) > 8 else 2.5
            wall = Entity(
                model="cube",
                color=_c((85, 100, 85)),
                position=(cx, height / 2, cz),
                scale=(max(wx, 0.5), height, max(wz, 0.5)),
                collider="box",
                texture="white_cube",
            )
            self.entities.append(wall)

        # Decorative props from map data
        props = [(200, 200, 1.2, 1.8, 1.2), (600, 400, 1.5, 2.0, 1.5)]
        for px, py, sx, sy, sz in props:
            wx, _, wz = pixel_to_world(px, py)
            crate = Entity(
                model="cube", color=_c((120, 90, 60)),
                position=(wx, sy / 2, wz), scale=(sx, sy, sz),
                collider="box", texture="white_cube",
            )
            self.entities.append(crate)

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
        self.bullet_entities = []
        self.gun_entity = None
        self.ui_root = None
        self.hud = None
        self.human_elev = 0.0
        self.human_vy = 0.0
        self.cam_yaw = 0.0
        self.mouse_sensitivity = 40

        # ── Effects (Prompt 1) ────────────────────────────────────────
        self.fx = None
        self.kill_feed = None
        self._prev_alive_ids = set()
        self._prev_human_gun = False
        self._prev_buck_count = 0
        self._near_murderer_timer = 0.0

        # ── UI widgets (Prompt 4) ─────────────────────────────────────
        self.timer_text = None
        self.stamina_bg = None
        self.stamina_fill = None
        self.stamina_label = None
        self.crosshair = None

        # ── Environment entities (Prompt 2) ───────────────────────────
        self.env_entities = []

    # ── Scene setup (Prompt 2) ──────────────────────────────────────────

    def setup_scene(self):
        # Night sky
        Sky(color=color.rgb(0.03, 0.04, 0.1))

        # Moonlight
        DirectionalLight(
            direction=(-0.57, -0.57, -0.57),
            color=color.rgba(140, 160, 255, 180),
        )
        AmbientLight(color=color.rgba(30, 25, 50, 100))

        # Fog
        scene.fog_color = color.rgba(12, 15, 28, 255)
        scene.fog_density = 0.022

        # Checkerboard ground tiles
        tile_size = 4.0
        shades = [
            color.rgba(40, 45, 38, 255),
            color.rgba(55, 60, 50, 255),
        ]
        for ix in range(-13, 13):
            for iz in range(-13, 13):
                wx = ix * tile_size + tile_size / 2
                wz = iz * tile_size + tile_size / 2
                shade_idx = (ix + iz) & 1
                tile = Entity(
                    model="cube",
                    color=shades[shade_idx],
                    position=(wx, -0.04, wz),
                    scale=(tile_size * 0.98, 0.08, tile_size * 0.98),
                    texture="white_cube",
                )
                self.env_entities.append(tile)

        # Trees
        tree_positions = [
            (-22, 0, -22), (22, 0, -22), (-22, 0, 22), (22, 0, 22),
            (0, 0, -36), (-36, 0, 0),
        ]
        for tp in tree_positions:
            self.env_entities.extend(create_tree(Vec3(*tp)))

        # Lampposts
        lamp_positions = [
            (-15, 0, -15), (15, 0, -15), (-15, 0, 15), (15, 0, 15),
        ]
        for lp in lamp_positions:
            self.env_entities.extend(create_lamppost(Vec3(*lp)))

        # Barrels
        barrel_positions = [
            (-8, 0, -10), (8, 0, -10), (-8, 0, 10), (8, 0, 10),
        ]
        for bp in barrel_positions:
            self.env_entities.extend(create_barrel(Vec3(*bp)))

    # ── App lifecycle ───────────────────────────────────────────────────

    def run(self):
        self.app = Ursina(
            title="M Mystery 3D",
            borderless=False,
            fullscreen=False,
            development_mode=False,
        )
        window.size = (1280, 720)
        window.fps_counter.enabled = True

        self.setup_scene()
        self.fx = ScreenEffects()
        self.kill_feed = KillFeed()

        self._build_menu_ui()
        global _APP_INSTANCE
        _APP_INSTANCE = self
        self.app.run()

    def _clear_ui(self):
        if self.ui_root:
            destroy(self.ui_root)
            self.ui_root = None

    # ── Main menu (Prompt 4 restyle) ────────────────────────────────────

    def _build_menu_ui(self):
        self._clear_ui()
        self.state = "menu"
        self.ui_root = Entity()

        # Dark panel background
        Entity(
            parent=self.ui_root, model="quad",
            color=color.rgba(6, 8, 22, 235),
            scale=(0.62, 0.52),
        )

        # Glowing cyan title
        Text(
            parent=self.ui_root, text="M MYSTERY",
            color=color.cyan, scale=4.8, position=(0, 0.13),
            origin=(0, 0),
        )

        # Subtitle
        Text(
            parent=self.ui_root, text="3D  EDITION",
            color=color.rgba(80, 210, 255, 200),
            scale=1.5, position=(0, 0.05), origin=(0, 0),
        )

        # Accent line
        Entity(
            parent=self.ui_root, model="quad",
            color=color.rgba(0, 200, 255, 50),
            scale=(0.62, 0.005), position=(0, 0.01),
        )

        def play():
            self._build_lobby_ui()

        # Play button (styled)
        Button(
            parent=self.ui_root, text="▶  PLAY",
            color=color.rgb(0, 0.51, 0.78),
            highlight_color=color.rgb(0, 0.6, 0.9),
            scale=(0.2, 0.07), position=(0, -0.08),
            on_click=play,
        )

        # Controls hint
        Text(
            parent=self.ui_root,
            text="[WASD] Move  [Shift] Sprint  [Space] Attack  [RMB] Camera",
            color=color.rgba(130, 130, 160, 200),
            scale=0.95, position=(0, -0.19), origin=(0, 0),
        )

        # Quit button
        Button(
            parent=self.ui_root, text="Quit",
            scale=(0.15, 0.05), position=(0, -0.27),
            color=color.rgb(0.35, 0.35, 0.45),
            on_click=application.quit,
        )

    # ── Lobby ───────────────────────────────────────────────────────────

    def _build_lobby_ui(self):
        self._clear_ui()
        self.state = "lobby"
        self.ui_root = Entity()
        m = self.maps[self.map_index]

        Text(parent=self.ui_root, text="SERVERS", y=0.38, scale=2.5, origin=(0, 0))
        Text(parent=self.ui_root, text=f"Map: {m['name']}  (< >)", y=0.28, scale=1.3, origin=(0, 0))
        Text(
            parent=self.ui_root,
            text=f"Round {self.round_number}  •  {len(self.all_players)}/6 players",
            y=0.22, scale=1, origin=(0, 0), color=color.light_gray,
        )

        y = 0.12
        for p in self.all_players:
            tag = " (You)" if p is self.human else ""
            Text(parent=self.ui_root, text=f"  {p.name}{tag}", y=y, scale=0.9, origin=(0, 0))
            y -= 0.05

        Button(parent=self.ui_root, text="Play", y=-0.12, scale=(0.3, 0.07),
               color=color.rgb(0, 0.75, 0.38), on_click=self._start_round)
        Button(parent=self.ui_root, text="Back", y=-0.22, scale=(0.2, 0.06),
               on_click=self._build_menu_ui)

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

        # ── Role glow on human avatar (Prompt 3) ──────────────────────
        if self.kill_feed:
            self.kill_feed.clear()

        self.state = "reveal"
        role = self.human.role.upper()
        rc = ROLE_COLORS.get(self.human.role, (200, 200, 200))
        self.role_panel = Entity()
        Text(parent=self.role_panel, text="YOUR ROLE IS", y=0.15, scale=2, origin=(0, 0))
        Text(parent=self.role_panel, text=role, y=0.05, scale=3, origin=(0, 0),
             color=color.rgb(rc[0] / 255, rc[1] / 255, rc[2] / 255))
        Text(parent=self.role_panel,
             text="Space=Attack  Shift=Sprint  Q=Jump  Mouse=Look",
             y=-0.05, scale=0.9, origin=(0, 0), color=color.light_gray)
        Button(parent=self.role_panel, text="I'm Ready", y=-0.15, scale=(0.25, 0.07),
               color=color.rgb(0.2, 0.7, 0.3), on_click=self._enter_world)

    def _enter_world(self):
        if self.role_panel:
            destroy(self.role_panel)
            self.role_panel = None
        self._clear_ui()

        map_data = self.maps[self.map_index]["data"]
        if self.map3d:
            self.map3d.destroy_map()
        self.map3d = Map3D(map_data)
        self.session = RoundSession(self.all_players, map_data, self.wallet, self.human)

        self.avatars = {}
        for p in self.all_players:
            wx, wy, wz = pixel_to_world(p.x, p.y)
            av = Avatar3D(p, position=(wx, wy, wz))
            av.set_role_glow(p.role)
            self.avatars[p.id] = av

        self._spawn_buck_visuals()
        self.state = "playing"
        self.human_elev = 0
        self.human_vy = 0
        self.cam_yaw = 0

        # Track state for event detection
        self._prev_alive_ids = {p.id for p in self.all_players if p.is_alive}
        self._prev_human_gun = self.human.has_gun
        self._prev_buck_count = len(self.session.bucks)
        self._near_murderer_timer = 0.0

        mouse.locked = True
        self._build_hud()
        self._setup_ui()

    # ── HUD & UI (Prompt 4) ─────────────────────────────────────────────

    def _build_hud(self):
        self.hud = Text(
            text="", position=(-0.86, 0.46), scale=1.2,
            color=color.white, background=True,
        )

    def _setup_ui(self):
        # Crosshair
        self.crosshair = Entity(parent=camera.ui)
        shadow_col = color.rgba(0, 0, 0, 80)
        Entity(parent=self.crosshair, model="quad", color=color.rgba(255, 255, 255, 190),
               scale=(0.002, 0.02))
        Entity(parent=self.crosshair, model="quad", color=color.rgba(255, 255, 255, 190),
               scale=(0.02, 0.002))
        Entity(parent=self.crosshair, model="quad", color=shadow_col,
               scale=(0.002, 0.02), position=(0.0005, -0.0005))
        Entity(parent=self.crosshair, model="quad", color=shadow_col,
               scale=(0.02, 0.002), position=(0.0005, -0.0005))

        # Timer text
        self.timer_text = Text(
            parent=camera.ui, origin=(0, 0), position=(0, 0.42),
            scale=2.0, color=color.white,
        )

        # Stamina bar
        self.stamina_bg = Entity(
            parent=camera.ui, model="quad",
            color=color.rgba(15, 15, 25, 220),
            scale=(0.22, 0.03), position=(0.78, -0.46),
        )
        self.stamina_fill = Entity(
            parent=camera.ui, model="quad",
            color=color.rgb(0.2, 0.82, 0.35),
            scale=(0.20, 0.025), position=(0.682, -0.46),
            origin=(-0.5, 0),
        )
        self.stamina_label = Text(
            parent=camera.ui, text="STAMINA",
            scale=0.85, color=color.rgba(180, 255, 180, 180),
            position=(0.78, -0.43), origin=(0, 0),
        )

    # ── Buck visuals ────────────────────────────────────────────────────

    def _spawn_buck_visuals(self):
        for ent, _, _ in self.buck_entities.values():
            destroy(ent)
        self.buck_entities.clear()
        for i, (bx, by, val) in enumerate(self.session.bucks):
            wx, wy, wz = pixel_to_world(bx, by, 1.0)
            coin = Entity(
                model="sphere", color=color.gold,
                position=(wx, wy, wz), scale=0.35 + val * 0.05,
            )
            coin.spin_speed = 90 + i * 10
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

    def _sync_visuals(self):
        for p in self.all_players:
            av = self.avatars.get(p.id)
            if not av:
                continue
            wx, base_y, wz = pixel_to_world(p.x, p.y)
            elev = self.human_elev if p is self.human else 0
            av.position = (wx, base_y + elev, wz)
            av.sync_alive(p.is_alive)
            av.animate_walk(p.is_moving)
            av.face_movement()

        # Bucks
        live = {(b[0], b[1]) for b in self.session.bucks}
        for key, (ent, bx, by) in list(self.buck_entities.items()):
            if (bx, by) not in live:
                destroy(ent)
                del self.buck_entities[key]
            else:
                ent.rotation_y += time.dt * getattr(ent, "spin_speed", 60)

        # Gun drop
        if self.session.dropped_gun_pos:
            gx, gy = self.session.dropped_gun_pos
            wx, wy, wz = pixel_to_world(gx, gy, 0.4)
            if not self.gun_entity:
                self.gun_entity = Entity(
                    model="cube", color=color.yellow,
                    position=(wx, wy, wz), scale=(0.5, 0.2, 0.8),
                )
            else:
                self.gun_entity.position = (wx, wy, wz)
                self.gun_entity.rotation_y += time.dt * 120
        elif self.gun_entity:
            destroy(self.gun_entity)
            self.gun_entity = None

        # Bullets
        for ent in self.bullet_entities:
            destroy(ent)
        self.bullet_entities.clear()
        for b in self.session.bullets:
            if b.is_active:
                wx, wy, wz = pixel_to_world(b.x, b.y, 0.8)
                be = Entity(model="sphere", color=color.white, position=(wx, wy, wz), scale=0.2)
                self.bullet_entities.append(be)

        # Third-person camera
        h = self.avatars.get(self.human.id)
        if h and self.human.is_alive:
            yr = math.radians(self.cam_yaw)
            dist = 11
            height = 5 + self.human_elev * 0.5
            cam_x = h.x - math.sin(yr) * dist
            cam_z = h.z - math.cos(yr) * dist
            camera.position = Vec3(cam_x, h.y + height, cam_z)
            camera.look_at(Vec3(h.x, h.y + 2, h.z))

        # HUD text
        if self.hud and self.session:
            role = self.human.role.upper()
            self.hud.text = (
                f"{role}  |  {self.session.round_manager.get_time_string()}  "
                f"|  Alive: {self.session.alive_count}  "
                f"|  Bucks: {self.human.m_bucks_this_round}/50  "
                f"|  Shift Sprint  Q Jump  Space Attack"
            )

    def _update_ui(self):
        if not self.session or self.state != "playing":
            return

        # Timer (Prompt 4)
        remaining = self.session.round_manager.remaining
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        if self.timer_text:
            self.timer_text.text = f"{mins}:{secs:02d}"
            if remaining < 30:
                self.timer_text.color = color.rgba(255, 60, 60, 255)
            else:
                self.timer_text.color = color.white

        # Stamina bar (Prompt 4)
        if self.human and self.stamina_fill:
            pct = self.human.stamina / self.human.max_stamina
            self.stamina_fill.scale_x = 0.20 * pct
            if pct > 0.6:
                self.stamina_fill.color = color.rgb(0.2, 0.82, 0.35)
            elif pct > 0.3:
                self.stamina_fill.color = color.rgb(0.86, 0.78, 0.2)
            else:
                self.stamina_fill.color = color.rgb(0.86, 0.27, 0.2)

    # ── Main update loop ────────────────────────────────────────────────

    def update(self):
        if self.state == "lobby":
            if held_keys["left arrow"]:
                self.map_index = (self.map_index - 1) % len(self.maps)
                self._build_lobby_ui()
            elif held_keys["right arrow"]:
                self.map_index = (self.map_index + 1) % len(self.maps)
                self._build_lobby_ui()

        if self.state != "playing" or not self.session:
            self.fx.update()
            if self.kill_feed:
                self.kill_feed.update()
            return

        if mouse.locked:
            self.cam_yaw += mouse.velocity[0] * self.mouse_sensitivity

        sprinting = held_keys["shift"]
        dx, dy = self._camera_relative_move()
        self.session.tick_human_move(time.dt, dx, dy, sprinting)

        if held_keys["q"] and self.human_elev <= 0.05:
            self.human_vy = 11
        self.human_vy -= 28 * time.dt
        self.human_elev += self.human_vy * time.dt
        if self.human_elev < 0:
            self.human_elev = 0
            self.human_vy = 0

        # ── Event detection ─────────────────────────────────────────────
        prev_alive = self._prev_alive_ids.copy()
        prev_gun = self._prev_human_gun
        prev_buck_count = self._prev_buck_count

        # Attack
        if held_keys["space"]:
            self.session._human_attack()

        # Tick simulation
        winner = self.session.tick_simulation(time.dt)

        # ── Detect knife kill (human only) ──────────────────────────────
        current_alive = {p.id for p in self.all_players if p.is_alive}
        dead_ids = prev_alive - current_alive
        if dead_ids and self.human.has_knife and "space" in held_keys:
            victim = next((p for p in self.all_players if p.id in dead_ids), None)
            if victim:
                d = math.hypot(self.human.x - victim.x, self.human.y - victim.y)
                if d <= 45:
                    wx, wy, wz = pixel_to_world(victim.x, victim.y)
                    spawn_death_particles(Vec3(wx, wy, wz))
                    self.fx.screen_shake(0.2, 0.25)
                    if self.kill_feed:
                        self.kill_feed.add("You", victim.name, "knife")

        # ── Detect gun fire ─────────────────────────────────────────────
        if prev_gun and not self.human.has_gun:
            h_av = self.avatars.get(self.human.id)
            if h_av:
                spawn_muzzle_flash(h_av.world_position + camera.forward * 0.5)
            self.fx.white_flash()

        # ── Detect buck collection ──────────────────────────────────────
        current_buck_count = len(self.session.bucks)
        if current_buck_count < prev_buck_count:
            collected = prev_buck_count - current_buck_count
            if collected > 0:
                h_av = self.avatars.get(self.human.id)
                if h_av:
                    spawn_coin_particles(h_av.world_position + Vec3(0, 1.5, 0))

        # ── Update tracking ─────────────────────────────────────────────
        self._prev_alive_ids = current_alive
        self._prev_human_gun = self.human.has_gun
        self._prev_buck_count = current_buck_count

        # ── Sync visuals ────────────────────────────────────────────────
        self._sync_visuals()

        # ── Shake from round_session ────────────────────────────────────
        shake = self.session.screen_shake
        if shake["frames_left"] > 0:
            shake["frames_left"] -= 1
            camera.position += Vec3(
                random.uniform(-0.2, 0.2),
                random.uniform(-0.1, 0.1),
                random.uniform(-0.2, 0.2),
            )

        # ── Blood flash near murderer ───────────────────────────────────
        self._near_murderer_timer += time.dt
        if self._near_murderer_timer > 1.5:
            murderer = next(
                (p for p in self.all_players if p.role == "murderer" and p.is_alive),
                None,
            )
            if murderer:
                dx = self.human.x - murderer.x
                dy = self.human.y - murderer.y
                if math.sqrt(dx * dx + dy * dy) < 60:
                    self.fx.blood_flash()
            self._near_murderer_timer = 0.0

        # ── UI updates ──────────────────────────────────────────────────
        self._update_ui()

        # ── Screen effects ──────────────────────────────────────────────
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
        if self.hud:
            destroy(self.hud)
            self.hud = None
        if self.timer_text:
            destroy(self.timer_text)
            self.timer_text = None
        if self.stamina_bg:
            destroy(self.stamina_bg)
            self.stamina_bg = None
        if self.stamina_fill:
            destroy(self.stamina_fill)
            self.stamina_fill = None
        if self.stamina_label:
            destroy(self.stamina_label)
            self.stamina_label = None
        if self.crosshair:
            destroy(self.crosshair)
            self.crosshair = None
        if self.kill_feed:
            self.kill_feed.clear()

        for ent in self.bullet_entities:
            destroy(ent)
        self.bullet_entities.clear()
        if self.gun_entity:
            destroy(self.gun_entity)
            self.gun_entity = None

        self.state = "end"
        label = "Murderer wins!" if winner == "murderer" else "Innocents win!"
        self.ui_root = Entity()
        Text(parent=self.ui_root, text=label, y=0.2, scale=2.5, origin=(0, 0))
        Button(parent=self.ui_root, text="Next Round", y=0, scale=(0.3, 0.07),
               on_click=self._next_round)
        Button(parent=self.ui_root, text="Menu", y=-0.1, scale=(0.25, 0.06),
               on_click=self._build_menu_ui)

    def _next_round(self):
        self.round_number += 1
        self._build_lobby_ui()

    # ── Input ───────────────────────────────────────────────────────────

    def input(self, key):
        if key == "escape":
            if self.state == "playing":
                mouse.locked = False
                self._end_round("innocents")
            elif self.state == "lobby":
                self._build_menu_ui()
            else:
                application.quit()


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

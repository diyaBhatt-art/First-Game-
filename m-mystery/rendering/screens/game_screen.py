import math
import random
import pygame

from core.player import Player
from core.round import RoundManager
from core.shop import ShopManager
from rendering.screens.shop_screen import ShopScreen

# Role hex → RGB for the aura_scan effect
ROLE_COLORS = {
    "murderer": (229, 49, 112),
    "sheriff": (244, 197, 66),
    "innocent": (44, 181, 232),
}


class GameScreen:
    """Main gameplay screen — renders the map, players, combat, HUD, and shop."""

    def __init__(self, players, wallet_manager, map_data, on_round_end=None, on_quit_to_menu=None):
        """
        Args:
            players: list of Player / Bot objects (roles already assigned)
            wallet_manager: WalletManager instance (for shop purchases)
            map_data: dict loaded from a map JSON file (must contain walls,
                      spawn_points, buck_spawn_zones)
            on_round_end: callable(winner_str) — invoked when a win condition is met
            on_quit_to_menu: callable — ESC confirmation → go to main menu
        """
        self.map_data = map_data

        self.walls = [
            pygame.Rect(w["x"], w["y"], w["w"], w["h"])
            for w in self.map_data["walls"]
        ]

        self.players = players
        self.human = next(p for p in players if not p.is_bot)

        # --- Round timer ---
        self.round_manager = RoundManager(180)
        self.on_round_end = on_round_end
        self.on_quit_to_menu = on_quit_to_menu

        # --- Combat state ---
        self.last_move_dir = (0, -1)
        self.bullets = []
        self.dropped_gun_pos = None

        # --- M Bucks pickups ---
        self.bucks = self._spawn_bucks()

        # --- Shop system ---
        self.wallet_manager = wallet_manager
        self.shop_manager = ShopManager()
        self.shop_open = False
        self.shop_screen = ShopScreen(
            self.shop_manager,
            self.wallet_manager,
            self.human,
            on_purchase=self._handle_shop_purchase,
            on_close=self._close_shop,
        )

        # --- Active timed effects (set by ShopManager) ---
        self.active_effects = {}

        # --- Murderer position trail (for footprints effect) ---
        self.murderer_trail = []  # list of (x, y), max 20 entries

        # --- Noise traps (placed by Noise Trap item) ---
        self.noise_traps = []

        # --- Screen shake (triggered by Noise Trap / Alarm) ---
        self.screen_shake = {"frames_left": 0, "intensity": 6}

        # --- ESC quit confirmation dialog ---
        self._show_quit_dialog = False
        self._quit_yes_btn = pygame.Rect(260, 310, 120, 40)
        self._quit_no_btn = pygame.Rect(420, 310, 120, 40)

    # ------------------------------------------------------------------
    # M Bucks spawning
    # ------------------------------------------------------------------

    def _spawn_bucks(self):
        zones = self.map_data["buck_spawn_zones"]
        picks = []
        for _ in range(20):
            zone = random.choice(zones)
            x = random.randint(zone["x"], zone["x"] + zone["w"])
            y = random.randint(zone["y"], zone["y"] + zone["h"])
            value = random.randint(1, 3)
            picks.append((x, y, value))
        return picks

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def alive_count(self):
        return sum(1 for p in self.players if p.is_alive)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_events(self, events):
        # ESC quit dialog takes priority
        if self._show_quit_dialog:
            for event in events:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self._show_quit_dialog = False
                    return
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mx, my = event.pos
                    if self._quit_yes_btn.collidepoint(mx, my):
                        self._show_quit_dialog = False
                        if self.on_quit_to_menu:
                            self.on_quit_to_menu()
                    elif self._quit_no_btn.collidepoint(mx, my):
                        self._show_quit_dialog = False
            return

        if self.shop_open:
            self.shop_screen.handle_events(events)
            return

        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self._show_quit_dialog = True
                elif event.key == pygame.K_e:
                    self.shop_open = True
                elif event.key == pygame.K_SPACE:
                    self._human_attack()

    def _human_attack(self):
        ghost_ids = set()
        if "ghost_mode" in self.active_effects:
            ghost_ids.add(self.active_effects["ghost_mode"]["buyer_id"])

        if self.human.has_knife:
            nearest = None
            nearest_dist = 41
            for p in self.players:
                if p is self.human or not p.is_alive:
                    continue
                if p.id in ghost_ids:
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
                    (p for p in self.players
                     if p.role == "murderer" and p.is_alive),
                    None,
                )
                if murderer:
                    dx = murderer.x - self.human.x
                    dy = murderer.y - self.human.y
                    dist = math.sqrt(dx * dx + dy * dy)
                    if dist <= 300:
                        fire_dir = (dx, dy)
                del self.active_effects["dead_eye"]

            bullet = self.human.try_shoot(fire_dir)
            if bullet:
                self.bullets.append(bullet)

    # ------------------------------------------------------------------
    # Game logic update  (called once per frame)
    # ------------------------------------------------------------------

    def update(self, dt):
        if self.shop_open:
            return

        self.round_manager.tick(dt)

        for p in self.players:
            if p.attack_cooldown > 0:
                p.attack_cooldown -= 1

        keys = pygame.key.get_pressed()
        dx = 0.0
        dy = 0.0
        speed = self.human.speed
        if keys[pygame.K_w]:
            dy = -speed
        if keys[pygame.K_s]:
            dy = speed
        if keys[pygame.K_a]:
            dx = -speed
        if keys[pygame.K_d]:
            dx = speed

        if dx != 0 or dy != 0:
            length = math.sqrt(dx * dx + dy * dy)
            self.last_move_dir = (dx / length, dy / length)

        self.human.move(dx, dy, self.walls)

        for p in self.players:
            if p.is_bot and p.is_alive:
                bullet = p.update(self.players, self.walls, self.dropped_gun_pos)
                if bullet:
                    self.bullets.append(bullet)

        self._update_bullets()
        self._check_dropped_gun()
        self._check_buck_collection()

        # Tick active effect timers
        self._tick_effects()

        # Track Murderer's recent positions for the footprints effect
        self._update_murderer_trail()

        # Noise trap checks
        self._check_noise_traps()

        # Alarm proximity check
        self._check_alarm()

        winner = self.round_manager.check_win_conditions(self.players)
        if winner and self.on_round_end:
            self.on_round_end(winner)
            self.on_round_end = None  # prevent re-fire on subsequent frames

    def _update_bullets(self):
        for bullet in self.bullets[:]:
            if not bullet.is_active:
                self.bullets.remove(bullet)
                continue

            bullet.update()

            b_rect = bullet.get_rect()
            hit_wall = any(b_rect.colliderect(w) for w in self.walls)
            if hit_wall:
                bullet.is_active = False
                self.bullets.remove(bullet)
                continue

            for p in self.players:
                if not p.is_alive:
                    continue
                dx = bullet.x - p.x
                dy = bullet.y - p.y
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < 15:
                    if p.role == "murderer":
                        p.is_alive = False
                        print(f"[COMBAT] {p.name} was shot and killed!")
                    else:
                        print(
                            f"[COMBAT] Bullet hit {p.name} but "
                            f"did nothing (gun only hurts Murderer)"
                        )
                    bullet.is_active = False
                    self.bullets.remove(bullet)
                    break

    def _check_dropped_gun(self):
        if self.dropped_gun_pos is None:
            for p in self.players:
                if p.role == "sheriff" and not p.is_alive:
                    self.dropped_gun_pos = (p.x, p.y)
                    print("[GAME] Sheriff died — gun dropped on the floor")
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
                    print(f"[GAME] {p.name} picked up the gun")
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
                    collected = p.collect_buck(value)
                    if collected > 0:
                        self.bucks.remove(buck)
                        print(f"[BUCKS] {p.name} collected {collected} M Buck(s)")

    # ------------------------------------------------------------------
    # Active effect management
    # ------------------------------------------------------------------

    def _tick_effects(self):
        """Decrement effect frame counters and remove expired effects."""
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
        """Store the last 20 positions of the living Murderer for footprints."""
        for p in self.players:
            if p.role == "murderer" and p.is_alive:
                self.murderer_trail.append((p.x, p.y))
                if len(self.murderer_trail) > 20:
                    self.murderer_trail.pop(0)
                return
        self.murderer_trail.clear()

    def _check_noise_traps(self):
        """If the Murderer walks over a noise trap, trigger screen shake."""
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
                print("[NOISE_TRAP] Murderer stepped on a trap!")

    def _check_alarm(self):
        """Shake the screen if the Murderer is within 100px of the alarm buyer."""
        eff = self.active_effects.get("alarm")
        if not eff:
            return
        buyer = next(
            (p for p in self.players if p.id == eff["buyer_id"] and p.is_alive), None
        )
        murderer = next(
            (p for p in self.players if p.role == "murderer" and p.is_alive), None
        )
        if not buyer or not murderer:
            return
        eff["buyer_x"] = buyer.x
        eff["buyer_y"] = buyer.y
        dx = murderer.x - buyer.x
        dy = murderer.y - buyer.y
        if math.sqrt(dx * dx + dy * dy) < 100:
            self.screen_shake["frames_left"] = max(self.screen_shake["frames_left"], 5)

    # ------------------------------------------------------------------
    # Shop callbacks
    # ------------------------------------------------------------------

    def _handle_shop_purchase(self, item_id):
        self.shop_manager.purchase(self.human.id, item_id, self.wallet_manager, self)

    def _close_shop(self):
        self.shop_open = False
        winner = self.round_manager.check_win_conditions(self.players)
        if winner and self.on_round_end:
            self.on_round_end(winner)
            self.on_round_end = None

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, screen):
        ox = oy = 0
        shake = self.screen_shake
        if shake["frames_left"] > 0:
            shake["frames_left"] -= 1
            ox = random.randint(-shake["intensity"], shake["intensity"])
            oy = random.randint(-shake["intensity"], shake["intensity"])

        screen.fill((30, 30, 30))

        for wall in self.walls:
            pygame.draw.rect(screen, (60, 60, 60),
                             (wall.x + ox, wall.y + oy, wall.w, wall.h))

        # Noise traps
        for trap in self.noise_traps:
            tx, ty = int(trap["x"]) + ox, int(trap["y"]) + oy
            pygame.draw.circle(screen, (200, 100, 50), (tx, ty), 6)
            pygame.draw.circle(screen, (255, 150, 80), (tx, ty), 3)

        for buck in self.bucks:
            bx, by, _ = buck
            pygame.draw.circle(screen, (255, 215, 0), (bx + ox, by + oy), 5)

        ghost_id = None
        if "ghost_mode" in self.active_effects:
            ghost_id = self.active_effects["ghost_mode"]["buyer_id"]

        for player in self.players:
            if not player.is_alive:
                continue
            cx, cy = int(player.x) + ox, int(player.y) + oy
            if player.id == ghost_id:
                surf = pygame.Surface((28, 28), pygame.SRCALPHA)
                pygame.draw.circle(surf, (*player.color, 80), (14, 14), 10)
                pygame.draw.circle(surf, (255, 255, 255, 80), (14, 14), 3)
                screen.blit(surf, (cx - 14, cy - 14))
            else:
                pygame.draw.circle(screen, player.color, (cx, cy), 10)
                pygame.draw.circle(screen, (255, 255, 255), (cx, cy), 3)

        for bullet in self.bullets:
            if bullet.is_active:
                pygame.draw.circle(
                    screen, (255, 255, 255),
                    (int(bullet.x) + ox, int(bullet.y) + oy), 4
                )

        if self.dropped_gun_pos is not None:
            gx, gy = int(self.dropped_gun_pos[0]) + ox, int(self.dropped_gun_pos[1]) + oy
            pygame.draw.circle(screen, (255, 255, 0), (gx, gy), 8)
            font = pygame.font.Font(None, 20)
            label = font.render("G", True, (0, 0, 0))
            label_rect = label.get_rect(center=(gx, gy))
            screen.blit(label, label_rect)

        # --- Active effects (on top of game world, under HUD) ---
        self._draw_active_effects(screen, ox, oy)

        # --- HUD (no shake offset) ---
        timer_str = self.round_manager.get_time_string()
        bucks_str = f"{self.human.m_bucks_this_round} / 50"
        hud_text = (
            f"Timer: {timer_str} | Alive: {self.alive_count} | "
            f"M Bucks: {bucks_str}"
        )
        font = pygame.font.Font(None, 28)
        hud_surf = font.render(hud_text, True, (255, 255, 255))
        pygame.draw.rect(screen, (0, 0, 0), (0, 0, screen.get_width(), 30))
        screen.blit(hud_surf, (10, 5))

        # --- Shop overlay (no shake offset) ---
        if self.shop_open:
            self.shop_screen.draw(screen)

        # --- ESC quit confirmation dialog (no shake offset) ---
        if self._show_quit_dialog:
            self._draw_quit_dialog(screen)

    def _draw_active_effects(self, screen, ox=0, oy=0):
        """Draw timed effect visuals (footprints, tracker, aura_scan)."""

        # ---- Footprints: fading trail behind the Murderer ----
        if "footprints" in self.active_effects:
            count = len(self.murderer_trail)
            for i, (tx, ty) in enumerate(self.murderer_trail):
                alpha = int(180 * (i / count)) if count > 0 else 0
                surf = pygame.Surface((10, 10), pygame.SRCALPHA)
                pygame.draw.circle(surf, (200, 200, 200, alpha), (5, 5), 4)
                screen.blit(surf, (int(tx - 5 + ox), int(ty - 5 + oy)))

        # ---- Tracker: yellow arrow pointing toward the Murderer ----
        if "tracker" in self.active_effects:
            murderer = None
            for p in self.players:
                if p.role == "murderer" and p.is_alive:
                    murderer = p
                    break
            if murderer:
                buyer_id = self.active_effects["tracker"]["buyer_id"]
                buyer = None
                for p in self.players:
                    if p.id == buyer_id:
                        buyer = p
                        break
                if buyer:
                    dx = murderer.x - buyer.x
                    dy = murderer.y - buyer.y
                    dist = math.sqrt(dx * dx + dy * dy)
                    if dist > 0:
                        nx, ny = dx / dist, dy / dist
                        size = 14
                        tip = (buyer.x + nx * size + ox, buyer.y + ny * size + oy)
                        left = (
                            buyer.x - nx * size * 0.5 + ny * size * 0.4 + ox,
                            buyer.y - ny * size * 0.5 - nx * size * 0.4 + oy,
                        )
                        right = (
                            buyer.x - nx * size * 0.5 - ny * size * 0.4 + ox,
                            buyer.y - ny * size * 0.5 + nx * size * 0.4 + oy,
                        )
                        pygame.draw.polygon(
                            screen, (255, 255, 0), [tip, left, right]
                        )

        # ---- Aura scan: role-colored rings around every player ----
        if "aura_scan" in self.active_effects:
            for p in self.players:
                if p.is_alive:
                    color = ROLE_COLORS.get(p.role, (255, 255, 255))
                    cx, cy = int(p.x) + ox, int(p.y) + oy
                    pygame.draw.circle(screen, color, (cx, cy), 18, 3)

    def _draw_quit_dialog(self, screen):
        """Overlay asking the player to confirm quitting mid-round."""
        dim = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 200))
        screen.blit(dim, (0, 0))

        font = pygame.font.Font(None, 36)
        msg = font.render("Are you sure?", True, (255, 255, 255))
        msg2 = pygame.font.Font(None, 24).render(
            "Your round progress will be lost.", True, (200, 200, 200)
        )
        screen.blit(msg, (400 - msg.get_width() // 2, 240))
        screen.blit(msg2, (400 - msg2.get_width() // 2, 280))

        mx, my = pygame.mouse.get_pos()
        for rect, label, color, hover_color in [
            (self._quit_yes_btn, "Yes", (130, 60, 60), (170, 80, 80)),
            (self._quit_no_btn, "No", (60, 60, 60), (80, 80, 80)),
        ]:
            hover = rect.collidepoint(mx, my)
            c = hover_color if hover else color
            pygame.draw.rect(screen, c, rect, border_radius=8)
            surf = pygame.font.Font(None, 30).render(label, True, (255, 255, 255))
            screen.blit(surf, surf.get_rect(center=rect.center))

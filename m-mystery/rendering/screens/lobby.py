import pygame

from rendering.avatar import draw_avatar_preview

# Roblox-inspired palette
BG_TOP = (45, 120, 200)
BG_BOTTOM = (25, 60, 120)
PANEL_COLOR = (35, 35, 45)
PANEL_BORDER = (70, 70, 90)
CARD_COLOR = (48, 48, 58)
BTN_COLOR = (0, 180, 80)
BTN_HOVER = (0, 210, 95)
BTN_DISABLED = (55, 55, 65)
BTN_TEXT = (255, 255, 255)
TITLE_COLOR = (255, 255, 255)

ROLE_COLORS = {
    "murderer": (229, 49, 112),
    "sheriff": (244, 197, 66),
    "innocent": (44, 181, 232),
}


class LobbyScreen:
    """Roblox-style server browser / lobby before a round."""

    def __init__(self, players, human, round_number_ref, available_maps,
                 selected_map_ref, on_start_round, on_quit_to_menu):
        self.players = players
        self.human = human
        self.round_number_ref = round_number_ref
        self.available_maps = available_maps
        self.selected_map_ref = selected_map_ref
        self.on_start_round = on_start_round
        self.on_quit_to_menu = on_quit_to_menu

        self.font_title = pygame.font.Font(None, 48)
        self.font_sub = pygame.font.Font(None, 26)
        self.font_player = pygame.font.Font(None, 22)
        self.font_btn = pygame.font.Font(None, 32)

        self.start_btn = pygame.Rect(520, 500, 200, 48)
        self.back_btn = pygame.Rect(80, 500, 120, 40)
        self.map_arrow_left = pygame.Rect(520, 130, 28, 28)
        self.map_arrow_right = pygame.Rect(720, 130, 28, 28)

    def _draw_gradient_bg(self, screen):
        h = screen.get_height()
        for y in range(h):
            t = y / h
            r = int(BG_TOP[0] * (1 - t) + BG_BOTTOM[0] * t)
            g = int(BG_TOP[1] * (1 - t) + BG_BOTTOM[1] * t)
            b = int(BG_TOP[2] * (1 - t) + BG_BOTTOM[2] * t)
            pygame.draw.line(screen, (r, g, b), (0, y), (screen.get_width(), y))

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                if self.map_arrow_left.collidepoint(mx, my):
                    n = len(self.available_maps)
                    self.selected_map_ref[0] = (self.selected_map_ref[0] - 1) % n
                elif self.map_arrow_right.collidepoint(mx, my):
                    n = len(self.available_maps)
                    self.selected_map_ref[0] = (self.selected_map_ref[0] + 1) % n
                elif self.start_btn.collidepoint(mx, my) and len(self.players) >= 2:
                    self.on_start_round()
                elif self.back_btn.collidepoint(mx, my) and self.on_quit_to_menu:
                    self.on_quit_to_menu()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                if self.on_quit_to_menu:
                    self.on_quit_to_menu()

    def update(self, dt):
        pass

    def draw(self, screen):
        self._draw_gradient_bg(screen)

        # Top bar (Roblox home strip style)
        bar = pygame.Rect(0, 0, 800, 52)
        pygame.draw.rect(screen, (30, 30, 38), bar)
        title = self.font_title.render("M Mystery", True, TITLE_COLOR)
        screen.blit(title, (16, 10))
        sub = self.font_sub.render("Servers", True, (180, 200, 220))
        screen.blit(sub, (200, 18))

        # ---- Server card (left) ----
        card = pygame.Rect(60, 70, 420, 400)
        pygame.draw.rect(screen, PANEL_COLOR, card, border_radius=10)
        pygame.draw.rect(screen, PANEL_BORDER, card, width=2, border_radius=10)

        map_entry = self.available_maps[self.selected_map_ref[0]]
        map_name = map_entry["name"]
        mx, my = pygame.mouse.get_pos()

        # Map thumbnail placeholder
        thumb = pygame.Rect(75, 85, 390, 120)
        pygame.draw.rect(screen, (55, 75, 55), thumb, border_radius=8)
        pygame.draw.rect(screen, (80, 100, 70), thumb, width=2, border_radius=8)
        map_label = self.font_sub.render(map_name, True, (240, 240, 240))
        screen.blit(map_label, (thumb.x + 12, thumb.y + 12))
        players_label = self.font_player.render(
            f"{len(self.players)} / 6 Players", True, (200, 200, 210)
        )
        screen.blit(players_label, (thumb.x + 12, thumb.y + 42))
        mode_label = self.font_player.render("Classic • Round " + str(self.round_number_ref[0]), True, (160, 180, 200))
        screen.blit(mode_label, (thumb.x + 12, thumb.y + 64))

        # Map arrows
        for rect, glyph in [(self.map_arrow_left, "<"), (self.map_arrow_right, ">")]:
            hover = rect.collidepoint(mx, my)
            col = (100, 140, 200) if hover else (70, 90, 130)
            pygame.draw.rect(screen, col, rect, border_radius=6)
            g = self.font_sub.render(glyph, True, (255, 255, 255))
            screen.blit(g, g.get_rect(center=rect.center))

        # Player slots in server card
        y = 220
        screen.blit(self.font_sub.render("Players in Server", True, (220, 220, 230)), (75, y))
        y += 32
        for i, p in enumerate(self.players):
            slot = pygame.Rect(75, y, 380, 52)
            pygame.draw.rect(screen, CARD_COLOR, slot, border_radius=8)

            av_rect = pygame.Rect(slot.x + 8, slot.y + 6, 40, 40)
            draw_avatar_preview(screen, av_rect, p)

            name = p.name + ("  (You)" if p is self.human else "")
            name_surf = self.font_player.render(name, True, (230, 230, 240))
            screen.blit(name_surf, (slot.x + 58, slot.y + 10))

            if p.is_bot:
                tag = self.font_player.render("Playing", True, (100, 200, 120))
            else:
                tag = self.font_player.render("You", True, (100, 180, 255))
            screen.blit(tag, (slot.x + 58, slot.y + 28))

            if p.role:
                rc = ROLE_COLORS.get(p.role, (120, 120, 120))
                pygame.draw.circle(screen, rc, (slot.right - 20, slot.centery), 6)

            y += 58

        # Empty slots
        for _ in range(max(0, 6 - len(self.players))):
            slot = pygame.Rect(75, y, 380, 40)
            pygame.draw.rect(screen, (40, 40, 48), slot, border_radius=6)
            empty = self.font_player.render("Waiting for player...", True, (90, 90, 100))
            screen.blit(empty, (slot.x + 58, slot.y + 10))
            y += 46

        # ---- Friends / quick join panel (right) ----
        right = pygame.Rect(500, 70, 280, 400)
        pygame.draw.rect(screen, PANEL_COLOR, right, border_radius=10)
        pygame.draw.rect(screen, PANEL_BORDER, right, width=2, border_radius=10)
        screen.blit(self.font_sub.render("Recommended", True, (220, 220, 230)), (515, 85))

        rec_maps = self.available_maps[:2]
        ry = 120
        for m in rec_maps:
            mini = pygame.Rect(515, ry, 250, 70)
            pygame.draw.rect(screen, CARD_COLOR, mini, border_radius=8)
            screen.blit(self.font_player.render(m["name"], True, (200, 200, 210)), (525, ry + 12))
            screen.blit(self.font_player.render("4-6 players", True, (130, 130, 150)), (525, ry + 36))
            ry += 82

        # Start button
        can_start = len(self.players) >= 2
        hover = self.start_btn.collidepoint(mx, my) and can_start
        color = BTN_HOVER if hover else (BTN_COLOR if can_start else BTN_DISABLED)
        pygame.draw.rect(screen, color, self.start_btn, border_radius=8)
        label = self.font_btn.render("Play", True, BTN_TEXT)
        screen.blit(label, label.get_rect(center=self.start_btn.center))

        if not can_start:
            hint = self.font_player.render("Need 2+ players", True, (140, 140, 150))
            screen.blit(hint, (self.start_btn.centerx - hint.get_width() // 2, 555))

        # Back
        bh = self.back_btn.collidepoint(mx, my)
        pygame.draw.rect(screen, (70, 70, 85) if bh else (55, 55, 68), self.back_btn, border_radius=6)
        bl = self.font_player.render("← Menu", True, (220, 220, 230))
        screen.blit(bl, bl.get_rect(center=self.back_btn.center))

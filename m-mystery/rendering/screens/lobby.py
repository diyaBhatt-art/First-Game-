import pygame

BG_COLOR = (26, 26, 46)
BTN_COLOR = (60, 130, 60)
BTN_HOVER = (80, 170, 80)
BTN_DISABLED = (50, 50, 50)
BTN_TEXT = (255, 255, 255)
TITLE_COLOR = (255, 255, 255)

ROLE_COLORS = {
    "murderer": (229, 49, 112),
    "sheriff": (244, 197, 66),
    "innocent": (44, 181, 232),
}


class LobbyScreen:
    """Lobby showing all players before a round starts."""

    def __init__(self, players, human, round_number_ref, available_maps,
                 selected_map_ref, on_start_round, on_quit_to_menu):
        """
        Args:
            players: list of Player / Bot objects
            human: the human Player object
            round_number_ref: list wrapping an int [round_number] (mutable reference)
            available_maps: list of {"id": str, "name": str, "data": dict}
            selected_map_ref: list wrapping an int [index] into available_maps
            on_start_round: callable — assign roles and go to role_reveal
            on_quit_to_menu: callable
        """
        self.players = players
        self.human = human
        self.round_number_ref = round_number_ref
        self.available_maps = available_maps
        self.selected_map_ref = selected_map_ref
        self.on_start_round = on_start_round
        self.on_quit_to_menu = on_quit_to_menu

        self.font_title = pygame.font.Font(None, 56)
        self.font_player = pygame.font.Font(None, 30)
        self.font_btn = pygame.font.Font(None, 36)

        btn_w, btn_h = 240, 55
        self.start_btn = pygame.Rect((800 - btn_w) // 2, 480, btn_w, btn_h)

        self.map_arrow_left = pygame.Rect(280, 118, 30, 30)
        self.map_arrow_right = pygame.Rect(490, 118, 30, 30)

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                if self.map_arrow_left.collidepoint(mx, my):
                    count = len(self.available_maps)
                    self.selected_map_ref[0] = (self.selected_map_ref[0] - 1) % count
                elif self.map_arrow_right.collidepoint(mx, my):
                    count = len(self.available_maps)
                    self.selected_map_ref[0] = (self.selected_map_ref[0] + 1) % count
                # Start Round — only if 2+ players
                elif self.start_btn.collidepoint(mx, my) and len(self.players) >= 2:
                    self.on_start_round()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                if self.on_quit_to_menu:
                    self.on_quit_to_menu()

    def update(self, dt):
        pass

    def draw(self, screen):
        screen.fill(BG_COLOR)

        # Title + round number
        title = self.font_title.render("LOBBY", True, TITLE_COLOR)
        screen.blit(title, (400 - title.get_width() // 2, 40))

        round_str = f"Round {self.round_number_ref[0]}"
        round_surf = self.font_player.render(round_str, True, (180, 180, 200))
        screen.blit(round_surf, (400 - round_surf.get_width() // 2, 95))

        # Map selector
        mx, my = pygame.mouse.get_pos()

        left_hover = self.map_arrow_left.collidepoint(mx, my)
        left_col = (180, 180, 220) if left_hover else (120, 120, 150)
        pygame.draw.rect(screen, left_col, self.map_arrow_left, border_radius=6)
        left_arrow = self.font_player.render("<", True, (255, 255, 255))
        screen.blit(left_arrow, left_arrow.get_rect(center=self.map_arrow_left.center))

        map_name = self.available_maps[self.selected_map_ref[0]]["name"]
        map_surf = self.font_player.render(map_name, True, (200, 200, 220))
        screen.blit(map_surf, (400 - map_surf.get_width() // 2, 121))

        right_hover = self.map_arrow_right.collidepoint(mx, my)
        right_col = (180, 180, 220) if right_hover else (120, 120, 150)
        pygame.draw.rect(screen, right_col, self.map_arrow_right, border_radius=6)
        right_arrow = self.font_player.render(">", True, (255, 255, 255))
        screen.blit(right_arrow, right_arrow.get_rect(center=self.map_arrow_right.center))

        # Player list
        y = 160
        for p in self.players:
            # Colored dot
            dot_color = ROLE_COLORS.get(p.role, (100, 100, 100))
            if not p.role:
                dot_color = (100, 100, 100)
            pygame.draw.circle(screen, dot_color, (220, y + 12), 8)

            # Name
            name = p.name
            if p is self.human:
                name += "  (You)"
            name_surf = self.font_player.render(name, True, (220, 220, 220))
            screen.blit(name_surf, (240, y))

            # Bot tag
            if p.is_bot:
                tag_surf = self.font_player.render("[BOT]", True, (130, 130, 140))
                screen.blit(tag_surf, (500, y))

            y += 40

        # Start Round button
        can_start = len(self.players) >= 2
        mx, my = pygame.mouse.get_pos()
        hover = self.start_btn.collidepoint(mx, my) and can_start

        if can_start:
            color = BTN_HOVER if hover else BTN_COLOR
        else:
            color = BTN_DISABLED

        pygame.draw.rect(screen, color, self.start_btn, border_radius=8)
        label = self.font_btn.render("Start Round", True, BTN_TEXT)
        screen.blit(label, label.get_rect(center=self.start_btn.center))

        # Hint if disabled
        if not can_start:
            hint = self.font_btn.render("Need 2+ players", True, (100, 100, 100))
            screen.blit(hint, (400 - hint.get_width() // 2, 545))

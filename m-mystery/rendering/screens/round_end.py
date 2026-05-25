import pygame

# Colours for the two outcomes
INNOCENTS_COLOR = (44, 181, 232)      # blue / cyan
MURDERER_COLOR = (229, 49, 112)       # red / pink
ROLE_COLORS = {
    "murderer": (229, 49, 112),
    "sheriff":  (244, 197, 66),
    "innocent": (44, 181, 232),
}


class RoundEndScreen:
    """
    Shows the round result: a win banner, a player-status list,
    round-earnings summary, and buttons to start the next round
    or quit to menu.
    """

    def __init__(self, winner, players, wallet_manager,
                 on_next_round, on_quit_to_menu, human=None):
        """
        Args:
            winner: "murderer" or "innocents"
            players: list of Player / Bot objects (with .role, .is_alive, etc.)
            wallet_manager: WalletManager instance (already updated with round earnings)
            on_next_round: callable — resets the game and shows role_reveal
            on_quit_to_menu: callable — goes back to the main menu
        """
        self.winner = winner
        self.players = players
        self.wallet_manager = wallet_manager

        self.on_next_round = on_next_round
        self.on_quit_to_menu = on_quit_to_menu
        self.human = human or next((p for p in players if not p.is_bot), None)

        # --- Decide banner text & colour ---
        if winner == "murderer":
            self.banner_text = "MURDERER WINS!"
            self.banner_color = MURDERER_COLOR
        else:
            self.banner_text = "INNOCENTS WIN!"
            self.banner_color = INNOCENTS_COLOR

        # --- Buttons ---
        self.next_btn = pygame.Rect(200, 490, 180, 50)
        self.quit_btn = pygame.Rect(420, 490, 180, 50)

    # ------------------------------------------------------------------
    # Interface required by ScreenManager
    # ------------------------------------------------------------------

    def handle_events(self, events):
        """Check for button clicks or ESC to quit."""
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN:
                if self.next_btn.collidepoint(event.pos):
                    self.on_next_round()
                elif self.quit_btn.collidepoint(event.pos):
                    self.on_quit_to_menu()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.on_quit_to_menu()

    def update(self, dt):
        """Nothing to animate."""
        pass

    def draw(self, screen):
        """Render the banner, player list, wallet summary, and buttons."""
        screen.fill((20, 20, 20))  # dark background

        # ---- Banner ----
        font_big = pygame.font.Font(None, 60)
        banner = font_big.render(self.banner_text, True, self.banner_color)
        banner_rect = banner.get_rect(center=(400, 50))
        screen.blit(banner, banner_rect)

        # ---- Human earnings summary ----
        if self.human:
            earned = self.human.m_bucks_this_round
            wallet_total = self.wallet_manager.get_balance(self.human.id)
            summary_font = pygame.font.Font(None, 28)
            summary = summary_font.render(
                f"You earned: +{earned} M Bucks | Wallet: {wallet_total} M Bucks",
                True, (255, 215, 0),
            )
            screen.blit(summary, (400 - summary.get_width() // 2, 82))

        # ---- Player status list ----
        font = pygame.font.Font(None, 26)
        y_start = 115
        row_h = 32

        # Header
        header = font.render(
            f"{'Player':<18} {'Role':<10} {'Status':<10} {'Earned':<10} {'Wallet':<10}",
            True, (180, 180, 180))
        screen.blit(header, (50, y_start))

        for i, p in enumerate(self.players):
            y = y_start + 26 + i * row_h

            name_str = p.name
            role_str = p.role.capitalize()
            status_str = "ALIVE" if p.is_alive else "DEAD"
            status_color = (80, 220, 80) if p.is_alive else (220, 80, 80)
            earned = p.m_bucks_this_round
            wallet_total = self.wallet_manager.get_balance(p.id)

            # Role colour dot
            role_color = ROLE_COLORS.get(p.role, (200, 200, 200))
            pygame.draw.circle(screen, role_color, (65, y + 10), 6)

            # Player name
            name_surf = font.render(name_str, True, (220, 220, 220))
            screen.blit(name_surf, (80, y))

            # Role name
            role_surf = font.render(role_str, True, (200, 200, 200))
            screen.blit(role_surf, (210, y))

            # Status
            status_surf = font.render(status_str, True, status_color)
            screen.blit(status_surf, (340, y))

            # Earned this round
            earned_text = f"+{earned}"
            earned_color = (255, 215, 0) if earned > 0 else (120, 120, 120)
            earned_surf = font.render(earned_text, True, earned_color)
            screen.blit(earned_surf, (445, y))

            # Wallet balance
            wallet_text = f"{wallet_total}"
            wallet_surf = font.render(wallet_text, True, (255, 255, 200))
            screen.blit(wallet_surf, (530, y))

        # ---- Buttons with hover ----
        mx, my = pygame.mouse.get_pos()
        self._draw_btn(screen, self.next_btn, (60, 130, 60), (80, 170, 80),
                       "Next Round", font, mx, my)
        self._draw_btn(screen, self.quit_btn, (130, 60, 60), (170, 80, 80),
                       "Quit to Menu", font, mx, my)


    @staticmethod
    def _draw_btn(screen, rect, color, hover_color, text, font, mx, my):
        hover = rect.collidepoint(mx, my)
        c = hover_color if hover else color
        pygame.draw.rect(screen, c, rect, border_radius=8)
        surf = font.render(text, True, (255, 255, 255))
        screen.blit(surf, surf.get_rect(center=rect.center))

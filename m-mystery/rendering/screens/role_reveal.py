import pygame

# Role display data: (display_name, card_color, flavor_text)
ROLE_INFO = {
    "murderer": ("Murderer", (229, 49, 112), "Kill everyone. Trust no one."),
    "sheriff":  ("Sheriff",  (244, 197, 66), "Find the Murderer. One shot."),
    "innocent": ("Innocent", (44, 181, 232), "Survive. Don't get caught."),
}


class RoleRevealScreen:
    """
    Shows the human player their assigned role before the round starts.

    Displays a colored role card with the role name, flavor text,
    and an "I'm Ready" button. When clicked, calls on_ready to
    transition to the game screen.
    """

    def __init__(self, human_player, on_ready, on_quit_to_menu=None):
        """
        Args:
            human_player: the Player object for the human (must have .role set)
            on_ready: callable — invoked when the player clicks "I'm Ready"
            on_quit_to_menu: callable — ESC goes back to main menu
        """
        self.player = human_player
        self.on_ready = on_ready
        self.on_quit_to_menu = on_quit_to_menu

        # Look up role display info
        role_id = self.player.role
        info = ROLE_INFO.get(role_id, ("Unknown", (100, 100, 100), "???"))
        self.display_name, self.card_color, self.flavor = info

        # Button rectangle (centred horizontally)
        btn_w, btn_h = 200, 50
        self.ready_btn = pygame.Rect(
            (800 - btn_w) // 2, 450, btn_w, btn_h
        )

    def handle_events(self, events):
        """Check for clicks on the "I'm Ready" button or ESC to quit."""
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN:
                if self.ready_btn.collidepoint(event.pos):
                    self.on_ready()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                if self.on_quit_to_menu:
                    self.on_quit_to_menu()

    def update(self, dt):
        """Nothing to animate — screen is static."""
        pass

    def draw(self, screen):
        """Render the role card, flavor text, and ready button."""
        screen.fill((20, 20, 20))  # dark background

        # ---- "YOUR ROLE IS:" heading ----
        font_lg = pygame.font.Font(None, 48)
        heading = font_lg.render("YOUR ROLE IS:", True, (200, 200, 200))
        heading_rect = heading.get_rect(center=(400, 120))
        screen.blit(heading, heading_rect)

        # ---- Coloured role card ----
        card_w, card_h = 360, 140
        card_rect = pygame.Rect((800 - card_w) // 2, 170, card_w, card_h)
        pygame.draw.rect(screen, self.card_color, card_rect, border_radius=12)
        # Subtle white border
        pygame.draw.rect(screen, (255, 255, 255), card_rect, width=3, border_radius=12)

        # Role name (big, bold)
        font_role = pygame.font.Font(None, 72)
        role_surf = font_role.render(self.display_name, True, (255, 255, 255))
        role_rect = role_surf.get_rect(center=(400, 240))
        screen.blit(role_surf, role_rect)

        # ---- Flavor text ----
        font_sm = pygame.font.Font(None, 28)
        flavor_surf = font_sm.render(self.flavor, True, (180, 180, 180))
        flavor_rect = flavor_surf.get_rect(center=(400, 340))
        screen.blit(flavor_surf, flavor_rect)

        # ---- "I'm Ready" button (with hover) ----
        mx, my = pygame.mouse.get_pos()
        hover = self.ready_btn.collidepoint(mx, my)
        btn_color = (80, 170, 80) if hover else (60, 130, 60)
        pygame.draw.rect(screen, btn_color, self.ready_btn, border_radius=8)
        btn_font = pygame.font.Font(None, 36)
        btn_surf = btn_font.render("I'm Ready", True, (255, 255, 255))
        btn_rect = btn_surf.get_rect(center=self.ready_btn.center)
        screen.blit(btn_surf, btn_rect)

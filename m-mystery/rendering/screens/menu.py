import random
import sys
import pygame

TAGLINES = [
    "No one is safe.",
    "Trust no one.",
    "The knife never lies.",
    "Everyone is a suspect.",
]

BG_COLOR = (26, 26, 46)
BTN_COLOR = (60, 60, 100)
BTN_HOVER = (80, 80, 140)
BTN_TEXT = (255, 255, 255)
TITLE_COLOR = (255, 255, 255)


class MenuScreen:
    """Main menu with title, buttons, and a random tagline."""

    def __init__(self, on_play, on_settings=None, on_quit=None):
        self.on_play = on_play
        self.on_settings = on_settings
        self.on_quit = on_quit

        self.tagline = random.choice(TAGLINES)
        self.font_title = pygame.font.Font(None, 72)
        self.font_btn = pygame.font.Font(None, 40)
        self.font_tag = pygame.font.Font(None, 24)

        btn_w, btn_h = 260, 55
        cx = 400
        self.buttons = [
            {"rect": pygame.Rect(cx - btn_w // 2, 220, btn_w, btn_h), "label": "Play Game", "action": "play"},
            {"rect": pygame.Rect(cx - btn_w // 2, 290, btn_w, btn_h), "label": "Settings", "action": "settings"},
            {"rect": pygame.Rect(cx - btn_w // 2, 360, btn_w, btn_h), "label": "Quit", "action": "quit"},
        ]

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                for btn in self.buttons:
                    if btn["rect"].collidepoint(mx, my):
                        if btn["action"] == "play" and self.on_play:
                            self.on_play()
                        elif btn["action"] == "settings" and self.on_settings:
                            self.on_settings()
                        elif btn["action"] == "quit" and self.on_quit:
                            self.on_quit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE and self.on_quit:
                    self.on_quit()

    def update(self, dt):
        pass

    def draw(self, screen):
        screen.fill(BG_COLOR)

        # Title
        title = self.font_title.render("M MYSTERY", True, TITLE_COLOR)
        title_rect = title.get_rect(center=(400, 130))
        screen.blit(title, title_rect)

        # Tagline
        tag = self.font_tag.render(self.tagline, True, (120, 120, 160))
        tag_rect = tag.get_rect(center=(400, 170))
        screen.blit(tag, tag_rect)

        # Buttons with hover
        mx, my = pygame.mouse.get_pos()
        for btn in self.buttons:
            hover = btn["rect"].collidepoint(mx, my)
            color = BTN_HOVER if hover else BTN_COLOR
            pygame.draw.rect(screen, color, btn["rect"], border_radius=8)
            surf = self.font_btn.render(btn["label"], True, BTN_TEXT)
            screen.blit(surf, surf.get_rect(center=btn["rect"].center))

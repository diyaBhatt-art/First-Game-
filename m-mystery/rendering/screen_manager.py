import sys
import pygame


class ScreenManager:
    """
    Holds named screens and delegates the game loop to whichever screen
    is currently active.  Supports a fade-to-black transition between
    screens for a polished feel.
    """

    def __init__(self, display_surface):
        self.display = display_surface
        self.screens = {}
        self.active_screen = None

        # Fade transition state
        self._fade_alpha = 0       # 0–255
        self._fade_dir = 0         # 0=off, 1=fade out, -1=fade in
        self._target_name = None

    def add_screen(self, name, screen_obj):
        """Register or replace a screen under a string name."""
        self.screens[name] = screen_obj

    def set_screen(self, name):
        """Immediately switch to a screen (no transition)."""
        self.active_screen = self.screens[name]

    def transition_to(self, name):
        """Switch to a screen with a fade-to-black + fade-in (≈13 frames each way)."""
        if self.active_screen is None:
            self.active_screen = self.screens[name]
            return
        self._target_name = name
        self._fade_alpha = 0
        self._fade_dir = 1  # start fading out

    def run(self):
        clock = pygame.time.Clock()

        while True:
            clock.tick(60)

            events = pygame.event.get()
            for e in events:
                if e.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()

            # --- Fade state machine ---
            if self._fade_dir == 1:
                self._fade_alpha = min(self._fade_alpha + 20, 255)
                if self._fade_alpha >= 255:
                    self.active_screen = self.screens[self._target_name]
                    self._target_name = None
                    self._fade_dir = -1
            elif self._fade_dir == -1:
                self._fade_alpha = max(self._fade_alpha - 20, 0)
                if self._fade_alpha <= 0:
                    self._fade_dir = 0

            # --- Normal update (only when NOT transitioning) ---
            if self.active_screen:
                if self._fade_dir == 0:
                    self.active_screen.handle_events(events)
                    self.active_screen.update(1 / 60)
                self.active_screen.draw(self.display)

            # --- Fade overlay on top of everything ---
            if self._fade_alpha > 0:
                surf = pygame.Surface(self.display.get_size())
                surf.set_alpha(self._fade_alpha)
                surf.fill((0, 0, 0))
                self.display.blit(surf, (0, 0))

            pygame.display.flip()

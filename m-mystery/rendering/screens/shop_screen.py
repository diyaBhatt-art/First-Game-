import pygame


class ShopScreen:
    """
    In-game shop overlay drawn on top of the game screen.

    Shows items grouped by tier (Cheap / Mid / Premium), the player's
    wallet balance, and a Close Shop button.  Items the player cannot
    afford or has exhausted are grayed out.
    """

    PANEL_RECT = pygame.Rect(100, 40, 600, 520)
    CLOSE_RECT = pygame.Rect(300, 520, 200, 40)
    BG_COLOR = (20, 20, 40)
    BORDER_COLOR = (100, 100, 140)
    GRAY = (100, 100, 100)
    WHITE = (220, 220, 220)
    GOLD = (255, 215, 0)
    RED = (255, 100, 100)
    GREEN = (100, 255, 100)
    DIM = (40, 40, 60)
    DESC_COLOR = (150, 150, 150)

    TIER_LABELS = {
        "cheap": "Cheap  ($50\u2013$100)",
        "mid": "Mid  ($100\u2013$200)",
        "premium": "Premium  ($1000\u2013$2000)",
    }

    def __init__(self, shop_manager, wallet_manager, human_player, on_purchase, on_close):
        self.shop_manager = shop_manager
        self.wallet_manager = wallet_manager
        self.human = human_player
        self.on_purchase = on_purchase
        self.on_close = on_close

        self.font_title = pygame.font.Font(None, 42)
        self.font_tier = pygame.font.Font(None, 32)
        self.font_item = pygame.font.Font(None, 24)
        self.font_small = pygame.font.Font(None, 20)

        self.item_buttons = []  # [(rect, item_id), ...] — rebuilt each draw()

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                if self.CLOSE_RECT.collidepoint(mx, my):
                    self.on_close()
                    return
                for rect, item_id in self.item_buttons:
                    if rect.collidepoint(mx, my):
                        self.on_purchase(item_id)
                        return
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_e:
                self.on_close()
                return

    def draw(self, screen):
        """Draw the semi-transparent shop overlay onto *screen*."""
        # --- Semi-transparent full-screen darken layer ---
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        screen.blit(overlay, (0, 0))

        # --- Panel background ---
        pygame.draw.rect(screen, self.BG_COLOR, self.PANEL_RECT, border_radius=8)
        pygame.draw.rect(screen, self.BORDER_COLOR, self.PANEL_RECT, 2, border_radius=8)

        # --- Title + Wallet ---
        balance = self.wallet_manager.get_balance(self.human.id)
        title = self.font_title.render("SHOP", True, (255, 255, 255))
        wallet_surf = self.font_tier.render(f"Wallet: ${balance}", True, self.GOLD)
        screen.blit(title, (self.PANEL_RECT.centerx - title.get_width() // 2, 55))
        screen.blit(wallet_surf, (self.PANEL_RECT.centerx - wallet_surf.get_width() // 2 + 130, 60))

        # --- Items by tier ---
        tiers = self.shop_manager.get_items_by_tier()
        y = 100
        self.item_buttons.clear()

        for tier_key in ("cheap", "mid", "premium"):
            # Tier heading
            header = self.font_tier.render(self.TIER_LABELS[tier_key], True, (180, 180, 220))
            screen.blit(header, (self.PANEL_RECT.x + 30, y))
            y += 35

            for item in tiers[tier_key]:
                can_afford = self.shop_manager.can_afford(
                    self.human.id, item["id"], self.wallet_manager
                )
                uses_left = self.shop_manager.uses_left(self.human.id, item["id"])

                # Role restriction
                role_ok = (
                    item["target_role"] == "any"
                    or item["target_role"] == self.human.role
                )

                disabled = not (can_afford and uses_left > 0 and role_ok)
                fg = self.GRAY if disabled else self.WHITE
                price_color = self.RED if not can_afford else self.GREEN

                # Row background
                row = pygame.Rect(self.PANEL_RECT.x + 30, y, 540, 40)
                if not disabled:
                    pygame.draw.rect(screen, self.DIM, row, border_radius=4)
                self.item_buttons.append((row, item["id"]))

                # Columns
                name_surf = self.font_item.render(item["name"], True, fg)
                desc_surf = self.font_small.render(item["description"], True, self.DESC_COLOR)
                price_surf = self.font_small.render(f"${item['price']}", True, price_color)
                uses_surf = self.font_small.render(
                    f"{uses_left}/{item['uses_per_round']}", True, fg
                )

                screen.blit(name_surf, (row.x + 10, row.y + 2))
                screen.blit(desc_surf, (row.x + 150, row.y + 2))
                screen.blit(price_surf, (row.x + 420, row.y + 2))
                screen.blit(uses_surf, (row.x + 480, row.y + 2))

                y += 45

            y += 10

        # --- Close button (with hover) ---
        mx, my = pygame.mouse.get_pos()
        close_hover = self.CLOSE_RECT.collidepoint(mx, my)
        close_bg = (90, 90, 120) if close_hover else (60, 60, 80)
        pygame.draw.rect(screen, close_bg, self.CLOSE_RECT, border_radius=6)
        pygame.draw.rect(screen, (140, 140, 180), self.CLOSE_RECT, 2, border_radius=6)
        label = self.font_tier.render("Close Shop", True, (255, 255, 255))
        screen.blit(
            label,
            (self.CLOSE_RECT.centerx - label.get_width() // 2,
             self.CLOSE_RECT.centery - label.get_height() // 2),
        )

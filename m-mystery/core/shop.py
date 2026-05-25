import json


class ShopManager:
    """
    Loads items from data/items.json and handles purchases.

    Tracks per-player, per-item usage counts for the current round.
    Effect functions are dispatched by name from the item data.
    """

    def __init__(self):
        with open("data/items.json") as f:
            raw = json.load(f)
        self.items = {item["id"]: item for item in raw["items"]}
        self.uses_this_round = {}  # key: (player_id, item_id) -> int

    def get_items_by_tier(self):
        """Return items grouped as {'cheap': [...], 'mid': [...], 'premium': [...]}."""
        tiers = {"cheap": [], "mid": [], "premium": []}
        for item in self.items.values():
            tiers[item["tier"]].append(item)
        return tiers

    def can_afford(self, player_id, item_id, wallet_manager):
        """Return True if the player's wallet balance >= item price."""
        item = self.items[item_id]
        return wallet_manager.get_balance(player_id) >= item["price"]

    def uses_left(self, player_id, item_id):
        """Return how many more times this item can be bought this round."""
        item = self.items[item_id]
        key = (player_id, item_id)
        used = self.uses_this_round.get(key, 0)
        return item["uses_per_round"] - used

    def purchase(self, player_id, item_id, wallet_manager, game_state):
        """
        Attempt to buy an item.

        Returns True on success, False if the player cannot afford or has no uses left.
        On success, deducts the price from the wallet, increments the use counter,
        and dispatches the appropriate effect.
        """
        item = self.items[item_id]

        if not self.can_afford(player_id, item_id, wallet_manager):
            return False
        if self.uses_left(player_id, item_id) <= 0:
            return False

        wallet_manager.add_round_earnings(player_id, -item["price"])
        wallet_manager.save()

        key = (player_id, item_id)
        self.uses_this_round[key] = self.uses_this_round.get(key, 0) + 1

        effect_fn = getattr(self, item["effect"])
        effect_fn(player_id, game_state)

        print(f"[SHOP] {player_id} bought {item['name']} for ${item['price']}")
        return True

    # ------------------------------------------------------------------
    # Effect implementations
    # ------------------------------------------------------------------

    def effect_footprints(self, player_id, game_state):
        """Show the Murderer's trail as fading circles for 5 seconds (300 frames)."""
        game_state.active_effects["footprints"] = {
            "frames_left": 300,
            "buyer_id": player_id,
        }

    def effect_tracker(self, player_id, game_state):
        """Show a yellow arrow toward the Murderer for 3 seconds (180 frames)."""
        game_state.active_effects["tracker"] = {
            "frames_left": 180,
            "buyer_id": player_id,
        }

    def effect_aura_scan(self, player_id, game_state):
        """Flash role-colored rings around every player for 2 seconds (120 frames)."""
        game_state.active_effects["aura_scan"] = {
            "frames_left": 120,
            "buyer_id": player_id,
        }

    def effect_shadow_blade(self, player_id, game_state):
        """
        Instant kill — only works if buyer is the Murderer.
        Kills the nearest living player regardless of distance.
        """
        buyer = None
        for p in game_state.players:
            if p.id == player_id:
                buyer = p
                break

        if not buyer or buyer.role != "murderer":
            print(f"[SHADOW_BLADE] {player_id} is not the Murderer — no effect")
            return

        nearest = None
        nearest_dist = float("inf")
        for p in game_state.players:
            if p is buyer or not p.is_alive:
                continue
            dx = buyer.x - p.x
            dy = buyer.y - p.y
            dist = dx * dx + dy * dy
            if dist < nearest_dist:
                nearest_dist = dist
                nearest = p

        if nearest:
            nearest.is_alive = False
            print(f"[SHADOW_BLADE] {buyer.name} instantly killed {nearest.name}!")

    def effect_noise_trap(self, player_id, game_state):
        """Place a trap at the buyer's position."""
        buyer = next(p for p in game_state.players if p.id == player_id)
        if not hasattr(game_state, "noise_traps"):
            game_state.noise_traps = []
        game_state.noise_traps.append({"x": buyer.x, "y": buyer.y})
        print(f"[NOISE_TRAP] {buyer.name} placed a trap at ({buyer.x:.0f}, {buyer.y:.0f})")

    def effect_alarm(self, player_id, game_state):
        """Shake the Murderer's screen when they approach the buyer for 30 s."""
        buyer = next(p for p in game_state.players if p.id == player_id)
        game_state.active_effects["alarm"] = {
            "frames_left": 1800,
            "buyer_id": player_id,
            "buyer_x": buyer.x,
            "buyer_y": buyer.y,
        }

    def effect_ghost_mode(self, player_id, game_state):
        """Make the buyer semi-transparent and untargetable for 10 s."""
        buyer = next(p for p in game_state.players if p.id == player_id)
        buyer.ghost = True
        game_state.active_effects["ghost_mode"] = {
            "frames_left": 600,
            "buyer_id": player_id,
        }
        print(f"[GHOST_MODE] {buyer.name} turned ghost for 10 seconds")

    def effect_dead_eye(self, player_id, game_state):
        """Next bullet auto-aims at the Murderer if within 300 px."""
        buyer = next(p for p in game_state.players if p.id == player_id)
        game_state.active_effects["dead_eye"] = {
            "frames_left": -1,
            "buyer_id": player_id,
        }
        print(f"[DEAD_EYE] {buyer.name} armed Dead Eye")

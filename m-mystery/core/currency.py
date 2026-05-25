import json
import os

WALLETS_PATH = "saves/wallets.json"


class WalletManager:
    """
    Persists player earnings across sessions.

    Data is stored in saves/wallets.json as:
        { "wallets": { "player_id": balance, ... } }
    """

    def __init__(self):
        """Load existing wallets or create an empty file."""
        self._data = {}  # player_id -> int balance
        self._load()

    def _load(self):
        """Read wallets.json, creating a default file if missing."""
        if not os.path.exists(WALLETS_PATH):
            # Ensure the directory exists
            os.makedirs(os.path.dirname(WALLETS_PATH), exist_ok=True)
            self._save_raw()
            return

        with open(WALLETS_PATH) as f:
            raw = json.load(f)
        wallets = raw.get("wallets", {})
        # Support legacy scaffold format {"wallets": []} as empty wallet
        self._data = wallets if isinstance(wallets, dict) else {}

    def _save_raw(self):
        """Write the current data dict to disk."""
        os.makedirs(os.path.dirname(WALLETS_PATH), exist_ok=True)
        with open(WALLETS_PATH, "w") as f:
            json.dump({"wallets": self._data}, f, indent=2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_round_earnings(self, player_id, amount):
        """
        Add *amount* to the player's wallet balance.

        The wallet has no cap — it grows indefinitely across rounds.
        """
        current = self._data.get(player_id, 0)
        self._data[player_id] = current + amount

    def get_balance(self, player_id):
        """Return the total wallet balance for a player."""
        return self._data.get(player_id, 0)

    def save(self):
        """Persist the current wallet state to saves/wallets.json."""
        self._save_raw()

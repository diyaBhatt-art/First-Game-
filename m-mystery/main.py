import json
import os
import pygame
import sys

from core.player import Player
from core.bot import Bot
from core.roles import assign_roles
from core.currency import WalletManager
from rendering.screen_manager import ScreenManager
from rendering.screens.menu import MenuScreen
from rendering.screens.lobby import LobbyScreen
from rendering.screens.game_screen import GameScreen
from rendering.screens.role_reveal import RoleRevealScreen
from rendering.screens.round_end import RoundEndScreen


def main():
    """Entry point — starts at the main menu, flows through the full game."""
    pygame.init()
    display = pygame.display.set_mode((800, 600))
    pygame.display.set_caption("M Mystery")

    # ---- Discover all maps in data/maps/ ----
    map_dir = "data/maps"
    map_files = sorted(f for f in os.listdir(map_dir) if f.endswith(".json"))
    available_maps = []
    for mf in map_files:
        with open(os.path.join(map_dir, mf)) as f:
            data = json.load(f)
        available_maps.append({
            "id": data["id"],
            "name": data["name"],
            "data": data,
        })

    selected_map_ref = [0]  # index into available_maps (mutable for sharing)

    # ---- Persistent state ----
    human = Player("p1", "Player 1", (44, 181, 232))
    # Bots exist in the lobby list from the start (positions set when a round begins)
    default_map = available_maps[0]["data"]
    spawns = default_map["spawn_points"]
    bots = [
        Bot("bot_1", "Bot 1", (148, 161, 178), spawns[1]["x"], spawns[1]["y"]),
        Bot("bot_2", "Bot 2", (148, 161, 178), spawns[2]["x"], spawns[2]["y"]),
        Bot("bot_3", "Bot 3", (148, 161, 178), spawns[3]["x"], spawns[3]["y"]),
    ]
    all_players = [human] + bots
    wallet_manager = WalletManager()

    round_number = [1]  # mutable list so closures can write to it
    manager = ScreenManager(display)

    # ------------------------------------------------------------------
    # Helper: reset all players to given spawn points
    # ------------------------------------------------------------------

    def reset_players(spawns):
        for i, p in enumerate(all_players):
            p.is_alive = True
            p.has_knife = False
            p.has_gun = False
            p.role = ""
            p.attack_cooldown = 0
            p.m_bucks_this_round = 0
            p.x = spawns[i]["x"]
            p.y = spawns[i]["y"]
            if p.is_bot:
                p.ticks_left = 0
                p.dx = 0
                p.dy = 0

    # ------------------------------------------------------------------
    # Helper: go to main menu
    # ------------------------------------------------------------------

    def go_to_menu():
        round_number[0] = 1
        manager.transition_to("menu")

    # ------------------------------------------------------------------
    # Helper: start a round (called from lobby "Start Round" and
    #          round-end "Next Round")
    # ------------------------------------------------------------------

    def start_round():
        map_entry = available_maps[selected_map_ref[0]]
        map_data = map_entry["data"]
        spawns = map_data["spawn_points"]

        # Move everyone to the selected map's spawn points
        reset_players(spawns)
        assign_roles(all_players)

        # --- Callback: round ends → show round-end screen ---
        def on_round_end(winner):
            # Save round earnings into persistent wallet
            for p in all_players:
                wallet_manager.add_round_earnings(p.id, p.m_bucks_this_round)
            wallet_manager.save()

            end_screen = RoundEndScreen(
                winner,
                all_players,
                wallet_manager,
                on_next_round=next_round,
                on_quit_to_menu=go_to_menu,
                human=human,
            )
            manager.add_screen("round_end", end_screen)
            manager.transition_to("round_end")

        # --- Game screen ---
        game_screen = GameScreen(
            all_players,
            wallet_manager,
            map_data,
            on_round_end=on_round_end,
            on_quit_to_menu=go_to_menu,
        )
        manager.add_screen("game", game_screen)

        # --- Role reveal ---
        role_screen = RoleRevealScreen(
            human,
            on_ready=lambda: manager.transition_to("game"),
            on_quit_to_menu=go_to_menu,
        )
        manager.add_screen("role_reveal", role_screen)

        manager.transition_to("role_reveal")

    def next_round():
        round_number[0] += 1
        start_round()

    # ------------------------------------------------------------------
    # Create screens (menu and lobby are created once)
    # ------------------------------------------------------------------

    menu_screen = MenuScreen(
        on_play=lambda: manager.transition_to("lobby"),
        on_settings=lambda: print("[MENU] Settings (placeholder)"),
        on_quit=lambda: sys.exit(),
    )

    lobby_screen = LobbyScreen(
        all_players,
        human,
        round_number,
        available_maps,
        selected_map_ref,
        on_start_round=start_round,
        on_quit_to_menu=go_to_menu,
    )

    manager.add_screen("menu", menu_screen)
    manager.add_screen("lobby", lobby_screen)

    # ---- Start at the main menu ----
    manager.set_screen("menu")
    manager.run()


if __name__ == "__main__":
    main()

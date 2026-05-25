import json
import random


def assign_roles(players):
    """
    Load role data from data/roles.json and randomly assign one role per player.

    - Always assigns exactly 1 Murderer
    - Assigns 1 Sheriff only if there are 4 or more players
    - Everyone else becomes Innocent

    The function sets the following fields on each Player object:
        .role (string id from JSON, e.g. "murderer")
        .has_knife
        .has_gun

    Args:
        players: list of Player / Bot objects

    Returns:
        The same list with roles populated.
    """
    # Load role definitions
    with open("data/roles.json") as f:
        roles_by_id = {r["id"]: r for r in json.load(f)["roles"]}

    # Shuffle so assignment is random
    shuffled = list(players)
    random.shuffle(shuffled)

    # 1 Murderer (always)
    shuffled[0].role = "murderer"

    # 1 Sheriff if 4+ players
    if len(players) >= 4:
        shuffled[1].role = "sheriff"
    else:
        shuffled[1].role = "innocent"

    # Rest are Innocent
    for p in shuffled[2:]:
        p.role = "innocent"

    # Apply weapon flags from the role definition
    for p in players:
        info = roles_by_id.get(p.role, {})
        p.has_knife = info.get("has_knife", False)
        p.has_gun = info.get("has_gun", False)

    # Debug output
    print("=" * 40)
    print("ROLE ASSIGNMENT")
    print("=" * 40)
    for p in players:
        tag = "BOT" if p.is_bot else "HUMAN"
        print(f"  {p.name} [{tag}] -> {p.role.upper()}")
    print("=" * 40)

    return players

"""
Integration tests for the multiplayer murder-mystery server.

Pure-websockets test (no ursina): starts the server as a subprocess, connects
three fake clients and exercises the full round flow:

  1. handshake / connected
  2. game_started with roles + spawns
  3. movement broadcast received by other players
  4. knife kill on the SHERIFF works (murderer round win)
  5. back_to_lobby includes the player list
  6. gun kill on the murderer ends the game with an innocents win

Run with:
  "/path/to/venv/bin/python" tests/test_mp_server.py
"""
import asyncio
import json
import os
import subprocess
import sys
import time

import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, '..', 'main_multiplayer.py')
PORT = 8799
URI = 'ws://localhost:{}'.format(PORT)


class FakeClient:
    """Minimal websocket game client for driving the server in tests."""

    def __init__(self, name):
        self.name = name
        self.ws = None
        self.player_id = None

    async def connect(self, uri):
        self.ws = await websockets.connect(uri)
        await self.send({'type': 'handshake', 'username': self.name})
        msg = await self.expect('connected')
        self.player_id = msg['player_id']
        return msg

    async def send(self, payload):
        await self.ws.send(json.dumps(payload))

    async def expect(self, msg_type, predicate=None, timeout=10.0):
        """Read messages (skipping unrelated ones) until a match or timeout."""
        deadline = time.time() + timeout
        seen = []
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            seen.append(msg.get('type'))
            if msg.get('type') == msg_type and (predicate is None
                                                or predicate(msg)):
                return msg
        raise AssertionError(
            "{}: timed out waiting for '{}' (saw: {})".format(
                self.name, msg_type, seen))

    async def close(self):
        if self.ws:
            await self.ws.close()


async def wait_for_server(uri, timeout=15.0):
    """Poll until the server accepts connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ws = await websockets.connect(uri)
            await ws.close()
            return
        except OSError:
            await asyncio.sleep(0.25)
    raise AssertionError("Server did not start within {}s".format(timeout))


def classify(clients, roles):
    """Map role names to the FakeClient holding that role."""
    by_role = {}
    for client in clients:
        role = roles[str(client.player_id)]
        by_role[role] = client
    return by_role


async def run_round_one(clients, spawns_by_round):
    """Round 1: movement broadcast, knife kills sheriff, murderer wins."""
    alice = clients[0]

    await alice.send({'type': 'start_game'})

    game_starts = {}
    for client in clients:
        gs = await client.expect('game_started')
        game_starts[client.name] = gs

    gs = game_starts['Alice']
    roles = gs['roles']
    spawns = gs['spawns']
    spawns_by_round.append(spawns)

    assert sorted(roles.values()) == ['innocent', 'murderer', 'sheriff'], \
        "Expected one of each role, got {}".format(roles)
    assert set(roles.keys()) == set(spawns.keys()), \
        "Spawns must cover every player"
    positions = [tuple(p) for p in spawns.values()]
    assert len(set(positions)) == len(positions), \
        "Spawn points must be distinct, got {}".format(positions)
    print("PASS: game_started carries roles + distinct spawn points")

    by_role = classify(clients, roles)
    murderer = by_role['murderer']
    sheriff = by_role['sheriff']
    innocent = by_role['innocent']

    # --- movement broadcast ---
    move_pos = [1.0, 0.0, 1.0]
    await murderer.send({'type': 'move', 'position': move_pos,
                         'rotation': 90, 'animation': 'walk'})
    for other in clients:
        if other is murderer:
            continue
        msg = await other.expect(
            'player_move',
            lambda m: m['player_id'] == murderer.player_id)
        assert msg['position'] == move_pos, msg
        assert msg['rotation'] == 90, msg
    print("PASS: movement broadcast received by the other players")

    # --- knife kill on the SHERIFF ---
    sheriff_spawn = spawns[str(sheriff.player_id)]
    near_sheriff = [sheriff_spawn[0] + 1.0, 0.0, sheriff_spawn[2]]
    await murderer.send({'type': 'move', 'position': near_sheriff,
                         'rotation': 0, 'animation': 'idle'})
    await murderer.send({'type': 'attack', 'attack_type': 'knife',
                         'target_id': sheriff.player_id})

    kill = await innocent.expect(
        'player_killed', lambda m: m['victim_id'] == sheriff.player_id)
    assert kill['weapon'] == 'knife', kill
    assert kill['killer_id'] == murderer.player_id, kill
    print("PASS: knife kill on the sheriff works")

    # --- murderer kills the last innocent -> murderer wins ---
    await asyncio.sleep(1.1)  # server-side knife cooldown
    innocent_spawn = spawns[str(innocent.player_id)]
    near_innocent = [innocent_spawn[0] + 1.0, 0.0, innocent_spawn[2]]
    await murderer.send({'type': 'move', 'position': near_innocent,
                         'rotation': 0, 'animation': 'idle'})
    await murderer.send({'type': 'attack', 'attack_type': 'knife',
                         'target_id': innocent.player_id})

    ended = await murderer.expect('game_ended')
    assert ended['winner'] == 'murderer', ended
    print("PASS: killing all non-murderers ends the round (murderer wins)")

    # --- back_to_lobby includes the player list ---
    lobby = await alice.expect('back_to_lobby', timeout=12)
    assert 'all_players' in lobby, lobby
    names = sorted(p['username'] for p in lobby['all_players'])
    assert names == ['Alice', 'Bob', 'Cara'], names
    # Sync the other clients to the lobby as well.
    for client in clients[1:]:
        await client.expect('back_to_lobby', timeout=12)
    print("PASS: back_to_lobby includes the full player list")


async def run_round_two(clients, spawns_by_round):
    """Round 2: gun kill on the murderer ends the game, innocents win."""
    alice = clients[0]

    await alice.send({'type': 'start_game'})
    game_starts = {}
    for client in clients:
        game_starts[client.name] = await client.expect('game_started')

    gs = game_starts['Alice']
    roles = gs['roles']
    spawns = gs['spawns']
    spawns_by_round.append(spawns)
    by_role = classify(clients, roles)
    murderer = by_role['murderer']
    sheriff = by_role['sheriff']
    innocent = by_role['innocent']

    # Sheriff sidles up next to the murderer and shoots straight at them.
    murderer_spawn = spawns[str(murderer.player_id)]
    shoot_from = [murderer_spawn[0] + 4.0, 0.0, murderer_spawn[2]]
    await sheriff.send({'type': 'move', 'position': shoot_from,
                        'rotation': 0, 'animation': 'idle'})
    await sheriff.send({'type': 'attack', 'attack_type': 'gun',
                        'direction': [-1.0, 0.0, 0.0]})

    fired = await innocent.expect('bullet_fired')
    assert fired['bullet']['shooter_id'] == sheriff.player_id, fired

    kill = await innocent.expect(
        'player_killed', lambda m: m['victim_id'] == murderer.player_id,
        timeout=5)
    assert kill['weapon'] == 'gun', kill
    assert kill['killer_id'] == sheriff.player_id, kill
    print("PASS: server-simulated bullet kills the murderer")

    ended = await innocent.expect('game_ended', timeout=5)
    assert ended['winner'] == 'innocents', ended
    print("PASS: gun kill on the murderer ends the game (innocents win)")


async def main():
    clients = [FakeClient('Alice'), FakeClient('Bob'), FakeClient('Cara')]
    spawns_by_round = []

    await wait_for_server(URI)

    # --- handshake / connected ---
    alice, bob, cara = clients
    ca = await alice.connect(URI)
    assert ca['username'] == 'Alice', ca
    assert len(ca['all_players']) == 1, ca

    cb = await bob.connect(URI)
    assert len(cb['all_players']) == 2, cb
    await alice.expect(
        'player_joined',
        lambda m: m['player']['player_id'] == bob.player_id)

    cc = await cara.connect(URI)
    names = sorted(p['username'] for p in cc['all_players'])
    assert names == ['Alice', 'Bob', 'Cara'], names
    print("PASS: handshake/connected with correct player lists")

    await run_round_one(clients, spawns_by_round)
    await run_round_two(clients, spawns_by_round)

    for client in clients:
        await client.close()

    print("\nALL TESTS PASSED")


if __name__ == '__main__':
    server_proc = subprocess.Popen(
        [sys.executable, MAIN, '--server', str(PORT)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        asyncio.get_event_loop().run_until_complete(
            asyncio.wait_for(main(), timeout=120))
    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()

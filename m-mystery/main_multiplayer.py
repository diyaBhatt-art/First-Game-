"""
Roblox-Style Multiplayer Murder Mystery Game
Client-server architecture with real-time multiplayer over websockets.

Run the server (headless):   python main_multiplayer.py --server [port]
Run a client:                python main_multiplayer.py [username]
"""
import asyncio
import json
import math
import queue
import random
import sys
import threading
import time

import websockets
from ursina import *


# ============================================================================
# SHARED CONSTANTS (used by both server simulation and client rendering so
# every player sees the same arena)
# ============================================================================

ARENA_HALF_X = 40
ARENA_HALF_Z = 30

# Fixed interior wall layout: {'position': [x, y, z], 'scale': [sx, sy, sz]}
INTERIOR_WALLS = [
    {'position': [-18, 1.5, -10], 'scale': [2, 3, 8]},
    {'position': [15, 1.5, -12], 'scale': [8, 3, 2]},
    {'position': [-12, 1.5, 12], 'scale': [8, 3, 2]},
    {'position': [20, 1.5, 10], 'scale': [2, 3, 8]},
    {'position': [0, 1.5, 2], 'scale': [2, 3, 10]},
]

# Spread-out spawn points, all clear of interior walls.
SPAWN_POINTS = [
    (-30, 0, -20), (28, 0, -20), (-30, 0, 20), (28, 0, 20),
    (0, 0, -24), (0, 0, 24), (-32, 0, 0), (32, 0, 0),
    (-12, 0, -22), (12, 0, 22),
]

KNIFE_RANGE = 3.0
KNIFE_COOLDOWN = 1.0
GUN_COOLDOWN = 0.8
BULLET_SPEED = 50.0
BULLET_LIFETIME = 2.0
BULLET_HIT_RADIUS = 1.0
SERVER_TICK = 0.05  # 20 Hz bullet simulation
ROUND_TIME = 180
LOBBY_RETURN_DELAY = 5.0


def vec_distance(a, b):
    """Euclidean distance between two [x, y, z] lists."""
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(a, b)))


# ============================================================================
# SERVER SIDE - Multiplayer Game Logic
# ============================================================================

class PlayerSession:
    """Represents a connected player session."""

    def __init__(self, websocket, player_id, username):
        self.websocket = websocket
        self.player_id = player_id
        self.username = username
        self.position = [0.0, 0.0, 0.0]
        self.rotation = 0
        self.is_alive = True
        self.role = None
        self.has_knife = False
        self.has_gun = False
        self.m_bucks = 0
        self.skin_color = [255, 204, 153]
        self.shirt_color = [30, 140, 200]
        self.pants_color = [35, 55, 120]
        self.hair_color = [44, 181, 232]
        self.animation_state = 'idle'
        self.last_knife_time = 0.0
        self.last_gun_time = 0.0
        self.last_update = time.time()


class MultiplayerServer:
    """Authoritative game server for multiplayer matches.

    Everything runs on a single asyncio event loop, so no threading locks
    are required.
    """

    def __init__(self, host='localhost', port=8765):
        self.host = host
        self.port = port
        self.players = {}  # player_id -> PlayerSession
        self.next_player_id = 1
        self.game_state = 'lobby'  # lobby, playing, ended
        self.round_time = ROUND_TIME
        self.round_id = 0
        self.murderer_id = None
        self.sheriff_id = None
        self.bullets = []
        self.next_bullet_id = 0
        self.m_bucks = []
        self.chat_messages = []

        self.generate_m_bucks()

    def generate_m_bucks(self):
        """Generate M Buck spawn locations."""
        zones = [
            {'x': -30, 'y': -20, 'w': 20, 'h': 15},
            {'x': 10, 'y': -25, 'w': 25, 'h': 20},
            {'x': -25, 'y': 10, 'w': 15, 'h': 20},
            {'x': 15, 'y': 15, 'w': 20, 'h': 15},
        ]

        self.m_bucks = []
        for _ in range(30):
            zone = random.choice(zones)
            x = random.uniform(zone['x'], zone['x'] + zone['w'])
            z = random.uniform(zone['y'], zone['y'] + zone['h'])
            value = random.randint(1, 3)
            self.m_bucks.append({
                'id': len(self.m_bucks),
                'position': [x, 0.5, z],
                'value': value,
                'collected': False,
            })

    async def handle_connection(self, websocket, path=None):
        """Handle a new player connection."""
        player_id = None
        try:
            # Wait for handshake
            handshake = await websocket.recv()
            data = json.loads(handshake)

            player_id = self.next_player_id
            self.next_player_id += 1
            username = data.get('username', 'Guest_{}'.format(player_id))

            player = PlayerSession(websocket, player_id, username)
            self.players[player_id] = player

            await websocket.send(json.dumps({
                'type': 'connected',
                'player_id': player_id,
                'username': username,
                'all_players': self.get_all_players_info(),
            }))

            await self.broadcast({
                'type': 'player_joined',
                'player': self.get_player_info(player),
            }, exclude=[player_id])

            print("Player {} (ID: {}) connected".format(username, player_id))

            async for message in websocket:
                await self.handle_message(player_id, message)

        except websockets.exceptions.ConnectionClosed:
            print("Player {} disconnected".format(player_id))
        except Exception as e:
            print("Connection error for player {}: {}".format(player_id, e))
        finally:
            if player_id is not None:
                await self.remove_player(player_id)

    async def handle_message(self, player_id, message):
        """Handle incoming messages from players."""
        try:
            data = json.loads(message)
            msg_type = data.get('type')

            player = self.players.get(player_id)
            if not player:
                return

            if msg_type == 'move':
                # Dead players cannot move.
                if not player.is_alive:
                    return
                player.position = list(data.get('position', player.position))
                player.rotation = data.get('rotation', player.rotation)
                player.animation_state = data.get('animation', 'idle')
                player.last_update = time.time()

                await self.broadcast({
                    'type': 'player_move',
                    'player_id': player_id,
                    'position': player.position,
                    'rotation': player.rotation,
                    'animation': player.animation_state,
                }, exclude=[player_id])

            elif msg_type == 'attack':
                await self.handle_attack(player_id, data)

            elif msg_type == 'collect_buck':
                await self.handle_collect_buck(player_id, data)

            elif msg_type == 'chat':
                await self.handle_chat(player_id, data)

            elif msg_type == 'start_game':
                if self.game_state == 'lobby' and len(self.players) >= 2:
                    await self.start_game()

        except Exception as e:
            print("Error handling message: {}".format(e))

    def _find_knife_target(self, attacker, target_id):
        """Validate or find a knife target near the attacker."""
        candidates = []
        if target_id is not None:
            target = self.players.get(target_id)
            if target:
                candidates = [target]
        else:
            candidates = list(self.players.values())

        best = None
        best_dist = KNIFE_RANGE
        for target in candidates:
            if target.player_id == attacker.player_id:
                continue
            if not target.is_alive:
                continue
            # Knife kills any non-murderer with a role (innocent OR sheriff).
            if target.role not in ('innocent', 'sheriff'):
                continue
            dist = vec_distance(attacker.position, target.position)
            if dist <= best_dist:
                best = target
                best_dist = dist
        return best

    async def handle_attack(self, attacker_id, data):
        """Handle attack action. Server enforces roles and cooldowns."""
        if self.game_state != 'playing':
            return
        player = self.players.get(attacker_id)
        if not player or not player.is_alive:
            return

        attack_type = data.get('attack_type')
        now = time.time()

        if attack_type == 'knife':
            # Only the murderer can knife.
            if player.role != 'murderer':
                return
            if now - player.last_knife_time < KNIFE_COOLDOWN:
                return
            player.last_knife_time = now

            target = self._find_knife_target(player, data.get('target_id'))
            if target:
                target.is_alive = False
                await self.broadcast({
                    'type': 'player_killed',
                    'killer_id': attacker_id,
                    'victim_id': target.player_id,
                    'weapon': 'knife',
                })
                await self.check_win_condition()

        elif attack_type == 'gun':
            # Only the sheriff can shoot.
            if player.role != 'sheriff':
                return
            if now - player.last_gun_time < GUN_COOLDOWN:
                return

            direction = data.get('direction')
            if not direction or len(direction) != 3:
                return
            length = math.sqrt(sum(c * c for c in direction))
            if length < 1e-6:
                return
            direction = [c / length for c in direction]
            player.last_gun_time = now

            bullet = {
                'id': self.next_bullet_id,
                'shooter_id': attacker_id,
                'position': [
                    player.position[0] + direction[0] * 0.8,
                    player.position[1] + 1.0 + direction[1] * 0.8,
                    player.position[2] + direction[2] * 0.8,
                ],
                'direction': direction,
                'speed': BULLET_SPEED,
                'lifetime': BULLET_LIFETIME,
            }
            self.next_bullet_id += 1
            self.bullets.append(bullet)

            await self.broadcast({
                'type': 'bullet_fired',
                'bullet': bullet,
            })

    # ------------------------------------------------------------------
    # Bullet simulation (server tick)
    # ------------------------------------------------------------------

    def _bullet_blocked(self, pos):
        """True if the bullet position is outside the arena or inside a wall."""
        x, y, z = pos
        if abs(x) >= ARENA_HALF_X or abs(z) >= ARENA_HALF_Z:
            return True
        for wall in INTERIOR_WALLS:
            wx, wy, wz = wall['position']
            sx, sy, sz = wall['scale']
            if (abs(x - wx) <= sx / 2 and abs(z - wz) <= sz / 2
                    and abs(y - wy) <= sy / 2):
                return True
        return False

    def _advance_bullet(self, bullet, dt):
        """Move a bullet with sub-stepping. Returns the player hit, or None.

        Sets bullet['blocked'] when the bullet hits a wall or leaves the
        arena.
        """
        pos = bullet['position']
        direction = bullet['direction']
        travel = bullet['speed'] * dt
        steps = max(1, int(math.ceil(travel / 0.5)))
        step = travel / steps

        for _ in range(steps):
            for i in range(3):
                pos[i] += direction[i] * step
            if self._bullet_blocked(pos):
                bullet['blocked'] = True
                return None
            for player in self.players.values():
                if player.player_id == bullet['shooter_id']:
                    continue
                if not player.is_alive or not player.role:
                    continue
                center = [player.position[0], player.position[1] + 1.0,
                          player.position[2]]
                if vec_distance(pos, center) < BULLET_HIT_RADIUS:
                    return player
        return None

    async def _resolve_gun_hit(self, shooter_id, victim):
        """Apply murder-mystery gun rules for a bullet hit."""
        if not victim.is_alive:
            return
        victim.is_alive = False
        await self.broadcast({
            'type': 'player_killed',
            'killer_id': shooter_id,
            'victim_id': victim.player_id,
            'weapon': 'gun',
        })

        # Classic MM rule: shooting an innocent kills the sheriff too.
        shooter = self.players.get(shooter_id)
        if victim.role != 'murderer' and shooter and shooter.is_alive:
            shooter.is_alive = False
            await self.broadcast({
                'type': 'player_killed',
                'killer_id': shooter_id,
                'victim_id': shooter_id,
                'weapon': 'gun',
                'reason': 'shot_innocent',
            })

    async def simulate_bullets(self, dt):
        """Advance all live bullets and resolve hits."""
        if not self.bullets:
            return

        hits = []
        remaining = []
        for bullet in self.bullets:
            victim = self._advance_bullet(bullet, dt)
            bullet['lifetime'] -= dt
            if victim is not None:
                hits.append((bullet['shooter_id'], victim))
            elif not bullet.get('blocked') and bullet['lifetime'] > 0:
                remaining.append(bullet)
        self.bullets = remaining

        for shooter_id, victim in hits:
            await self._resolve_gun_hit(shooter_id, victim)
        if hits:
            await self.check_win_condition()

    async def tick_loop(self):
        """Persistent ~20 Hz server simulation loop."""
        while True:
            await asyncio.sleep(SERVER_TICK)
            try:
                if self.game_state == 'playing':
                    await self.simulate_bullets(SERVER_TICK)
            except Exception as e:
                print("Tick error: {}".format(e))

    # ------------------------------------------------------------------
    # Round lifecycle
    # ------------------------------------------------------------------

    async def handle_collect_buck(self, player_id, data):
        """Handle M Buck collection."""
        if self.game_state != 'playing':
            return
        player = self.players.get(player_id)
        if not player or not player.is_alive:
            return

        buck_id = data.get('buck_id')
        for buck in self.m_bucks:
            if buck['id'] == buck_id and not buck['collected']:
                dist = vec_distance(player.position, buck['position'])
                if dist < 1.5:
                    buck['collected'] = True
                    player.m_bucks += buck['value']

                    await self.broadcast({
                        'type': 'buck_collected',
                        'player_id': player_id,
                        'buck_id': buck_id,
                        'm_bucks': player.m_bucks,
                    })
                break

    async def handle_chat(self, player_id, data):
        """Handle chat message."""
        player = self.players.get(player_id)
        if not player:
            return

        message = str(data.get('message', ''))[:100]
        if not message:
            return

        self.chat_messages.append({
            'player_id': player_id,
            'username': player.username,
            'message': message,
            'timestamp': time.time(),
        })

        await self.broadcast({
            'type': 'chat_message',
            'player_id': player_id,
            'username': player.username,
            'message': message,
        })

    async def start_game(self):
        """Start a new game round."""
        if self.game_state == 'playing':
            return

        player_list = list(self.players.values())
        if len(player_list) < 2:
            return

        self.game_state = 'playing'
        self.round_id += 1
        self.bullets = []

        # Assign roles: exactly one murderer, one sheriff, rest innocents.
        roles = ['innocent'] * (len(player_list) - 2) + ['murderer', 'sheriff']
        random.shuffle(roles)

        # Assign spread-out spawn points.
        spawn_points = list(SPAWN_POINTS)
        random.shuffle(spawn_points)

        self.murderer_id = None
        self.sheriff_id = None
        spawns = {}

        for i, (player, role) in enumerate(zip(player_list, roles)):
            player.role = role
            player.is_alive = True
            player.has_knife = (role == 'murderer')
            player.has_gun = (role == 'sheriff')
            player.last_knife_time = 0.0
            player.last_gun_time = 0.0

            spawn = spawn_points[i % len(spawn_points)]
            player.position = list(spawn)
            spawns[player.player_id] = list(spawn)

            if role == 'murderer':
                self.murderer_id = player.player_id
            elif role == 'sheriff':
                self.sheriff_id = player.player_id

        self.round_time = ROUND_TIME

        # Reset M Bucks for the new round.
        for buck in self.m_bucks:
            buck['collected'] = False

        await self.broadcast({
            'type': 'game_started',
            'roles': {p.player_id: p.role for p in player_list},
            'spawns': spawns,
            'murderer_id': self.murderer_id,
            'sheriff_id': self.sheriff_id,
            'round_time': self.round_time,
            'm_bucks': self.m_bucks,
        })

        asyncio.ensure_future(self.run_round_timer(self.round_id))

    async def run_round_timer(self, round_id):
        """Run the round timer. Guarded by round_id so stale timers die."""
        while (self.game_state == 'playing' and self.round_id == round_id
               and self.round_time > 0):
            await asyncio.sleep(1)
            if self.round_id != round_id:
                return
            self.round_time -= 1

            if self.round_time % 5 == 0:
                await self.broadcast({
                    'type': 'timer_update',
                    'time_left': self.round_time,
                })

        if self.game_state == 'playing' and self.round_id == round_id:
            # Time ran out: the murderer failed, innocents survive.
            await self.end_game('innocents')

    def _alive_roles(self):
        """Roles of living players that are part of the current round."""
        return [p.role for p in self.players.values()
                if p.is_alive and p.role]

    async def check_win_condition(self):
        """Check if someone has won. Works for any player count."""
        if self.game_state != 'playing':
            return

        alive_roles = self._alive_roles()
        if 'murderer' not in alive_roles:
            # Murderer dead or disconnected: innocents win.
            await self.end_game('innocents')
        elif not any(r in ('innocent', 'sheriff') for r in alive_roles):
            # No innocents or sheriff left alive: murderer wins.
            await self.end_game('murderer')

    async def end_game(self, winner):
        """End the current game round and return everyone to the lobby."""
        if self.game_state != 'playing':
            return
        self.game_state = 'ended'
        self.bullets = []
        round_id = self.round_id

        await self.broadcast({
            'type': 'game_ended',
            'winner': winner,
            'final_stats': {
                pid: {'role': p.role, 'm_bucks': p.m_bucks,
                      'alive': p.is_alive}
                for pid, p in self.players.items()
            },
        })

        await asyncio.sleep(LOBBY_RETURN_DELAY)
        if self.round_id != round_id or self.game_state != 'ended':
            return

        # Reset everyone for the lobby.
        for player in self.players.values():
            player.role = None
            player.is_alive = True
            player.has_knife = False
            player.has_gun = False

        self.game_state = 'lobby'
        await self.broadcast({
            'type': 'back_to_lobby',
            'all_players': self.get_all_players_info(),
        })

    async def remove_player(self, player_id):
        """Remove a player; handle mid-round disconnects."""
        player = self.players.pop(player_id, None)
        if not player:
            return

        await self.broadcast({
            'type': 'player_left',
            'player_id': player_id,
            'username': player.username,
        })

        # A disconnect mid-round can decide the game (e.g. the murderer
        # leaving means innocents win).
        if self.game_state == 'playing':
            await self.check_win_condition()

    def get_player_info(self, player):
        """Get player info for broadcasting."""
        return {
            'player_id': player.player_id,
            'username': player.username,
            'position': player.position,
            'rotation': player.rotation,
            'is_alive': player.is_alive,
            'role': player.role if self.game_state == 'playing' else None,
            'has_knife': player.has_knife,
            'has_gun': player.has_gun,
            'm_bucks': player.m_bucks,
            'skin_color': player.skin_color,
            'shirt_color': player.shirt_color,
            'pants_color': player.pants_color,
            'hair_color': player.hair_color,
            'animation_state': player.animation_state,
        }

    def get_all_players_info(self):
        """Get all players info."""
        return [self.get_player_info(p) for p in self.players.values()]

    async def broadcast(self, message, exclude=None):
        """Broadcast message to all players."""
        exclude = exclude or []
        payload = json.dumps(message)
        tasks = []

        for player in list(self.players.values()):
            if player.player_id in exclude:
                continue
            tasks.append(asyncio.ensure_future(
                player.websocket.send(payload)))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self):
        """Run the WebSocket server."""
        server = await websockets.serve(self.handle_connection,
                                        self.host, self.port)
        asyncio.ensure_future(self.tick_loop())
        print("Multiplayer server running on ws://{}:{}".format(
            self.host, self.port))
        await server.wait_closed()


# ============================================================================
# CLIENT SIDE - 3D Roblox-Style Game
# ============================================================================

class BlockyCharacter(Entity):
    """Roblox-style R6 blocky character model."""

    def __init__(self, name, player_id=0, position=(0, 0, 0),
                 skin_color=(255, 204, 153), shirt_color=(30, 140, 200),
                 pants_color=(35, 55, 120), hair_color=(44, 181, 232),
                 **kwargs):
        super().__init__(**kwargs)

        self.player_id = player_id
        self.character_name = name
        self.is_alive = True
        self.has_knife = False
        self.has_gun = False
        self.role = ''
        self.speed = 8
        self.sprint_speed = 14
        self.stamina = 100
        self.max_stamina = 100
        self.m_bucks = 0
        self.animation_state = 'idle'

        # Scale for R6 proportions
        s = 0.5

        # NOTE: color.rgb expects 0-255 ints in this ursina version.
        self.torso = Entity(parent=self, model='cube',
                            color=color.rgb(*shirt_color),
                            scale=(2*s, 2*s, 1*s), position=(0, 1.5*s, 0))
        self.head = Entity(parent=self, model='cube',
                           color=color.rgb(*skin_color),
                           scale=(1*s, 1*s, 1*s), position=(0, 2.5*s, 0))
        self.hair = Entity(parent=self, model='cube',
                           color=color.rgb(*hair_color),
                           scale=(1.05*s, 0.3*s, 1*s), position=(0, 2.8*s, 0))
        self.left_leg = Entity(parent=self, model='cube',
                               color=color.rgb(*pants_color),
                               scale=(0.7*s, 1.2*s, 0.7*s),
                               position=(-0.5*s, 0.6*s, 0))
        self.right_leg = Entity(parent=self, model='cube',
                                color=color.rgb(*pants_color),
                                scale=(0.7*s, 1.2*s, 0.7*s),
                                position=(0.5*s, 0.6*s, 0))
        self.left_arm = Entity(parent=self, model='cube',
                               color=color.rgb(*skin_color),
                               scale=(0.6*s, 1.4*s, 0.6*s),
                               position=(-1.3*s, 1.5*s, 0))
        self.right_arm = Entity(parent=self, model='cube',
                                color=color.rgb(*skin_color),
                                scale=(0.6*s, 1.4*s, 0.6*s),
                                position=(1.3*s, 1.5*s, 0))

        # World-space billboard name tag. Parented to the character so it is
        # destroyed together with it (no camera.ui leak).
        self.name_tag = Text(
            text=name,
            parent=self,
            position=(0, 2.1, 0),
            scale=8,
            origin=(0, 0),
            color=color.white,
        )
        self.name_tag.billboard = True

        # Weapon indicators
        self.knife_indicator = None
        self.gun_indicator = None

        self.set_position(position)

    def set_position(self, pos):
        """Set position from list or tuple."""
        self.position = Vec3(*pos)

    def show_weapon(self, weapon_type):
        """Show weapon indicator on character."""
        if weapon_type == 'knife':
            if not self.knife_indicator:
                self.knife_indicator = Entity(
                    parent=self.right_arm, model='cube', color=color.gray,
                    scale=(0.1, 0.6, 0.1), position=(0, -0.5, 0.3))
            self.knife_indicator.enabled = True
        elif weapon_type == 'gun':
            if not self.gun_indicator:
                self.gun_indicator = Entity(
                    parent=self.right_arm, model='cube',
                    color=color.dark_gray,
                    scale=(0.15, 0.2, 0.3), position=(0, -0.3, 0.4))
            self.gun_indicator.enabled = True

    def hide_weapons(self):
        """Hide all weapon indicators."""
        if self.knife_indicator:
            self.knife_indicator.enabled = False
        if self.gun_indicator:
            self.gun_indicator.enabled = False

    def die(self):
        """Mark the character dead: tip over and hide the name tag."""
        self.is_alive = False
        self.reset_animation()
        self.rotation_x = -90
        self.name_tag.enabled = False

    def revive(self):
        """Reset the character to a living state."""
        self.is_alive = True
        self.rotation_x = 0
        self.name_tag.enabled = True
        self.has_knife = False
        self.has_gun = False
        self.role = ''
        self.stamina = self.max_stamina
        self.hide_weapons()
        self.reset_animation()

    def animate_walk(self, speed_factor=1):
        """Simple walking animation."""
        t = time.time() * speed_factor * 10
        self.left_leg.rotation_x = math.sin(t) * 20
        self.right_leg.rotation_x = math.sin(t + math.pi) * 20
        self.left_arm.rotation_x = math.sin(t + math.pi) * 15
        self.right_arm.rotation_x = math.sin(t) * 15

    def reset_animation(self):
        """Reset limbs to neutral position."""
        self.left_leg.rotation_x = 0
        self.right_leg.rotation_x = 0
        self.left_arm.rotation_x = 0
        self.right_arm.rotation_x = 0


class MultiplayerGame3D:
    """Main 3D multiplayer game client with Roblox-style gameplay.

    Networking model:
    - One background thread runs one persistent asyncio loop that owns the
      websocket connection.
    - Incoming messages are parsed on the network thread and pushed onto a
      thread-safe queue; they are applied on the main (ursina) thread from
      update().
    - Outgoing messages are scheduled onto the network loop with
      asyncio.run_coroutine_threadsafe.
    """

    MOVE_SEND_INTERVAL = 0.05  # 20 Hz position updates

    def __init__(self, server_uri='ws://localhost:8765', username='Guest'):
        self.server_uri = server_uri
        self.websocket = None
        self.connected = False
        self._connecting = False
        self._net_loop = None
        self._net_thread = None
        self.incoming = queue.Queue()

        self.my_player_id = None
        self.username = username

        # Game state
        self.remote_players = {}   # player_id -> BlockyCharacter
        self.local_player = None
        self.walls = []
        self.m_bucks_entities = {}
        self.bullets = []
        self.end_screen_entities = []
        self.lobby_players = []    # list of player info dicts
        self.player_names = {}     # player_id -> username
        self.my_bucks = 0

        # Round state
        self.round_time = ROUND_TIME
        self.game_state = 'menu'   # menu, lobby, playing, ended
        self.my_role = None

        # Input pacing
        self._last_attack_time = 0.0
        self._last_move_sent = 0.0
        self._buck_request_times = {}

        # Chat / kill feed buffers
        self.chat_lines = []
        self.kill_feed_entries = []  # list of (line, expiry_time)

        # Setup Ursina app. NOTE: macOS Panda3D auto-lighting shaders fail to
        # compile here, so the scene stays unlit/stylized (no lights, no
        # lit_with_shadows_shader).
        self.app = Ursina(title='M Mystery 3D - Multiplayer',
                          borderless=False, fullscreen=False,
                          development_mode=False)
        window.color = color.rgb(120, 170, 255)

        # Camera setup
        self.camera_pivot = Entity()
        self.mouse_sensitivity = 0.15

        self.setup_scene()
        self.setup_ui()
        self.setup_camera()

        # Pre-fill username and auto-connect shortly after startup.
        self.username_input.text = self.username
        invoke(self.attempt_connect, delay=1.0)

    # ------------------------------------------------------------------
    # Scene / UI setup
    # ------------------------------------------------------------------

    def setup_scene(self):
        """Setup the 3D scene (unlit, stylized)."""
        Sky(texture='sky_sunset')

        self.ground = Entity(
            model='plane',
            texture='grass',
            scale=(100, 1, 100),
            collider='box',
            color=color.rgba(92, 130, 92, 255),
        )

        # Grid pattern for the Roblox baseplate feel.
        grid_size = 10
        for x in range(-50, 50, grid_size):
            for z in range(-50, 50, grid_size):
                shade = 0.9 if ((x // grid_size) + (z // grid_size)) % 2 == 0 else 1.0
                Entity(
                    model='cube',
                    color=color.rgba(int(92 * shade), int(130 * shade),
                                     int(92 * shade), 255),
                    scale=(grid_size, 0.1, grid_size),
                    position=(x + grid_size / 2, -0.05, z + grid_size / 2),
                    texture='white_cube',
                )

        # Perimeter walls.
        wall_positions = [
            (-ARENA_HALF_X, 1.5, 0, 1, 3, ARENA_HALF_Z * 2),
            (ARENA_HALF_X, 1.5, 0, 1, 3, ARENA_HALF_Z * 2),
            (0, 1.5, -ARENA_HALF_Z, ARENA_HALF_X * 2, 3, 1),
            (0, 1.5, ARENA_HALF_Z, ARENA_HALF_X * 2, 3, 1),
        ]
        for wx, wy, wz, ws, wh, wd in wall_positions:
            w = Entity(
                model='cube',
                color=color.rgba(72, 88, 72, 255),
                scale=(ws, wh, wd),
                position=(wx, wy, wz),
                collider='box',
                texture='brick',
            )
            self.walls.append(w)

        # Fixed interior walls shared with the server, so every client sees
        # the same map and server bullet collision matches the visuals.
        for wall in INTERIOR_WALLS:
            w = Entity(
                model='cube',
                color=color.rgba(72, 88, 72, 255),
                scale=tuple(wall['scale']),
                position=tuple(wall['position']),
                collider='box',
                texture='brick',
            )
            self.walls.append(w)

    def setup_camera(self):
        """Setup third-person camera like Roblox."""
        self.camera_pivot.position = (0, 10, 0)
        camera.parent = self.camera_pivot
        camera.position = (0, 5, -10)
        camera.look_at(self.camera_pivot)

    def setup_ui(self):
        """Setup HUD UI elements."""
        # HUD background
        self.hud_bg = Entity(
            parent=camera.ui, model='quad',
            color=color.rgba(25, 25, 35, 200),
            scale=(0.8, 0.05), position=(0, 0.45))
        self.hud_bg.enabled = False

        self.hud_text = Text(
            text='', parent=camera.ui, position=(-0.38, 0.43),
            scale=1.2, color=color.white)
        self.hud_text.enabled = False

        # Stamina bar
        self.stamina_bar_bg = Entity(
            parent=camera.ui, model='quad',
            color=color.rgba(40, 40, 50, 200),
            scale=(0.2, 0.03), position=(0.4, -0.45))
        self.stamina_bar_bg.enabled = False

        self.stamina_bar = Entity(
            parent=camera.ui, model='quad',
            color=color.rgb(80, 200, 120),
            scale=(0.19, 0.025), position=(0.4, -0.45))
        self.stamina_bar.enabled = False

        # Role indicator
        self.role_text = Text(
            text='', parent=camera.ui, position=(-0.38, 0.38),
            scale=1.5, color=color.yellow)
        self.role_text.enabled = False

        # Kill feed (top right)
        self.kill_feed_text = Text(
            text='', parent=camera.ui, position=(0.62, 0.42),
            scale=0.9, color=color.rgba(255, 235, 235, 255),
            origin=(0.5, 0.5))

        # Chat box
        self.chat_panel = Entity(
            parent=camera.ui, model='quad',
            color=color.rgba(0, 0, 0, 150),
            scale=(0.5, 0.3), position=(-0.55, -0.25))
        self.chat_panel.enabled = False

        self.chat_messages_ui = Text(
            text='', parent=camera.ui, position=(-0.78, -0.12),
            scale=0.8, color=color.white)
        self.chat_messages_ui.enabled = False

        self.chat_input = InputField(
            parent=camera.ui, position=(-0.55, -0.42))
        self.chat_input.scale = (0.4, 0.05)
        self.chat_input.enabled = False

        # Connection screen
        self.conn_panel = Entity(
            parent=camera.ui, model='quad',
            color=color.rgba(0, 0, 0, 200),
            scale=(0.5, 0.45), position=(0, 0))

        self.conn_title = Text(
            text='M MYSTERY 3D\nMULTIPLAYER', parent=camera.ui,
            position=(0, 0.12), scale=2, color=color.cyan, origin=(0, 0))

        self.username_input = InputField(
            parent=camera.ui, position=(0, 0.02))
        self.username_input.scale = (0.3, 0.05)

        self.server_input = InputField(
            parent=camera.ui, position=(0, -0.06),
            text='ws://localhost:8765')
        self.server_input.scale = (0.3, 0.05)

        self.connect_button = Button(
            text='CONNECT', parent=camera.ui, scale=(0.2, 0.08),
            position=(0, -0.16), color=color.azure)
        self.connect_button.on_click = self.attempt_connect

        self.conn_status = Text(
            text='', parent=camera.ui, position=(0, -0.23),
            scale=1, color=color.orange, origin=(0, 0))

        # Lobby UI
        self.lobby_panel = Entity(
            parent=camera.ui, model='quad',
            color=color.rgba(0, 0, 0, 200),
            scale=(0.5, 0.45), position=(0, 0))
        self.lobby_panel.enabled = False

        self.lobby_title = Text(
            text='LOBBY', parent=camera.ui, position=(0, 0.15),
            scale=2.5, color=color.green, origin=(0, 0))
        self.lobby_title.enabled = False

        self.players_list = Text(
            text='', parent=camera.ui, position=(0, 0.02),
            scale=1.2, color=color.white, origin=(0, 0))
        self.players_list.enabled = False

        self.start_button = Button(
            text='START GAME', parent=camera.ui, scale=(0.25, 0.08),
            position=(0, -0.15), color=color.green)
        self.start_button.enabled = False
        self.start_button.on_click = self.request_start_game

    # ------------------------------------------------------------------
    # Screen management
    # ------------------------------------------------------------------

    def show_connection_screen(self):
        self.conn_panel.enabled = True
        self.conn_title.enabled = True
        self.username_input.enabled = True
        self.server_input.enabled = True
        self.connect_button.enabled = True
        self.conn_status.enabled = True

    def hide_connection_screen(self):
        self.conn_panel.enabled = False
        self.conn_title.enabled = False
        self.username_input.enabled = False
        self.server_input.enabled = False
        self.connect_button.enabled = False
        self.conn_status.enabled = False

    def show_lobby(self, players):
        """Show lobby with the given player list."""
        self.hide_connection_screen()
        self.disable_game_ui()
        self.lobby_panel.enabled = True
        self.lobby_title.enabled = True
        self.players_list.enabled = True
        self.lobby_players = list(players)
        for p in self.lobby_players:
            self.player_names[p['player_id']] = p['username']
        self.update_lobby_player_list()

    def hide_lobby(self):
        self.lobby_panel.enabled = False
        self.lobby_title.enabled = False
        self.players_list.enabled = False
        self.start_button.enabled = False

    def update_lobby_player_list(self):
        """Update the player list shown in the lobby."""
        names = [p['username'] for p in self.lobby_players]
        self.players_list.text = 'Players ({}):\n{}'.format(
            len(names), '\n'.join(names) if names else '(waiting...)')
        self.start_button.enabled = (self.lobby_panel.enabled
                                     and len(names) >= 2)

    def enable_game_ui(self):
        """Enable game HUD."""
        self.hide_lobby()
        self.hud_bg.enabled = True
        self.hud_text.enabled = True
        self.role_text.enabled = True
        self.stamina_bar_bg.enabled = True
        self.stamina_bar.enabled = True
        self.chat_panel.enabled = True
        self.chat_messages_ui.enabled = True
        self.role_text.text = 'ROLE: {}'.format(
            self.my_role.upper() if self.my_role else '?')

    def disable_game_ui(self):
        self.hud_bg.enabled = False
        self.hud_text.enabled = False
        self.role_text.enabled = False
        self.stamina_bar_bg.enabled = False
        self.stamina_bar.enabled = False
        self.chat_panel.enabled = False
        self.chat_messages_ui.enabled = False
        self.close_chat_input(send=False)

    def show_end_screen(self, winner):
        """Show game end screen (entities tracked for later cleanup)."""
        self.disable_game_ui()

        panel = Entity(
            parent=camera.ui, model='quad',
            color=color.rgba(0, 0, 0, 200),
            scale=(0.5, 0.3), position=(0, 0))

        if winner == 'murderer':
            winner_text = 'MURDERER WINS!'
            text_color = color.red
        elif winner in ('innocents', 'time'):
            winner_text = 'INNOCENTS WIN!'
            text_color = color.green
        else:
            winner_text = 'DRAW!'
            text_color = color.white

        label = Text(
            text='GAME OVER\n{}'.format(winner_text),
            parent=camera.ui, position=(0, 0.05), scale=2,
            color=text_color, origin=(0, 0))

        self.end_screen_entities = [panel, label]

    def cleanup_round_entities(self):
        """Destroy round-scoped entities: bullets, m_bucks, end screen."""
        for bullet in self.bullets:
            destroy(bullet)
        self.bullets = []

        for buck in self.m_bucks_entities.values():
            destroy(buck)
        self.m_bucks_entities = {}
        self._buck_request_times = {}

        for entity in self.end_screen_entities:
            destroy(entity)
        self.end_screen_entities = []

    # ------------------------------------------------------------------
    # Networking: one background thread, one persistent event loop
    # ------------------------------------------------------------------

    def attempt_connect(self):
        """Attempt to connect to the server (idempotent)."""
        if self.connected or self._connecting:
            return

        self.username = self.username_input.text or 'Guest'
        server_uri = self.server_input.text or 'ws://localhost:8765'
        self.conn_status.text = 'Connecting to {}...'.format(server_uri)
        print("Connecting to {} as {}...".format(server_uri, self.username))

        self._connecting = True
        self._net_thread = threading.Thread(
            target=self._network_thread_main, args=(server_uri,),
            daemon=True)
        self._net_thread.start()

    def _network_thread_main(self, server_uri):
        """Entry point of the network thread: owns the asyncio loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._net_loop = loop
        try:
            loop.run_until_complete(self._client_session(server_uri))
        finally:
            self._net_loop = None
            loop.close()

    async def _client_session(self, server_uri):
        """Connect, handshake and read messages until disconnected."""
        try:
            websocket = await websockets.connect(server_uri)
        except Exception as e:
            self._connecting = False
            self.incoming.put({'type': '_conn_failed', 'error': str(e)})
            return

        self.websocket = websocket
        self.connected = True
        self._connecting = False
        try:
            await websocket.send(json.dumps({
                'type': 'handshake',
                'username': self.username,
            }))
            async for message in websocket:
                try:
                    self.incoming.put(json.loads(message))
                except ValueError:
                    pass
        except Exception as e:
            print("Connection error: {}".format(e))
        finally:
            self.connected = False
            self.websocket = None
            self.incoming.put({'type': '_disconnected'})

    def send_json(self, payload):
        """Thread-safe send: schedules the coroutine on the network loop."""
        websocket = self.websocket
        loop = self._net_loop
        if not (self.connected and websocket and loop):
            return
        try:
            asyncio.run_coroutine_threadsafe(
                websocket.send(json.dumps(payload)), loop)
        except RuntimeError:
            pass  # Loop already shut down.

    def request_start_game(self):
        self.send_json({'type': 'start_game'})

    def send_move(self, position, rotation, animation):
        self.send_json({
            'type': 'move',
            'position': [position.x, position.y, position.z],
            'rotation': rotation,
            'animation': animation,
        })

    def send_attack(self, target_id=None, attack_type='knife',
                    direction=None):
        self.send_json({
            'type': 'attack',
            'target_id': target_id,
            'attack_type': attack_type,
            'direction': ([direction.x, direction.y, direction.z]
                          if direction else None),
        })

    def send_collect_buck(self, buck_id):
        self.send_json({'type': 'collect_buck', 'buck_id': buck_id})

    def send_chat(self, message):
        self.send_json({'type': 'chat', 'message': message})

    # ------------------------------------------------------------------
    # Server message handling (runs on the MAIN thread, from update())
    # ------------------------------------------------------------------

    def process_network_messages(self):
        """Drain the incoming queue and apply messages on the main thread."""
        while True:
            try:
                data = self.incoming.get_nowait()
            except queue.Empty:
                break
            try:
                self.apply_server_message(data)
            except Exception as e:
                print("Error applying server message {}: {}".format(
                    data.get('type'), e))

    def apply_server_message(self, data):
        msg_type = data.get('type')

        if msg_type == '_conn_failed':
            self.conn_status.text = 'Connection failed: {}'.format(
                data.get('error', ''))[:80]
            self.show_connection_screen()

        elif msg_type == '_disconnected':
            self.on_disconnected()

        elif msg_type == 'connected':
            self.my_player_id = data['player_id']
            print("Connected! My ID: {}".format(self.my_player_id))
            # Spawn characters for everyone who was already connected.
            for player_data in data['all_players']:
                if player_data['player_id'] != self.my_player_id:
                    self.add_remote_player(player_data)
            self.game_state = 'lobby'
            self.show_lobby(data['all_players'])

        elif msg_type == 'player_joined':
            player = data['player']
            self.player_names[player['player_id']] = player['username']
            self.lobby_players.append(player)
            self.add_remote_player(player)
            if self.game_state == 'lobby':
                self.update_lobby_player_list()

        elif msg_type == 'player_left':
            pid = data['player_id']
            name = self.player_names.get(pid, 'Player {}'.format(pid))
            self.remove_remote_player(pid)
            self.lobby_players = [p for p in self.lobby_players
                                  if p['player_id'] != pid]
            if self.game_state == 'lobby':
                self.update_lobby_player_list()
            else:
                self.add_kill_feed('{} left the game'.format(name))

        elif msg_type == 'player_move':
            pid = data['player_id']
            if pid in self.remote_players:
                remote_player = self.remote_players[pid]
                remote_player.set_position(data['position'])
                remote_player.rotation_y = data['rotation']
                if data.get('animation') == 'walk':
                    remote_player.animate_walk()
                else:
                    remote_player.reset_animation()

        elif msg_type == 'game_started':
            self.start_round(data)

        elif msg_type == 'player_killed':
            self.on_player_killed(data)

        elif msg_type == 'bullet_fired':
            self.spawn_bullet_entity(data['bullet'])

        elif msg_type == 'buck_collected':
            buck_id = data['buck_id']
            if buck_id in self.m_bucks_entities:
                destroy(self.m_bucks_entities[buck_id])
                del self.m_bucks_entities[buck_id]
            if data['player_id'] == self.my_player_id:
                self.my_bucks = data['m_bucks']

        elif msg_type == 'timer_update':
            self.round_time = data['time_left']

        elif msg_type == 'game_ended':
            self.game_state = 'ended'
            winner = data['winner']
            print("Game ended! Winner: {}".format(winner))
            self.show_end_screen(winner)

        elif msg_type == 'back_to_lobby':
            self.return_to_lobby(data)

        elif msg_type == 'chat_message':
            self.add_chat_message(data['username'], data['message'])

    def on_disconnected(self):
        """Reset the client to the connection screen."""
        self.connected = False
        self.game_state = 'menu'
        self.my_role = None
        self.cleanup_round_entities()
        for pid in list(self.remote_players.keys()):
            self.remove_remote_player(pid)
        if self.local_player:
            destroy(self.local_player)
            self.local_player = None
        self.lobby_players = []
        self.hide_lobby()
        self.disable_game_ui()
        self.show_connection_screen()
        self.conn_status.text = 'Disconnected from server'

    def start_round(self, data):
        """Apply a game_started message."""
        self.cleanup_round_entities()
        self.game_state = 'playing'
        self.my_role = data['roles'].get(str(self.my_player_id))
        self.round_time = data.get('round_time', ROUND_TIME)
        self.my_bucks = 0

        spawns = data.get('spawns', {})
        my_spawn = spawns.get(str(self.my_player_id), [0, 0, 0])

        # Local player: create or revive, then apply the server spawn point.
        if not self.local_player:
            self.local_player = BlockyCharacter(
                name=self.username,
                player_id=self.my_player_id,
                position=my_spawn,
            )
        else:
            self.local_player.revive()
            self.local_player.set_position(my_spawn)

        self.local_player.role = self.my_role or ''
        self.local_player.has_knife = (self.my_role == 'murderer')
        self.local_player.has_gun = (self.my_role == 'sheriff')
        if self.my_role == 'murderer':
            self.local_player.show_weapon('knife')
        elif self.my_role == 'sheriff':
            self.local_player.show_weapon('gun')

        # Remote players: revive and apply server spawn points.
        for pid_str, spawn in spawns.items():
            pid = int(pid_str)
            if pid == self.my_player_id:
                continue
            char = self.remote_players.get(pid)
            if char:
                char.revive()
                char.set_position(spawn)

        # Spawn M Bucks.
        for buck_data in data.get('m_bucks', []):
            if not buck_data.get('collected'):
                self.spawn_m_buck_entity(buck_data)

        self.enable_game_ui()

    def on_player_killed(self, data):
        """Apply a kill broadcast: update characters and the kill feed."""
        killer_id = data['killer_id']
        victim_id = data['victim_id']
        weapon = data.get('weapon', '?')

        killer_name = self.player_names.get(killer_id,
                                            'Player {}'.format(killer_id))
        victim_name = self.player_names.get(victim_id,
                                            'Player {}'.format(victim_id))

        if victim_id in self.remote_players:
            self.remote_players[victim_id].die()

        if victim_id == self.my_player_id and self.local_player:
            self.local_player.die()
            self.role_text.text = 'YOU DIED - SPECTATING'
            print("You were killed!")

        if data.get('reason') == 'shot_innocent':
            self.add_kill_feed(
                '{} shot an innocent and paid the price'.format(victim_name))
        else:
            self.add_kill_feed(
                '{} [{}] {}'.format(killer_name, weapon, victim_name))

    def return_to_lobby(self, data):
        """Apply a back_to_lobby message: clean up and re-show the lobby."""
        self.game_state = 'lobby'
        self.my_role = None
        self.cleanup_round_entities()

        if self.local_player:
            self.local_player.revive()
        for char in self.remote_players.values():
            char.revive()

        players = data.get('all_players', self.lobby_players)
        self.show_lobby(players)

    # ------------------------------------------------------------------
    # Entity management
    # ------------------------------------------------------------------

    def add_remote_player(self, player_data):
        """Add a remote player character."""
        pid = player_data['player_id']
        if pid in self.remote_players or pid == self.my_player_id:
            return

        self.player_names[pid] = player_data['username']
        char = BlockyCharacter(
            name=player_data['username'],
            player_id=pid,
            position=player_data['position'],
            skin_color=player_data['skin_color'],
            shirt_color=player_data['shirt_color'],
            pants_color=player_data['pants_color'],
            hair_color=player_data['hair_color'],
        )

        if player_data.get('has_knife'):
            char.show_weapon('knife')
        elif player_data.get('has_gun'):
            char.show_weapon('gun')
        if not player_data.get('is_alive', True):
            char.die()

        self.remote_players[pid] = char

    def remove_remote_player(self, player_id):
        """Remove a remote player character (and its name tag)."""
        char = self.remote_players.pop(player_id, None)
        if char:
            # The tag is parented to the character, but destroy it explicitly
            # too so it can never leak.
            if char.name_tag:
                destroy(char.name_tag)
                char.name_tag = None
            destroy(char)

    def spawn_m_buck_entity(self, buck_data):
        """Spawn an M Buck entity."""
        buck_id = buck_data['id']
        if buck_id in self.m_bucks_entities:
            return

        buck = Entity(
            model='sphere',
            color=color.gold,
            scale=(0.3, 0.3, 0.3),
            position=buck_data['position'],
        )
        buck.value = buck_data['value']
        buck.buck_id = buck_id
        buck.animate_y(buck_data['position'][1] + 0.3, duration=1,
                       loop='pingpong')

        self.m_bucks_entities[buck_id] = buck

    def spawn_bullet_entity(self, bullet_data):
        """Spawn a client-side bullet visual."""
        bullet = Entity(
            model='sphere',
            color=color.white,
            scale=(0.15, 0.15, 0.15),
            position=bullet_data['position'],
            collider='box',
        )
        bullet.direction = Vec3(*bullet_data['direction'])
        bullet.speed = bullet_data['speed']
        bullet.lifetime = bullet_data['lifetime']
        bullet.shooter_id = bullet_data['shooter_id']

        self.bullets.append(bullet)

    # ------------------------------------------------------------------
    # Chat / kill feed
    # ------------------------------------------------------------------

    def add_chat_message(self, username, message):
        """Add chat message to the chat panel."""
        self.chat_lines.append('{}: {}'.format(username, message))
        self.chat_lines = self.chat_lines[-8:]
        self.chat_messages_ui.text = '\n'.join(self.chat_lines)

    def add_kill_feed(self, line):
        """Add a line to the kill feed (auto-expires)."""
        self.kill_feed_entries.append((line, time.time() + 6.0))
        self.kill_feed_entries = self.kill_feed_entries[-5:]
        self._refresh_kill_feed()

    def _refresh_kill_feed(self):
        self.kill_feed_text.text = '\n'.join(
            line for line, _ in self.kill_feed_entries)

    def update_kill_feed(self):
        """Expire old kill feed entries."""
        now = time.time()
        fresh = [(line, expiry) for line, expiry in self.kill_feed_entries
                 if expiry > now]
        if len(fresh) != len(self.kill_feed_entries):
            self.kill_feed_entries = fresh
            self._refresh_kill_feed()

    def open_chat_input(self):
        self.chat_input.enabled = True
        self.chat_input.text = ''
        self.chat_input.active = True

    def close_chat_input(self, send=True):
        if not self.chat_input.enabled:
            return
        text = self.chat_input.text.strip()
        if send and text:
            self.send_chat(text)
        self.chat_input.text = ''
        self.chat_input.active = False
        self.chat_input.enabled = False

    @property
    def chat_open(self):
        return self.chat_input.enabled

    # ------------------------------------------------------------------
    # Per-frame logic (driven by the module-level update()/input() hooks)
    # ------------------------------------------------------------------

    def update_camera(self):
        """Update third-person camera to follow the player."""
        if not self.local_player:
            return

        self.camera_pivot.position = lerp(
            self.camera_pivot.position,
            self.local_player.position,
            0.1)

        if held_keys['right mouse'] and self.game_state == 'playing':
            self.camera_pivot.rotation_y += (
                mouse.velocity[0] * self.mouse_sensitivity * 100)
            camera.rotation_x += (
                mouse.velocity[1] * self.mouse_sensitivity * 100)
            camera.rotation_x = clamp(camera.rotation_x, -89, 89)

    def handle_movement(self):
        """Handle held-key movement (taps are handled in input())."""
        if (self.game_state != 'playing' or not self.local_player
                or not self.local_player.is_alive or self.chat_open):
            return

        direction = Vec3(0, 0, 0)
        if held_keys['w']:
            direction += camera.forward
        if held_keys['s']:
            direction -= camera.forward
        if held_keys['a']:
            direction -= camera.right
        if held_keys['d']:
            direction += camera.right

        sprinting = held_keys['shift'] and self.local_player.stamina > 0
        speed = (self.local_player.sprint_speed if sprinting
                 else self.local_player.speed)

        if sprinting and direction != Vec3(0, 0, 0):
            self.local_player.stamina = max(
                0, self.local_player.stamina - 30 * time.dt)
        else:
            self.local_player.stamina = min(
                100, self.local_player.stamina + 18 * time.dt)

        animation = 'idle'
        if direction != Vec3(0, 0, 0):
            direction.y = 0
            direction = direction.normalized()
            new_pos = self.local_player.position + direction * speed * time.dt
            # Keep the player inside the arena.
            new_pos.x = clamp(new_pos.x, -ARENA_HALF_X + 1, ARENA_HALF_X - 1)
            new_pos.z = clamp(new_pos.z, -ARENA_HALF_Z + 1, ARENA_HALF_Z - 1)
            self.local_player.position = new_pos
            animation = 'walk'

            self.local_player.animate_walk(
                speed_factor=1.5 if sprinting else 1)

            target_rotation = math.degrees(
                math.atan2(direction.x, direction.z))
            self.local_player.rotation_y = lerp(
                self.local_player.rotation_y, target_rotation, 0.2)
        else:
            self.local_player.reset_animation()

        # Throttled movement updates (~20 Hz instead of every frame).
        now = time.time()
        if now - self._last_move_sent >= self.MOVE_SEND_INTERVAL:
            self._last_move_sent = now
            self.send_move(self.local_player.position,
                           self.local_player.rotation_y, animation)

        # Auto-collect nearby M Bucks (re-request at most once per second).
        for buck_id, buck in list(self.m_bucks_entities.items()):
            if distance(self.local_player.position, buck.position) < 1.5:
                last = self._buck_request_times.get(buck_id, 0)
                if now - last > 1.0:
                    self._buck_request_times[buck_id] = now
                    self.send_collect_buck(buck_id)
                break

    def try_attack(self):
        """Attempt an attack (tap, with a client-side cooldown)."""
        if (not self.local_player or not self.local_player.is_alive
                or self.game_state != 'playing'):
            return

        now = time.time()
        if self.local_player.has_knife:
            if now - self._last_attack_time < KNIFE_COOLDOWN:
                return
            # Find nearest living player in knife range.
            target_id = None
            best_dist = KNIFE_RANGE
            for pid, player in self.remote_players.items():
                if not player.is_alive:
                    continue
                dist = distance(self.local_player.position, player.position)
                if dist < best_dist:
                    best_dist = dist
                    target_id = pid
            if target_id is None:
                return
            self._last_attack_time = now
            self.send_attack(target_id=target_id, attack_type='knife')

        elif self.local_player.has_gun:
            if now - self._last_attack_time < GUN_COOLDOWN:
                return
            # Shoot horizontally in the camera's facing direction.
            direction = Vec3(camera.forward.x, 0, camera.forward.z)
            if direction.length() < 0.001:
                rad = math.radians(self.local_player.rotation_y)
                direction = Vec3(math.sin(rad), 0, math.cos(rad))
            direction = direction.normalized()
            self._last_attack_time = now
            self.send_attack(attack_type='gun', direction=direction)

    def update_bullets(self):
        """Update client-side bullet visuals."""
        for bullet in self.bullets[:]:
            bullet.position += bullet.direction * bullet.speed * time.dt
            bullet.lifetime -= time.dt

            expired = bullet.lifetime <= 0
            if not expired:
                hit = bullet.intersects()
                if hit.hit and hit.entity in self.walls:
                    expired = True

            if expired:
                self.bullets.remove(bullet)
                destroy(bullet)

    def update_ui(self):
        """Update HUD UI."""
        if not self.local_player:
            return

        alive_count = sum(
            1 for p in self.remote_players.values() if p.is_alive)
        if self.local_player.is_alive:
            alive_count += 1

        self.hud_text.text = (
            '{}  |  Time: {}s  |  Alive: {}  |  Bucks: {}  |  '
            'Shift=Sprint  Space=Attack  Enter=Chat'.format(
                self.my_role.upper() if self.my_role else '?',
                int(self.round_time), alive_count, self.my_bucks))

        stamina_pct = self.local_player.stamina / self.local_player.max_stamina
        self.stamina_bar.scale_x = 0.19 * max(0.001, stamina_pct)
        if stamina_pct > 0.25:
            self.stamina_bar.color = color.rgb(80, 200, 120)
        else:
            self.stamina_bar.color = color.rgb(200, 80, 80)

    def update(self):
        """Main per-frame update (called via the module-level update())."""
        # Network messages are applied here, on the main thread.
        self.process_network_messages()
        self.update_kill_feed()

        if self.game_state == 'playing':
            if self.round_time > 0:
                self.round_time -= time.dt
            self.update_camera()
            self.handle_movement()
            self.update_bullets()
            self.update_ui()

    def input(self, key):
        """Tap input (called via the module-level input())."""
        if key == 'enter':
            if self.chat_open:
                self.close_chat_input(send=True)
            elif self.game_state == 'playing':
                self.open_chat_input()
            return

        if key == 'escape' and self.chat_open:
            self.close_chat_input(send=False)
            return

        if self.chat_open:
            return

        if key == 'space':
            self.try_attack()


# ----------------------------------------------------------------------------
# Module-level ursina hooks: ursina calls __main__.update() / __main__.input()
# each frame, so these trampolines delegate to the running game instance.
# ----------------------------------------------------------------------------

_APP_INSTANCE = None


def update():
    if _APP_INSTANCE:
        _APP_INSTANCE.update()


def input(key):
    if _APP_INSTANCE:
        _APP_INSTANCE.input(key)


def run_server(host='localhost', port=8765):
    """Run the multiplayer server (headless)."""
    server = MultiplayerServer(host=host, port=port)
    asyncio.run(server.run())


def run_client(username='Guest'):
    """Run the 3D multiplayer client."""
    global _APP_INSTANCE
    game = MultiplayerGame3D(username=username)
    _APP_INSTANCE = game
    game.app.run()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--server':
        port = 8765
        if len(sys.argv) > 2:
            try:
                port = int(sys.argv[2])
            except ValueError:
                pass
        print("Starting Multiplayer Server...")
        run_server(port=port)
    else:
        username = sys.argv[1] if len(sys.argv) > 1 else 'Guest'
        print("Starting Multiplayer Client as {}...".format(username))
        run_client(username)

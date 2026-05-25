"""
Roblox-Style Multiplayer Murder Mystery Game
Complete client-server architecture with real-time multiplayer
"""
import asyncio
import json
import websockets
import threading
import random
import math
import time
from datetime import datetime
from collections import defaultdict
from ursina import *
from ursina.shaders import lit_with_shadows_shader


# ============================================================================
# SERVER SIDE - Multiplayer Game Logic
# ============================================================================

class PlayerSession:
    """Represents a connected player session."""
    
    def __init__(self, websocket, player_id, username):
        self.websocket = websocket
        self.player_id = player_id
        self.username = username
        self.position = [0, 0, 0]
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
        self.last_update = time.time()


class MultiplayerServer:
    """Authoritative game server for multiplayer matches."""
    
    def __init__(self, host='localhost', port=8765):
        self.host = host
        self.port = port
        self.players = {}  # player_id -> PlayerSession
        self.next_player_id = 1
        self.game_state = 'lobby'  # lobby, playing, ended
        self.round_time = 180
        self.alive_players = []
        self.murderer_id = None
        self.sheriff_id = None
        self.bullets = []
        self.m_bucks = []
        self.chat_messages = []
        self.lock = threading.Lock()
        
        # Generate M Bucks spawn points
        self.generate_m_bucks()
    
    def generate_m_bucks(self):
        """Generate M Buck spawn locations."""
        zones = [
            {'x': -30, 'y': -20, 'w': 20, 'h': 15},
            {'x': 10, 'y': -25, 'w': 25, 'h': 20},
            {'x': -25, 'y': 10, 'w': 15, 'h': 20},
            {'x': 15, 'y': 15, 'w': 20, 'h': 15},
        ]
        
        for _ in range(30):
            zone = random.choice(zones)
            x = random.uniform(zone['x'], zone['x'] + zone['w'])
            z = random.uniform(zone['y'], zone['y'] + zone['h'])
            value = random.randint(1, 3)
            self.m_bucks.append({
                'id': len(self.m_bucks),
                'position': [x, 0.5, z],
                'value': value,
                'collected': False
            })
    
    async def handle_connection(self, websocket, path):
        """Handle new player connection."""
        player_id = None
        try:
            # Wait for handshake
            handshake = await websocket.recv()
            data = json.loads(handshake)
            
            player_id = self.next_player_id
            self.next_player_id += 1
            
            username = data.get('username', f'Guest_{player_id}')
            
            # Create player session
            with self.lock:
                player = PlayerSession(websocket, player_id, username)
                self.players[player_id] = player
                
                # Send success response
                await websocket.send(json.dumps({
                    'type': 'connected',
                    'player_id': player_id,
                    'username': username,
                    'all_players': self.get_all_players_info()
                }))
                
                # Broadcast new player
                await self.broadcast({
                    'type': 'player_joined',
                    'player': self.get_player_info(player)
                }, exclude=[player_id])
            
            print(f"Player {username} (ID: {player_id}) connected")
            
            # Main message loop
            async for message in websocket:
                await self.handle_message(player_id, message)
                
        except websockets.exceptions.ConnectionClosed:
            print(f"Player {player_id} disconnected")
        finally:
            if player_id:
                await self.remove_player(player_id)
    
    async def handle_message(self, player_id, message):
        """Handle incoming messages from players."""
        try:
            data = json.loads(message)
            msg_type = data.get('type')
            
            with self.lock:
                player = self.players.get(player_id)
                if not player:
                    return
                
                if msg_type == 'move':
                    player.position = data.get('position', player.position)
                    player.rotation = data.get('rotation', player.rotation)
                    player.animation_state = data.get('animation', 'idle')
                    
                    # Broadcast movement
                    await self.broadcast({
                        'type': 'player_move',
                        'player_id': player_id,
                        'position': player.position,
                        'rotation': player.rotation,
                        'animation': player.animation_state
                    }, exclude=[player_id])
                
                elif msg_type == 'attack':
                    await self.handle_attack(player_id, data)
                
                elif msg_type == 'collect_buck':
                    await self.handle_collect_buck(player_id, data)
                
                elif msg_type == 'chat':
                    await self.handle_chat(player_id, data)
                
                elif msg_type == 'start_game':
                    if len(self.players) >= 2:
                        await self.start_game()
                
        except Exception as e:
            print(f"Error handling message: {e}")
    
    async def handle_attack(self, attacker_id, data):
        """Handle attack action."""
        player = self.players.get(attacker_id)
        if not player or not player.is_alive:
            return
        
        target_id = data.get('target_id')
        attack_type = data.get('attack_type')  # 'knife' or 'gun'
        bullet_dir = data.get('direction')
        
        if attack_type == 'knife':
            # Check knife range
            target = self.players.get(target_id)
            if target and target.is_alive:
                dist = math.sqrt(sum((a-b)**2 for a, b in zip(player.position, target.position)))
                if dist < 3.0:  # Knife range
                    if target.role == 'innocent':
                        target.is_alive = False
                        await self.broadcast({
                            'type': 'player_killed',
                            'killer_id': attacker_id,
                            'victim_id': target_id,
                            'weapon': 'knife'
                        })
                        await self.check_win_condition()
        
        elif attack_type == 'gun' and bullet_dir:
            # Create bullet (server authoritative)
            bullet = {
                'id': len(self.bullets),
                'shooter_id': attacker_id,
                'position': player.position.copy(),
                'direction': bullet_dir,
                'speed': 50,
                'lifetime': 2.0
            }
            self.bullets.append(bullet)
            
            # Broadcast bullet
            await self.broadcast({
                'type': 'bullet_fired',
                'bullet': bullet
            })
    
    async def handle_collect_buck(self, player_id, data):
        """Handle M Buck collection."""
        player = self.players.get(player_id)
        if not player or not player.is_alive:
            return
        
        buck_id = data.get('buck_id')
        for buck in self.m_bucks:
            if buck['id'] == buck_id and not buck['collected']:
                dist = math.sqrt(sum((a-b)**2 for a, b in zip(player.position, buck['position'])))
                if dist < 1.5:
                    buck['collected'] = True
                    player.m_bucks += buck['value']
                    
                    await self.broadcast({
                        'type': 'buck_collected',
                        'player_id': player_id,
                        'buck_id': buck_id,
                        'm_bucks': player.m_bucks
                    })
                    break
    
    async def handle_chat(self, player_id, data):
        """Handle chat message."""
        player = self.players.get(player_id)
        if not player:
            return
        
        message = data.get('message', '')[:100]  # Limit length
        
        self.chat_messages.append({
            'player_id': player_id,
            'username': player.username,
            'message': message,
            'timestamp': time.time()
        })
        
        await self.broadcast({
            'type': 'chat_message',
            'player_id': player_id,
            'username': player.username,
            'message': message
        })
    
    async def start_game(self):
        """Start a new game round."""
        if self.game_state == 'playing':
            return
        
        self.game_state = 'playing'
        player_list = list(self.players.values())
        
        # Assign roles
        roles = ['innocent'] * (len(player_list) - 2) + ['murderer', 'sheriff']
        random.shuffle(roles)
        
        murderer_id = None
        sheriff_id = None
        
        for player, role in zip(player_list, roles):
            player.role = role
            player.is_alive = True
            player.has_knife = (role == 'murderer')
            player.has_gun = (role == 'sheriff')
            
            if role == 'murderer':
                murderer_id = player.player_id
            elif role == 'sheriff':
                sheriff_id = player.player_id
        
        self.murderer_id = murderer_id
        self.sheriff_id = sheriff_id
        self.round_time = 180
        
        # Reset M Bucks
        for buck in self.m_bucks:
            buck['collected'] = False
        
        # Broadcast game start
        await self.broadcast({
            'type': 'game_started',
            'roles': {p.player_id: p.role for p in player_list},
            'murderer_id': murderer_id,
            'sheriff_id': sheriff_id,
            'round_time': self.round_time,
            'm_bucks': self.m_bucks
        })
        
        # Start round timer
        asyncio.create_task(self.run_round_timer())
    
    async def run_round_timer(self):
        """Run the round timer."""
        while self.game_state == 'playing' and self.round_time > 0:
            await asyncio.sleep(1)
            self.round_time -= 1
            
            # Broadcast timer update every 5 seconds
            if self.round_time % 5 == 0:
                await self.broadcast({
                    'type': 'timer_update',
                    'time_left': self.round_time
                })
        
        if self.game_state == 'playing':
            await self.end_game('time')
    
    async def check_win_condition(self):
        """Check if someone has won."""
        alive_roles = [p.role for p in self.players.values() if p.is_alive]
        
        if 'murderer' not in alive_roles:
            await self.end_game('innocents')
        elif 'innocent' not in alive_roles and 'sheriff' not in alive_roles:
            await self.end_game('murderer')
    
    async def end_game(self, winner):
        """End the current game round."""
        self.game_state = 'ended'
        
        await self.broadcast({
            'type': 'game_ended',
            'winner': winner,
            'final_stats': {
                pid: {'role': p.role, 'm_bucks': p.m_bucks, 'alive': p.is_alive}
                for pid, p in self.players.items()
            }
        })
        
        # Return to lobby after 5 seconds
        await asyncio.sleep(5)
        self.game_state = 'lobby'
        await self.broadcast({'type': 'back_to_lobby'})
    
    async def remove_player(self, player_id):
        """Remove a player from the game."""
        with self.lock:
            if player_id in self.players:
                del self.players[player_id]
        
        await self.broadcast({
            'type': 'player_left',
            'player_id': player_id
        })
    
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
            'animation_state': player.animation_state
        }
    
    def get_all_players_info(self):
        """Get all players info."""
        return [self.get_player_info(p) for p in self.players.values()]
    
    async def broadcast(self, message, exclude=None):
        """Broadcast message to all players."""
        exclude = exclude or []
        tasks = []
        
        for player in list(self.players.values()):
            if player.player_id not in exclude:
                try:
                    tasks.append(asyncio.create_task(
                        player.websocket.send(json.dumps(message))
                    ))
                except:
                    pass
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def run(self):
        """Run the WebSocket server."""
        server = await websockets.serve(self.handle_connection, self.host, self.port)
        print(f"🎮 Multiplayer server running on ws://{self.host}:{self.port}")
        await server.wait_closed()


# ============================================================================
# CLIENT SIDE - 3D Roblox-Style Game
# ============================================================================

class BlockyCharacter(Entity):
    """Roblox-style R6 blocky character model."""
    
    def __init__(self, name, player_id=0, position=(0,0,0), 
                 skin_color=[255, 204, 153], shirt_color=[30, 140, 200],
                 pants_color=[35, 55, 120], hair_color=[44, 181, 232], **kwargs):
        super().__init__(**kwargs)
        
        self.player_id = player_id
        self.character_name = name
        self.is_alive = True
        self.has_knife = False
        self.has_gun = False
        self.role = ""
        self.speed = 8
        self.sprint_speed = 14
        self.stamina = 100
        self.max_stamina = 100
        self.m_bucks = 0
        self.animation_state = 'idle'
        
        # Scale for R6 proportions
        s = 0.5
        
        # Create body parts as children
        self.torso = Entity(parent=self, model='cube', 
                           color=color.rgb(*shirt_color), 
                           scale=(2*s, 2*s, 1*s), position=(0, 1.5*s, 0))
        
        self.head = Entity(parent=self, model='cube', 
                          color=color.rgb(*skin_color),
                          scale=(1*s, 1*s, 1*s), position=(0, 2.5*s, 0))
        
        # Hair
        self.hair = Entity(parent=self, model='cube', 
                          color=color.rgb(*hair_color),
                          scale=(1.05*s, 0.3*s, 1*s), position=(0, 2.8*s, 0))
        
        # Legs
        self.left_leg = Entity(parent=self, model='cube', 
                              color=color.rgb(*pants_color),
                              scale=(0.7*s, 1.2*s, 0.7*s), position=(-0.5*s, 0.6*s, 0))
        self.right_leg = Entity(parent=self, model='cube', 
                               color=color.rgb(*pants_color),
                               scale=(0.7*s, 1.2*s, 0.7*s), position=(0.5*s, 0.6*s, 0))
        
        # Arms
        self.left_arm = Entity(parent=self, model='cube', 
                              color=color.rgb(*skin_color),
                              scale=(0.6*s, 1.4*s, 0.6*s), position=(-1.3*s, 1.5*s, 0))
        self.right_arm = Entity(parent=self, model='cube', 
                               color=color.rgb(*skin_color),
                               scale=(0.6*s, 1.4*s, 0.6*s), position=(1.3*s, 1.5*s, 0))
        
        # Name tag (billboard)
        self.name_tag = Text(
            text=name,
            parent=camera.ui,
            origin=(0, 0),
            scale=1.5,
            color=color.white
        )
        
        # Weapon indicators
        self.knife_indicator = None
        self.gun_indicator = None
        
        self.set_position(position)
    
    def set_position(self, pos):
        """Set position from list or tuple."""
        if isinstance(pos, list):
            self.position = Vec3(*pos)
        else:
            self.position = Vec3(*pos)
    
    def update_name_tag_position(self):
        """Update name tag to follow the character in 3D space."""
        if not self.is_alive:
            self.name_tag.enabled = False
            return
            
        pos = camera.world_to_camera_point(self.world_position + Vec3(0, 3.5, 0))
        if pos.z > 0:
            self.name_tag.position = Vec2(pos.x / aspect_ratio, pos.y)
            self.name_tag.enabled = True
        else:
            self.name_tag.enabled = False
    
    def show_weapon(self, weapon_type):
        """Show weapon indicator on character."""
        if weapon_type == 'knife':
            if not self.knife_indicator:
                self.knife_indicator = Entity(
                    parent=self.right_arm,
                    model='cube',
                    color=color.gray,
                    scale=(0.1, 0.6, 0.1),
                    position=(0, -0.5, 0.3)
                )
        elif weapon_type == 'gun':
            if not self.gun_indicator:
                self.gun_indicator = Entity(
                    parent=self.right_arm,
                    model='cube',
                    color=color.dark_gray,
                    scale=(0.15, 0.2, 0.3),
                    position=(0, -0.3, 0.4)
                )
    
    def hide_weapons(self):
        """Hide all weapon indicators."""
        if self.knife_indicator:
            self.knife_indicator.enabled = False
        if self.gun_indicator:
            self.gun_indicator.enabled = False
    
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
    """Main 3D multiplayer game client with Roblox-style gameplay."""
    
    def __init__(self, server_uri='ws://localhost:8765'):
        self.server_uri = server_uri
        self.websocket = None
        self.connected = False
        self.my_player_id = None
        self.username = "Guest"
        
        # Game state
        self.remote_players = {}  # player_id -> BlockyCharacter
        self.local_player = None
        self.walls = []
        self.m_bucks_entities = {}
        self.bullets = []
        
        # Round state
        self.round_time = 180
        self.game_state = 'menu'  # menu, lobby, playing, ended
        self.my_role = None
        
        # Setup Ursina app
        self.app = Ursina(title='M Mystery 3D - Multiplayer', 
                         borderless=False, fullscreen=False,
                         use_development_tools=False, 
                         shaders=lit_with_shadows_shader)
        window.color = color.sky
        
        # Camera setup
        self.camera_pivot = Entity()
        self.mouse_sensitivity = 0.15
        
        # Setup scene
        self.setup_scene()
        self.setup_ui()
        self.setup_camera()
        
        # Connection UI
        self.show_connection_screen()
        
        self.app.run()
    
    def setup_scene(self):
        """Setup basic 3D scene."""
        # Sky
        Sky(texture='sky_sunset')
        
        # Lighting
        AmbientLight(color=color.rgba(100, 100, 100, 100))
        self.sun = DirectionalLight(shadows=True, rotation=(45, 45, 45))
        
        # Ground plane (Roblox baseplate style)
        self.ground = Entity(
            model='plane',
            texture='grass',
            scale=(100, 1, 100),
            collider='box',
            color=color.rgba(92, 130, 92, 255)
        )
        
        # Add grid pattern to ground for Roblox feel
        grid_size = 5
        for x in range(-50, 50, grid_size):
            for z in range(-50, 50, grid_size):
                shade = 0.9 if ((x // grid_size) + (z // grid_size)) % 2 == 0 else 1.0
                Entity(
                    model='cube',
                    color=color.rgba(int(92*shade), int(130*shade), int(92*shade), 255),
                    scale=(grid_size, 0.1, grid_size),
                    position=(x, -0.05, z),
                    texture='white_cube'
                )
        
        # Create walls (simple arena)
        wall_positions = [
            (-40, 0, 0, 1, 3, 80),
            (40, 0, 0, 1, 3, 80),
            (0, 0, -30, 80, 3, 1),
            (0, 0, 30, 80, 3, 1),
        ]
        
        for wx, wy, wz, ws, wh, wd in wall_positions:
            w = Entity(
                model='cube',
                color=color.rgba(72, 88, 72, 255),
                scale=(ws, wh, wd),
                position=(wx, wy, wz),
                collider='box',
                texture='brick'
            )
            self.walls.append(w)
        
        # Add some interior walls
        for i in range(5):
            x = random.uniform(-30, 30)
            z = random.uniform(-20, 20)
            w = Entity(
                model='cube',
                color=color.rgba(72, 88, 72, 255),
                scale=(2, 3, 8),
                position=(x, 1.5, z),
                collider='box',
                texture='brick'
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
            parent=camera.ui,
            model='quad',
            color=color.rgba(25, 25, 35, 200),
            scale=(0.8, 0.05),
            position=(0, 0.45)
        )
        self.hud_bg.enabled = False
        
        # HUD text
        self.hud_text = Text(
            text='',
            parent=camera.ui,
            position=(-0.38, 0.43),
            scale=1.2,
            color=color.white
        )
        self.hud_text.enabled = False
        
        # Stamina bar
        self.stamina_bar_bg = Entity(
            parent=camera.ui,
            model='quad',
            color=color.rgba(40, 40, 50, 200),
            scale=(0.2, 0.03),
            position=(0.4, -0.45)
        )
        self.stamina_bar_bg.enabled = False
        
        self.stamina_bar = Entity(
            parent=camera.ui,
            model='quad',
            color=color.rgb(80, 200, 120),
            scale=(0.19, 0.025),
            position=(0.3, -0.45)
        )
        self.stamina_bar.enabled = False
        
        # Role indicator
        self.role_text = Text(
            text='',
            parent=camera.ui,
            position=(-0.38, 0.38),
            scale=1.5,
            color=color.yellow
        )
        self.role_text.enabled = False
        
        # Chat box
        self.chat_panel = Entity(
            parent=camera.ui,
            model='quad',
            color=color.rgba(0, 0, 0, 150),
            scale=(0.5, 0.3),
            position=(-0.35, -0.3),
            visible=False
        )
        
        self.chat_messages_ui = Text(
            text='',
            parent=camera.ui,
            position=(-0.58, -0.15),
            scale=0.8,
            color=color.white,
            origin=(0, 0)
        )
        
        self.chat_input = InputField(
            parent=camera.ui,
            position=(-0.35, -0.45),
            scale=(0.3, 0.05),
            visible=False
        )
        
        # Connection screen
        self.conn_panel = Entity(
            parent=camera.ui,
            model='quad',
            color=color.rgba(0, 0, 0, 200),
            scale=(0.5, 0.4),
            position=(0, 0)
        )
        
        self.conn_title = Text(
            text='M MYSTERY 3D\nMULTIPLAYER',
            parent=camera.ui,
            position=(0, 0.1),
            scale=2,
            color=color.cyan,
            origin=(0, 0)
        )
        
        self.username_input = InputField(
            parent=camera.ui,
            position=(0, 0),
            scale=(0.3, 0.05),
            placeholder='Enter Username'
        )
        
        self.server_input = InputField(
            parent=camera.ui,
            position=(0, -0.1),
            scale=(0.3, 0.05),
            placeholder='ws://localhost:8765',
            text='ws://localhost:8765'
        )
        
        self.connect_button = Button(
            text='CONNECT',
            parent=camera.ui,
            scale=(0.2, 0.08),
            position=(0, -0.2),
            color=color.azure,
            text_color=color.white
        )
        self.connect_button.on_click = self.attempt_connect
        
        # Lobby UI
        self.lobby_panel = Entity(
            parent=camera.ui,
            model='quad',
            color=color.rgba(0, 0, 0, 200),
            scale=(0.5, 0.4),
            position=(0, 0)
        )
        self.lobby_panel.enabled = False
        
        self.lobby_title = Text(
            text='LOBBY',
            parent=camera.ui,
            position=(0, 0.15),
            scale=2.5,
            color=color.green,
            origin=(0, 0)
        )
        self.lobby_title.enabled = False
        
        self.players_list = Text(
            text='',
            parent=camera.ui,
            position=(0, 0),
            scale=1.2,
            color=color.white,
            origin=(0, 0)
        )
        self.players_list.enabled = False
        
        self.start_button = Button(
            text='START GAME',
            parent=camera.ui,
            scale=(0.25, 0.08),
            position=(0, -0.15),
            color=color.green,
            text_color=color.white
        )
        self.start_button.enabled = False
        self.start_button.on_click = self.request_start_game
    
    def show_connection_screen(self):
        """Show connection screen."""
        self.conn_panel.enabled = True
        self.conn_title.enabled = True
        self.username_input.enabled = True
        self.server_input.enabled = True
        self.connect_button.enabled = True
    
    def hide_connection_screen(self):
        """Hide connection screen."""
        self.conn_panel.enabled = False
        self.conn_title.enabled = False
        self.username_input.enabled = False
        self.server_input.enabled = False
        self.connect_button.enabled = False
    
    def show_lobby(self, players):
        """Show lobby with player list."""
        self.hide_connection_screen()
        self.lobby_panel.enabled = True
        self.lobby_title.enabled = True
        self.players_list.enabled = True
        self.start_button.enabled = len(players) >= 2
        
        player_names = [p['username'] for p in players]
        self.players_list.text = '\n'.join(player_names)
    
    def hide_lobby(self):
        """Hide lobby UI."""
        self.lobby_panel.enabled = False
        self.lobby_title.enabled = False
        self.players_list.enabled = False
        self.start_button.enabled = False
    
    def attempt_connect(self):
        """Attempt to connect to server."""
        self.username = self.username_input.text or "Guest"
        server_uri = self.server_input.text or "ws://localhost:8765"
        
        print(f"Connecting to {server_uri} as {self.username}...")
        
        # Start connection in separate thread
        thread = threading.Thread(target=self.run_client, args=(server_uri,))
        thread.daemon = True
        thread.start()
    
    def run_client(self, server_uri):
        """Run WebSocket client in separate thread."""
        import asyncio
        
        async def connect():
            try:
                self.websocket = await websockets.connect(server_uri)
                self.connected = True
                
                # Send handshake
                await self.websocket.send(json.dumps({
                    'type': 'handshake',
                    'username': self.username
                }))
                
                # Listen for messages
                async for message in self.websocket:
                    await self.handle_server_message(message)
                    
            except Exception as e:
                print(f"Connection error: {e}")
                self.connected = False
        
        asyncio.new_event_loop().run_until_complete(connect())
    
    async def handle_server_message(self, message):
        """Handle messages from server."""
        data = json.loads(message)
        msg_type = data.get('type')
        
        if msg_type == 'connected':
            self.my_player_id = data['player_id']
            print(f"Connected! My ID: {self.my_player_id}")
            
            # Create local player
            if self.local_player:
                destroy(self.local_player)
            
            # Show lobby
            invoke(self.show_lobby, data['all_players'], delay=0.1)
        
        elif msg_type == 'player_joined':
            player = data['player']
            self.add_remote_player(player)
            invoke(self.update_lobby_player_list, delay=0.1)
        
        elif msg_type == 'player_left':
            pid = data['player_id']
            self.remove_remote_player(pid)
        
        elif msg_type == 'player_move':
            pid = data['player_id']
            if pid in self.remote_players:
                remote_player = self.remote_players[pid]
                remote_player.set_position(data['position'])
                remote_player.rotation_y = data['rotation']
                if data['animation'] == 'walk':
                    remote_player.animate_walk()
                else:
                    remote_player.reset_animation()
        
        elif msg_type == 'game_started':
            self.game_state = 'playing'
            self.my_role = data['roles'].get(str(self.my_player_id))
            self.round_time = data['round_time']
            
            # Setup roles
            for pid, role in data['roles'].items():
                pid = int(pid)
                if pid == self.my_player_id and self.local_player:
                    self.local_player.role = role
                    self.local_player.has_knife = (role == 'murderer')
                    self.local_player.has_gun = (role == 'sheriff')
                    if role == 'murderer':
                        self.local_player.show_weapon('knife')
                    elif role == 'sheriff':
                        self.local_player.show_weapon('gun')
            
            # Spawn M Bucks
            for buck_data in data['m_bucks']:
                self.spawn_m_buck_entity(buck_data)
            
            # Update UI
            invoke(self.enable_game_ui, delay=0.1)
        
        elif msg_type == 'player_killed':
            killer_id = data['killer_id']
            victim_id = data['victim_id']
            
            if victim_id in self.remote_players:
                self.remote_players[victim_id].is_alive = False
            
            if victim_id == self.my_player_id and self.local_player:
                self.local_player.is_alive = False
                print("You were killed!")
        
        elif msg_type == 'bullet_fired':
            bullet_data = data['bullet']
            self.spawn_bullet_entity(bullet_data)
        
        elif msg_type == 'buck_collected':
            buck_id = data['buck_id']
            if buck_id in self.m_bucks_entities:
                destroy(self.m_bucks_entities[buck_id])
                del self.m_bucks_entities[buck_id]
        
        elif msg_type == 'timer_update':
            self.round_time = data['time_left']
        
        elif msg_type == 'game_ended':
            self.game_state = 'ended'
            winner = data['winner']
            print(f"Game ended! Winner: {winner}")
            invoke(self.show_end_screen, winner, delay=0.5)
        
        elif msg_type == 'back_to_lobby':
            self.game_state = 'lobby'
            invoke(self.show_lobby, [], delay=0.1)
        
        elif msg_type == 'chat_message':
            self.add_chat_message(data['username'], data['message'])
    
    def add_remote_player(self, player_data):
        """Add a remote player character."""
        pid = player_data['player_id']
        if pid in self.remote_players:
            return
        
        char = BlockyCharacter(
            name=player_data['username'],
            player_id=pid,
            position=player_data['position'],
            skin_color=player_data['skin_color'],
            shirt_color=player_data['shirt_color'],
            pants_color=player_data['pants_color'],
            hair_color=player_data['hair_color']
        )
        
        if player_data.get('has_knife'):
            char.show_weapon('knife')
        elif player_data.get('has_gun'):
            char.show_weapon('gun')
        
        self.remote_players[pid] = char
    
    def remove_remote_player(self, player_id):
        """Remove a remote player character."""
        if player_id in self.remote_players:
            destroy(self.remote_players[player_id])
            del self.remote_players[player_id]
    
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
            collider='box'
        )
        buck.value = buck_data['value']
        buck.buck_id = buck_id
        
        # Add floating animation
        buck.animate_y(buck_data['position'][1] + 0.3, duration=1, loop='pingpong')
        
        self.m_bucks_entities[buck_id] = buck
    
    def spawn_bullet_entity(self, bullet_data):
        """Spawn a bullet entity."""
        bullet = Entity(
            model='sphere',
            color=color.white,
            scale=(0.1, 0.1, 0.1),
            position=bullet_data['position'],
            collider='box'
        )
        bullet.direction = Vec3(*bullet_data['direction'])
        bullet.speed = bullet_data['speed']
        bullet.lifetime = bullet_data['lifetime']
        bullet.shooter_id = bullet_data['shooter_id']
        
        self.bullets.append(bullet)
    
    def enable_game_ui(self):
        """Enable game HUD."""
        self.hide_lobby()
        self.hud_bg.enabled = True
        self.hud_text.enabled = True
        self.role_text.enabled = True
        self.stamina_bar_bg.enabled = True
        self.stamina_bar.enabled = True
        self.role_text.text = f'ROLE: {self.my_role.upper() if self.my_role else "?"}'
        
        # Create local player if not exists
        if not self.local_player:
            self.local_player = BlockyCharacter(
                name=self.username,
                player_id=self.my_player_id,
                position=(0, 0, 0)
            )
            if self.my_role == 'murderer':
                self.local_player.has_knife = True
                self.local_player.show_weapon('knife')
            elif self.my_role == 'sheriff':
                self.local_player.has_gun = True
                self.local_player.show_weapon('gun')
    
    def show_end_screen(self, winner):
        """Show game end screen."""
        self.hud_bg.enabled = False
        self.hud_text.enabled = False
        self.role_text.enabled = False
        
        end_panel = Entity(
            parent=camera.ui,
            model='quad',
            color=color.rgba(0, 0, 0, 200),
            scale=(0.5, 0.3),
            position=(0, 0)
        )
        
        winner_text = "INNOCENTS WIN!" if winner == 'innocents' else \
                     "MURDERER WINS!" if winner == 'murderer' else "DRAW!"
        
        Text(
            text=f'GAME OVER\n{winner_text}',
            parent=camera.ui,
            position=(0, 0.05),
            scale=2,
            color=color.green if winner == 'innocents' else color.red,
            origin=(0, 0)
        )
    
    def request_start_game(self):
        """Request to start the game."""
        if self.websocket and self.connected:
            asyncio.new_event_loop().run_until_complete(
                self.websocket.send(json.dumps({'type': 'start_game'}))
            )
    
    def send_move(self, position, rotation, animation):
        """Send movement update to server."""
        if self.websocket and self.connected:
            msg = json.dumps({
                'type': 'move',
                'position': [position.x, position.y, position.z],
                'rotation': rotation,
                'animation': animation
            })
            asyncio.new_event_loop().run_until_complete(
                self.websocket.send(msg)
            )
    
    def send_attack(self, target_id=None, attack_type='knife', direction=None):
        """Send attack action to server."""
        if self.websocket and self.connected:
            msg = json.dumps({
                'type': 'attack',
                'target_id': target_id,
                'attack_type': attack_type,
                'direction': [direction.x, direction.y, direction.z] if direction else None
            })
            asyncio.new_event_loop().run_until_complete(
                self.websocket.send(msg)
            )
    
    def send_collect_buck(self, buck_id):
        """Send M Buck collection to server."""
        if self.websocket and self.connected:
            msg = json.dumps({
                'type': 'collect_buck',
                'buck_id': buck_id
            })
            asyncio.new_event_loop().run_until_complete(
                self.websocket.send(msg)
            )
    
    def send_chat(self, message):
        """Send chat message to server."""
        if self.websocket and self.connected:
            msg = json.dumps({
                'type': 'chat',
                'message': message
            })
            asyncio.new_event_loop().run_until_complete(
                self.websocket.send(msg)
            )
    
    def add_chat_message(self, username, message):
        """Add chat message to UI."""
        # Implementation for chat display
        pass
    
    def update_lobby_player_list(self):
        """Update player list in lobby."""
        pass
    
    def update_camera(self):
        """Update third-person camera to follow player."""
        if not self.local_player:
            return
        
        target_pos = self.local_player.position
        self.camera_pivot.position = lerp(
            self.camera_pivot.position,
            target_pos,
            0.1
        )
        
        # Mouse look rotation
        if held_keys['right mouse'] and self.game_state == 'playing':
            self.camera_pivot.rotation_y += mouse.velocity[0] * self.mouse_sensitivity * 100
            camera.rotation_x += mouse.velocity[1] * self.mouse_sensitivity * 100
            camera.rotation_x = clamp(camera.rotation_x, -89, 89)
    
    def handle_input(self):
        """Handle player input."""
        if self.game_state != 'playing' or not self.local_player or not self.local_player.is_alive:
            return
        
        # Movement
        direction = Vec3(0, 0, 0)
        
        if held_keys['w']:
            direction += camera.forward
        if held_keys['s']:
            direction -= camera.forward
        if held_keys['a']:
            direction -= camera.right
        if held_keys['d']:
            direction += camera.right
        
        # Sprint
        sprinting = held_keys['shift']
        speed = self.local_player.sprint_speed if sprinting else self.local_player.speed
        
        # Update stamina
        if sprinting and direction != Vec3(0, 0, 0):
            self.local_player.stamina = max(0, self.local_player.stamina - 0.5)
        else:
            self.local_player.stamina = min(100, self.local_player.stamina + 0.3)
        
        # Move player
        animation = 'idle'
        if direction != Vec3(0, 0, 0):
            direction.y = 0
            direction = direction.normalized()
            self.local_player.position += direction * speed * time.dt
            animation = 'walk'
            
            if sprinting and self.local_player.stamina > 0:
                self.local_player.animate_walk(speed_factor=1.5)
            else:
                self.local_player.animate_walk()
            
            # Rotate player to face movement direction
            target_rotation = math.degrees(math.atan2(direction.x, direction.z))
            self.local_player.rotation_y = lerp(self.local_player.rotation_y, target_rotation, 0.2)
        else:
            self.local_player.reset_animation()
        
        # Send movement to server
        self.send_move(self.local_player.position, self.local_player.rotation_y, animation)
        
        # Attack
        if held_keys['space']:
            if self.local_player.has_knife:
                # Find nearby players for knife attack
                target_id = None
                for pid, player in self.remote_players.items():
                    if player.is_alive:
                        dist = distance(self.local_player.position, player.position)
                        if dist < 3:
                            target_id = pid
                            break
                
                self.send_attack(target_id=target_id, attack_type='knife')
            
            elif self.local_player.has_gun:
                # Shoot bullet
                self.send_attack(attack_type='gun', direction=camera.forward)
        
        # Collect M Bucks
        for buck_id, buck in list(self.m_bucks_entities.items()):
            if distance(self.local_player.position, buck.position) < 1.5:
                self.send_collect_buck(buck_id)
                break
        
        # Chat (Enter key)
        if held_keys['enter']:
            # Toggle chat input
            pass
    
    def update_bullets(self):
        """Update bullet positions."""
        for bullet in self.bullets[:]:
            bullet.position += bullet.direction * bullet.speed * time.dt
            bullet.lifetime -= time.dt
            
            # Check wall collision
            for wall in self.walls:
                if intersects(bullet, wall).hit:
                    self.bullets.remove(bullet)
                    destroy(bullet)
                    break
            else:
                # Remove old bullets
                if bullet.lifetime <= 0 and bullet in self.bullets:
                    self.bullets.remove(bullet)
                    destroy(bullet)
    
    def update_ui(self):
        """Update HUD UI."""
        if not self.local_player:
            return
        
        alive_count = sum(1 for p in self.remote_players.values() if p.is_alive)
        if self.local_player.is_alive:
            alive_count += 1
        
        self.hud_text.text = (
            f'{self.my_role.upper() if self.my_role else "?"}  |  '
            f'Time: {int(self.round_time)}s  |  '
            f'Alive: {alive_count}  |  '
            f'Shift=Sprint  Space=Attack'
        )
        
        # Update stamina bar
        stamina_pct = self.local_player.stamina / self.local_player.max_stamina
        self.stamina_bar.scale_x = 0.19 * stamina_pct
        self.stamina_bar.color = color.rgb(
            int(80 if stamina_pct > 0.25 else 200),
            int(200 if stamina_pct > 0.25 else 80),
            int(120 if stamina_pct > 0.25 else 80)
        )
    
    def update(self):
        """Main update loop."""
        if self.game_state == 'playing':
            # Update round timer
            if self.round_time > 0:
                self.round_time -= time.dt
            
            # Update camera
            self.update_camera()
            
            # Handle input
            self.handle_input()
            
            # Update bullets
            self.update_bullets()
            
            # Update name tags
            if self.local_player:
                self.local_player.update_name_tag_position()
            for player in self.remote_players.values():
                player.update_name_tag_position()
            
            # Update UI
            self.update_ui()


def run_server():
    """Run the multiplayer server."""
    import asyncio
    server = MultiplayerServer()
    asyncio.run(server.run())


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--server':
        # Run as server
        print("🎮 Starting Multiplayer Server...")
        run_server()
    else:
        # Run as client
        print("🎮 Starting Multiplayer Client...")
        print("Make sure the server is running first!")
        game = MultiplayerGame3D()

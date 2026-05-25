"""
3D Roblox-style version of M Mystery
Uses Ursina engine for 3D rendering with blocky R6-style characters
"""
import json
import os
import random
import math
from ursina import *
from ursina.shaders import lit_with_shadows_shader
from datetime import datetime


class BlockyCharacter(Entity):
    """Roblox-style R6 blocky character model."""
    
    def __init__(self, name, position=(0,0,0), body_color=color.blue, 
                 shirt_color=color.azure, pants_color=color.blue,
                 skin_color=color.peach, **kwargs):
        super().__init__(**kwargs)
        
        self.character_name = name
        self.is_alive = True
        self.has_knife = False
        self.has_gun = False
        self.role = ""
        self.speed = 8
        self.sprint_speed = 14
        self.stamina = 100
        self.max_stamina = 100
        
        # Parent entity for the whole character
        self.model = None
        self.position = position
        
        # Scale for R6 proportions
        s = 0.5
        
        # Create body parts as children
        self.torso = Entity(parent=self, model='cube', color=shirt_color, 
                           scale=(2*s, 2*s, 1*s), position=(0, 1.5*s, 0))
        
        self.head = Entity(parent=self, model='cube', color=skin_color,
                          scale=(1*s, 1*s, 1*s), position=(0, 2.5*s, 0))
        
        # Hair
        self.hair = Entity(parent=self, model='cube', color=body_color,
                          scale=(1.05*s, 0.3*s, 1*s), position=(0, 2.8*s, 0))
        
        # Legs
        self.left_leg = Entity(parent=self, model='cube', color=pants_color,
                              scale=(0.7*s, 1.2*s, 0.7*s), position=(-0.5*s, 0.6*s, 0))
        self.right_leg = Entity(parent=self, model='cube', color=pants_color,
                               scale=(0.7*s, 1.2*s, 0.7*s), position=(0.5*s, 0.6*s, 0))
        
        # Arms
        self.left_arm = Entity(parent=self, model='cube', color=skin_color,
                              scale=(0.6*s, 1.4*s, 0.6*s), position=(-1.3*s, 1.5*s, 0))
        self.right_arm = Entity(parent=self, model='cube', color=skin_color,
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
        
    def update_name_tag_position(self):
        """Update name tag to follow the character in 3D space."""
        if not self.is_alive:
            self.name_tag.enabled = False
            return
            
        # Project 3D position to screen space
        pos = camera.world_to_camera_point(self.world_position + Vec3(0, 3.5, 0))
        if pos.z > 0:  # Only show if in front of camera
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


class Game3D:
    """Main 3D game class with Roblox-style gameplay."""
    
    def __init__(self):
        self.app = Ursina(title='M Mystery 3D', borderless=False, fullscreen=False,
                         use_development_tools=False, shaders=lit_with_shadows_shader)
        window.color = color.sky
        
        # Game state
        self.players = []
        self.human_player = None
        self.camera_pivot = Entity()
        self.walls = []
        self.bucks = []
        self.dropped_gun = None
        self.bullets = []
        self.noise_traps = []
        
        # Round state
        self.round_time = 180
        self.round_active = False
        self.alive_count = 0
        
        # Setup
        self.setup_scene()
        self.load_map('data/maps/map_01.json')
        self.create_players()
        self.setup_camera()
        self.setup_ui()
        
        # Start menu state
        self.game_state = 'menu'
        self.show_menu()
        
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
    
    def load_map(self, map_path):
        """Load map from JSON file."""
        with open(map_path, 'r') as f:
            map_data = json.load(f)
        
        self.map_width = map_data.get('width', 800) / 10  # Scale down for 3D
        self.map_height = map_data.get('height', 600) / 10
        self.spawn_points = map_data['spawn_points']
        
        # Create walls
        for wall in map_data['walls']:
            w = Entity(
                model='cube',
                color=color.rgba(72, 88, 72, 255),
                scale=(wall['w']/10, 3, wall['h']/10),
                position=(
                    (wall['x'] + wall['w']/2)/10 - 40,
                    1.5,
                    (wall['y'] + wall['h']/2)/10 - 30
                ),
                collider='box',
                texture='brick'
            )
            self.walls.append(w)
        
        # Spawn M Bucks
        self.spawn_bucks(map_data['buck_spawn_zones'])
    
    def spawn_bucks(self, zones):
        """Spawn collectible M Bucks."""
        for _ in range(20):
            zone = random.choice(zones)
            x = random.randint(zone['x'], zone['x'] + zone['w']) / 10 - 40
            z = random.randint(zone['y'], zone['y'] + zone['h']) / 10 - 30
            value = random.randint(1, 3)
            
            buck = Entity(
                model='sphere',
                color=color.gold,
                scale=(0.3, 0.3, 0.3),
                position=(x, 0.5, z),
                collider='box'
            )
            buck.value = value
            self.bucks.append(buck)
            
            # Add floating animation
            buck.animate_y(0.8, duration=1, loop='pingpong')
    
    def create_players(self):
        """Create player characters."""
        # Human player
        self.human_player = BlockyCharacter(
            name='Guest_You',
            position=(0, 0, 0),
            body_color=color.rgb(44, 181, 232),
            shirt_color=color.rgb(30, 140, 200),
            pants_color=color.rgb(35, 55, 120),
            skin_color=color.rgb(255, 204, 153)
        )
        self.players.append(self.human_player)
        
        # Bot players
        bot_configs = [
            ('bot_1', 'xXShadowBladeXx', color.rgb(229, 80, 120), color.rgb(200, 50, 90)),
            ('bot_2', 'CoolSheriff_Jake', color.rgb(244, 197, 66), color.rgb(220, 170, 40)),
            ('bot_3', 'NoobSurvivor42', color.rgb(100, 200, 255), color.rgb(70, 160, 230)),
        ]
        
        for i, (bid, name, accent, shirt) in enumerate(bot_configs):
            bot = BlockyCharacter(
                name=name,
                position=(0, 0, 0),
                body_color=accent,
                shirt_color=shirt,
                pants_color=color.rgb(60, 60, 90),
                skin_color=color.rgb(255, 204, 153)
            )
            self.players.append(bot)
    
    def setup_camera(self):
        """Setup third-person camera like Roblox."""
        self.camera_pivot.position = (0, 10, 0)
        camera.parent = self.camera_pivot
        camera.position = (0, 5, -10)
        camera.look_at(self.camera_pivot)
        
        # Mouse look
        self.mouse_sensitivity = 0.15
    
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
        
        # HUD text
        self.hud_text = Text(
            text='',
            parent=camera.ui,
            position=(-0.38, 0.43),
            scale=1.2,
            color=color.white
        )
        
        # Stamina bar
        self.stamina_bar_bg = Entity(
            parent=camera.ui,
            model='quad',
            color=color.rgba(40, 40, 50, 200),
            scale=(0.2, 0.03),
            position=(0.4, -0.45)
        )
        
        self.stamina_bar = Entity(
            parent=camera.ui,
            model='quad',
            color=color.rgb(80, 200, 120),
            scale=(0.19, 0.025),
            position=(0.3, -0.45)
        )
        
        # Role indicator
        self.role_text = Text(
            text='',
            parent=camera.ui,
            position=(-0.38, 0.38),
            scale=1.5,
            color=color.yellow
        )
        
        # Menu UI
        self.menu_panel = Entity(
            parent=camera.ui,
            model='quad',
            color=color.rgba(0, 0, 0, 200),
            scale=(0.6, 0.5),
            position=(0, 0)
        )
        self.menu_panel.enabled = False
        
        self.menu_title = Text(
            text='M MYSTERY 3D',
            parent=camera.ui,
            position=(0, 0.1),
            scale=3,
            color=color.cyan,
            origin=(0, 0)
        )
        self.menu_title.enabled = False
        
        self.play_button = Button(
            text='PLAY',
            parent=camera.ui,
            scale=(0.2, 0.08),
            position=(0, -0.1),
            color=color.azure,
            text_color=color.white
        )
        self.play_button.enabled = False
        self.play_button.on_click = self.start_game
    
    def show_menu(self):
        """Show main menu."""
        self.menu_panel.enabled = True
        self.menu_title.enabled = True
        self.play_button.enabled = True
        self.hud_bg.enabled = False
        self.hud_text.enabled = False
        self.role_text.enabled = False
        
        # Disable player controls
        self.human_player.disable()
    
    def hide_menu(self):
        """Hide main menu."""
        self.menu_panel.enabled = False
        self.menu_title.enabled = False
        self.play_button.enabled = False
        self.hud_bg.enabled = True
        self.hud_text.enabled = True
        self.role_text.enabled = True
    
    def start_game(self):
        """Start the game round."""
        self.hide_menu()
        self.reset_round()
        self.game_state = 'playing'
        self.human_player.enable()
    
    def reset_round(self):
        """Reset round state."""
        # Reset player positions
        for i, player in enumerate(self.players):
            spawn = self.spawn_points[i % len(self.spawn_points)]
            player.position = (
                spawn['x']/10 - 40,
                0,
                spawn['y']/10 - 30
            )
            player.is_alive = True
            player.has_knife = False
            player.has_gun = False
            player.reset_animation()
        
        # Assign roles (simple random assignment)
        roles = ['innocent'] * (len(self.players) - 2) + ['murderer', 'sheriff']
        random.shuffle(roles)
        for player, role in zip(self.players, roles):
            player.role = role
            if role == 'murderer':
                player.has_knife = True
                player.show_weapon('knife')
            elif role == 'sheriff':
                player.has_gun = True
                player.show_weapon('gun')
        
        # Show human player their role
        self.role_text.text = f'ROLE: {self.human_player.role.upper()}'
        
        # Reset round timer
        self.round_time = 180
        self.round_active = True
    
    def update_camera(self):
        """Update third-person camera to follow player."""
        if not self.human_player:
            return
        
        # Smooth camera follow
        target_pos = self.human_player.position
        self.camera_pivot.position = lerp(
            self.camera_pivot.position,
            target_pos,
            0.1
        )
        
        # Mouse look rotation
        if held_keys['right mouse']:
            self.camera_pivot.rotation_y += mouse.velocity[0] * self.mouse_sensitivity * 100
            camera.rotation_x += mouse.velocity[1] * self.mouse_sensitivity * 100
            camera.rotation_x = clamp(camera.rotation_x, -89, 89)
    
    def handle_input(self):
        """Handle player input."""
        if self.game_state != 'playing' or not self.human_player.is_alive:
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
        speed = self.human_player.sprint_speed if sprinting else self.human_player.speed
        
        # Update stamina
        if sprinting and direction != Vec3(0, 0, 0):
            self.human_player.stamina = max(0, self.human_player.stamina - 0.5)
        else:
            self.human_player.stamina = min(100, self.human_player.stamina + 0.3)
        
        # Move player
        if direction != Vec3(0, 0, 0):
            direction.y = 0
            direction = direction.normalized()
            self.human_player.position += direction * speed * time.dt
            self.human_player.animate_walk(speed_factor=sprinting and self.human_player.stamina > 0)
            
            # Rotate player to face movement direction
            target_rotation = math.degrees(math.atan2(direction.x, direction.z))
            self.human_player.rotation_y = lerp(self.human_player.rotation_y, target_rotation, 0.2)
        else:
            self.human_player.reset_animation()
        
        # Attack
        if held_keys['space']:
            self.perform_attack()
        
        # Shop (E key)
        if held_keys['e']:
            print("Shop system - to be implemented")
    
    def perform_attack(self):
        """Perform attack based on equipped weapon."""
        if not self.human_player.has_knife and not self.human_player.has_gun:
            return
        
        if self.human_player.has_knife:
            # Knife attack - check nearby players
            for player in self.players:
                if player != self.human_player and player.is_alive:
                    dist = distance(self.human_player.position, player.position)
                    if dist < 3:  # Knife range
                        if player.role == 'innocent':
                            player.is_alive = False
                            print(f'{player.character_name} was killed!')
        
        elif self.human_player.has_gun:
            # Shoot bullet
            bullet = Entity(
                model='sphere',
                color=color.white,
                scale=(0.1, 0.1, 0.1),
                position=self.human_player.position + Vec3(0, 1.5, 0),
                collider='box'
            )
            bullet.direction = camera.forward
            bullet.speed = 50
            bullet.lifetime = 2
            self.bullets.append(bullet)
    
    def update_bullets(self):
        """Update bullet positions and check collisions."""
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
                # Check player collision
                for player in self.players:
                    if player.is_alive and player.role == 'murderer':
                        if distance(bullet.position, player.position) < 1:
                            player.is_alive = False
                            print(f'{player.character_name} (Murderer) was shot!')
                            self.bullets.remove(bullet)
                            destroy(bullet)
                            break
                
                # Remove old bullets
                if bullet.lifetime <= 0 and bullet in self.bullets:
                    self.bullets.remove(bullet)
                    destroy(bullet)
    
    def check_buck_collection(self):
        """Check if player collects M Bucks."""
        for buck in self.bucks[:]:
            if distance(self.human_player.position, buck.position) < 1:
                print(f'Collected {buck.value} M Bucks!')
                self.bucks.remove(buck)
                destroy(buck)
    
    def update_ui(self):
        """Update HUD UI."""
        alive_count = sum(1 for p in self.players if p.is_alive)
        self.hud_text.text = (
            f'{self.human_player.role.upper() if self.human_player.role else "?"}  |  '
            f'Time: {int(self.round_time)}s  |  '
            f'Alive: {alive_count}  |  '
            f'Shift=Sprint  Space=Attack'
        )
        
        # Update stamina bar
        stamina_pct = self.human_player.stamina / self.human_player.max_stamina
        self.stamina_bar.scale_x = 0.19 * stamina_pct
        self.stamina_bar.color = color.rgb(
            int(80 if stamina_pct > 0.25 else 200),
            int(200 if stamina_pct > 0.25 else 80),
            int(120 if stamina_pct > 0.25 else 80)
        )
    
    def update(self):
        """Main update loop."""
        if self.game_state == 'playing' and self.round_active:
            # Update round timer
            self.round_time -= time.dt
            if self.round_time <= 0:
                self.round_active = False
                print('Round ended!')
            
            # Update camera
            self.update_camera()
            
            # Handle input
            self.handle_input()
            
            # Update bullets
            self.update_bullets()
            
            # Check buck collection
            self.check_buck_collection()
            
            # Update name tags
            for player in self.players:
                player.update_name_tag_position()
            
            # Update UI
            self.update_ui()
            
            # Check win conditions
            alive_roles = [p.role for p in self.players if p.is_alive]
            if 'murderer' not in alive_roles:
                print('Innocents win!')
                self.round_active = False
            elif alive_roles.count('innocent') == 0 and 'sheriff' not in alive_roles:
                print('Murderer wins!')
                self.round_active = False


if __name__ == '__main__':
    game = Game3D()

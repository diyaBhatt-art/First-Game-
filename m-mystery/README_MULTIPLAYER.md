# 🎮 M Mystery 3D - Roblox-Style Multiplayer Murder Mystery

A fully working **Roblox-style 3D multiplayer** murder mystery game built with Python and Ursina engine!

## ✨ Features

### 🎯 Core Gameplay (Just Like Roblox!)
- **Blocky R6-style characters** - Authentic Roblox avatar appearance with customizable colors
- **Third-person camera** - Smooth mouse-look controls exactly like Roblox
- **Stud-patterned ground** - Classic Roblox baseplate aesthetic
- **Real-time multiplayer** - Play with friends online!
- **Role-based gameplay** - Murderer, Sheriff, and Innocents
- **M Bucks collection** - Collect currency scattered around the map
- **Combat system** - Knife attacks (Murderer) and gun shooting (Sheriff)
- **Win conditions** - Complete game logic with victory screens

### 🌐 Multiplayer Architecture
- **Client-Server model** - Authoritative server prevents cheating
- **WebSocket communication** - Real-time player synchronization
- **Lobby system** - Join lobby, wait for players, start game
- **Player movement sync** - Smooth animation and position updates
- **Chat system** - In-game text chat
- **Round management** - Automatic round timer and win detection

## 🚀 How to Run

### Prerequisites
```bash
pip install ursina websockets
```

### Step 1: Start the Server (Host)
```bash
python main_multiplayer.py --server
```

The server will start on `ws://localhost:8765` by default.

### Step 2: Connect Clients (Players)
Open additional terminal windows and run:
```bash
python main_multiplayer.py
```

Each client can:
1. Enter a username
2. Connect to the server (default: `ws://localhost:8765`)
3. Wait in the lobby until 2+ players are connected
4. Click "START GAME" to begin

## 🎮 Controls

| Key/Action | Description |
|------------|-------------|
| **WASD** | Move character |
| **Shift** | Sprint (uses stamina) |
| **Space** | Attack (knife/gun) |
| **Right Mouse Hold** | Look around (camera) |
| **Enter** | Chat (coming soon) |

## 🎭 Roles

### 🔪 Murderer
- Goal: Eliminate all innocents and the sheriff
- Weapon: Knife (melee attack)
- Wins when: Only murderer remains alive

### 🔫 Sheriff
- Goal: Protect innocents and eliminate the murderer
- Weapon: Gun (ranged attack)
- Wins when: Murderer is eliminated

### 😊 Innocent
- Goal: Survive and help find the murderer
- Weapon: None (must rely on sheriff)
- Wins when: Murderer is eliminated

## 🏗️ Technical Details

### Server (`MultiplayerServer` class)
- Handles player connections/disconnections
- Manages game state (lobby, playing, ended)
- Validates all player actions (anti-cheat)
- Broadcasts state updates to all clients
- Runs round timer and checks win conditions

### Client (`MultiplayerGame3D` class)
- Renders 3D graphics using Ursina engine
- Captures player input (movement, attacks)
- Sends actions to server for validation
- Receives and displays other players' positions
- Shows HUD with role, timer, alive count, stamina

### Character Model (`BlockyCharacter` class)
- R6-style blocky body parts (torso, head, arms, legs)
- Customizable colors (skin, shirt, pants, hair)
- Walking animations
- Weapon indicators (knife/gun)
- Billboard name tags

## 📁 Files

- `main_multiplayer.py` - Complete multiplayer game (server + client)
- `main_3d.py` - Single-player 3D version
- `requirements.txt` - Python dependencies

## 🎨 Visual Style

The game features authentic Roblox aesthetics:
- ✅ Blocky character models (R6 rig style)
- ✅ Stud-patterned baseplate ground
- ✅ Bright, colorful environment
- ✅ Third-person over-the-shoulder camera
- ✅ Floating collectibles with bobbing animation
- ✅ Clean HUD UI with role indicators

## 🔧 Customization

You can easily modify:
- Character colors in `BlockyCharacter.__init__()`
- Map layout in `setup_scene()`
- Game balance (speed, stamina, timer) in class attributes
- M Buck spawn locations in `generate_m_bucks()`

## 🐛 Troubleshooting

**Connection Issues:**
- Make sure server is running before connecting clients
- Check firewall settings for port 8765
- Use `ws://YOUR_IP:8765` for LAN play

**Performance:**
- Lower graphics quality in Ursina settings if needed
- Reduce number of players for better performance

**Audio Warnings:**
- Audio device warnings in headless environments are normal
- Game will still work without audio

---

**Enjoy your Roblox-style Murder Mystery game! 🎉**

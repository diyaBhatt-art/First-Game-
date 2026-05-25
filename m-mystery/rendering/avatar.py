"""
Roblox-inspired blocky avatar renderer (R6-style proportions).
"""
import math
import pygame

from core.player import PLAYER_SIZE


def _shade(rgb, delta):
    return tuple(max(0, min(255, c + delta)) for c in rgb)


def draw_avatar(screen, player, ox=0, oy=0, show_name=True, alpha=255):
    """
    Draw a blocky character at the player's position.

    Uses player.body_color, player.shirt_color, player.pants_color,
    and player.facing (dx, dy) unit vector.
    """
    cx = int(player.x) + ox
    cy = int(player.y) + oy

    body = player.body_color
    shirt = player.shirt_color
    pants = player.pants_color
    skin = player.skin_color

    fx, fy = player.facing
    if fx == 0 and fy == 0:
        fx, fy = 0, -1

    # Scale to fit collision radius (~10px circle → ~22px tall avatar)
    s = 1.1
    head = int(7 * s)
    torso_w, torso_h = int(10 * s), int(9 * s)
    leg_w, leg_h = int(4 * s), int(6 * s)
    arm_w, arm_h = int(3 * s), int(7 * s)

    def rect_surf(w, h, color, a=alpha):
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        c = (*color, a) if len(color) == 3 else color
        pygame.draw.rect(surf, c, (0, 0, w, h), border_radius=2)
        return surf

    # Shadow on ground
    shadow = pygame.Surface((18, 6), pygame.SRCALPHA)
    pygame.draw.ellipse(shadow, (0, 0, 0, min(80, alpha)), (0, 0, 18, 6))
    screen.blit(shadow, (cx - 9, cy + 8))

    base_y = cy + 6

    # Legs (pants)
    leg_offset = 3
    for side in (-1, 1):
        lx = cx + side * leg_offset - leg_w // 2
        ly = base_y - leg_h
        screen.blit(rect_surf(leg_w, leg_h, pants, alpha), (lx, ly))

    # Torso (shirt)
    tw, th = torso_w, torso_h
    tx = cx - tw // 2
    ty = base_y - leg_h - th
    screen.blit(rect_surf(tw, th, shirt, alpha), (tx, ty))

    # Arms — swing slightly with movement
    swing = int(math.sin(player.anim_phase) * 2) if getattr(player, "is_moving", False) else 0
    for side in (-1, 1):
        ax = cx + side * (torso_w // 2 + 1) - arm_w // 2
        ay = ty + 2 + swing * side
        screen.blit(rect_surf(arm_w, arm_h, _shade(skin, -15), alpha), (ax, ay))

    # Head (skin + hair cap)
    hx = cx - head // 2
    hy = ty - head - 1
    screen.blit(rect_surf(head, head, skin, alpha), (hx, hy))
    hair_h = max(3, head // 3)
    screen.blit(rect_surf(head, hair_h, body, alpha), (hx, hy))

    # Simple face toward movement
    eye_y = hy + head // 2 - 1
    ex_off = 2 if fx >= 0 else -2
    if alpha > 100:
        pygame.draw.circle(screen, (30, 30, 40), (cx + ex_off - 2, eye_y), 1)
        pygame.draw.circle(screen, (30, 30, 40), (cx + ex_off + 2, eye_y), 1)

    # Role gear indicators
    if player.is_alive:
        if player.has_knife and alpha > 150:
            # Knife glint near right hand
            pygame.draw.polygon(
                screen,
                (200, 200, 210),
                [(cx + 12, ty + 8), (cx + 16, ty + 4), (cx + 14, ty + 12)],
            )
        if player.has_gun and alpha > 150:
            pygame.draw.rect(screen, (60, 60, 70), (cx + 10, ty + 6, 6, 3), border_radius=1)

    # Username billboards (Roblox-style)
    if show_name:
        font = pygame.font.Font(None, 18)
        label = player.name
        if getattr(player, "is_bot", False):
            label = player.name  # keep display names; no [BOT] in-world
        surf = font.render(label, True, (255, 255, 255))
        bg = pygame.Surface((surf.get_width() + 8, surf.get_height() + 4), pygame.SRCALPHA)
        bg.fill((0, 0, 0, min(140, alpha)))
        screen.blit(bg, (cx - bg.get_width() // 2, hy - 18))
        screen.blit(surf, (cx - surf.get_width() // 2, hy - 16))


def draw_avatar_preview(screen, rect, player, scale=2.0):
    """Draw a static avatar inside a UI rect (lobby cards)."""
    cx, cy = rect.centerx, rect.centery + int(8 * scale)
    saved_x, saved_y = player.x, player.y
    player.x, player.y = cx, cy
    old_phase = getattr(player, "anim_phase", 0)
    player.anim_phase = 0.5
    player.facing = (0, -1)
    draw_avatar(screen, player, show_name=False, alpha=255)
    player.x, player.y = saved_x, saved_y
    player.anim_phase = old_phase

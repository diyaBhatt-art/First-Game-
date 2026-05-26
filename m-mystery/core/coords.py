"""2D pixel map space ↔ 3D world units (Y is up)."""

PIXEL_SCALE = 1 / 15


def pixel_to_world(px, py, height=0.5):
    return (px * PIXEL_SCALE, height, py * PIXEL_SCALE)


def world_to_pixel(wx, wz):
    return wx / PIXEL_SCALE, wz / PIXEL_SCALE

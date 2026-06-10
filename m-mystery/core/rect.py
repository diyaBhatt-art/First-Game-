"""Minimal pure-Python axis-aligned rectangle and line-of-sight helpers.

Keeps core/ free of engine imports (pygame/ursina).  ``Rect`` covers the
subset of the pygame.Rect API the simulation uses, and its collision
methods accept any rect-like object exposing ``x``, ``y``, ``w``, ``h``
attributes — including a real pygame.Rect, so the 2D frontend can keep
passing pygame rect walls into core code.  ``Rect`` also iterates as
``(x, y, w, h)`` so it can be handed back to pygame APIs if needed.
"""
import math


def _unpack(other):
    """Return (x, y, w, h) from a Rect, pygame.Rect, or 4-sequence."""
    try:
        return other.x, other.y, other.w, other.h
    except AttributeError:
        x, y, w, h = other
        return x, y, w, h


class Rect:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x, y, w, h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    # -- pygame-style accessors -------------------------------------
    @property
    def width(self):
        return self.w

    @property
    def height(self):
        return self.h

    @property
    def left(self):
        return self.x

    @property
    def top(self):
        return self.y

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    @property
    def centerx(self):
        return self.x + self.w / 2

    @property
    def centery(self):
        return self.y + self.h / 2

    @property
    def center(self):
        return (self.centerx, self.centery)

    # -- collision ---------------------------------------------------
    def colliderect(self, other):
        ox, oy, ow, oh = _unpack(other)
        return (
            self.x < ox + ow
            and ox < self.x + self.w
            and self.y < oy + oh
            and oy < self.y + self.h
        )

    def collidepoint(self, px, py):
        return (
            self.x <= px < self.x + self.w
            and self.y <= py < self.y + self.h
        )

    # -- sequence protocol (rect-style for pygame interop) -----------
    def __iter__(self):
        return iter((self.x, self.y, self.w, self.h))

    def __len__(self):
        return 4

    def __getitem__(self, i):
        return (self.x, self.y, self.w, self.h)[i]

    def __eq__(self, other):
        try:
            return (self.x, self.y, self.w, self.h) == tuple(_unpack(other))
        except (TypeError, ValueError):
            return NotImplemented

    def __repr__(self):
        return "Rect({}, {}, {}, {})".format(self.x, self.y, self.w, self.h)


def point_in_any_rect(px, py, rects, margin=0):
    """True if point (px, py) lies inside any rect (expanded by margin)."""
    for r in rects:
        if (r.x - margin <= px <= r.x + r.w + margin
                and r.y - margin <= py <= r.y + r.h + margin):
            return True
    return False


def has_line_of_sight(x1, y1, x2, y2, walls, step=14.0):
    """Cheap sampled line-of-sight test between two points.

    Samples points every ``step`` pixels along the segment and checks them
    against the wall rects.  Good enough for AI perception; not used for
    physics.
    """
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist < step:
        return True
    n = int(dist / step)
    inv = 1.0 / (n + 1)
    for i in range(1, n + 1):
        t = i * inv
        px = x1 + (x2 - x1) * t
        py = y1 + (y2 - y1) * t
        if point_in_any_rect(px, py, walls):
            return False
    return True

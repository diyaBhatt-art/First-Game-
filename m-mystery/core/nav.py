"""Coarse-grid pathfinding for bot navigation — pure Python, no engine imports.

Builds a walkable cell grid from a map's wall rectangles (inflated by the
player's half-size so paths keep body clearance), then answers A* path
queries in pixel coordinates.  Grids are cached per wall layout, so every
bot on a map shares one grid and the build cost is paid once per map.

Costs are deliberately tiny: an 800x600 map at 25 px cells is a 32x24 grid
(768 nodes), so a worst-case A* query is well under a millisecond and bots
only repath a few times per second (see BotBrain._toward_point).
"""
import heapq
import math

# ── Tuning ─────────────────────────────────────────────────────────────
CELL_SIZE = 25      # px per grid cell (800x600 map -> 32x24 cells)
WALL_INFLATE = 11   # px — walls grow by this so paths clear the player body

_SQRT2 = math.sqrt(2.0)

_GRID_CACHE = {}    # geometry key -> NavGrid


def get_nav_grid(width, height, walls):
    """Return a cached NavGrid for the given wall layout.

    *walls* is any iterable of rect-like objects exposing x/y/w/h.
    """
    key = (width, height, tuple((r.x, r.y, r.w, r.h) for r in walls))
    grid = _GRID_CACHE.get(key)
    if grid is None:
        grid = NavGrid(width, height, walls)
        _GRID_CACHE[key] = grid
    return grid


class NavGrid:
    """Walkability grid + A* over a wall layout."""

    def __init__(self, width, height, walls, cell=CELL_SIZE, inflate=WALL_INFLATE):
        self.cell = float(cell)
        self.cols = max(1, int(math.ceil(width / self.cell)))
        self.rows = max(1, int(math.ceil(height / self.cell)))

        blocked = [[False] * self.cols for _ in range(self.rows)]
        for r in walls:
            x0 = int(math.floor((r.x - inflate) / self.cell))
            y0 = int(math.floor((r.y - inflate) / self.cell))
            x1 = int(math.floor((r.x + r.w + inflate) / self.cell))
            y1 = int(math.floor((r.y + r.h + inflate) / self.cell))
            for cy in range(max(0, y0), min(self.rows - 1, y1) + 1):
                row = blocked[cy]
                for cx in range(max(0, x0), min(self.cols - 1, x1) + 1):
                    row[cx] = True
        self._blocked = blocked

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def cell_of(self, x, y):
        """Clamped (cx, cy) grid cell containing pixel point (x, y)."""
        cx = min(self.cols - 1, max(0, int(x / self.cell)))
        cy = min(self.rows - 1, max(0, int(y / self.cell)))
        return cx, cy

    def center(self, cx, cy):
        """Pixel centre of cell (cx, cy)."""
        return (cx + 0.5) * self.cell, (cy + 0.5) * self.cell

    def walkable(self, cx, cy):
        return (0 <= cx < self.cols and 0 <= cy < self.rows
                and not self._blocked[cy][cx])

    def nearest_walkable(self, cx, cy, max_radius=6):
        """Nearest walkable cell to (cx, cy), searching outward in rings."""
        if self.walkable(cx, cy):
            return cx, cy
        for radius in range(1, max_radius + 1):
            best = None
            best_d = None
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy)) != radius:
                        continue
                    nx, ny = cx + dx, cy + dy
                    if self.walkable(nx, ny):
                        d = dx * dx + dy * dy
                        if best_d is None or d < best_d:
                            best_d = d
                            best = (nx, ny)
            if best is not None:
                return best
        return None

    def nearest_open(self, x, y):
        """Snap a pixel point to the centre of the nearest walkable cell."""
        cell = self.nearest_walkable(*self.cell_of(x, y))
        if cell is None:
            return x, y
        return self.center(*cell)

    # ------------------------------------------------------------------
    # Pathfinding
    # ------------------------------------------------------------------

    def find_path(self, sx, sy, gx, gy):
        """A* path from pixel (sx, sy) to pixel (gx, gy).

        Returns a list of pixel waypoints ending at (or as close as the
        grid allows to) the goal.  Empty list means "same cell — walk
        straight" or "no route exists".
        """
        start = self.nearest_walkable(*self.cell_of(sx, sy))
        goal_cell_raw = self.cell_of(gx, gy)
        goal = self.nearest_walkable(*goal_cell_raw)
        if start is None or goal is None:
            return []
        if start == goal:
            if self.walkable(*goal_cell_raw):
                return [(gx, gy)]
            return []

        cells = self._astar(start, goal)
        if not cells:
            return []

        cells = self._compress(cells)
        path = [self.center(cx, cy) for (cx, cy) in cells]

        # Finish on the exact goal point when it sits in open space.
        if goal == goal_cell_raw:
            path[-1] = (gx, gy)
        # The first waypoint is where we already are — drop it.
        if len(path) > 1:
            path.pop(0)
        return path

    def _astar(self, start, goal):
        cols = self.cols
        blocked = self._blocked
        gx, gy = goal

        open_heap = [(0.0, 0, start)]
        g_score = {start: 0.0}
        came_from = {start: None}
        tie = 0

        while open_heap:
            _f, _t, current = heapq.heappop(open_heap)
            if current == goal:
                cells = []
                node = current
                while node is not None:
                    cells.append(node)
                    node = came_from[node]
                cells.reverse()
                return cells

            cx, cy = current
            base = g_score[current]
            for dx, dy, cost in (
                (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
                (1, 1, _SQRT2), (1, -1, _SQRT2),
                (-1, 1, _SQRT2), (-1, -1, _SQRT2),
            ):
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < cols and 0 <= ny < self.rows):
                    continue
                if blocked[ny][nx]:
                    continue
                # No cutting corners diagonally past a blocked cell
                if dx and dy and (blocked[cy][nx] or blocked[ny][cx]):
                    continue
                tentative = base + cost
                neighbor = (nx, ny)
                if tentative < g_score.get(neighbor, float("inf")):
                    g_score[neighbor] = tentative
                    came_from[neighbor] = current
                    ddx, ddy = abs(nx - gx), abs(ny - gy)
                    h = (ddx + ddy) + (_SQRT2 - 2.0) * min(ddx, ddy)
                    tie += 1
                    heapq.heappush(open_heap, (tentative + h, tie, neighbor))
        return []

    def _compress(self, cells):
        """Drop intermediate cells that have straight-line grid clearance."""
        if len(cells) <= 2:
            return cells
        result = [cells[0]]
        anchor = 0
        for i in range(2, len(cells)):
            if not self._clear_line(cells[anchor], cells[i]):
                result.append(cells[i - 1])
                anchor = i - 1
        result.append(cells[-1])
        return result

    def _clear_line(self, a, b):
        """True if the segment between two cell centres stays on walkable cells."""
        ax, ay = self.center(*a)
        bx, by = self.center(*b)
        dist = math.hypot(bx - ax, by - ay)
        steps = max(1, int(dist / (self.cell * 0.5)))
        for i in range(1, steps + 1):
            t = i / float(steps)
            px = ax + (bx - ax) * t
            py = ay + (by - ay) * t
            if not self.walkable(*self.cell_of(px, py)):
                return False
        return True

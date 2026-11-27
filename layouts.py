"""Board layouts: which tiles of the W x H grid are floor (diggable, walkable) and which are walls.

Pure Python so both the game server and the training simulator (ai/env.py) use the same generator.
A layout is a bytearray of W*H, 1 = floor, indexed y * W + x.

  field   - one open rectangle in the middle of the grid (the classic square map)
  dungeon - rooms joined by corridors that you travel through; a new one every round
"""
import random

LAYOUTS = ["dungeon", "field"]


def field(W, H, fw=None, fh=None):
    fw, fh = min(fw or W, W), min(fh or H, H)
    x0, y0 = (W - fw) // 2, (H - fh) // 2
    out = bytearray(W * H)
    for y in range(y0, y0 + fh):
        out[y * W + x0:y * W + x0 + fw] = b"\x01" * fw
    return out


def dungeon(W, H, rng=random, min_floor=None):
    """Rooms carved out of solid rock, joined into one connected network by L-shaped corridors
    (a spanning tree plus a few extra loops). The outer ring of the grid is always wall."""
    small = min(W, H) < 24
    rmin, rmax = (3, 5) if small else (max(5, W // 9), max(8, W // 5))
    cw = 1 if small else 2                       # corridor width
    min_floor = min_floor or int(W * H * 0.36)
    best = None
    for _ in range(40):
        out = bytearray(W * H)
        rooms = []
        for _ in range(300):
            w, h = rng.randint(rmin, rmax), rng.randint(rmin, rmax)
            x, y = rng.randint(1, W - w - 1), rng.randint(1, H - h - 1)
            # keep a wall of at least 2 tiles between rooms so they read as separate chambers
            if any(x < rx + rw + 2 and rx < x + w + 2 and y < ry + rh + 2 and ry < y + h + 2 for rx, ry, rw, rh in rooms):
                continue
            rooms.append((x, y, w, h))
        if len(rooms) < 3:
            continue

        def carve(x0, y0, x1, y1):
            for yy in range(max(1, min(y0, y1)), min(H - 1, max(y0, y1) + 1)):
                for xx in range(max(1, min(x0, x1)), min(W - 1, max(x0, x1) + 1)):
                    out[yy * W + xx] = 1

        for x, y, w, h in rooms:
            carve(x, y, x + w - 1, y + h - 1)
        centres = [(x + w // 2, y + h // 2) for x, y, w, h in rooms]

        def corridor(a, b):
            (ax, ay), (bx, by) = centres[a], centres[b]
            if rng.random() < 0.5:
                carve(ax, ay, bx, ay + cw - 1); carve(bx, ay, bx + cw - 1, by)
            else:
                carve(ax, ay, ax + cw - 1, by); carve(ax, by, bx, by + cw - 1)

        # Prim's spanning tree on centre distance, then a few loops so there is more than one route
        linked, edges = {0}, []
        while len(linked) < len(rooms):
            a, b = min(((i, j) for i in linked for j in range(len(rooms)) if j not in linked),
                       key=lambda e: abs(centres[e[0]][0] - centres[e[1]][0]) + abs(centres[e[0]][1] - centres[e[1]][1]))
            corridor(a, b); edges.append((a, b)); linked.add(b)
        for _ in range(max(1, len(rooms) // 4)):
            a, b = rng.sample(range(len(rooms)), 2)
            corridor(a, b)
        n = sum(out)
        if n >= min_floor:
            return out
        if best is None or n > sum(best):
            best = out
    return best


def make(kind, W, H, rng=random, field_size=None):
    if kind == "field":
        fw, fh = field_size or (W, H)
        return field(W, H, fw, fh)
    return dungeon(W, H, rng)


def connected(floor, W, H):
    """True if every floor tile can reach every other one (4-neighbour walk)."""
    start = next((i for i in range(W * H) if floor[i]), None)
    if start is None:
        return False
    seen, stack = {start}, [start]
    while stack:
        i = stack.pop()
        x, y = i % W, i // W
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            j = ny * W + nx
            if 0 <= nx < W and 0 <= ny < H and floor[j] and j not in seen:
                seen.add(j); stack.append(j)
    return len(seen) == sum(floor)


if __name__ == "__main__":
    import sys
    W, H = (int(a) for a in sys.argv[1:3]) if len(sys.argv) > 2 else (48, 48)
    f = dungeon(W, H)
    print(f"{sum(f)} floor tiles of {W * H}, connected={connected(f, W, H)}")
    for y in range(H):
        print("".join("." if f[y * W + x] else "#" for x in range(W)))

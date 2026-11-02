"""Route planning on the navigation grid (pure functions, no robot state).

Routes follow the centreline of the free space: the medial axis, where the nearest
obstacles on both sides are equally far away.  Between two walls a route keeps equal
clearance on both sides; it never runs along one wall.

  1. clearance d: distance to the nearest blocked or unknown cell;
  2. centreline: the lambda-medial axis (cells whose nearest obstacle points, compared
     with a neighbour's, lie on opposite walls at least MEDIAL_LAMBDA_M apart, so the
     roughness of a wall does not create spurious branches);
  3. offset ratio r = m / (m + d), m = distance to the centreline: 0 on the centreline,
     towards 1 at a wall;
  4. A* on a PLAN_RES grid whose step cost grows steeply with r (cells with d below
     HARD_CLEARANCE_M are never entered), so paths run along the centreline and leave
     it only to reach the start and the goal;
  5. smoothing inside a narrow band around the centreline (a point may not move to a
     larger offset ratio than CENTRE_BAND, or than it had, nor closer to an obstacle);
  6. per-point curvature and clearance, used by the controller's speed caps.

The tour loop is the outline of the centreline network with its enclosed faces filled:
it runs along the outermost cycle and traces deeper branches out and back along their
centreline; short branches are cut.
"""
import heapq
import math

import numpy as np
from scipy.ndimage import binary_fill_holes, distance_transform_edt, label
from scipy.spatial import cKDTree

PLAN_RES = 0.10               # A* grid
ROUTE_STEP_M = 0.05           # spacing of every route
ROBOT_RADIUS = 0.35           # half of the 0.5-0.7 m body width, centred on the turning point
HARD_CLEARANCE_M = 0.45       # turning point to nearest obstacle on any planned point
MEDIAL_LAMBDA_M = 0.80        # opposite-wall separation that defines a centreline cell
CENTRE_WEIGHT = 40.0          # step cost multiplier at r = 1 (1 on the centreline)
CENTRE_BAND = 0.12            # smoothing keeps points within this offset ratio of the centreline
ESCAPE_RADIUS_M = 1.5         # a start inside the hard clearance may leave through ...
ESCAPE_CLEARANCE_M = 0.25     # ... cells with at least this clearance, at ESCAPE_COST per cell
ESCAPE_COST = 30.0
GOAL_SNAP_M = 1.0             # an unreachable goal moves to the nearest reachable cell this close
SMOOTH_ITERATIONS = 150
SMOOTH_GAIN = 0.35            # Laplacian smoothing per iteration
SMOOTH_PULL_M = 0.01          # pull toward the centreline per iteration
CURVATURE_WINDOW_M = 0.30     # heading change measured over +-this arc
CUSP_SPAN_M = 0.15            # a cusp: the heading this far before and after ...
CUSP_ANGLE = math.radians(120)    # ... differs by more than this (out-and-back turnaround)
# The outline of the centreline network traces every branch out and back.  Branches up to
# SPUR_MAX_M / 2 deep (wall-corner artifacts, short alcoves) are cut; deeper ones stay in the
# tour as out-and-back excursions along their centreline: in this venue the gaps west of the
# central block are narrower than 2 * HARD_CLEARANCE_M, so the only true cycle is the 16 m one
# around the eastern obstacle and the rest of the area is reachable only out and back.
SPUR_JOIN_M = 0.30            # a traced-out branch comes back within this of itself ...
SPUR_MIN_M, SPUR_MAX_M = 0.5, 6.0    # ... after this much travel ...
SPUR_FOLD_M = 0.40            # ... with both legs this close all along: cut
ENTRY_TURN_M = 0.5            # loop entry: metres of extra distance per unit (1 - cos) of turning


def disk(radius_cells):
    r = int(math.ceil(radius_cells))
    o = np.arange(-r, r + 1)
    return np.hypot(*np.meshgrid(o, o, indexing='ij')) <= radius_cells


def resample(points, step=ROUTE_STEP_M):
    points = np.asarray(points, float)
    keep = np.r_[True, np.linalg.norm(np.diff(points, axis=0), axis=1) > 1e-9]
    points = points[keep]
    if len(points) < 2:
        return points.copy()
    arc = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    s = np.r_[np.arange(0.0, arc[-1], step), arc[-1]]
    return np.c_[np.interp(s, arc, points[:, 0]), np.interp(s, arc, points[:, 1])]


def medial_axis(blocked, res, lam=MEDIAL_LAMBDA_M):
    """Lambda-medial axis of the free space (bool mask at map resolution)."""
    _, (fi, fj) = distance_transform_edt(~blocked, return_indices=True)
    lam2 = (lam / res) ** 2
    medial = np.zeros(blocked.shape, bool)
    for axis in (0, 1):
        a = [slice(None), slice(None)]
        b = [slice(None), slice(None)]
        a[axis], b[axis] = slice(0, -1), slice(1, None)
        a, b = tuple(a), tuple(b)
        sep = (fi[a] - fi[b]) ** 2 + (fj[a] - fj[b]) ** 2
        mark = sep >= lam2
        medial[a] |= mark
        medial[b] |= mark
    return medial & ~blocked


class Field:
    """Clearance, centreline and offset ratio at map resolution, with bilinear sampling."""

    def __init__(self, blocked, origin, res):
        self.origin = np.asarray(origin, float)
        self.res = float(res)
        self.blocked = blocked
        self.d = (distance_transform_edt(~blocked) * res).astype(np.float32)
        self.medial = medial_axis(blocked, res) & (self.d >= HARD_CLEARANCE_M)
        self.m = (distance_transform_edt(~self.medial) * res).astype(np.float32) if self.medial.any() \
            else np.full(blocked.shape, 1e3, np.float32)
        self.r = (self.m / np.maximum(self.m + self.d, 1e-6)).astype(np.float32)
        gx, gy = np.gradient(self.m)
        self.gx, self.gy = gx.astype(np.float32), gy.astype(np.float32)

    def _cells(self, xy):
        ij = np.floor((np.atleast_2d(xy) - self.origin) / self.res).astype(int)
        ij[:, 0] = np.clip(ij[:, 0], 0, self.d.shape[0] - 1)
        ij[:, 1] = np.clip(ij[:, 1], 0, self.d.shape[1] - 1)
        return ij

    def _bilinear(self, grid, xy):
        u = (np.atleast_2d(np.asarray(xy, float)) - self.origin) / self.res - 0.5
        i0 = np.clip(np.floor(u[:, 0]).astype(int), 0, grid.shape[0] - 2)
        j0 = np.clip(np.floor(u[:, 1]).astype(int), 0, grid.shape[1] - 2)
        fi = np.clip(u[:, 0] - i0, 0.0, 1.0)
        fj = np.clip(u[:, 1] - j0, 0.0, 1.0)
        return ((1 - fi) * (1 - fj) * grid[i0, j0] + fi * (1 - fj) * grid[i0 + 1, j0]
                + (1 - fi) * fj * grid[i0, j0 + 1] + fi * fj * grid[i0 + 1, j0 + 1])

    def clearance(self, xy):
        """Clearance at points, never more than the nearest cell's clearance + half a cell."""
        ij = self._cells(xy)
        return np.minimum(self._bilinear(self.d, xy), self.d[ij[:, 0], ij[:, 1]] + self.res * 0.5)

    def offset(self, xy):
        """Offset ratio from the centreline (0 on it, towards 1 at a wall)."""
        m = self._bilinear(self.m, xy)
        d = self.clearance(xy)
        return m / np.maximum(m + d, 1e-6)

    def toward_centre(self, xy):
        g = -np.c_[self._bilinear(self.gx, xy), self._bilinear(self.gy, xy)]
        return g / np.maximum(np.linalg.norm(g, axis=1), 1e-9)[:, None]

    def segment_clear(self, a, b, minimum):
        n = max(2, int(np.linalg.norm(np.asarray(b) - np.asarray(a)) / (self.res * 0.5)) + 1)
        pts = np.asarray(a) + (np.asarray(b) - np.asarray(a)) * np.linspace(0, 1, n)[:, None]
        return bool(self.clearance(pts).min() >= minimum)


class Route:
    """Dense polyline with arc length, curvature and planned clearance per point."""

    def __init__(self, points, field=None, closed=False):
        self.points = resample(points)
        if len(self.points) < 2:
            self.points = np.vstack([self.points, self.points])
        self.arc = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(self.points, axis=0), axis=1))]
        self.length = float(self.arc[-1])
        self.closed = closed
        self.kappa = curvature(self.points, self.arc)
        if field is not None:
            self.clearance = field.clearance(self.points).astype(np.float32)
            self.offset = field.offset(self.points).astype(np.float32)
        else:
            self.clearance = np.full(len(self.points), 1.0, np.float32)
            self.offset = np.zeros(len(self.points), np.float32)
        self.cusps = cusps(self.points, self.arc)
        for array in (self.points, self.arc, self.kappa, self.clearance, self.offset, self.cusps):
            array.setflags(write=False)

    def next_cusp(self, s):
        """Arc of the first cusp after s, or the route length."""
        k = int(np.searchsorted(self.cusps, s + 1e-6))
        return float(self.cusps[k]) if k < len(self.cusps) else self.length

    def previous_cusp(self, s):
        k = int(np.searchsorted(self.cusps, s - 1e-6)) - 1
        return float(self.cusps[k]) if k >= 0 else 0.0

    def index_at(self, s):
        return int(np.clip(np.searchsorted(self.arc, s, side='right') - 1, 0, len(self.arc) - 2))

    def point_at(self, s):
        s = float(np.clip(s, 0.0, self.length))
        return np.array([np.interp(s, self.arc, self.points[:, 0]), np.interp(s, self.arc, self.points[:, 1])])

    def heading_at(self, s):
        a, b = self.point_at(s - 0.1), self.point_at(s + 0.1)
        return math.atan2(b[1] - a[1], b[0] - a[0])

    def project(self, position, low, high):
        """(s, error) of the closest point to `position` within the arc window [low, high]."""
        low, high = max(0.0, low), min(self.length, high)
        if high <= low:
            high = min(self.length, low + ROUTE_STEP_M)
        i0, i1 = self.index_at(low), self.index_at(high)
        a = self.points[i0:i1 + 1]
        v = self.points[i0 + 1:i1 + 2] - a
        L2 = np.maximum(np.sum(v * v, axis=1), 1e-12)
        t = np.clip(np.sum((position - a) * v, axis=1) / L2, 0.0, 1.0)
        s = np.clip(self.arc[i0:i1 + 1] + t * np.sqrt(L2), low, high)
        q = np.c_[np.interp(s, self.arc, self.points[:, 0]), np.interp(s, self.arc, self.points[:, 1])]
        e = np.linalg.norm(q - position, axis=1)
        k = int(np.argmin(e))
        return float(s[k]), float(e[k])

    def window(self, s, length):
        """Points of the arc window [s, s + length] and their arc offsets from s."""
        i0, i1 = self.index_at(s), self.index_at(s + length)
        pts = np.vstack([self.point_at(s), self.points[i0 + 1:i1 + 1]])
        return pts, np.r_[0.0, self.arc[i0 + 1:i1 + 1] - s]

    def max_curvature(self, s, length):
        i0, i1 = self.index_at(s), self.index_at(s + length)
        return float(np.abs(self.kappa[i0:i1 + 2]).max())


def cusps(points, arc):
    """Arc positions where the route reverses (out-and-back turnarounds): the heading
    0.15 m before and after differs by more than CUSP_ANGLE.  One position per reversal."""
    if len(points) < 5:
        return np.zeros(0)

    def at(s):
        s = np.clip(s, 0.0, arc[-1])
        return np.c_[np.interp(s, arc, points[:, 0]), np.interp(s, arc, points[:, 1])]

    a, m, b = at(arc - CUSP_SPAN_M), at(arc), at(arc + CUSP_SPAN_M)
    u, v = m - a, b - m
    nu, nv = np.linalg.norm(u, axis=1), np.linalg.norm(v, axis=1)
    cos = np.sum(u * v, axis=1) / np.maximum(nu * nv, 1e-9)
    reversed_ = (cos < math.cos(CUSP_ANGLE)) & (nu > CUSP_SPAN_M * 0.5) & (nv > CUSP_SPAN_M * 0.5)
    out = []
    i = 0
    while i < len(arc):
        if reversed_[i]:
            j = i
            while j + 1 < len(arc) and reversed_[j + 1]:
                j += 1
            k = i + int(np.argmin(cos[i:j + 1]))
            out.append(arc[k])
            i = j + 1
        else:
            i += 1
    return np.asarray(out, float)


def curvature(points, arc):
    """Signed curvature from the heading change over +-CURVATURE_WINDOW_M."""
    if len(points) < 3:
        return np.zeros(len(points), np.float32)
    s0 = np.clip(arc - CURVATURE_WINDOW_M, 0.0, arc[-1])
    s1 = np.clip(arc + CURVATURE_WINDOW_M, 0.0, arc[-1])

    def at(s):
        return np.c_[np.interp(s, arc, points[:, 0]), np.interp(s, arc, points[:, 1])]

    a, m, b = at(s0), at(arc), at(s1)
    h1 = np.arctan2(m[:, 1] - a[:, 1], m[:, 0] - a[:, 0])
    h2 = np.arctan2(b[:, 1] - m[:, 1], b[:, 0] - m[:, 0])
    dh = np.remainder(h2 - h1 + np.pi, 2 * np.pi) - np.pi
    k = dh / np.maximum((s1 - s0) / 2.0, 1e-6)
    k[(s1 - arc < 1e-6) | (arc - s0 < 1e-6)] = 0.0
    return k.astype(np.float32)


class Costmap:
    """Clearance/centreline field plus the A* grid (PLAN_RES) derived from it."""

    def __init__(self, blocked, unknown, origin, res):
        self.origin = np.asarray(origin, float)
        self.res = res
        self.field = Field(blocked | unknown, origin, res)
        k = max(1, int(round(PLAN_RES / res)))
        W, H = (blocked.shape[0] // k) * k, (blocked.shape[1] // k) * k

        def blocks(grid, reduce):
            return reduce(grid[:W, :H].reshape(W // k, k, H // k, k), axis=(1, 3))

        d = blocks(self.field.d, np.min)
        r = blocks(self.field.r, np.min)          # a block touching the centreline counts as on it
        self.d = d
        cost = 1.0 + (CENTRE_WEIGHT - 1.0) * r ** 2
        cost[d < HARD_CLEARANCE_M] = np.inf
        self.cost = cost.astype(np.float64)
        self.escape_ok = d >= ESCAPE_CLEARANCE_M

    def cell(self, xy):
        return tuple(np.floor((np.asarray(xy, float) - self.origin) / PLAN_RES).astype(int))

    def xy(self, cells):
        return self.origin + (np.asarray(cells, float) + 0.5) * PLAN_RES

    def inside(self, c):
        return 0 <= c[0] < self.cost.shape[0] and 0 <= c[1] < self.cost.shape[1]

    def astar(self, start_xy, goal_xy, blocked_extra=None, radius_m=None):
        """Grid path start -> goal or (None, reason).  The start may lie inside the hard
        clearance (the robot is where it is); it then leaves through escape cells."""
        cost = self.cost.copy()
        if blocked_extra is not None:
            cost[blocked_extra] = np.inf
        s, g = self.cell(start_xy), self.cell(goal_xy)
        if not self.inside(s):
            return None, 'start_outside'
        if not self.inside(g):
            return None, 'goal_blocked'
        W, H = cost.shape
        if radius_m is not None:
            xx, yy = np.ogrid[:W, :H]
            cost[(xx - s[0]) ** 2 + (yy - s[1]) ** 2 > (radius_m / PLAN_RES) ** 2] = np.inf
        if not np.isfinite(cost[g]):
            r = int(GOAL_SNAP_M / PLAN_RES)
            x0, x1, y0, y1 = max(g[0] - r, 0), min(g[0] + r + 1, W), max(g[1] - r, 0), min(g[1] + r + 1, H)
            cand = np.argwhere(np.isfinite(cost[x0:x1, y0:y1])) + (x0, y0)
            if not len(cand):
                return None, 'goal_blocked'
            g = tuple(cand[np.argmin(np.hypot(cand[:, 0] - g[0], cand[:, 1] - g[1]))])
        if not np.isfinite(cost[s]):
            r = int(math.ceil(ESCAPE_RADIUS_M / PLAN_RES))
            x0, x1, y0, y1 = max(s[0] - r, 0), min(s[0] + r + 1, W), max(s[1] - r, 0), min(s[1] + r + 1, H)
            gx, gy = np.meshgrid(np.arange(x0, x1) - s[0], np.arange(y0, y1) - s[1], indexing='ij')
            rr = np.hypot(gx, gy) * PLAN_RES
            win = cost[x0:x1, y0:y1]
            ok = self.escape_ok[x0:x1, y0:y1] | (rr <= ROBOT_RADIUS)
            if blocked_extra is not None:
                ok &= ~blocked_extra[x0:x1, y0:y1]
            win[~np.isfinite(win) & (rr <= ESCAPE_RADIUS_M) & ok] = ESCAPE_COST
            cost[s] = ESCAPE_COST
        flat = cost.ravel().tolist()            # Python lists: scalar access in the inner loop
        isfinite = math.isfinite
        start, goal = s[0] * H + s[1], g[0] * H + g[1]
        gcost = [math.inf] * (W * H)
        parent = [-1] * (W * H)
        closed = bytearray(W * H)
        gcost[start] = 0.0
        diag = math.sqrt(2)
        moves = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
                 (1, 1, diag), (1, -1, diag), (-1, 1, diag), (-1, -1, diag)]
        heap = [(0.0, start)]
        while heap:
            _, cur = heapq.heappop(heap)
            if closed[cur]:
                continue
            if cur == goal:
                path = [cur]
                while parent[path[-1]] >= 0:
                    path.append(parent[path[-1]])
                path = np.array(path[::-1])
                return self.xy(np.c_[path // H, path % H]), 'ok'
            closed[cur] = 1
            ci, cj = divmod(cur, H)
            here = flat[cur]
            for di, dj, step in moves:
                ni, nj = ci + di, cj + dj
                if not (0 <= ni < W and 0 <= nj < H):
                    continue
                nb = ni * H + nj
                c = flat[nb]
                if closed[nb] or not isfinite(c):
                    continue
                if di and dj and not (isfinite(flat[ci * H + nj]) and isfinite(flat[ni * H + cj])):
                    continue                     # no diagonal corner cutting
                ng = gcost[cur] + step * 0.5 * (c + here)
                if ng < gcost[nb]:
                    gcost[nb] = ng
                    parent[nb] = cur
                    heapq.heappush(heap, (ng + math.hypot(g[0] - ni, g[1] - nj), nb))
        return None, 'no_path'


def smooth(points, field, closed=False, iterations=SMOOTH_ITERATIONS):
    """Smooth a polyline inside the centreline band.

    Each iteration combines Laplacian smoothing with a small pull toward the centreline.
    A point moves only if its new position keeps an offset ratio within
    max(CENTRE_BAND, its current ratio) and a clearance of at least min(its current
    clearance, HARD_CLEARANCE_M): smoothing rounds corners and removes grid steps but can
    neither leave the centreline nor approach a wall.  Open polylines keep their ends.
    """
    p = resample(points)
    if closed and len(p) > 1 and np.allclose(p[0], p[-1]):
        p = p[:-1]
    if len(p) < 3:
        return p
    for it in range(iterations):
        if closed:
            prev, nxt = np.roll(p, 1, axis=0), np.roll(p, -1, axis=0)
        else:
            prev, nxt = np.vstack([p[:1], p[:-1]]), np.vstack([p[1:], p[-1:]])
        d, r = field.clearance(p), field.offset(p)
        cand = p + SMOOTH_GAIN * (0.5 * (prev + nxt) - p) + SMOOTH_PULL_M * field.toward_centre(p)
        if not closed:
            cand[0], cand[-1] = p[0], p[-1]
        ok = ((field.offset(cand) <= np.maximum(r, CENTRE_BAND) + 1e-4)
              & (field.clearance(cand) >= np.minimum(d, HARD_CLEARANCE_M) - 1e-4))
        p = np.where(ok[:, None], cand, p)
        if it % 25 == 24:
            p = resample(np.vstack([p, p[:1]]))[:-1] if closed else resample(p)
    return resample(np.vstack([p, p[:1]])) if closed else resample(p)


def plan_path(costmap, start_xy, goal_xy, blocked_extra=None, radius_m=None):
    """Smooth centreline route start -> goal, or (None, reason)."""
    grid, why = costmap.astar(start_xy, goal_xy, blocked_extra=blocked_extra, radius_m=radius_m)
    if grid is None:
        return None, why
    raw = np.vstack([np.asarray(start_xy, float), grid[1:]]) if len(grid) > 1 \
        else np.vstack([np.asarray(start_xy, float), grid])
    return smooth(raw, costmap.field), 'ok'


def component(field, robot_xy, max_snap_m=1.5):
    """Free component (d >= HARD_CLEARANCE_M) that contains, or lies next to, the robot."""
    free = field.d >= HARD_CLEARANCE_M
    lab, n = label(free)
    if n == 0:
        return None
    c = np.clip(np.floor((np.asarray(robot_xy) - field.origin) / field.res).astype(int), 0,
                np.array(free.shape) - 1)
    comp_id = lab[tuple(c)]
    if comp_id == 0:
        cells = np.argwhere(lab > 0)
        near = cells[np.argmin(np.linalg.norm(cells - c, axis=1))]
        if np.linalg.norm(near - c) * field.res > max_snap_m:
            return None
        comp_id = lab[tuple(near)]
    return lab == comp_id


def loop_ring(field, robot_xy, exclude=None):
    """Closed tour loop on the centreline network of the robot's free component, or None.

    The outline of the centreline with its enclosed faces filled runs along the network's
    outermost cycle; branches leaving that cycle are traced out and back and cut.
    `exclude` (bool mask) removes centreline cells, e.g. on weakly mapped ground.
    """
    import cv2
    comp = component(field, robot_xy)
    if comp is None:
        return None
    centre = field.medial & comp
    if exclude is not None:
        centre &= ~exclude
    lab, n = label(centre, np.ones((3, 3)))
    if n == 0:
        return None
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    filled = binary_fill_holes(lab == int(np.argmax(sizes)))
    contours, _ = cv2.findContours(filled.T.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    cells = max(contours, key=cv2.contourArea)[:, 0, :]
    if len(cells) < 8:
        return None
    raw = field.origin + (cells.astype(float) + 0.5) * field.res
    ring = resample(np.vstack([raw, raw[:1]]))
    for _ in range(4):          # a cut can expose a further traced-out branch
        cut = cut_out_and_back(ring, field)
        if len(cut) == len(ring):
            break
        ring = cut
    if np.linalg.norm(np.diff(ring, axis=0), axis=1).sum() < 2.0:
        return None             # no cycle: the free space is a tree (only out-and-back routes)
    return smooth(ring, field, closed=True)


def folded(pts, i, j):
    """True if pts[i..j] goes out and comes back along the same line: every point of the
    outbound half lies within SPUR_FOLD_M of its mirror on the return half.  A cycle that
    starts and ends at one junction is not folded (its middle points are far apart)."""
    k = np.arange(0, (j - i) // 2 + 1, 2)
    return bool(np.linalg.norm(pts[i + k] - pts[j - k], axis=1).max() <= SPUR_FOLD_M)


def cut_out_and_back(ring_closed, field):
    """Remove whole short branches: folded sections (traced out and back) that start at a
    junction, whose straight join keeps the hard clearance and whose out-and-back length
    is at most SPUR_MAX_M.  'Starts at a junction' means the fold is maximal: just outside
    it the two legs diverge.  Without that test the tip of every deep branch counted as a
    short fold and repeated passes ate deep branches 3 m at a time (168.7 -> 16.0 m).
    Nested short branches fold only after their own tips are cut, hence the caller's
    repeated passes.  The ring is scanned from two starts half a lap apart, so a branch
    across the ring's start is found too."""
    ring = ring_closed[:-1]
    for shift in (0, len(ring) // 2):
        pts = np.roll(ring, -shift, axis=0)
        n = len(pts)
        arc = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
        tree = cKDTree(pts)
        out = 4                               # 0.2 m outside the fold
        keep, i = [], 0
        while i < n:
            keep.append(i)
            nxt = i + 1
            for j in sorted(tree.query_ball_point(pts[i], SPUR_JOIN_M), reverse=True):
                if not (j > i and SPUR_MIN_M < arc[j] - arc[i] <= SPUR_MAX_M):
                    continue
                maximal = np.linalg.norm(pts[(i - out) % n] - pts[(j + out) % n]) > SPUR_FOLD_M
                if maximal and folded(pts, i, j) and field.segment_clear(pts[i], pts[j], HARD_CLEARANCE_M):
                    nxt = j
                    break
            i = nxt
        ring = pts[keep]
    return resample(np.vstack([ring, ring[:1]]))


def loop_entry(ring_closed, robot_xy, robot_yaw):
    """Rotate/orient a closed ring so it starts where, and runs the way, the robot can join
    it heading forward.  Returns the closed ring (first point repeated)."""
    ring = ring_closed[:-1]
    best = None
    for candidate in (ring, ring[::-1]):
        cost = np.linalg.norm(candidate - robot_xy, axis=1)
        if robot_yaw is not None:
            heading = np.array([math.cos(robot_yaw), math.sin(robot_yaw)])
            bearing = candidate - robot_xy
            bearing /= np.maximum(np.linalg.norm(bearing, axis=1), 1e-6)[:, None]
            direction = np.roll(candidate, -1, axis=0) - candidate
            direction /= np.maximum(np.linalg.norm(direction, axis=1), 1e-6)[:, None]
            close = np.linalg.norm(candidate - robot_xy, axis=1) < 0.3
            bearing[close] = direction[close]          # already on the ring: only its direction counts
            cost = cost + ENTRY_TURN_M * ((1 - bearing @ heading)
                                          + (1 - np.einsum('ij,ij->i', bearing, direction)))
        k = int(np.argmin(cost))
        if best is None or cost[k] < best[0]:
            best = (cost[k], candidate, k)
    _, ring, k = best
    ring = np.roll(ring, -k, axis=0)
    return np.vstack([ring, ring[:1]])

"""Write a synthetic raw.xt session (LiDAR clouds + IMU + status) for testing the control server
and the operator console without a robot: python -m flyhead.server.app --replay OUT.xt

The robot stands still for 3 s (SLAM seed frame and IMU levelling), then drives forward through
the synthetic arena (flyhead.sim.synthetic_map) at 0.2 m/s with a gentle turn until DRIVE_UNTIL_S.
As on the real robot the LiDAR faces backwards (LiDAR +x = body backward, lidar_slam.BODY_YAW_DEG).
With --person a person (0.25 m radius) appears 3.2 m ahead of the stopped robot, walks toward it
at 0.5 m/s, stops 0.8 m away, then walks off sideways -- a looming stimulus for brain shadow mode.
Clouds are ray-cast in the LiDAR frame (360 deg x -5..+55 deg, obstacles 1.5 m high, floor), 10 Hz,
per-point time offsets; IMU at 200 Hz (yaw quaternion, gyro z, gravity +z). Not a sensor model:
it only feeds the pipeline.

--base-out DIR also writes a navigation package (DIR/nav) of the arena in this recording's SLAM
frame (LiDAR at the start = origin, floor at -LIDAR_H) and an ideal arena point cloud (DIR/map.ply).
For relocalization use the map.ply the server saves after replaying the recording once (mapping),
then --base runs/replay_*/map.ply --nav DIR/nav, and tools/export_preview_map.py for the console.

python tools/make_synthetic_raw.py OUT.xt [--seconds 20] [--person] [--base-out DIR]
"""
import argparse
import json
import math
import struct
from pathlib import Path

import numpy as np

from flyhead.slam import rawlog
from flyhead.sim import synthetic_map as SM

LIDAR_H = 0.45
WALL_TOP = SM.WALL_TOP
START = (7.0, -1.1, 0.0)            # LiDAR position and LiDAR heading in arena coordinates (body faces -x)
DRIVE_UNTIL_S = 13.0
PERSON_R, PERSON_AT_S, PERSON_AHEAD_M, PERSON_V, PERSON_STOP_M = 0.25, 16.0, 3.2, 0.5, 0.8
PERSON_LEAVE_S, PERSON_LEAVE_V = 28.0, 0.6


def person_track(seconds, x, y, yaw):
    """Person position per 5 ms step (None before it appears), for a robot stopped at (x, y) with body heading yaw."""
    out, p = [], None
    for k in range(int(seconds * 200)):
        t = k / 200.0
        if t >= PERSON_AT_S and p is None:
            p = [x + PERSON_AHEAD_M * math.cos(yaw), y + PERSON_AHEAD_M * math.sin(yaw)]
        if p is not None:
            if t >= PERSON_LEAVE_S:
                p[0] += -math.sin(yaw) * PERSON_LEAVE_V / 200; p[1] += math.cos(yaw) * PERSON_LEAVE_V / 200
            elif math.hypot(p[0] - x, p[1] - y) - PERSON_R > PERSON_STOP_M:
                p[0] -= math.cos(yaw) * PERSON_V / 200; p[1] -= math.sin(yaw) * PERSON_V / 200
        out.append(None if p is None else tuple(p))
    return out


def cloud_frame(cloud, x, y, yaw, az, wall_range, person_xy, rng, max_points=9000):
    """One LiDAR frame from saved cloud points: in range, not behind the first grid wall of their
    azimuth, above -8 deg elevation; plus a person cylinder. Returns float32 rows in the LiDAR frame."""
    rel = cloud[:, :2] - [x, y]
    r = np.hypot(rel[:, 0], rel[:, 1])
    ang = np.arctan2(rel[:, 1], rel[:, 0]) - yaw
    b = np.floor((np.remainder(ang + math.pi, 2 * math.pi)) / (2 * math.pi) * len(az)).astype(int) % len(az)
    elev = np.arctan2(cloud[:, 2], np.maximum(r, 1e-6))
    keep = (r > 0.4) & (r < 11.0) & (r <= wall_range[b] + 0.2) & (elev > math.radians(-8))
    pts = cloud[keep]
    if person_xy is not None:
        dp = np.hypot(person_xy[0] - x, person_xy[1] - y)
        if 0.3 < dp < 11.0:
            face = math.atan2(y - person_xy[1], x - person_xy[0])
            th = face + np.linspace(-1.3, 1.3, 24)
            zs = np.arange(-LIDAR_H + 0.05, 1.7 - LIDAR_H, 0.08)
            ring = np.c_[person_xy[0] + PERSON_R * np.cos(th), person_xy[1] + PERSON_R * np.sin(th)]
            pts = np.vstack([pts, np.c_[np.repeat(ring, len(zs), 0), np.tile(zs, len(ring))]])
    if len(pts) > max_points:
        pts = pts[rng.choice(len(pts), max_points, replace=False)]
    rel = pts[:, :2] - [x, y]
    c, s = math.cos(-yaw), math.sin(-yaw)
    lx, ly = c * rel[:, 0] - s * rel[:, 1], s * rel[:, 0] + c * rel[:, 1]
    out = np.c_[lx, ly, pts[:, 2], np.full(len(pts), 100.0), rng.uniform(0, 0.1, len(pts))]
    out[:, :3] += rng.normal(0, 0.01, (len(pts), 3))
    return out.astype('<f4')


def write_base(out_dir):
    """Arena base map (PLY) + navigation package, both in the recording's SLAM frame."""
    out = Path(out_dir)
    nav = SM.write(out / 'nav')
    shift = np.array(START[:2])
    (nav / 'map.yaml').write_text((nav / 'map.yaml').read_text().replace(
        'origin: [%.4f, %.4f, 0.0]' % SM.ORIGIN,
        'origin: [%.4f, %.4f, 0.0]' % (SM.ORIGIN[0] - shift[0], SM.ORIGIN[1] - shift[1])))
    np.save(nav / 'floor.npy', np.full(np.load(nav / 'floor.npy').shape, -LIDAR_H, np.float32))
    grid = SM.build()
    occ = grid == 0
    edge = occ & ~(np.roll(occ, 1, 0) & np.roll(occ, -1, 0) & np.roll(occ, 1, 1) & np.roll(occ, -1, 1))
    ij = np.argwhere(edge)
    xy = SM.ORIGIN + (ij + 0.5) * SM.RES
    walls = np.vstack([np.c_[xy, np.full(len(xy), z)] for z in np.arange(0.02, WALL_TOP, 0.08)])
    free = np.argwhere(grid == 254)
    free = free[(free[:, 0] % 2 == 0) & (free[:, 1] % 2 == 0)]           # 0.10 m floor grid
    floor = np.c_[SM.ORIGIN + (free + 0.5) * SM.RES, np.zeros(len(free))]
    pts = np.vstack([walls, floor]) - [shift[0], shift[1], LIDAR_H]
    header = 'ply\nformat binary_little_endian 1.0\nelement vertex %d\nproperty float x\nproperty float y\nproperty float z\nend_header\n' % len(pts)
    (out / 'map.ply').write_bytes(header.encode() + pts.astype('<f4').tobytes())
    print('base map', out / 'map.ply', len(pts), 'points; navigation package', nav)


def main(out, seconds=20.0, person=False, base_out=None, map_pkg=None, from_cloud=False):
    cloud_pts = None
    if map_pkg:
        # a saved map package moved to the start frame (tools/shift_map_package.py): rays hit its walls
        from flyhead.slam.navmap import NavMap
        nm = NavMap(map_pkg)
        grid = nm.blocked_for(0.32)
        res, ox, oy = nm.res, nm.origin[0], nm.origin[1]
        start = (0.0, 0.0, 0.0)
        if from_cloud:
            # scans are taken from the package's own saved cloud (occluded by the grid), so they
            # match the base map; the person is added as a cylinder of points
            from flyhead.slam.reloc import load_points
            cloud_pts = load_points(str(Path(map_pkg) / 'map.ply'))
            cloud_pts = cloud_pts[(cloud_pts[:, 2] > -LIDAR_H - 0.1) & (cloud_pts[:, 2] < WALL_TOP)]
    else:
        grid = SM.build() == 0
        res, ox, oy = SM.RES, SM.ORIGIN[0], SM.ORIGIN[1]
        start = START
    az = np.linspace(-math.pi, math.pi, 360, endpoint=False)
    el = np.radians(np.linspace(-5, 55, 16))
    steps = np.arange(0.2, 12.0, 0.02)
    rng = np.random.default_rng(1)
    t0 = 1.0e9
    x, y, yaw = start
    stop_pose = None
    track = None
    records = []

    def rec(t, kind, payload):
        records.append(rawlog.RECORD_HEADER.pack(t, b'XT', kind, len(payload)) + payload)

    for k in range(int(seconds * 200)):
        t = k / 200.0
        moving = 3.0 <= t < DRIVE_UNTIL_S
        v, w = (0.2, 0.06) if moving else (0.0, 0.0)
        heading = yaw + math.pi                          # body forward = LiDAR -x
        x += v * math.cos(heading) / 200; y += v * math.sin(heading) / 200; yaw += w / 200
        if person and t >= DRIVE_UNTIL_S and track is None:
            stop_pose = (x, y, yaw + math.pi)
            track = [None] * k + person_track(seconds, *stop_pose)[k:]
        q = (0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2))
        rec(t0 + t, rawlog.IMU, struct.pack('<d10f', t0 + t, *q, 0.0, 0.0, w, 0.0, 0.0, 9.81))
        if k % 20 == 0:                                 # 10 Hz cloud
            d = np.c_[np.cos(az + yaw), np.sin(az + yaw)]
            pts = np.array([x, y]) + d[:, None, :] * steps[None, :, None]
            ij = np.floor((pts - [ox, oy]) / res).astype(int)
            ok = (ij[..., 0] >= 0) & (ij[..., 0] < grid.shape[0]) & (ij[..., 1] >= 0) & (ij[..., 1] < grid.shape[1])
            hit = np.zeros(ok.shape, bool)
            hit[ok] = grid[ij[..., 0][ok], ij[..., 1][ok]]
            p = track[k] if track else None
            if p is not None:
                hit |= np.hypot(pts[..., 0] - p[0], pts[..., 1] - p[1]) <= PERSON_R
            first = np.where(hit.any(axis=1), hit.argmax(axis=1), -1)
            if cloud_pts is not None:
                c = cloud_frame(cloud_pts, x, y, yaw, az, np.where(first >= 0, steps[np.maximum(first, 0)], 11.0), p, rng)
                rec(t0 + t, rawlog.CLOUD, struct.pack('<dI', t0 + t, len(c)) + c.tobytes())
                continue_cloud = True
            else:
                continue_cloud = False
            cloud = []
            for e in (() if continue_cloud else el):
                for i, a in enumerate(az):
                    r_wall = steps[first[i]] if first[i] >= 0 else None
                    r_floor = LIDAR_H / math.tan(-e) if e < 0 else None
                    r = None
                    if r_floor is not None and (r_wall is None or r_floor < r_wall):
                        r = r_floor
                    elif r_wall is not None and LIDAR_H + r_wall * math.tan(e) < WALL_TOP:
                        r = r_wall
                    if r is None or r > 11.0:
                        continue
                    r += rng.normal(0, 0.01)
                    cloud.append((r * math.cos(e) * math.cos(a), r * math.cos(e) * math.sin(a), r * math.sin(e),
                                  100.0, (i / len(az)) * 0.1))
            if not continue_cloud:
                c = np.asarray(cloud, '<f4')
                rec(t0 + t, rawlog.CLOUD, struct.pack('<dI', t0 + t, len(c)) + c.tobytes())
        if k % 100 == 0:
            rec(t0 + t, rawlog.JSON, json.dumps(dict(event='status', t=t0 + t, synthetic=True,
                                                     chassis_running=False, lidar_h=LIDAR_H)).encode())
    with open(out, 'wb') as f:
        f.writelines(records)
    print('wrote', out, len(records), 'records,', seconds, 's', '(person from %.0f s)' % PERSON_AT_S if person else '')
    if base_out:
        write_base(base_out)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out')
    ap.add_argument('--seconds', type=float, default=20.0)
    ap.add_argument('--person', action='store_true')
    ap.add_argument('--base-out')
    ap.add_argument('--map', help='saved map package shifted to the start frame (tools/shift_map_package.py)')
    ap.add_argument('--from-cloud', action='store_true', help='with --map: take scan points from the package map.ply')
    a = ap.parse_args()
    main(a.out, a.seconds, a.person, a.base_out, a.map, a.from_cloud)

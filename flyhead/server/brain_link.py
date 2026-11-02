"""Link to the fly-brain service (flyhead.fly.service) for brain mode.

Enabled only when the server runs with XT_BRAIN_ENABLED=1. The retina (flyhead.fly.encoders.lidar_loom)
and envelope (flyhead.safety.envelope) are the same modules the offline stages and simulations use;
the server itself never loads the connectome (no torch): it talks to the service over local TCP.
Modes: 'off' | 'shadow' (intents logged, never sent) | 'drive' (stage 5: intent -> envelope ->
geofence -> the normal command path with its 0.3 s lease, clock anchor and battery stop) |
'reflex' (stage 6: the planner drives a navigation task; the brain takes over only while it
freezes or escapes, then the task replans; the retina sees only points away from mapped walls).
The brain decides; this module can only withhold, reduce or zero its command.
"""
import json
import math
import os
import socket
import threading
import time

import numpy as np
from scipy.ndimage import distance_transform_edt, label

from flyhead import paths
from flyhead.fly.encoders.lidar_loom import LidarRetinaV3
from flyhead.safety import envelope as ENV
from flyhead.slam.navmap import ROBOT_HEIGHT

BRAIN_ENABLED = os.environ.get('XT_BRAIN_ENABLED', os.environ.get('XT_BRAIN_DIR') and '1' or '0') == '1'
PORT = int(os.environ.get('XT_BRAIN_PORT', '8095'))
INTENT_MAX_AGE_S = 0.35            # a decoded window older than this is not executed
INPUT_MAX_AGE_S = 0.45             # ... nor one computed from a scan older than this
BAND_LOW_M, BAND_HIGH_M = 0.08, 0.50
MIN_FITNESS = 0.80
DRIVE_LIMITS = dict(v_max=0.15, v_back=0.10, w_max=0.40)
ESCAPE_LIMITS = dict(v_max=0.20, v_back=0.30, w_max=1.0)    # while the brain runs an escape program
ESCAPE_MIN_FITNESS = 0.50          # during an escape: a person close to the LiDAR lowers the match score;
                                   # collisions are guarded by the live scan, the pose only serves the fence
ESCAPE_FENCE_MARGIN_M = 0.5        # an escape may carry the robot this far past the geofence
KEEPIN_CLEARANCE_M = 0.30         # map keep-in: known free cells this far from mapped obstacles (standing height)
KEEPIN_ESCAPE_M = 0.15            # an escape may carry the robot this far outside the map keep-in
HARD_OUT_M = 0.25                 # beyond the allowed edge by more than this nothing moves (RC recovers)
KEEPIN_SLOW_M = 0.30              # inside the keep-in this close to its edge, outward speed is scaled down
KEEPIN_SLOW_MIN = 0.25            # ... to this fraction at the edge (standing needs ~0.8 s to stop)
FAST_STATES = ('ESCAPE_PROGRAM', 'FLEE')   # brain states that may use ESCAPE_LIMITS
REFLEX_STATES = ('FREEZE', 'ESCAPE_PROGRAM')   # reflex mode: brain states that take over from the planner
REFLEX_STATIC_MARGIN_M = 0.20     # reflex mode: band points this close to a mapped obstacle are not shown to
                                  # the retina (the planner already avoids walls; the brain reacts to the rest)
REFLEX_HABITUATE_M = 0.30         # ... nor points within a planner keep-out disc (+ this) left by an earlier
                                  # reflex: the brain habituates to a threat it already escaped (stage6_002)
STAND_GAIN = 1.35                  # standing: measured / commanded speed (learned 1.34 on 2026-10-08)


class BrainLink:
    def __init__(self, session):
        self.s = session
        self.enabled = BRAIN_ENABLED
        self.mode = 'off'
        self.retina = LidarRetinaV3() if self.enabled else None
        self.sock = None
        self.lock = threading.Lock()
        self.seq = 0
        self.intent = None              # latest service row
        self.intent_at = 0.0
        self.body_points = np.zeros((0, 2))
        self.points_at = 0.0
        self.fence = None               # (x, y, radius)
        self.threat_xy = None           # reflex mode: nearest unmapped band point (world), for the planner
        self.keepin = None              # map keep-in: dict(out=metres outside, gx, gy=gradient, nm=NavMap)
        self.last = {}
        self.windows = 0
        if self.enabled:
            threading.Thread(target=self._connect_loop, daemon=True).start()

    # ---------------------------------------------------------------- service connection
    def _connect_loop(self):
        while True:
            try:
                sock = socket.create_connection(('127.0.0.1', PORT), timeout=3)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.settimeout(None)
                with self.lock:
                    self.sock = sock
                buf = b''
                while True:
                    data = sock.recv(65536)
                    if not data:
                        break
                    buf += data
                    while b'\n' in buf:
                        line, buf = buf.split(b'\n', 1)
                        row = json.loads(line)
                        if row.get('type') == 'intent':
                            with self.lock:
                                self.intent, self.intent_at = row, time.time()
                                self.windows += 1
            except (OSError, ValueError):
                pass
            with self.lock:
                self.sock = None
            time.sleep(1.0)

    def connected(self):
        return self.sock is not None and time.time() - self.intent_at < 2.0

    # ---------------------------------------------------------------- per scan (SLAM thread)
    def on_scan(self, nav, world, sensor_xyz):
        if not self.enabled or self.mode == 'off' or nav.pose is None or nav.lidar_h is None:
            return
        _, x, y, yaw = nav.pose
        floor = float(sensor_xyz[2]) - nav.lidar_h
        band = world[(world[:, 2] > floor + BAND_LOW_M) & (world[:, 2] < floor + BAND_HIGH_M)]
        rel = band[:, :2] - [x, y]
        c, s = math.cos(yaw), math.sin(yaw)
        body = np.c_[rel[:, 0] * c + rel[:, 1] * s, -rel[:, 0] * s + rel[:, 1] * c]   # envelope: every point
        seen = body
        if self.mode == 'reflex' and len(band):
            unmapped = ~self._near_static(nav, band[:, :2])
            seen = body[unmapped]                                              # retina: unmapped objects only
            if unmapped.any():
                k = int(np.argmin(np.hypot(seen[:, 0], seen[:, 1])))
                self.threat_xy = tuple(band[unmapped][k, :2])                  # nearest unmapped point (world)
            else:
                self.threat_xy = None
        t = nav.pose[0]                                      # source time on the server clock
        rates, feats = self.retina.step(seen, yaw, t, (x, y))
        with self.lock:
            self.body_points, self.points_at = body, time.time()
            sock = self.sock
        self.seq += 1
        msg = dict(type='rates', seq=self.seq, t=t, rates={'%s_%s' % k: round(v, 2) for k, v in rates.items()})
        self.last['features'] = {k: v for k, v in feats.items() if k != 'world_ranges_m'}
        if sock is not None:
            try:
                sock.sendall((json.dumps(msg) + '\n').encode())
            except OSError:
                pass

    def _near_static(self, nav, xy):
        nm = nav.nm
        key = ('reflex_static', round(ROBOT_HEIGHT['stand'], 2))
        mask = nm._block_cache.get(key)
        if mask is None:
            mask = nm.clearance_for(ROBOT_HEIGHT['stand']) <= REFLEX_STATIC_MARGIN_M
            nm._block_cache[key] = mask
        ij = nm.to_ij(xy)
        ok = nm.inside(ij)
        near = np.ones(len(xy), bool)                     # outside the map counts as mapped surroundings
        near[ok] = mask[ij[ok, 0], ij[ok, 1]]
        now = time.time()
        for kx, ky, kr, until in getattr(nav, 'keepouts', []):
            if until > now:
                near |= np.hypot(xy[:, 0] - kx, xy[:, 1] - ky) <= kr + REFLEX_HABITUATE_M
        return near

    # ---------------------------------------------------------------- per control cycle
    def set_mode(self, mode, radius=None, area=None):
        if not self.enabled:
            return 'Brain mode is not available (server started without XT_BRAIN_ENABLED=1)'
        if mode == 'drive':
            nav = self.s.nav
            if nav is None or nav.pose is None:
                return 'Brain drive needs a localized session'
            if area == 'map':
                keepin, why = self._map_keepin(nav)
                if why:
                    return why
                self.fence, self.keepin = None, keepin
            else:
                self.fence, self.keepin = (nav.pose[1], nav.pose[2], float(radius or 2.0)), None
        if mode == 'reflex':
            self.fence, self.keepin = None, None
        self.mode = mode
        return None

    def _map_keepin(self, nav):
        """Free mapped floor reachable from the robot: known cells >= KEEPIN_CLEARANCE_M from static obstacles."""
        nm = nav.nm
        free = (nm.clearance_for(ROBOT_HEIGHT['stand']) >= KEEPIN_CLEARANCE_M) & ~nav.planning_unknown()
        lab, _ = label(free)
        ij = nm.to_ij(np.array([nav.pose[1:3]]))[0]
        if not nm.inside(ij) or lab[ij[0], ij[1]] == 0:
            return None, 'Brain drive refused: the robot is not inside the map keep-in (>= %.2f m from mapped obstacles)' % KEEPIN_CLEARANCE_M
        region = lab == lab[ij[0], ij[1]]
        excluded = self._excluded(nm)
        if excluded is not None:
            if excluded[ij[0], ij[1]]:
                return None, 'Brain drive refused: the robot is in an excluded part of the map keep-in'
            region &= ~excluded
        # signed distance to the keep-in edge: > 0 outside, < 0 inside
        sd = ((distance_transform_edt(~region) - distance_transform_edt(region)) * nm.res).astype(np.float32)
        gx, gy = np.gradient(sd)                  # map index 0 is x, 1 is y; points outward
        return dict(nm=nm, sd=sd, gx=gx, gy=gy, area_m2=round(float(region.sum()) * nm.res ** 2, 1)), None

    @staticmethod
    def _excluded(nm):
        """Cells left out of the keep-in (configs/fly/keepin_exclude.json, for the map it names only)."""
        path = str(paths.keepin_exclude_path())
        if not os.path.exists(path):
            return None
        cfg = json.load(open(path))
        if cfg.get('map') != nm.pkg.name:
            return None
        ii, jj = np.indices(nm.shape)
        x = nm.origin[0] + (ii + 0.5) * nm.res
        y = nm.origin[1] + (jj + 0.5) * nm.res
        mask = np.zeros(nm.shape, bool)
        for cx, cy, r in cfg.get('circles', []):
            mask |= (x - cx) ** 2 + (y - cy) ** 2 <= r * r
        return mask

    def _edge(self, x, y, escaping):
        """(metres beyond the allowed edge, unit vector pointing back inside, label) for the fence or keep-in."""
        if self.keepin is not None:
            k = self.keepin
            ij = k['nm'].to_ij(np.array([[x, y]]))[0]
            if not k['nm'].inside(ij):
                return math.inf, (0.0, 0.0), 'map keep-in'
            g = np.array([k['gx'][ij[0], ij[1]], k['gy'][ij[0], ij[1]]])
            n = float(np.hypot(*g))
            inward = tuple(-g / n) if n > 0 else (0.0, 0.0)
            return float(k['sd'][ij[0], ij[1]]) - (KEEPIN_ESCAPE_M if escaping else 0.0), inward, 'map keep-in'
        fx, fy, fr = self.fence or (x, y, math.inf)                      # shadow: no fence is set
        r = math.hypot(x - fx, y - fy)
        inward = ((fx - x) / r, (fy - y) / r) if r > 0 else (0.0, 0.0)
        return r - fr - (ESCAPE_FENCE_MARGIN_M if escaping else 0.0), inward, 'geofence %.1f m' % fr

    def command(self, now):
        """(v, w, record) for drive mode; (0, 0, record) whenever anything is not right."""
        with self.lock:
            row, at, pts, pts_at = self.intent, self.intent_at, self.body_points, self.points_at
        rec = dict(mode=self.mode, connected=self.connected())
        nav = self.s.nav
        why = None
        if row is None or now - at > INTENT_MAX_AGE_S:
            why = 'no fresh brain window'
        elif row.get('stale') or row.get('input_age_s') is None or row['input_age_s'] > INPUT_MAX_AGE_S:
            why = 'brain input stale'
        elif nav is None or nav.pose is None or now - pts_at > INPUT_MAX_AGE_S:
            why = 'no fresh scan'
        elif nav.fitness is None or nav.fitness < (
                ESCAPE_MIN_FITNESS if row['intent']['state'] == 'ESCAPE_PROGRAM' else MIN_FITNESS):
            why = 'localization fitness %.2f' % (nav.fitness or 0)
        if row is not None:
            rec.update(window=row['window'], state=row['intent']['state'], brain_v=row['intent']['v'],
                       brain_w=row['intent']['w'], input_age_s=row.get('input_age_s'), brain_ms=row.get('brain_ms'))
        if self.mode == 'reflex' and not why and row['intent']['state'] not in REFLEX_STATES:
            why = 'reflex mode: planner drives (%s)' % row['intent']['state']
        if why:
            rec.update(v=0.0, w=0.0, withheld=why, takeover=False)
            self.last['record'] = rec
            return 0.0, 0.0, rec
        escaping = row['intent']['state'] == 'ESCAPE_PROGRAM'
        lim = ESCAPE_LIMITS if row['intent']['state'] in FAST_STATES else DRIVE_LIMITS
        v = max(-lim['v_back'], min(lim['v_max'], row['intent']['v']))
        w = max(-lim['w_max'], min(lim['w_max'], row['intent']['w']))
        # the envelope's stop rule works on the speed the robot really moves at
        standing = nav.hardware_stand is True or nav.mode == 'stand'
        gain = STAND_GAIN if standing else 1.0
        v2, w2, env_why = ENV.limit(pts, v * gain, w)
        v2 /= gain
        _, x, y, yaw = nav.pose
        over, (ix, iy), edge = self._edge(x, y, escaping)
        if over > HARD_OUT_M:
            v2, w2, env_why = 0.0, 0.0, (env_why or '') + ' %s: %.2f m outside, stopped' % (edge, over)
        elif over > 0:
            # outside: only translation back inside, and only turns that bring the heading toward the inside
            # (standing in-place turns displace the body, so unrestricted turning lets it creep outward)
            hx, hy = math.cos(yaw), math.sin(yaw)
            if v2 * (hx * ix + hy * iy) <= 0:
                v2 = 0.0
            a = math.atan2(hx * iy - hy * ix, hx * ix + hy * iy)    # heading -> inside, signed
            if w2 * a <= 0 and abs(a) < 2.6:
                w2 = 0.0
            env_why = (env_why or '') + ' ' + edge
        elif self.keepin is not None and over > -KEEPIN_SLOW_M and v2 * (math.cos(yaw) * ix + math.sin(yaw) * iy) < 0:
            # close to the edge and moving toward it: slow down so the standing stop lag ends inside
            v2 *= max(KEEPIN_SLOW_MIN, -over / KEEPIN_SLOW_M)
            env_why = (env_why or '') + ' keep-in slow'
        if self.keepin is not None:
            rec.update(keepin_out=round(over + (KEEPIN_ESCAPE_M if escaping else 0.0), 2), arousal=row['intent'].get('arousal'))
        elif self.fence is not None:
            rec.update(fence_r=round(math.hypot(x - self.fence[0], y - self.fence[1]), 2))
        rec.update(takeover=self.mode == 'reflex')
        rec.update(v=round(v2, 3), w=round(w2, 3), envelope=env_why, standing=standing,
                   pose=[round(x, 3), round(y, 3), round(yaw, 3)], fitness=round(nav.fitness, 3))
        self.last['record'] = rec
        return v2, w2, rec

    def status(self):
        rec = self.last.get('record') or {}
        return dict(enabled=self.enabled, mode=self.mode, connected=self.connected() if self.enabled else False,
                    windows=self.windows, fence=self.fence,
                    keepin=self.keepin and dict(area_m2=self.keepin['area_m2'], clearance_m=KEEPIN_CLEARANCE_M), last=rec, features=self.last.get('features'))

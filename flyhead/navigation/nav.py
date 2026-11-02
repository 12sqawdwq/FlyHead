"""Navigation on the saved SLAM map: planning, tracking and the host safety chain.

The navigator steers the robot's measured turning point (REFERENCE_BODY), the point that
stays fixed when the robot turns in place; every pose, clearance and arrival test uses it.
Routes come from planning.py: they follow the centreline of the free space (equal
clearance to both sides) and keep at least HARD_CLEARANCE_M from every obstacle.

A committed route is never re-planned on a timer.  It changes only when
  * a new obstacle on the route is confirmed (debounced) -> a local detour is spliced in,
  * the robot has been off the route for TRACK_REJOIN_S -> a short rejoin path is spliced in.
Tracking is pure pursuit on the route's arc-length progress (bounded window, so a route
that passes the same place twice never jumps), with hysteretic turns in place and
command acceleration limits.  Commands leave through the server's 0.3 s lease path; the
host chain in control_target is the single stop / slow / detour authority.
"""
import math
import threading
import time
from collections import deque

import numpy as np
from scipy.ndimage import binary_dilation, label, maximum_filter1d, uniform_filter

from . import planning as P
from flyhead.slam.navmap import ADD_HITS, ROBOT_HEIGHT, ChangeTracker, LiveLayer, NavMap

# ---- robot model ----
# Turning point in the body frame (x forward), relative to the LiDAR.  Fitted from 47 turns in
# place in four runs (live_20261008T103347 .. T113059): the point that stays fixed lies
# 0.56 +- 0.02 m behind and 0.06 m right of the old 'body centre' 0.45 m ahead of the LiDAR,
# i.e. 0.11 m behind the LiDAR.  Steering the old point made every turn swing it 0.45 m per
# 46 deg and let the real body cut inside every curve.
REFERENCE_BODY = (-0.11, -0.01, 0.0)
ROBOT_RADIUS = P.ROBOT_RADIUS
# ---- speeds and turning ----
V_MAX = 0.10
W_MAX = 0.20                  # tracking angular ceiling, rad/s
W_TRACK_LIMIT = 0.60          # operator ceiling for the tracking turn rate
W_ROTATE_IN_PLACE = 0.12      # rad/s default for turns in place; faster pure rotation made the pose
                              # estimate jump with the old reference point (live_20261006T224145)
W_ROTATE_LIMIT = 0.30         # operator ceiling for turns in place (raise only with pose evidence)
ROTATE_ENTER = math.radians(50)
ROTATE_EXIT = math.radians(12)
ROTATE_SIGN_AMBIGUOUS = math.radians(150)   # beyond this the error's sign is noise: keep the turn direction
LINEAR_ACCEL = 0.10           # command m/s^2
LINEAR_DECEL = 0.20
ANGULAR_ACCEL = 0.80          # command rad/s^2
ANGULAR_DECEL = 1.20
CONTROL_DT_MAX = 0.20
COMMAND_ZERO = 1e-6
LOOKAHEAD_MIN_M = 0.5         # pursuit lookahead: MIN + GAIN * speed, at most MAX
LOOKAHEAD_GAIN_S = 4.0
LOOKAHEAD_MAX_M = 1.0
CURVE_LOOKAHEAD_M = 0.6       # route curvature considered for the speed cap
CURVE_MIN_V = 0.06            # the curve cap never goes below this: a route kink (kappa ~10) with the
                              # 0.20 rad/s turn rate gave 0.02 m/s, which does not move the robot;
                              # pursuit (v <= w_max/kappa) and turns in place handle sharp corners
SLOW_CLEARANCE_M = 0.80       # route clearance below this lowers the speed (to half at the hard clearance)
GOAL_TOL = 0.20
TOUR_TOL = 0.30
GOAL_DECEL = 0.5              # allowed speed (m/s) per metre to the end of the route
# ---- route following ----
PROGRESS_BACK_M = 0.30        # progress window behind the current progress (pose noise)
PROGRESS_BACK_RECOVERY_M = 1.5    # ... after a recovery reversal
TRACK_REJOIN_M = 0.50         # off the route by more than this for TRACK_REJOIN_S -> rejoin path
TRACK_REJOIN_S = 2.0
TRACK_ABORT_M = 1.50          # off the route by more than this: stop the task
REJOIN_AHEAD_M = (1.0, 1.5, 2.5, 3.5)
# At a cusp (an out-and-back turnaround) the outbound and return legs lie on one line, so
# projection cannot tell them apart: progress stuck at the tip of the first branch and the
# robot circled a target next to it (simulation, 600 s at 18.9 m).  Progress and the pursuit
# target stop at the next cusp; within CUSP_REACH_M progress steps across and the robot
# turns in place onto the return leg.
CUSP_REACH_M = 0.15
# ---- obstacles on the route ----
BLOCK_LOOKAHEAD_M = 3.0       # route checked ahead for new (unmapped) obstacles
BLOCK_RADIUS_M = ROBOT_RADIUS + 0.05
BLOCK_CONFIRM_CYCLES = 3      # consecutive control cycles before the route counts as blocked
BLOCK_CLEAR_S = 1.0           # clear this long before it counts as free again
BLOCK_STOP_GAP_M = 0.50       # approach a confirmed obstacle to this arc distance at most
DETOUR_RETRY_S = 3.0
DETOUR_RADIUS_M = 6.0
DETOUR_REJOIN_M = (0.8, 1.5, 2.5, 4.0)   # rejoin this far beyond the obstacle
DETOUR_MAX_RATIO = 3.0        # detour length <= ratio * replaced length + 2 m
BLOCKED_GIVEUP_S = 60.0       # goal legs: give up after this long blocked (tours wait)
# ---- host safety chain ----
HOST_STOP_M = 0.35            # swept free travel kept as a margin after a full stop
HOST_SLOW_M = 0.70
# Speed-dependent stopping.  A fixed stop distance is only right at one speed: at 0.30 m/s the
# robot travels ~0.18 m before it even reacts (pose up to 0.5 s old + 0.1 s control period)
# and then brakes.  The allowed speed is the highest one whose reaction + braking distance
# fits in the free travel ahead minus HOST_STOP_M.  REACT_S and BRAKE_DECEL are conservative
# until measured stops replace them.
REACT_S = 0.6
BRAKE_DECEL = 0.20            # m/s^2
HOST_BACKSTOP_M = 0.15        # chassis guard nearest (any direction) that stops regardless
HOST_MIN_SPEED = 0.02         # a speed cap below this cannot move the robot: treat it as blocked
SWEEP_STEP_M = 0.05
SWEEP_RANGE_M = 3.0          # covers the stopping distance at the highest (Turbo) speed
SWEEP_RADIUS_M = ROBOT_RADIUS * 0.8
BODY_INNER_M = 0.25           # returns this close to the turning point are body residue
STALL_SPEED = 0.08            # commanded forward speed that must move the robot ...
STALL_S = 2.0                 # ... within this time ...
STALL_MOVE_M = 0.05           # ... by at least this much
STALL_CLEAR_M = 0.20
RECOVER_DELAY_S = 8.0         # blocked this long without a detour -> reverse a little
RECOVER_V = 0.08
RECOVER_REVERSE_MAX_S = 15.0   # reversing that moved < RECOVER_STUCK_M in this time gives up: 2026-10-09
RECOVER_STUCK_M = 0.10         # the standing robot swayed 0.02-0.06 m at -0.08 m/s for 11 min
RECOVER_MAX_M = 0.60
RECOVER_REAR_STOP_M = 0.25
RECOVER_WAIT_S = 2.0
RECOVER_CYCLES = 3
RECOVER_RESET_M = 2.0
# ---- Turbo ----
# Fast laps that stay safe.  Plain pursuit overshot every bend above 0.40 m/s (0.72 m at 0.60,
# 2026-10-08) because the curve cap looked 0.6 m ahead only.  Turbo plans a speed profile along
# the route instead: the bend speed from the lateral acceleration and the turn rate, then a
# backward pass so the robot brakes *before* each bend.  Speeds in Turbo are measured speeds:
# standing, the robot drives 1.2-2x the command, so the command is divided by a running
# measured/commanded estimate (TURBO_GAIN_*) and the stop rule uses the measured stop of
# 2026-10-08 (0.63 m/s -> 0.74 m in 1.42 s, about 0.8 s + 0.8 m/s^2) with margin.
TURBO_V_LIMIT = 1.0           # m/s measured; the server ceiling XT_MAX_V must allow the command too
TURBO_ACCEL = 0.35            # command ramp, m/s^2
TURBO_RAMP_DECEL = 0.60       # command ramp down (safety caps cut immediately anyway)
TURBO_PLAN_DECEL = 0.35       # m/s^2 planned braking into bends (well below the measured 0.8)
# 2026-10-08 23:09 the pose slipped 0.5 m at 0.75 m/s measured with a 0.37 rad/s turn
# (v*w ~ 0.28 m/s^2): fast turning at speed is what the LiDAR odometry cannot follow.
TURBO_LAT_ACCEL = 0.15        # m/s^2 planned in bends: v <= sqrt(a / kappa)
TURBO_VW_MAX = 0.18           # m/s * rad/s, measured speed x turn rate allowed while driving
TURBO_W_TRACK = 0.80          # rad/s driving turn rate in Turbo
TURBO_CHORD_M = 1.0           # bend curvature = heading change over a chord this long (the scale the
                              # robot follows; pointwise curvature of the centreline is mostly wiggle)
TURBO_CURVE_WINDOW_M = 0.3    # ... then the maximum over +- this
TURBO_SAGITTA_M = 0.08        # Turbo lookahead is shortened in bends so the chord cuts at most this
TURBO_PREVIEW_S = 0.6         # profile minimum over the next v * this (pose age + control period)
TURBO_REACT_S = 0.8
TURBO_BRAKE_DECEL = 0.50
# route clearance (m) -> Turbo speed cap (m/s): narrow places stay slow
TURBO_NARROW = ((P.HARD_CLEARANCE_M, 0.25), (0.80, 0.45), (1.20, TURBO_V_LIMIT))
TURBO_FIT_FULL = 0.95         # Turbo speed falls linearly from full at this fitness ...
TURBO_MIN_FITNESS = 0.85      # ... to TURBO_FALLBACK_V at this one (and below)
TURBO_FALLBACK_V = 0.30
TURBO_POSE_FULL_S = 0.35      # pose-age speed ramp in Turbo (0.35 m blind at 1 m/s)
TURBO_POSE_ZERO_S = 0.70
TURBO_LOOKAHEAD_MAX_M = 1.8
TURBO_GAIN_RANGE = (0.8, 1.6) # bounds of the measured / commanded speed estimate
TURBO_GAIN_ALPHA = 0.12
TURBO_GAIN_STAND_START = 1.3   # standing start value until measured (0.58 command -> 0.69 m/s)
NORMAL_V_LIMIT = 0.40         # outside Turbo (fastest measured lap, 2026-10-08)
# ---- pose / map freshness ----
POSE_STALE_S = 3.0
REFLEX_HOLD_S = 0.3            # the fly-brain reflex holds the task this long after its last cycle
REFLEX_REJOIN_GIVEUP_S = 15.0  # after a reflex: no way back onto the tour route within this -> stop
REFLEX_KEEPOUT_R_M = 0.60      # after a reflex, plans keep this disc around the threat point blocked ...
REFLEX_KEEPOUT_S = 30.0        # ... for this long (stage6_001: replanned detours led back past the person)
POSE_FULL_SPEED_S = 0.5       # speed falls to zero between these pose ages (driving blind)
POSE_ZERO_SPEED_S = 1.0
POSE_RESUME_FRAMES = 5
MIN_FITNESS = 0.6
LOW_FIT_CRAWL = 0.80           # below this fitness (any mode) crawl until it recovers or the drift
LOW_FIT_CRAWL_V = 0.15         # alarm relocalizes: a slipping pose must not be driven at speed
FITNESS_HOLD_S = 1.0
OCCLUSION_NEAR_M = 1.0
OCCLUSION_WAIT_S = 20.0
# ---- posture ----
STAND_ENTER_H = 0.27
STAND_EXIT_H = 0.25
ROBOT_TOP_ABOVE_LIDAR = 0.12
TOUR_HEIGHT_RESERVE_M = 0.10
# Unknown map cells block planning, but the base map is dotted with tiny unknown specks:
# floor pixels no beam happened to hit.  Each one acted as an obstacle in the middle of the
# floor; a 2.5 m wide passage at (-2.5, -2.8) shrank to 0.46 m and every goal west of it had
# no path (2026-10-08).  Unknown patches of at most this many cells (0.04 m^2) are treated as
# floor for planning; larger unknown areas still block.  Real obstacles there are still seen
# by the live layer, the route-blockage check and the host safety chain.
UNKNOWN_SPECK_CELLS = 16
# The height comes from the LiDAR height above the map floor, so a floor-estimate error makes
# a crouched robot look taller; that alone ended live_20261008T101201 ("height exceeds the
# planned tour height").  With the chassis reporting 'not standing' the excess is ignored;
# otherwise the tour holds this long before it is cancelled.
TOUR_HEIGHT_HOLD_S = 10.0
TOUR_SUPPORT_WINDOW_M = 1.0   # loop centreline must lie on ground mapped at least this well ...
TOUR_SUPPORT_MIN = 0.6        # ... (known fraction within the window)

STATE_TEXT = {'explore': 'Heading to the exploration point', 'home': 'Returning to the start point',
              'tour': 'Tour: following the centreline route'}


class Navigator:
    """Owns the map layers, the committed route and the control decision chain."""

    def __init__(self, pkg, out_dir, on_commit=None):
        self.nm = NavMap(pkg)
        self.live = LiveLayer(self.nm)
        self.changes = ChangeTracker(self.nm, out_dir, on_commit)
        self.lock = threading.Lock()
        self.goal = None
        self.route = None             # planning.Route being followed
        self.route_revision = 0
        self.progress = 0.0           # arc position on self.route
        self.progress_offset = 0.0    # tour distance before the current route (splices)
        self.tracking_error = 0.0
        self.off_route_since = None
        self.active = False
        self.state = 'idle'
        self.reason = ''
        self.leg = None               # None | 'explore' | 'home' | 'tour'
        self.home = None
        self.pose = None              # (stamp, x, y, yaw) of the turning point
        self.pose_mono = None
        self.source_clock_valid = False
        self.source_stamp = None
        self.input_received_at = None
        self.processing_started_at = None
        self.pose_age_basis = 'source_and_ingress'
        self.fitness = None
        self.pitch = None
        self.mode = 'crouch'
        self.hardware_stand = None
        self.lidar_h = None
        self.control_layer = None
        self.live_update_ms = self.changes_update_ms = self.raycast_ms = 0.0
        self.map_update_error = None
        self.robot_guard = None
        self.v_max, self.w_max, self.w_rotate = V_MAX, W_MAX, W_ROTATE_IN_PLACE
        self.turbo = False
        self.speed_gain = 1.0          # measured / commanded forward speed (running estimate)
        self.measured_v = None
        self.pose_track = deque(maxlen=40)
        self.command_track = deque(maxlen=40)
        self._profile = None           # (route, key, speeds) Turbo speed profile cache
        self.profile_cap = None
        self.loop_info = None
        self.tour_planning = False
        self.tour_route_height = None
        self.detour_count = 0
        self.detour_reason = ''
        self.last_detour = None
        self.plan_ms = None
        self._costmaps = {}
        self.pause_until = 0.0
        self.reflex_until = 0.0        # fly-brain reflex (server brain mode 'reflex') has control until then
        self.reflex_why = ''
        self.reflex_engaged = False
        self.reflex_resume = None      # (route revision, since) while rejoining the tour after a reflex
        self.reflex_count = 0
        self.keepouts = []             # [(x, y, radius, until)] threat points from fly-brain reflexes
        self.detour_attempt_at = 0.0
        self.taller_since = None
        self.low_fit_since = None
        self.pose_resume_required = False
        self.pose_resume_frames = 0
        self.pose_resume_stamp = None
        self.reset_blockage()
        self.reset_recovery()
        self.reset_controller()
        self.plan_req = threading.Event()
        self.plan_kind = None         # 'goal' | 'detour' | 'rejoin'
        self.stop_evt = threading.Event()
        self.pending_scan = None
        self.scan_evt = threading.Event()
        self.pending_rays = None
        self.ray_evt = threading.Event()
        threading.Thread(target=self.live_loop, name='live-obstacles', daemon=True).start()
        threading.Thread(target=self.changes_loop, name='map-evidence', daemon=True).start()
        threading.Thread(target=self.plan_loop, name='route-planner', daemon=True).start()

    # ------------------------------------------------------------------ inputs
    def feed(self, Wb, sensor_xyz, world, fitness, received_at=None, source_stamp=None,
             processing_started_at=None):
        c = Wb[:3, :3] @ np.array(REFERENCE_BODY) + Wb[:3, 3]
        now = time.time()
        ingress = now if received_at is None else received_at
        self.source_clock_valid = (source_stamp is not None and math.isfinite(source_stamp)
                                   and math.isfinite(ingress) and source_stamp <= ingress + 0.25)
        stamp = min(ingress, source_stamp) if self.source_clock_valid else ingress
        self.source_stamp = source_stamp
        self.input_received_at = received_at
        self.processing_started_at = processing_started_at
        self.fitness = fitness
        observed_mono = time.monotonic() - (now - stamp)
        self.pose_mono = observed_mono
        self.pose = (stamp, float(c[0]), float(c[1]), math.atan2(Wb[1, 0], Wb[0, 0]))
        self.update_measured_speed(stamp, float(c[0]), float(c[1]))
        self.pitch = math.degrees(math.asin(max(-1.0, min(1.0, -Wb[2, 0]))))
        f = self.nm.floor_at(sensor_xyz[None, :2])[0]
        if np.isfinite(f):
            self.lidar_h = float(sensor_xyz[2] - f)
            if self.mode == 'crouch' and self.lidar_h > STAND_ENTER_H:
                self.mode = 'stand'
            elif self.mode == 'stand' and self.lidar_h < STAND_EXIT_H:
                self.mode = 'crouch'
            if self.mode == 'crouch':
                self.live.lidar_h_guess = self.lidar_h
        with self.lock:
            self.pending_scan = (sensor_xyz, world, self.robot_height(), stamp, self.pose[1:3], observed_mono)
        self.scan_evt.set()

    def pose_age(self):
        if self.pose is None:
            return float('inf')
        wall_age = time.time() - self.pose[0]
        mono_age = wall_age if self.pose_mono is None else time.monotonic() - self.pose_mono
        return max(wall_age, mono_age)

    @staticmethod
    def layer_age(layer):
        if layer is None:
            return float('inf')
        wall_age = time.time() - layer[2]
        mono_age = wall_age if len(layer) < 6 else time.monotonic() - layer[5]
        return max(wall_age, mono_age)

    def live_loop(self):
        while not self.stop_evt.is_set():
            if not self.scan_evt.wait(0.5):
                continue
            self.scan_evt.clear()
            with self.lock:
                item, self.pending_scan = self.pending_scan, None
            if item is None:
                continue
            try:
                started = time.monotonic()
                ray_inputs = self.live.update(*item[:4])
                hits, passes, observed_at = self.live.published
                obstacles = self.new_obstacles(hits, height=item[2])
                obstacles.setflags(write=False)
                self.control_layer = (hits, passes, observed_at, item[2], obstacles, item[5])
                self.live_update_ms = (time.monotonic() - started) * 1000
                with self.lock:
                    self.pending_rays = (*ray_inputs, hits, np.asarray(item[4]))
                self.ray_evt.set()
            except Exception as exc:
                self.reason = 'live layer error: %r' % exc

    def changes_loop(self):
        deadline = time.monotonic()
        while not self.stop_evt.wait(max(0.0, deadline - time.monotonic())):
            if not self.ray_evt.wait(0.5):
                continue
            self.ray_evt.clear()
            with self.lock:
                item, self.pending_rays = self.pending_rays, None
            if item is None:
                continue
            started = time.monotonic()
            deadline = started + 1.0
            try:
                sensor, targets, hits, position = item
                passes = self.live.update_passes(sensor, targets)
                self.raycast_ms = (time.monotonic() - started) * 1000
                if self.stop_evt.is_set():
                    return
                changed_at = time.monotonic()
                self.changes.step(hits, passes, robot_xy=position)
                self.changes_update_ms = (time.monotonic() - changed_at) * 1000
                self.map_update_error = None
            except Exception as exc:
                self.map_update_error = repr(exc)

    def robot_height(self):
        if self.hardware_stand is False:
            # The chassis reports a crouched body: its height is fixed.  Deriving it from the
            # LiDAR height above the (imperfect) map floor flickered between 5 cm steps.
            return ROBOT_HEIGHT['crouch']
        height = ROBOT_HEIGHT[self.mode] if self.lidar_h is None else (
            round(float(np.clip(self.lidar_h + ROBOT_TOP_ABOVE_LIDAR, 0.25, 1.2)) * 20) / 20)
        if self.hardware_stand is True:      # a low floor estimate must not shrink a standing body
            height = max(height, ROBOT_HEIGHT['stand'])
        return height

    # ------------------------------------------------------------------ map views
    def new_obstacles(self, hits, height=None):
        """Live obstacle cells that are not known static structure (+-0.1 m)."""
        h = self.robot_height() if height is None else height
        key = ('near', round(h, 2))
        near = self.nm._block_cache.get(key)
        if near is None:
            near = binary_dilation(self.nm.blocked_for(h), np.ones((5, 5)))
            self.nm._block_cache[key] = near
        return (hits >= ADD_HITS * 0.75) & ~near

    def static_blocked(self, height):
        with self.changes.lock:
            return (self.nm.blocked_for(height) & ~self.changes.removed) | self.changes.added

    def planning_unknown(self):
        """Unknown cells that block planning: the map's unknown space without tiny specks."""
        cached = self.nm._block_cache.get('planning_unknown')
        if cached is None:
            unknown = self.nm.static == 205
            lab, _ = label(unknown)
            sizes = np.bincount(lab.ravel())
            speck = sizes <= UNKNOWN_SPECK_CELLS
            speck[0] = False
            cached = unknown & ~speck[lab]
            self.nm._block_cache['planning_unknown'] = cached
        return cached

    def costmap(self, height):
        """Static map + committed changes at this height (cached per change version)."""
        key = (round(height, 2), self.changes.version)
        cm = self._costmaps.get(key)
        if cm is None:
            cm = P.Costmap(self.static_blocked(height), self.planning_unknown(), self.nm.origin, self.nm.res)
            self._costmaps = {key: cm}
        return cm

    def planning_costmap(self, height):
        """Costmap for a plan made now: static map + committed changes, plus the confirmed
        live obstacles when there are any.  The live obstacles must enter the clearance
        field itself, not only the A* grid: smoothing pulls routes onto the centreline of
        the field, and with the static field alone it pulled a detour straight back
        through the obstacle it was planned around (simulation: 986 detours in 300 s)."""
        layer = self.control_layer
        live = None if layer is None else self.new_obstacles(layer[0], height=layer[3])
        keep = self.keepout_mask()
        if keep is not None:
            live = keep if live is None else live | keep
        if live is None or not live.any():
            return self.costmap(height)
        return P.Costmap(self.static_blocked(height) | live, self.planning_unknown(), self.nm.origin, self.nm.res)

    def add_keepout(self, xy, radius=REFLEX_KEEPOUT_R_M, ttl=REFLEX_KEEPOUT_S):
        """Block a disc around a fly-brain threat point for later plans (never over the robot itself)."""
        if xy is None:
            return
        self.keepouts = [k for k in self.keepouts if k[3] > time.time()] + [
            (float(xy[0]), float(xy[1]), float(radius), time.time() + ttl)]

    def keepout_mask(self):
        now = time.time()
        self.keepouts = [k for k in self.keepouts if k[3] > now]
        if not self.keepouts:
            return None
        ii, jj = np.indices(self.nm.shape)
        mask = np.zeros(self.nm.shape, bool)
        for x, y, r, _ in self.keepouts:
            if self.pose is not None:     # shrink so the disc never covers the robot itself (plan start)
                r = min(r, math.hypot(x - self.pose[1], y - self.pose[2]) - ROBOT_RADIUS - 0.05)
            if r <= self.nm.res:
                continue
            ci, cj = self.nm.to_ij(np.array([x, y]))
            n = int(r / self.nm.res) + 1
            sub = (slice(max(0, ci - n), ci + n + 1), slice(max(0, cj - n), cj + n + 1))
            mask[sub] |= (ii[sub] - ci) ** 2 + (jj[sub] - cj) ** 2 <= (r / self.nm.res) ** 2
        return mask

    def weak_map_mask(self):
        """Map cells on weakly mapped ground (known fraction below TOUR_SUPPORT_MIN nearby)."""
        known = (self.nm.static != 205).astype(np.float32)
        window = max(3, int(round(TOUR_SUPPORT_WINDOW_M / self.nm.res)))
        weak = uniform_filter(known, size=window, mode='constant') < TOUR_SUPPORT_MIN
        return binary_dilation(weak, P.disk(ROBOT_RADIUS / self.nm.res))

    # ------------------------------------------------------------------ tasks
    def reset_controller(self):
        self.controller_mode = 'track'
        self.command = (0.0, 0.0)
        self.command_target = (0.0, 0.0)
        self.command_time = time.monotonic()
        self.heading_error = 0.0
        self.curvature = 0.0
        self.turn_sign = 1.0
        self.speed_limit = None
        self.safety_v_cap = 0.0
        self.safety_stop = True
        self.preserve_turn_mode = False
        self.limit_override = False
        self.control_interval_s = None
        self.lookahead_target = None

    def reset_blockage(self):
        """Forget the blockage state of the previous route (the detour retry timer is kept:
        resetting it let a still-blocked robot request a new detour every cycle)."""
        self.block_cycles = 0
        self.block_clear_since = None
        self.block_confirmed = False
        self.block_at = None          # arc distance ahead of the robot
        self.block_point = None
        self.blocked_since = None
        self.last_path_blocked = False
        self.guard_v_cap = V_MAX
        self.front_clearance_m = self.rear_clearance_m = None

    def reset_recovery(self):
        self.recover_state = 'idle'
        self.recover_from = None
        self.recover_since = 0.0
        self.recover_cycles = 0
        self.recover_anchor = None
        self.recover_stuck = None
        self.progress_back_m = PROGRESS_BACK_M
        self.stall_latched = False
        self.stall_since = self.stall_from = None

    @property
    def path(self):
        route = self.route
        return None if route is None else route.points

    @property
    def tour_arc(self):
        route = self.route
        return None if route is None or self.leg != 'tour' else route.arc + self.progress_offset

    @property
    def tour_progress_m(self):
        return self.progress_offset + self.progress if self.leg == 'tour' else 0.0

    @property
    def guard_recover_state(self):        # name kept for the status consumers
        return self.recover_state

    def install_route(self, points, height, keep_offset=False):
        """Commit a route (caller holds the lock)."""
        cm = self.costmap(height)
        if keep_offset:
            self.progress_offset += self.progress
        else:
            self.progress_offset = 0.0
        self.route = P.Route(points, cm.field)
        self.progress = 0.0
        self.tracking_error = 0.0
        self.off_route_since = None
        self.route_revision += 1
        self.reset_blockage()

    def set_goal(self, x, y):
        with self.lock:
            if self.leg == 'tour':
                self.leg = None
                self.loop_info = None
            self.reset_controller()
            self.goal = (float(x), float(y))
            self.route = None
            self.route_revision += 1
            self.state = 'planning'
            self.reason = ''
            self.plan_kind = 'goal'
        self.plan_req.set()

    def start(self):
        if self.goal is None:
            return False, 'Set a goal on the map first'
        self.reset_controller()
        self.reset_blockage()
        self.reset_recovery()
        self.active = True
        self.low_fit_since = None
        self.reflex_until, self.reflex_engaged, self.reflex_resume = 0.0, False, None
        if self.route is None:
            self.state = 'planning'
            self.plan_kind = 'goal'
            self.plan_req.set()
        else:
            self.state = 'driving'
            self.reason = STATE_TEXT.get(self.leg, 'Following the route')
        return True, ''

    def start_mission(self, goal):
        """Go to goal, pause, then come back to where we started."""
        self.home = (float(self.pose[1]), float(self.pose[2]))
        self.leg = 'explore'
        self.set_goal(*goal)
        return self.start()

    def go_home(self):
        if self.home is None:
            return False, 'No start point recorded'
        self.leg = 'home'
        self.set_goal(*self.home)
        return self.start()

    def reflex_hold(self, why):
        """The fly brain's reflex commands the robot this cycle; the task holds and replans afterwards."""
        self.reflex_until = time.time() + REFLEX_HOLD_S
        self.reflex_why = why

    def cancel(self, why='Stopped'):
        with self.lock:
            self.reset_controller()
            self.route_revision += 1
            if self.active:
                self.active = False
                self.state = 'stopped'
                self.reason = why

    def set_turbo(self, on):
        """Turbo on/off.  Off clamps the speed limit back to NORMAL_V_LIMIT."""
        self.turbo = bool(on)
        if self.turbo and self.hardware_stand is True and self.speed_gain < TURBO_GAIN_STAND_START                 and not getattr(self, 'gain_learned', False):
            self.speed_gain = TURBO_GAIN_STAND_START
        if not self.turbo:
            self.v_max = min(self.v_max, NORMAL_V_LIMIT)
        self._profile = None
        return self.turbo

    def update_measured_speed(self, stamp, x, y):
        self.pose_track.append((stamp, x, y))
        old = [q for q in self.pose_track if stamp - q[0] >= 0.5]
        if not old:
            return
        t0, x0, y0 = old[-1]
        if stamp - t0 > 1.5:
            self.measured_v = None
            return
        v = math.hypot(x - x0, y - y0) / (stamp - t0)
        if v > 2.0:                                   # relocalization jump, not motion
            return
        self.measured_v = v
        # gain: straight, steady driving only (command roughly constant over the window)
        cmds = [c for c in self.command_track if c[0] >= t0 - 0.3]
        if len(cmds) >= 4:
            vs = [c[1] for c in cmds]
            ws = [abs(c[2]) for c in cmds]
            mean = sum(vs) / len(vs)
            if mean > 0.15 and max(vs) - min(vs) < 0.06 and max(ws) < 0.12:
                ratio = float(np.clip(v / mean, *TURBO_GAIN_RANGE))
                self.speed_gain += TURBO_GAIN_ALPHA * (ratio - self.speed_gain)
                self.gain_learned = True

    @staticmethod
    def chord_curvature(route):
        """|heading change| / TURBO_CHORD_M around every route point (cached on the route)."""
        cached = getattr(route, '_chord_kappa', None)
        if cached is not None:
            return cached
        h = TURBO_CHORD_M / 2.0
        def heading(s0, s1):
            a = np.c_[np.interp(s0, route.arc, route.points[:, 0]), np.interp(s0, route.arc, route.points[:, 1])]
            b = np.c_[np.interp(s1, route.arc, route.points[:, 0]), np.interp(s1, route.arc, route.points[:, 1])]
            return np.arctan2(b[:, 1] - a[:, 1], b[:, 0] - a[:, 0])
        s = route.arc
        lo, mid, hi = np.clip(s - h, 0, route.length), s, np.clip(s + h, 0, route.length)
        d = np.abs(np.remainder(heading(mid, hi) - heading(lo, mid) + np.pi, 2 * np.pi) - np.pi)
        k = d / np.maximum(1e-3, (hi - lo) / 2.0)
        route._chord_kappa = k
        return k

    def turbo_profile(self, route):
        """Measured-speed ceiling per route point: bend speed, narrow places, braking ahead."""
        key = (round(self.v_max, 3), round(self.w_max, 3))
        if self._profile is not None and self._profile[0] is route and self._profile[1] == key:
            return self._profile[2]
        step = max(1e-3, route.length / max(1, len(route.arc) - 1))
        k = maximum_filter1d(self.chord_curvature(route), size=max(1, int(2 * TURBO_CURVE_WINDOW_M / step)) | 1)
        k = np.maximum(k, 1e-6)
        w_track = max(self.w_max, TURBO_W_TRACK)
        v = np.minimum(np.sqrt(TURBO_LAT_ACCEL / k), w_track / k)
        v = np.minimum(v, min(self.v_max, TURBO_V_LIMIT))
        cl = np.asarray(route.clearance, float)
        v = np.minimum(v, np.interp(cl, [c for c, _ in TURBO_NARROW], [u for _, u in TURBO_NARROW]))
        for c in route.cusps:
            v[np.abs(route.arc - c) < 0.3] = CURVE_MIN_V
        v[-1] = min(v[-1], 0.05)
        v = np.maximum(v, CURVE_MIN_V)
        ds = np.diff(route.arc)
        for i in range(len(v) - 2, -1, -1):           # brake before bends
            v[i] = min(v[i], math.sqrt(v[i + 1] ** 2 + 2.0 * TURBO_PLAN_DECEL * ds[i]))
        self._profile = (route, key, v)
        return v

    def set_turn_limits(self, track=None, rotate=None):
        """Operator turn rates: `track` while driving, `rotate` for turns in place."""
        if track is not None:
            self.w_max = float(np.clip(float(track), 0.05, W_TRACK_LIMIT))
        if rotate is not None:
            self.w_rotate = float(np.clip(float(rotate), 0.05, W_ROTATE_LIMIT))
        return self.w_max, self.w_rotate

    def stop_constants(self):
        return (TURBO_REACT_S, TURBO_BRAKE_DECEL) if self.turbo else (REACT_S, BRAKE_DECEL)

    def stop_speed(self, free_m):
        """Highest command speed whose reaction + braking distance fits in `free_m` metres.
        In Turbo the rule holds for the measured speed (command x speed gain)."""
        if free_m <= 0.0:
            return 0.0
        react, decel = self.stop_constants()
        # v * react + v^2 / (2 * decel) = free_m
        a, b = 1.0 / (2.0 * decel), react
        v = float((-b + math.sqrt(b * b + 4.0 * a * free_m)) / (2.0 * a))
        return v / self.speed_gain if self.turbo else v

    def stopping_distance(self, v):
        """Stopping distance at command speed v (measured speed in Turbo)."""
        react, decel = self.stop_constants()
        if self.turbo:
            v *= self.speed_gain
        return v * react + v * v / (2.0 * decel)

    def pick_explore_goal(self, min_d=5.0, max_d=10.0, max_ratio=2.0, _fallback=True):
        """Reachable centreline point 5-10 m away, preferring far and open."""
        if self.pose is None:
            return None, 'no pose yet'
        cm = self.costmap(self.robot_height())
        p = np.array(self.pose[1:3])
        ij = np.argwhere(cm.field.medial)
        if not len(ij):
            return None, 'no open area nearby'
        xy = cm.field.origin + (ij + 0.5) * cm.field.res
        d = np.linalg.norm(xy - p, axis=1)
        sel = (d >= min_d) & (d <= max_d)
        if not sel.any():
            if _fallback and min_d > 3.0:
                return self.pick_explore_goal(3.0, 6.0, max_ratio, _fallback=False)
            return None, 'no reachable open point within %.0f-%.0f m' % (min_d, max_d)
        ij, xy, d = ij[sel], xy[sel], d[sel]
        clear = cm.field.d[ij[:, 0], ij[:, 1]]
        order = np.argsort(-(d + 2.0 * clear))[::7][:30]
        for k in order:
            path, _ = P.plan_path(cm, p, xy[k])
            if path is None:
                continue
            length = float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum())
            if length <= max_ratio * d[k] + 0.3:
                return (float(xy[k][0]), float(xy[k][1])), 'ok (clearance %.2f m, path %.1f m)' % (clear[k], length)
        if _fallback and min_d > 3.0:
            return self.pick_explore_goal(3.0, 6.0, max_ratio, _fallback=False)
        return None, 'no candidate had a suitable path'

    # ------------------------------------------------------------------ tour
    def compute_loop(self):
        """Plan one approach + centreline loop + return route (called off the event loop)."""
        if self.pose is None:
            return None, 'no pose'
        measured = self.robot_height()
        height = round(measured + TOUR_HEIGHT_RESERVE_M, 2)
        p = np.array(self.pose[1:3])
        yaw = self.pose[3]
        tic = time.time()
        cm = self.costmap(height)
        ring = P.loop_ring(cm.field, p, exclude=self.weak_map_mask())
        if ring is None:
            return None, 'no centreline loop in the free space around the robot'
        ring = P.loop_entry(ring, p, yaw)
        approach, why = P.plan_path(cm, p, ring[0])
        if approach is None:
            return None, 'no approach path to the loop: %s' % why
        route = np.vstack([approach, ring[1:], approach[-2::-1]])
        if self.robot_height() > height:
            return None, 'robot height changed during tour planning; plan again'
        loop = P.Route(ring, cm.field, closed=True)
        full = P.Route(route, cm.field)
        self.loop_info = dict(
            perimeter_m=round(loop.length, 1), route_length_m=round(full.length, 1),
            route_points=len(full.points), waypoints=0, robot_height=height,
            measured_height_m=measured, height_reserve_m=TOUR_HEIGHT_RESERVE_M,
            route_mode='whole_route', start_xy=p.tolist(), blocked_policy='local_detour_then_wait',
            planner='centreline', min_clearance_m=round(float(full.clearance.min()), 2),
            median_clearance_m=round(float(np.median(full.clearance)), 2),
            median_centre_offset=round(float(np.median(full.offset)), 3),
            plan_s=round(time.time() - tic, 2))
        return route, 'ok'

    def start_tour(self, route):
        if self.pose is None or self.active or self.loop_info is None:
            return False, 'Cannot start the tour: no pose or a task is already active'
        if self.robot_height() > self.loop_info['robot_height']:
            return False, 'Robot height changed; plan the tour again'
        if np.linalg.norm(np.array(self.pose[1:3]) - self.loop_info['start_xy']) > GOAL_TOL:
            return False, 'Robot moved during planning; plan the tour again'
        points = np.asarray(route, dtype=float)
        if len(points) < 4:
            return False, 'Tour route too short'
        with self.lock:
            self.reset_controller()
            self.reset_recovery()
            self.home = tuple(map(float, self.pose[1:3]))
            self.leg = 'tour'
            self.tour_route_height = self.loop_info['robot_height']
            self.install_route(points, self.tour_route_height)
            if self.route.length <= 2 * TOUR_TOL:
                self.route = None
                return False, 'Tour route too short'
            self.goal = tuple(map(float, self.route.points[-1]))
            self.detour_count = 0
            self.last_detour = None
            self.detour_reason = ''
            self.active = True
            self.state = 'driving'
            self.reason = STATE_TEXT['tour']
            self.low_fit_since = None
            self.pause_until = 0.0
            self.reflex_until, self.reflex_engaged, self.reflex_resume = 0.0, False, None
        return True, self.reason

    # ------------------------------------------------------------------ planner thread
    def plan_loop(self):
        while not self.stop_evt.is_set():
            self.plan_req.wait(1.0)
            self.plan_req.clear()
            kind, self.plan_kind = self.plan_kind, None
            if kind is None:
                continue
            try:
                if kind == 'goal':
                    self.plan_goal()
                elif kind in ('detour', 'rejoin'):
                    self.plan_splice(kind)
            except Exception as exc:
                self.detour_reason = 'planning error, holding still: %r' % (exc,)

    def plan_goal(self):
        with self.lock:
            goal, pose, revision = self.goal, self.pose, self.route_revision
        if goal is None or pose is None:
            return
        height = self.robot_height()
        tic = time.time()
        cm = self.planning_costmap(height)
        points, why = P.plan_path(cm, np.array(pose[1:3]), np.array(goal))
        with self.lock:
            if self.stop_evt.is_set() or revision != self.route_revision or goal != self.goal:
                return
            self.plan_ms = round((time.time() - tic) * 1000)
            if points is None:
                self.state = 'blocked' if self.active else 'no_path'
                self.reason = {'goal_blocked': 'No reachable position within 1 m of the goal (obstacle/unknown)',
                               'no_path': 'No feasible path with %.2f m clearance' % P.HARD_CLEARANCE_M,
                               'start_outside': 'Current position is outside the map'}.get(why, why)
                return
            self.install_route(points, height)
            self.state = 'driving' if self.active else 'planned'
            self.reason = STATE_TEXT.get(self.leg, 'Following the route') if self.active else ''

    def plan_splice(self, kind):
        """Replace the route ahead of the robot with a local detour (around a confirmed
        obstacle) or a rejoin path (back onto the route), keeping the rest unchanged."""
        with self.lock:
            route, pose, revision = self.route, self.pose, self.route_revision
            progress, block_at = self.progress, self.block_at
            active = self.active
        if not active or route is None or pose is None:
            return
        if not self.source_clock_valid or self.pose_age() > POSE_STALE_S:
            return
        height = self.tour_route_height if self.leg == 'tour' and self.tour_route_height else self.robot_height()
        if self.robot_height() > height and self.hardware_stand is not False:
            return
        if self.control_layer is None:
            return
        cm = self.planning_costmap(height)
        position = np.array(pose[1:3])
        if kind == 'detour':
            base = progress + (block_at if block_at is not None else 0.0)
            targets = [base + d for d in DETOUR_REJOIN_M]
        else:
            targets = [progress + d for d in REJOIN_AHEAD_M]
        chosen = None
        for s in targets:
            if s >= route.length:
                s = route.length
            target = route.point_at(s)
            if np.linalg.norm(target - position) < 0.5:
                continue
            points, why = P.plan_path(cm, position, target, radius_m=DETOUR_RADIUS_M)
            if points is None or np.linalg.norm(points[-1] - target) > P.PLAN_RES * 1.5:
                continue
            length = float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())
            if length <= DETOUR_MAX_RATIO * (s - progress) + 2.0:
                chosen = (s, points, length)
                break
            if s >= route.length:
                break
        if chosen is None:
            self.detour_reason = ('No safe detour around the obstacle yet' if kind == 'detour'
                                  else 'No safe path back onto the route yet')
            return
        s, points, length = chosen
        i = route.index_at(s)
        spliced = np.vstack([points, route.points[i + 1:]])
        with self.lock:
            if (not self.active or self.route is not route or self.route_revision != revision
                    or self.pose is None or np.linalg.norm(np.asarray(self.pose[1:3]) - position) > 0.15):
                self.detour_reason = 'State changed during planning; retrying'
                return
            self.install_route(spliced, height, keep_offset=self.leg == 'tour')
            self.detour_count += 1
            self.last_detour = dict(t=time.time(), kind=kind, revision=self.route_revision,
                                    replaced_m=round(s - progress, 2), bypass_m=round(length, 2),
                                    rejoin_xy=[round(float(v), 2) for v in route.point_at(s)])
            self.detour_reason = 'Local detour joined the route ahead' if kind == 'detour' else 'Rejoined the route'
            self.reset_controller()
            self.state = 'driving'
            self.reason = self.detour_reason

    def request_plan(self, kind):
        if self.plan_kind is None:
            self.plan_kind = kind
            self.plan_req.set()

    # ------------------------------------------------------------------ route following
    def update_progress(self, position, now):
        """Advance the arc progress within a bounded window; return the cross-track error."""
        route = self.route
        ahead = max(0.3, 3.0 * self.v_max * CONTROL_DT_MAX + 0.2)
        cusp = route.next_cusp(self.progress)
        low = max(self.progress - self.progress_back_m, route.previous_cusp(self.progress))
        s, err = route.project(position, low, min(self.progress + ahead, cusp))
        if self.recover_state != 'idle' or self.progress_back_m > PROGRESS_BACK_M:
            self.progress = s           # after reversing the robot may be behind its progress
            if s >= self.progress and self.recover_state == 'idle':
                self.progress_back_m = PROGRESS_BACK_M
        else:
            self.progress = max(self.progress, s)
        if cusp < route.length and (cusp - self.progress <= CUSP_REACH_M
                                    or np.linalg.norm(route.point_at(cusp) - position) <= CUSP_REACH_M):
            self.progress = min(route.length, cusp + 0.05)        # turnaround reached: cross it
            err = route.project(position, cusp, self.progress)[1]
        self.tracking_error = err
        if err > TRACK_REJOIN_M:
            self.off_route_since = self.off_route_since or now
        else:
            self.off_route_since = None
        return err

    def path_window(self, length):
        return self.route.window(self.progress, length)

    def route_obstacle(self, hits):
        """Arc distance ahead to the first new obstacle within BLOCK_RADIUS_M of the route."""
        live = self.new_obstacles(hits)
        pts, along = self.path_window(BLOCK_LOOKAHEAD_M)
        r = int(math.ceil(BLOCK_RADIUS_M / self.nm.res))
        o = np.arange(-r, r + 1)
        disk = np.hypot(*np.meshgrid(o, o, indexing='ij')) * self.nm.res <= BLOCK_RADIUS_M
        robot = np.asarray(self.pose[1:3])
        for q, a in zip(pts, along):
            if a < 0.1:
                continue
            i, j = self.nm.to_ij(q)
            if not (r <= i < self.nm.shape[0] - r and r <= j < self.nm.shape[1] - r):
                continue
            window = live[i - r:i + r + 1, j - r:j + r + 1] & disk
            if window.any():
                cells = self.nm.to_xy(np.argwhere(window) + np.array([i - r, j - r]))
                cells = cells[np.linalg.norm(cells - robot, axis=1) >= BODY_INNER_M]
                if len(cells):
                    self.block_point = [round(float(v), 2) for v in cells[0]]
                    return float(a)
        self.block_point = None
        return None

    def sweep(self, centres, travel):
        """Travel until a body disc at `centres` touches a live return it approaches."""
        layer = self.control_layer
        if layer is None or self.pose is None:
            return None
        occupied = layer[0] >= ADD_HITS * 0.75
        res = self.nm.res
        radius = int(math.ceil(SWEEP_RADIUS_M / res))
        o = np.arange(-radius, radius + 1)
        disk = np.hypot(*np.meshgrid(o, o, indexing='ij')) * res <= SWEEP_RADIUS_M
        robot = np.asarray(self.pose[1:3], dtype=float)
        for centre, distance in zip(centres, travel):
            i, j = self.nm.to_ij(centre)
            if not (radius <= i < self.nm.shape[0] - radius and radius <= j < self.nm.shape[1] - radius):
                return float(distance)
            window = occupied[i - radius:i + radius + 1, j - radius:j + radius + 1] & disk
            if window.any():
                cells = self.nm.to_xy(np.argwhere(window) + np.array([i - radius, j - radius]))
                from_robot = np.linalg.norm(cells - robot, axis=1)
                from_centre = np.linalg.norm(cells - centre, axis=1)
                # only returns the body moves toward count: beside a wall it can still leave
                if ((from_robot >= BODY_INNER_M) & (from_centre < from_robot - 0.02)).any():
                    return float(distance)
        return SWEEP_RANGE_M

    def corridor(self):
        """(front, rear) free travel: front along the route ahead, rear straight back."""
        if self.pose is None:
            return None, None
        _, x, y, yaw = self.pose
        steps = np.arange(0.0, SWEEP_RANGE_M + 1e-9, SWEEP_STEP_M)
        rear = self.sweep(np.c_[x - steps * math.cos(yaw), y - steps * math.sin(yaw)], steps)
        if self.route is None:
            return None, rear
        pts, along = self.path_window(SWEEP_RANGE_M)
        lead = float(np.linalg.norm(pts[0] - np.array([x, y])))
        centres = np.vstack([[x, y], pts])
        travel = np.r_[0.0, lead + along]
        dense = np.arange(0.0, min(SWEEP_RANGE_M, travel[-1]) + 1e-9, SWEEP_STEP_M)
        if not len(dense):
            return None, rear
        centres = np.c_[np.interp(dense, travel, centres[:, 0]), np.interp(dense, travel, centres[:, 1])]
        return self.sweep(centres, dense), rear

    def update_stall(self, now):
        """True once forward commands >= STALL_SPEED failed to move the robot (latched)."""
        position = np.asarray(self.pose[1:3], dtype=float)
        if self.stall_latched:
            if np.linalg.norm(position - self.stall_from) >= STALL_CLEAR_M:
                self.stall_latched = False
                self.stall_since = self.stall_from = None
            return self.stall_latched
        if self.command[0] < STALL_SPEED or self.recover_state != 'idle':
            self.stall_since = self.stall_from = None
            return False
        if self.stall_since is None or np.linalg.norm(position - self.stall_from) >= STALL_MOVE_M:
            self.stall_since, self.stall_from = now, position
            return False
        self.stall_latched = now - self.stall_since >= STALL_S
        return self.stall_latched

    # ------------------------------------------------------------------ control
    def control(self, slam_ok, chassis_ok):
        """Rate-limit the target command; stop branches bypass the limiter."""
        target = self.control_target(slam_ok, chassis_ok)
        if target is None or self.safety_stop:
            mode = self.controller_mode if self.preserve_turn_mode else 'track'
            sign = self.turn_sign
            self.reset_controller()
            self.controller_mode, self.turn_sign = mode, sign
            if target is not None and self.recover_state == 'reversing':
                self.command = target
            return target
        now = time.monotonic()
        self.control_interval_s = max(0.0, now - self.command_time)
        dt = min(self.control_interval_s, CONTROL_DT_MAX)
        previous_v, previous_w = self.command
        target_v, target_w = target
        self.command_target = (float(target_v), float(target_w))
        if previous_w * target_w < 0.0:
            target_w = 0.0                       # brake through zero before reversing the turn
        if self.turbo:
            linear = TURBO_ACCEL if target_v > previous_v else TURBO_RAMP_DECEL
        else:
            linear = LINEAR_ACCEL if target_v > previous_v else LINEAR_DECEL
        angular = ANGULAR_ACCEL if abs(target_w) > abs(previous_w) else ANGULAR_DECEL
        v = previous_v + float(np.clip(target_v - previous_v, -linear * dt, linear * dt))
        w = previous_w + float(np.clip(target_w - previous_w, -angular * dt, angular * dt))
        scale = 1.0
        if v > 0.0:
            v_top = self.v_max / self.speed_gain if self.turbo else self.v_max
            scale = min(scale, max(0.0, min(v_top, self.safety_v_cap)) / v)
        ceiling = self.w_rotate if self.controller_mode in ('rotate', 'brake_rotate') else (
            max(self.w_max, TURBO_W_TRACK) if self.turbo else self.w_max)
        if abs(w) > 0.0:
            scale = min(scale, ceiling / abs(w))
        self.limit_override = scale < 1.0
        self.command = (float(v * scale), float(w * scale))
        self.command_time = now
        self.command_track.append((time.time(), self.command[0], self.command[1]))
        return self.command

    def hold(self, state, reason, preserve=True):
        self.preserve_turn_mode = preserve
        self.state = state
        self.reason = reason
        return (0.0, 0.0)

    def control_target(self, slam_ok, chassis_ok):
        """Target (v, w) for this cycle; every stop branch leaves safety_stop set."""
        self.safety_stop = True
        self.preserve_turn_mode = False
        if not self.active:
            return None
        now = time.time()
        # ---- freshness gates: hold (and resume) rather than cancel ----
        if not chassis_ok:
            return self.hold('waiting', 'Chassis status unavailable; holding until it returns')
        if not slam_ok or self.pose is None:
            self.cancel('SLAM is not localized')
            return (0.0, 0.0)
        if not self.source_clock_valid:
            self.pose_resume_required, self.pose_resume_frames = True, 0
            return self.hold('waiting', 'Sensor source timestamp invalid or ahead; holding', preserve=False)
        age = self.pose_age()
        if age > POSE_STALE_S:
            self.pose_resume_required, self.pose_resume_frames, self.pose_resume_stamp = True, 0, None
            return self.hold('waiting', 'SLAM pose stale (%.1f s); task kept, waiting' % age)
        if self.pose_resume_required:
            if self.pose_resume_stamp != self.pose[0]:
                self.pose_resume_stamp = self.pose[0]
                layer = self.control_layer
                qualified = (self.fitness is not None and self.fitness >= MIN_FITNESS and layer is not None
                             and layer[3] == self.robot_height() and self.layer_age(layer) <= POSE_STALE_S)
                self.pose_resume_frames = self.pose_resume_frames + 1 if qualified else 0
            if self.pose_resume_frames < POSE_RESUME_FRAMES:
                return self.hold('waiting', 'Waiting for a stable pose and obstacle layer (%d/%d frames)'
                                 % (self.pose_resume_frames, POSE_RESUME_FRAMES))
            self.pose_resume_required = False
        if self.fitness is not None and self.fitness < MIN_FITNESS:
            self.low_fit_since = self.low_fit_since or now
            near = self.live.nearest
            if near is not None and near < OCCLUSION_NEAR_M:
                if now - self.low_fit_since > OCCLUSION_WAIT_S:
                    self.cancel('Close occlusion did not clear within %d s' % OCCLUSION_WAIT_S)
                    return (0.0, 0.0)
                return self.hold('waiting', 'Close occlusion (%.2f m); waiting for it to leave' % near)
            if now - self.low_fit_since > FITNESS_HOLD_S:
                self.cancel('Localization fitness stayed low (%.2f)' % self.fitness)
                return (0.0, 0.0)
        else:
            self.low_fit_since = None
        # ---- fly-brain reflex (brain mode 'reflex'): the brain commands, the task waits ----
        if now < self.reflex_until:
            if not self.reflex_engaged:
                self.reflex_engaged, self.reflex_count = True, self.reflex_count + 1
            self.reflex_resume = None
            return self.hold('reflex', 'Fly-brain reflex in control: %s' % self.reflex_why, preserve=False)
        if self.reflex_engaged:
            # the reflex moved the robot off the route: plan from where it is now
            self.reflex_engaged = False
            self.reset_controller()
            with self.lock:
                if self.leg == 'tour':
                    self.reflex_resume = (self.route_revision, now)
                    self.request_plan('rejoin')
                else:
                    self.route = None
                    self.route_revision += 1
                    self.blocked_since = None
                    self.request_plan('goal')
            return self.hold('planning', 'Resuming after the fly-brain reflex')
        if self.reflex_resume is not None:
            revision, since = self.reflex_resume
            if self.route_revision != revision:
                self.reflex_resume = None
            elif now - since > REFLEX_REJOIN_GIVEUP_S:
                self.reflex_resume = None
                self.cancel('No way back onto the tour route within %d s after the fly-brain reflex'
                            % REFLEX_REJOIN_GIVEUP_S)
                return (0.0, 0.0)
            else:
                if self.plan_kind is None and now - self.detour_attempt_at > 1.0:
                    self.detour_attempt_at = now
                    self.request_plan('rejoin')
                return self.hold('planning', 'Rejoining the route after the fly-brain reflex')
        if now < self.pause_until:
            return (0.0, 0.0)
        taller = (self.leg == 'tour' and self.tour_route_height is not None
                  and self.robot_height() > self.tour_route_height and self.hardware_stand is not False)
        if self.leg == 'tour' and self.tour_route_height is None:
            self.cancel('Tour without a planned height; plan the route again')
            return (0.0, 0.0)
        if taller:
            self.taller_since = self.taller_since or now
            if now - self.taller_since > TOUR_HEIGHT_HOLD_S:
                self.cancel('Robot height %.2f m exceeds the planned tour height %.2f m; plan the route again'
                            % (self.robot_height(), self.tour_route_height))
                return (0.0, 0.0)
            return self.hold('waiting', 'Robot measured taller than planned (%.2f > %.2f m); holding'
                             % (self.robot_height(), self.tour_route_height))
        self.taller_since = None
        layer = self.control_layer
        if layer is None or layer[3] != self.robot_height():
            return self.hold('waiting', 'Waiting for the live obstacle layer of the current posture')
        layer_age = self.layer_age(layer)
        if layer_age > POSE_STALE_S:
            return self.hold('waiting', 'Live obstacle layer stale (%.1f s); holding' % layer_age)
        with self.lock:
            route = self.route
        if route is None:
            self.blocked_since = self.blocked_since or now
            if now - self.blocked_since > BLOCKED_GIVEUP_S and self.state in ('blocked', 'no_path'):
                self.cancel('No path for %d s; giving up' % BLOCKED_GIVEUP_S)
                return (0.0, 0.0)
            if self.state not in ('blocked', 'no_path'):
                self.state = 'planning'
            if self.plan_kind is None and now - self.detour_attempt_at > DETOUR_RETRY_S:
                self.detour_attempt_at = now
                self.request_plan('goal')
            return (0.0, 0.0)

        _, x, y, yaw = self.pose
        p = np.array([x, y])
        # ---- route progress, arrival, deviation ----
        error = self.update_progress(p, now)
        remaining = route.length - self.progress
        tol = TOUR_TOL if self.leg == 'tour' else GOAL_TOL
        if remaining <= tol and np.linalg.norm(route.points[-1] - p) <= tol:
            return self.arrive(now)
        if error > TRACK_ABORT_M:
            self.cancel('Off the route by %.2f m; plan again' % error)
            return (0.0, 0.0)
        if self.off_route_since is not None and now - self.off_route_since > TRACK_REJOIN_S:
            if now - self.detour_attempt_at > DETOUR_RETRY_S:
                self.detour_attempt_at = now
                self.request_plan('rejoin')

        # ---- obstacles on the route (debounced) ----
        hit = self.route_obstacle(layer[0])
        if hit is not None:
            self.block_cycles += 1
            self.block_clear_since = None
            if self.block_cycles >= BLOCK_CONFIRM_CYCLES:
                self.block_confirmed = True
                self.block_at = hit
        else:
            self.block_cycles = 0
            self.block_clear_since = self.block_clear_since or now
            if self.block_confirmed and now - self.block_clear_since >= BLOCK_CLEAR_S:
                self.block_confirmed = False
                self.block_at = None
        self.last_path_blocked = self.block_confirmed
        block_cap = self.v_max
        if self.block_confirmed and self.block_at is not None:
            block_cap = min(self.v_max, self.stop_speed(self.block_at - BLOCK_STOP_GAP_M))

        # ---- host safety chain: swept clearance, backstop, stall ----
        front_m, rear_m = self.corridor()
        self.front_clearance_m, self.rear_clearance_m = front_m, rear_m
        guard = self.robot_guard or {}
        backstop = guard.get('nearest_m') if guard.get('fresh') else None
        self.guard_v_cap = self.v_max
        if front_m is not None and front_m < SWEEP_RANGE_M:
            self.guard_v_cap = min(self.v_max, self.stop_speed(front_m - HOST_STOP_M))
        stalled = self.update_stall(now)
        hard_stop = bool(self.guard_v_cap < HOST_MIN_SPEED or stalled
                         or (backstop is not None and float(backstop) < HOST_BACKSTOP_M))
        stopped_by_block = self.block_confirmed and block_cap < HOST_MIN_SPEED
        blocked = hard_stop or stopped_by_block
        if blocked:
            self.blocked_since = self.blocked_since or now
        elif self.recover_state == 'idle':
            self.blocked_since = None

        # ---- detour / recovery while blocked ----
        if self.recover_state != 'idle' or blocked:
            if self.block_confirmed and now - self.detour_attempt_at > DETOUR_RETRY_S:
                self.detour_attempt_at = now
                self.request_plan('detour')
            action = self.recovery(now, rear_m, front_m, stalled, backstop)
            if action is not None:
                return action
            if blocked:
                waited = now - (self.blocked_since or now)
                if self.leg != 'tour' and waited > BLOCKED_GIVEUP_S:
                    self.cancel('Blocked for more than %d s; giving up' % BLOCKED_GIVEUP_S)
                    return (0.0, 0.0)
                if stalled:
                    why = 'Stalled: commanded forward but not moving (contact?)'
                elif self.guard_v_cap < HOST_MIN_SPEED:
                    why = 'Obstacle %.2f m ahead along the route: host stop' % (front_m if front_m is not None else -1.0)
                elif backstop is not None and float(backstop) < HOST_BACKSTOP_M:
                    why = 'Chassis guard reports %.2f m: backstop' % float(backstop)
                else:
                    why = 'New obstacle %.2f m ahead on the route' % (self.block_at or 0.0)
                return self.hold('waiting', '%s; waiting %.0f s, %s' % (why, waited, self.detour_reason or 'planning a detour'))

        if self.state in ('waiting', 'blocked', 'planning', 'avoiding'):
            self.state = 'driving'
            self.reason = STATE_TEXT.get(self.leg, 'Following the route')
        return self.track(p, yaw, route, remaining, min(block_cap, self.guard_v_cap))

    def recovery(self, now, rear_m, front_m, stalled, backstop):
        """Narrow-space recovery: blocked for RECOVER_DELAY_S without a detour -> reverse up
        to RECOVER_MAX_M (rear clear), wait, re-plan.  Returns a command or None."""
        if self.recover_state == 'idle':
            if self.blocked_since is None or now - self.blocked_since < RECOVER_DELAY_S:
                return None
            position = np.asarray(self.pose[1:3], float)
            if self.recover_anchor is not None and np.linalg.norm(position - self.recover_anchor) > RECOVER_RESET_M:
                self.recover_cycles = 0
                self.recover_stuck = None
            if self.recover_cycles >= RECOVER_CYCLES and getattr(self, 'recover_stuck', None):
                return self.hold('waiting', self.recover_stuck)
            if self.recover_cycles >= RECOVER_CYCLES:
                return self.hold('waiting', 'Blocked here; reversed %d times without a way through, waiting for the operator'
                                 % self.recover_cycles)
            self.recover_state = 'reversing'
            self.recover_from = position
            self.recover_anchor = position if self.recover_anchor is None else self.recover_anchor
            self.recover_since = now
            self.recover_cycles += 1
            self.progress_back_m = PROGRESS_BACK_RECOVERY_M
        if self.recover_state == 'reversing':
            travelled = float(np.linalg.norm(np.asarray(self.pose[1:3]) - self.recover_from))
            if now - self.recover_since > RECOVER_REVERSE_MAX_S and travelled < RECOVER_STUCK_M:
                self.recover_state = 'idle'
                self.recover_cycles = RECOVER_CYCLES       # no further automatic reversals here
                self.recover_stuck = ('Blocked, and reversing moved the robot only %.2f m in %.0f s; '
                                      'waiting for the operator (clear the way or move the robot)'
                                      % (travelled, now - self.recover_since))
                return self.hold('waiting', self.recover_stuck)
            if travelled < RECOVER_MAX_M and (rear_m is None or rear_m > RECOVER_REAR_STOP_M) \
                    and (backstop is None or float(backstop) >= HOST_BACKSTOP_M or travelled < 0.1):
                self.state = 'avoiding'
                self.reason = 'Blocked: reversing %.2f/%.2f m to make room' % (travelled, RECOVER_MAX_M)
                self.speed_limit = RECOVER_V
                return (-RECOVER_V, 0.0)
            self.recover_state = 'waiting'
            self.recover_since = now
            self.stall_latched = False
            self.stall_since = self.stall_from = None
        if self.recover_state == 'waiting':
            if now - self.recover_since < RECOVER_WAIT_S:
                return self.hold('waiting', 'Reversed; letting the scan settle before re-planning')
            self.recover_state = 'idle'
            self.blocked_since = None
            if self.block_confirmed:
                self.detour_attempt_at = now
                self.request_plan('detour')
            return self.hold('planning', 'Re-planning after the recovery reversal')
        return None

    def arrive(self, now):
        if self.leg == 'explore' and self.home is not None:
            self.leg = 'home'
            with self.lock:
                self.goal = self.home
                self.route = None
                self.route_revision += 1
                self.plan_kind = 'goal'
            self.state = 'planning'
            self.reason = 'Exploration point reached; returning to the start in 2 s'
            self.pause_until = now + 2.0
            self.plan_req.set()
            return (0.0, 0.0)
        with self.lock:
            self.active = False
            self.route_revision += 1
            self.state = 'arrived'
            self.reason = {'home': 'Back at the start point', 'tour': 'Tour complete; back at the start point'}.get(self.leg, '')
            self.leg = None
        return (0.0, 0.0)

    def track(self, p, yaw, route, remaining, obstacle_cap):
        """Pure pursuit on the route with turns in place and speed caps."""
        v_prev = abs(self.command[0])
        look_max = TURBO_LOOKAHEAD_MAX_M if self.turbo else LOOKAHEAD_MAX_M
        lookahead = float(np.clip(LOOKAHEAD_MIN_M + LOOKAHEAD_GAIN_S * v_prev, LOOKAHEAD_MIN_M, look_max))
        if self.turbo:
            # a long chord cuts the bend: keep the sagitta L^2 kappa / 8 within TURBO_SAGITTA_M
            kc = self.chord_curvature(route)
            k_ahead = float(kc[route.index_at(self.progress):route.index_at(self.progress + lookahead) + 2].max())
            if k_ahead > 1e-6:
                lookahead = float(np.clip(math.sqrt(8.0 * TURBO_SAGITTA_M / k_ahead), LOOKAHEAD_MIN_M, lookahead))
        cusp = route.next_cusp(self.progress)
        target = route.point_at(min(self.progress + lookahead, cusp))
        offset = target - p
        distance = float(np.linalg.norm(offset))
        alpha = math.remainder(math.atan2(offset[1], offset[0]) - yaw, 2 * math.pi) if distance > 0.05 else 0.0
        kappa = 2.0 * math.sin(alpha) / max(distance, 0.2)
        self.heading_error, self.curvature = alpha, kappa
        self.lookahead_target = target.tolist()
        # speed caps
        route_kappa = route.max_curvature(self.progress, CURVE_LOOKAHEAD_M)
        curve_cap = max(CURVE_MIN_V, self.w_max / max(route_kappa, 1e-6))
        clearance = float(route.clearance[route.index_at(self.progress):route.index_at(self.progress + 0.5) + 2].min())
        clear_cap = self.v_max * float(np.clip(0.5 + 0.5 * (clearance - P.HARD_CLEARANCE_M)
                                               / (SLOW_CLEARANCE_M - P.HARD_CLEARANCE_M), 0.5, 1.0))
        end_cap = max(0.03, GOAL_DECEL * min(remaining, cusp - self.progress))
        age_cap = self.v_max * float(np.clip((POSE_ZERO_SPEED_S - self.pose_age())
                                             / (POSE_ZERO_SPEED_S - POSE_FULL_SPEED_S), 0.0, 1.0))
        self.profile_cap = None
        if self.turbo:
            # speed profile (measured m/s) over the next stretch, converted to a command
            prof = self.turbo_profile(route)
            v_now = max(v_prev * self.speed_gain, self.measured_v or 0.0)
            i0 = route.index_at(self.progress)
            i1 = route.index_at(self.progress + v_now * TURBO_PREVIEW_S + 0.2) + 2
            cap = float(prof[i0:i1].min())
            if self.fitness is not None and self.fitness < TURBO_FIT_FULL:
                k = float(np.clip((self.fitness - TURBO_MIN_FITNESS) / (TURBO_FIT_FULL - TURBO_MIN_FITNESS), 0.0, 1.0))
                cap = min(cap, TURBO_FALLBACK_V + (max(cap, TURBO_FALLBACK_V) - TURBO_FALLBACK_V) * k)
            cap *= float(np.clip((TURBO_POSE_ZERO_S - self.pose_age())
                                 / (TURBO_POSE_ZERO_S - TURBO_POSE_FULL_S), 0.0, 1.0))
            self.profile_cap = cap
            curve_cap = clear_cap = age_cap = cap / self.speed_gain
        self.safety_v_cap = min(self.v_max / self.speed_gain if self.turbo else self.v_max, obstacle_cap, end_cap)
        if self.fitness is not None and self.fitness < LOW_FIT_CRAWL:
            self.safety_v_cap = min(self.safety_v_cap, LOW_FIT_CRAWL_V / (self.speed_gain if self.turbo else 1.0))
        if self.safety_v_cap <= 0.0:
            return (0.0, 0.0)
        self.safety_stop = False
        # turns in place, hysteretic; direction held where the error's sign is noise
        if self.controller_mode == 'track' and abs(alpha) > ROTATE_ENTER:
            self.controller_mode = 'brake_rotate'
        if self.controller_mode == 'brake_rotate':
            if max(abs(c) for c in self.command) > COMMAND_ZERO:
                self.speed_limit = 0.0
                return (0.0, 0.0)
            self.controller_mode = 'rotate'
            self.turn_sign = 1.0 if alpha > 0 else -1.0
        if self.controller_mode == 'rotate':
            if abs(alpha) > ROTATE_EXIT:
                if abs(alpha) < ROTATE_SIGN_AMBIGUOUS:
                    self.turn_sign = 1.0 if alpha > 0 else -1.0
                self.speed_limit = 0.0
                return (0.0, float(self.turn_sign * float(np.clip(1.2 * abs(alpha), 0.05, self.w_rotate))))
            self.controller_mode = 'track'
        heading_scale = float(np.clip(1.0 - abs(alpha) / ROTATE_ENTER, 0.25, 1.0))
        v_top = self.v_max / self.speed_gain if self.turbo else self.v_max
        v = min(self.safety_v_cap, curve_cap, clear_cap, age_cap, max(0.03, v_top * heading_scale))
        if self.turbo and self.measured_v is not None and self.measured_v > self.v_max + 0.03:
            # over-speed governor: the gain estimate lags (it only learns on steady straights)
            v = min(v, v_prev * self.v_max / self.measured_v)
        w_track = max(self.w_max, TURBO_W_TRACK) if self.turbo else self.w_max
        if abs(kappa) > 1e-9:
            v = min(v, w_track / abs(kappa))
            if self.turbo:
                # measured v x turn rate = gain * v^2 * kappa <= TURBO_VW_MAX
                v = min(v, max(CURVE_MIN_V, math.sqrt(TURBO_VW_MAX / (self.speed_gain * abs(kappa)))))        # keep the curvature when the turn rate binds
        self.speed_limit = float(v)
        return (float(v), float(v * kappa))

    # ------------------------------------------------------------------ telemetry
    def status(self):
        route = self.route
        tour = self.leg == 'tour'
        return dict(
            type='nav', controller='centreline_pursuit',
            controller_mode='hold' if self.safety_stop else self.controller_mode,
            command=list(self.command), command_target=list(self.command_target),
            heading_error_rad=self.heading_error, curvature_inv_m=self.curvature,
            acceleration_override=self.limit_override, lookahead_target=self.lookahead_target,
            control_interval_s=self.control_interval_s,
            pose_age_s=None if self.pose is None else max(0.0, self.pose_age()),
            source_clock_valid=self.source_clock_valid,
            processing_age_s=None if self.processing_started_at is None else time.time() - self.processing_started_at,
            source_stamp=self.source_stamp, pose_age_basis=self.pose_age_basis,
            receiver_age_s=None if self.input_received_at is None else max(0.0, time.time() - self.input_received_at),
            live_age_s=None if self.control_layer is None else max(0.0, self.layer_age(self.control_layer)),
            controller_config=dict(reference_body_m=list(REFERENCE_BODY[:2]), lookahead_min_m=LOOKAHEAD_MIN_M,
                                   lookahead_max_m=LOOKAHEAD_MAX_M, rotate_enter_rad=ROTATE_ENTER,
                                   rotate_exit_rad=ROTATE_EXIT, hard_clearance_m=P.HARD_CLEARANCE_M,
                                   linear_accel=LINEAR_ACCEL, linear_decel=LINEAR_DECEL,
                                   angular_accel=ANGULAR_ACCEL, angular_decel=ANGULAR_DECEL),
            continuous_tour=tour, tour_route_mode='whole_route' if tour else None,
            tour_progress_m=round(self.tour_progress_m, 2) if tour else None,
            tour_length_m=round(self.progress_offset + route.length, 2) if tour and route is not None else None,
            tour_tracking_error_m=round(self.tracking_error, 3) if tour else None,
            tracking_error_m=round(self.tracking_error, 3),
            active=self.active, state=self.state, reason=self.reason,
            goal=self.goal, pose=None if self.pose is None else [round(v, 3) for v in self.pose[1:]],
            fitness=None if self.fitness is None else round(self.fitness, 3),
            path=None if route is None else route.points[::3].round(2).tolist(),
            remaining_m=None if route is None else round(route.length - self.progress, 1),
            loop=self.loop_info, v_max=self.v_max, w_max=self.w_max, w_rotate=self.w_rotate,
            stopping_distance_m=round(self.stopping_distance(self.v_max / (self.speed_gain if self.turbo else 1.0)) + HOST_STOP_M, 2),
            turbo=self.turbo, speed_gain=round(self.speed_gain, 3), reflex_count=self.reflex_count,
            keepouts=[[round(k[0], 2), round(k[1], 2), round(k[2], 2)] for k in self.keepouts if k[3] > time.time()],
            measured_speed_mps=None if self.measured_v is None else round(self.measured_v, 3),
            profile_cap=None if self.profile_cap is None else round(self.profile_cap, 3),
            path_blocked=self.last_path_blocked, block_point=self.block_point,
            leg=self.leg, home=self.home, speed_limit=self.speed_limit,
            nearest=None if self.live.nearest is None else round(self.live.nearest, 2),
            front_clearance_m=None if self.front_clearance_m is None else round(self.front_clearance_m, 2),
            mode='stand' if self.hardware_stand is True else self.mode,
            lidar_mode=self.mode, hardware_stand=self.hardware_stand,
            lidar_h=None if self.lidar_h is None else round(self.lidar_h, 3),
            robot_height=self.robot_height(), planned_height_m=self.tour_route_height,
            detour_count=self.detour_count, detour_reason=self.detour_reason, last_detour=self.last_detour,
            route_revision=self.route_revision, recovery=self.recover_state,
            pose_resume_required=self.pose_resume_required, pose_resume_frames=self.pose_resume_frames,
            pitch=None if self.pitch is None else round(self.pitch, 1),
            cloud_version=self.changes.version, changes=self.changes.events[-20:],
            auto_submit=self.changes.auto_submit, pending=len(self.changes.pending))

    def decision_snapshot(self):
        """Per-control-cycle decision record: what the controller saw and chose."""
        with self.lock:
            pose = None if self.pose is None else [round(v, 3) for v in self.pose[1:]]
            look = None if self.lookahead_target is None else [round(v, 2) for v in self.lookahead_target]
            return dict(pose=pose, yaw_deg=None if self.pose is None else round(math.degrees(self.pose[3]), 1),
                        heading_error_deg=round(math.degrees(self.heading_error), 1),
                        lookahead=look, curvature=round(self.curvature, 3),
                        controller_mode=self.controller_mode, turn_sign=self.turn_sign,
                        command=[round(v, 4) for v in self.command],
                        command_target=[round(v, 4) for v in self.command_target],
                        speed_limit=None if self.speed_limit is None else round(self.speed_limit, 3),
                        safety_v_cap=round(self.safety_v_cap, 3), safety_stop=self.safety_stop,
                        state=self.state, nav_reason=self.reason,
                        progress_m=round(self.progress, 2), tracking_error_m=round(self.tracking_error, 3),
                        route_revision=self.route_revision,
                        live_nearest=None if self.live.nearest is None else round(self.live.nearest, 2),
                        floor_offset_m=None if self.live.floor_offset is None else round(self.live.floor_offset, 3),
                        front_clearance_m=None if self.front_clearance_m is None else round(self.front_clearance_m, 2),
                        rear_clearance_m=None if self.rear_clearance_m is None else round(self.rear_clearance_m, 2),
                        path_blocked=self.last_path_blocked, block_at_m=self.block_at,
                        block_point=self.block_point, recovery=self.recover_state,
                        tour_progress_m=None if self.leg != 'tour' else round(self.tour_progress_m, 2))

    def close(self):
        self.stop_evt.set()

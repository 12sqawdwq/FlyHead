#!/usr/bin/env python3
"""Robot-side bridge (Raspberry Pi, ROS 2 Foxy), started by the compute server over SSH.

stdout: binary frames  b'XT' | type:u8 | length:u32le | payload
    1 CLOUD  f64 stamp, u32 n, n*(x,y,z,intensity,time) float32
    2 IMU    f64 stamp, 10 float32 (qx,qy,qz,qw,gx,gy,gz,ax,ay,az)
    3 JSON   utf-8 status / event object
    4 JPEG   f64 stamp, jpeg bytes (RGB camera, for observation only)
stdin: JSON lines from the server; every operation except ping/quit carries an
increasing "sequence" and an absolute "deadline_mono" on this host's monotonic clock
    {"op":"ping","clock_token":str}    keepalive and clock-anchor echo
    {"op":"cmd","v":m/s,"w":rad/s}     velocity, valid until its deadline (<= LEASE_S)
    {"op":"chassis","on":bool}         start / stop the chassis driver
    {"op":"posture","stand":bool}      one stand / crouch request, confirmed by chassis feedback
    {"op":"safety_reset"}              forward /diablo/safety/reset
    {"op":"camera","on":bool}          start / stop the RGB camera driver
    {"op":"retrace"}                   return along the driven path (operator request)
    {"op":"quit"}

Stops motion when a command lease or the server keepalive expires.  When the
server becomes unreachable the bridge keeps the LiDAR and chassis alive and
returns along the path it actually drove (the applied-command trace replayed
backwards with both channels negated), then waits for the server and exits.
Motion uses only forward/left; posture requests are one-shot mode_mark frames.
"""
import collections
import json
import math
import os
import queue
import signal
import struct
import subprocess
import sys
import threading
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2, Imu, Image, BatteryState
from std_msgs.msg import String, Empty
from motion_msgs.msg import MotionCtrl, RobotStatus
from transport import FrameMailbox

LEASE_S = 0.3          # a velocity command is valid this long
KEEPALIVE_S = 2.0      # server silence longer than this zeroes motion
ORPHAN_S = 10.0        # server silence longer than this starts the return along the driven path
TRACE_PERIOD_S = 0.1   # applied-command sample period
TRACE_KEEP_S = 1200.0  # keep this much of the driven history
LIDAR_STALL_S = 5.0    # no scan for this long (after the first one) restarts the LiDAR node
LIDAR_START_GRACE_S = 25.0  # allow the node this long to publish its first scan
LIDAR_RESTART_LIMIT = 4     # do not loop restarts forever
RETRACE_SPEED = 0.20   # m/s cap while returning along the path
RETRACE_TURN = 0.30    # rad/s cap while returning
RETRACE_MAX_M = 60.0   # never return further than this
RETRACE_MAX_S = 360.0  # hard time bound for the return
RETRACE_HOLD_S = 30.0  # wait this long for the server, then release the robot
# Command ceiling; 0.30 m/s (the lidar_viewer limit) unless the compute server passes XT_MAX_V
# for speed exploration.  Never above HARD_MAX_V (raised from 1.0 on 2026-10-10 to probe the
# chassis top speed; the firmware's own limit is undocumented).
HARD_MAX_V = 2.0
MAX_V = max(0.05, min(HARD_MAX_V, float(os.environ.get('XT_MAX_V', '0.30'))))
MAX_W = 1.0
# Robot-side install locations (DIABLO + Unitree L1 + Orbbec); override per robot with the XT_*_EXE variables.
LIDAR_EXE = os.path.expanduser(os.environ.get('XT_LIDAR_EXE', '~/unilidar_sdk/unitree_lidar_ros2/install/unitree_lidar_ros2/lib/unitree_lidar_ros2/unitree_lidar_ros2_node'))
LIDAR_ARGS = ['--ros-args', '-p', 'port:=/dev/ttyUSB0', '-p', 'rotate_yaw_bias:=0.0',
              '-p', 'range_scale:=0.001', '-p', 'range_bias:=0.0', '-p', 'range_max:=50.0',
              '-p', 'range_min:=0.0', '-p', 'cloud_frame:=unilidar_lidar',
              '-p', 'cloud_topic:=unilidar/cloud', '-p', 'cloud_scan_num:=18',
              '-p', 'imu_frame:=unilidar_imu', '-p', 'imu_topic:=unilidar/imu']
CHASSIS_EXE = os.path.expanduser(os.environ.get('XT_CHASSIS_EXE', '~/diablo_ws/build/diablo_ctrl/diablo_ctrl_node'))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # FlyHead checkout on the robot
LOG_DIR = os.path.join(ROOT, 'logs')
CAM_DIR = os.path.join(ROOT, 'robot', 'camera')
CAM_EXE = os.path.expanduser(os.environ.get('XT_CAMERA_EXE', '~/ros2_ws/install/orbbec_camera/lib/orbbec_camera/orbbec_camera_node'))
CAM_ARGS = ['--ros-args', '-r', '__node:=ob_camera_node', '-r', '__ns:=/xt_camera',
            '--params-file', os.path.join(CAM_DIR, 'camera.yaml'),
            '--disable-rosout-logs', '--disable-external-lib-logs']
CAM_FPS = max(0.1, float(os.environ.get('XT_CAM_FPS', '3')))
CAM_MAX_WIDTH = max(160, int(os.environ.get('XT_CAM_MAX_WIDTH', '480')))
CAM_QUALITY = 60
cv2.setNumThreads(1)  # image conversion must not create another competing pool

NODE = None            # set in main(); the output writer reports a broken link to it


def link_broken():
    """The server-side pipe failed.  Keep running: the bridge returns along its path."""
    node = NODE
    if node is not None:
        node.link_lost('output pipe to the compute server failed')
    return node is not None


out_q = FrameMailbox()


def emit(kind, payload):
    out_q.put(kind, payload)


def emit_json(obj):
    out_q.put(3, json.dumps(obj, ensure_ascii=False, allow_nan=False).encode(),
              latest_status=obj.get('event') == 'status')


def writer():
    out = sys.stdout.buffer
    while True:
        frame = out_q.get()
        if frame is None:
            return
        try:
            frames = [frame]
            size = len(frame)
            while len(frames) < 32 and size < 65536:
                additional = out_q.get(wait=False)
                if additional is None:
                    break
                frames.append(additional)
                size += len(additional)
            out.write(b''.join(frames))
            out.flush()
        except (BrokenPipeError, OSError):
            if not link_broken():
                os.kill(os.getpid(), signal.SIGTERM)
                return
            time.sleep(0.2)      # server is gone; discard frames instead of dying


def port_free(dev):
    r = subprocess.run(['fuser', dev], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
    return r.returncode == 1 and not r.stdout.strip()


def spawn(name, cmd, env=None):
    os.makedirs(LOG_DIR, exist_ok=True)
    log = open(os.path.join(LOG_DIR, name + '_' + time.strftime('%Y%m%dT%H%M%S') + '.log'), 'w')
    return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                            env=env, cwd=LOG_DIR)


def stop_child(p, grace=4.0):
    if p is None or p.poll() is not None:
        return
    os.killpg(p.pid, signal.SIGINT)
    try:
        p.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGTERM)
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)


class Bridge(Node):
    def __init__(self):
        super().__init__('xt_slam_bridge')
        self.lock = threading.Lock()
        self.shutdown_event = threading.Event()
        # Physical motion needs both interlocks: charging lock off and remote opt-in.
        self.chassis_disabled = (os.environ.get('XT_CHASSIS_DISABLED', '1') != '0'
                                 or os.environ.get('XT_REMOTE_MOTION_ENABLED', '0') != '1')
        self.operation_lock = threading.Lock()
        self.operations = queue.Queue(maxsize=8)
        self.operation_busy = False
        self.last_sequence = -1
        self.rejected_commands = 0
        self.tick_interval_s = None
        self.last_tick = None
        self.camera_event = threading.Event()
        self.camera_lock = threading.Lock()
        self.camera_latest = None
        self.v = self.w = 0.0
        self.cmd_until = 0.0
        self.last_rx = time.monotonic()
        self.zero_until = 0.0
        self.chassis = None
        self.lidar = None
        self.camera = None
        self.cam_last = 0.0
        self.cam_frames = 0
        self.safety = None
        self.safety_received_at = 0.0
        self.safety_clear_since = None
        self.posture_result = dict(state='idle', ok=None)
        self.last_auto_reset = 0.0
        # height target carried by every movement frame.  The driver repeats the last
        # frame every 50 ms, so it must be 0 after a crouch request (the official
        # teleop never sends up=1.0 after stand_mode=False); 1.0 after standing.
        self.up = 1.0
        self.auto_resets = 0
        self.body = None
        self.applied_trace = collections.deque()
        self.trace_distance = 0.0
        self.last_cloud_mono = time.monotonic()
        self.lidar_started_mono = time.monotonic()
        self.lidar_restarts = 0
        self.returning = False
        self.return_done = False
        self.return_reason = None
        self.return_force = False
        self.return_state = None
        self.clouds = self.imus = 0
        self.offsets = None
        self.pub = self.create_publisher(MotionCtrl, '/diablo/MotionCmd', 1)
        self.reset_pub = self.create_publisher(Empty, '/diablo/safety/reset', 1)
        self.create_subscription(PointCloud2, '/unilidar/cloud', self.on_cloud, qos_profile_sensor_data)
        self.create_subscription(Imu, '/unilidar/imu', self.on_imu, qos_profile_sensor_data)
        self.create_subscription(Image, '/xt_camera/color/image_raw', self.on_image, qos_profile_sensor_data)
        self.create_subscription(String, '/diablo/safety/status', self.on_safety, 1)
        self.create_subscription(RobotStatus, '/diablo/sensor/Body_state', self.on_body, 10)
        self.create_subscription(BatteryState, '/diablo/sensor/Battery', self.on_battery, 10)
        self.battery = None
        self.workers = [
            threading.Thread(target=self.control_worker, name='bridge-control', daemon=True),
            threading.Thread(target=self.operation_worker, name='bridge-operations', daemon=True),
            threading.Thread(target=self.camera_worker, name='bridge-jpeg', daemon=True),
            threading.Thread(target=self.lidar_watchdog, name='bridge-lidar-watch', daemon=True),
        ]
        for worker in self.workers:
            worker.start()
        self.create_timer(0.5, self.report)

    # ---------- sensors ----------
    def on_cloud(self, msg):
        self.last_cloud_mono = time.monotonic()
        if self.offsets is None:
            offs = {f.name: f.offset for f in msg.fields if f.datatype == 7 and f.count == 1}
            if not {'x', 'y', 'z', 'time'} <= set(offs):
                emit_json(dict(event='error', error='cloud fields missing', fields=[f.name for f in msg.fields]))
                return
            self.offsets = offs
            emit_json(dict(event='cloud_format', fields=[(f.name, f.offset, f.datatype) for f in msg.fields],
                           point_step=msg.point_step, frame=msg.header.frame_id))
        n = msg.width * msg.height
        if n == 0:
            return
        dt = '>f4' if msg.is_bigendian else '<f4'
        buf = bytes(msg.data)
        cols = []
        for k in ('x', 'y', 'z', 'intensity', 'time'):
            if k not in self.offsets:
                cols.append(np.zeros(n, np.float32))
                continue
            a = np.ndarray((n,), dtype=dt, buffer=buf, offset=self.offsets[k], strides=(msg.point_step,))
            cols.append(a.astype(np.float32))
        arr = np.ascontiguousarray(np.stack(cols, axis=1), dtype='<f4')
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        emit(1, struct.pack('<dI', stamp, n) + arr.tobytes())
        self.clouds += 1

    def on_imu(self, msg):
        q, g, a = msg.orientation, msg.angular_velocity, msg.linear_acceleration
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        emit(2, struct.pack('<d10f', stamp, q.x, q.y, q.z, q.w, g.x, g.y, g.z, a.x, a.y, a.z))
        self.imus += 1

    def on_image(self, msg):
        now = time.monotonic()
        if now - self.cam_last < 1.0 / CAM_FPS or msg.encoding not in ('rgb8', 'bgr8'):
            return
        self.cam_last = now
        with self.camera_lock:
            self.camera_latest = msg
        self.camera_event.set()

    def camera_worker(self):
        while not self.shutdown_event.is_set():
            if not self.camera_event.wait(0.5):
                continue
            self.camera_event.clear()
            with self.camera_lock:
                msg, self.camera_latest = self.camera_latest, None
            if msg is not None:
                try:
                    self.encode_image(msg)
                except Exception as error:
                    emit_json(dict(event='error', error='JPEG: %r' % error))

    def encode_image(self, msg):
        img = np.frombuffer(msg.data, np.uint8).reshape(msg.height, msg.step)[:, :msg.width * 3]
        img = img.reshape(msg.height, msg.width, 3)
        if msg.width > CAM_MAX_WIDTH:
            height = max(1, round(msg.height * CAM_MAX_WIDTH / msg.width))
            img = cv2.resize(img, (CAM_MAX_WIDTH, height), interpolation=cv2.INTER_AREA)
        if msg.encoding == 'rgb8':
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        ok, jpg = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, CAM_QUALITY])
        if ok:
            stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            emit(4, struct.pack('<d', stamp) + jpg.tobytes())
            self.cam_frames += 1

    def start_camera(self):
        if self.camera is not None and self.camera.poll() is None:
            return emit_json(dict(event='camera', ok=True, note='already running'))
        env = dict(os.environ)
        env['AMENT_PREFIX_PATH'] = os.path.join(CAM_DIR, 'overlay') + ':' + env.get('AMENT_PREFIX_PATH', '')
        env['ROS_LOG_DIR'] = LOG_DIR
        self.camera = spawn('camera', [CAM_EXE] + CAM_ARGS, env=env)
        emit_json(dict(event='camera', ok=True, pid=self.camera.pid))

    def stop_camera(self):
        stop_child(self.camera)
        self.camera = None
        emit_json(dict(event='camera', ok=True, stopped=True))

    def on_safety(self, msg):
        try:
            sf = json.loads(msg.data)
        except ValueError:
            return
        self.safety = sf
        received_at = time.monotonic()
        if received_at - self.safety_received_at > 0.5:
            self.safety_clear_since = None
        self.safety_received_at = received_at
        # Applied-command trace: the driver reports what it actually kept after
        # its own guard.  This is the path the robot drove, so it is what the
        # link-loss return replays backwards.
        if not self.applied_trace or received_at - self.applied_trace[-1][0] >= TRACE_PERIOD_S:
            forward = float(sf.get('command_forward') or 0.0)
            turn = float(sf.get('command_turn') or 0.0)
            if self.applied_trace:
                self.trace_distance += abs(forward) * max(0.0, received_at - self.applied_trace[-1][0])
            self.applied_trace.append((received_at, forward, turn))
            while self.applied_trace and received_at - self.applied_trace[0][0] > TRACE_KEEP_S:
                self.applied_trace.popleft()
        clear = (sf.get('fresh') is True and sf.get('imu_fresh') is True
                 and sf.get('blocked') is False and sf.get('latched') is False
                 and sf.get('present') is False)
        if clear:
            self.safety_clear_since = self.safety_clear_since or self.safety_received_at
        else:
            self.safety_clear_since = None
        # diablo_ctrl starts latched and re-latches on any stale LiDAR gap; it
        # then blocks everything but reverse until /diablo/safety/reset.  Send
        # that reset only when the driver itself reports no obstacle within
        # stop_m and reset_ready (fresh, clear for clear_hold_s).  A real
        # obstacle (present) is never cleared here.
        now = time.monotonic()
        if (not self.chassis_disabled and sf.get('latched') is True and sf.get('present') is False and sf.get('reset_ready') is True
                and sf.get('fresh') is True and now - self.last_auto_reset > 1.0):
            self.reset_pub.publish(Empty())
            self.last_auto_reset = now
            self.auto_resets += 1

    def on_battery(self, msg):
        self.battery = dict(voltage=round(float(msg.voltage), 2), pct=round(float(msg.percentage), 1),
                            t=time.monotonic())

    def on_body(self, msg):
        self.body = dict(ctrl_mode=msg.ctrl_mode_msg, robot_mode=msg.robot_mode_msg,
                         error=msg.error_msg, warning=msg.warning_msg, t=time.monotonic())

    # ---------- commands ----------
    def handle_cmd(self, obj):
        op = obj.get('op')
        now = time.monotonic()
        if op not in ('ping', 'cmd', 'chassis', 'camera', 'posture', 'safety_reset', 'retrace', 'quit'):
            raise ValueError('Unknown operation')
        with self.lock:
            self.last_rx = now
        if op == 'ping':
            token = obj.get('clock_token')
            if isinstance(token, str) and len(token) <= 64:
                emit_json(dict(event='clock', clock_token=token,
                               mono=time.monotonic(), wall=time.time()))
            return
        if op == 'quit':
            raise SystemExit
        if self.chassis_disabled and (op in ('posture', 'safety_reset')
                                      or (op == 'chassis' and obj.get('on'))):
            emit_json(dict(event='error', error='charging debug: chassis operations disabled'))
            return
        sequence = obj.get('sequence', -1)
        deadline = obj.get('deadline_mono')
        valid = (isinstance(sequence, int) and sequence > self.last_sequence
                 and isinstance(deadline, (float, int)) and math.isfinite(deadline)
                 and 0 < deadline - now <= 2.1)
        if isinstance(sequence, int):
            self.last_sequence = max(self.last_sequence, sequence)
        if op == 'cmd':
            v, w = float(obj.get('v', 0)), float(obj.get('w', 0))
            valid = valid and deadline - now <= LEASE_S + 0.01
            if self.chassis_disabled or not (math.isfinite(v) and math.isfinite(w)) or not valid or self.operation_busy:
                v = w = 0.0
                self.rejected_commands += 1
            with self.lock:
                self.v = max(-MAX_V, min(MAX_V, v))
                self.w = max(-MAX_W, min(MAX_W, w))
                # Absolute sender deadline on the same onboard monotonic clock.
                # Receipt never grants an old command another 300 ms of motion.
                self.cmd_until = min(deadline, now + LEASE_S) if (self.v or self.w) else 0.0
            return
        if not valid:
            self.rejected_commands += 1
            emit_json(dict(event='error', error='expired/unversioned operation: %s' % op))
            return
        try:
            self.operations.put_nowait(obj)
        except queue.Full:
            self.rejected_commands += 1
            emit_json(dict(event='error', error='operation queue full; request not executed'))

    def operation_worker(self):
        while not self.shutdown_event.is_set():
            try:
                obj = self.operations.get(timeout=0.2)
            except queue.Empty:
                continue
            with self.operation_lock:
                if self.shutdown_event.is_set():
                    return
                if time.monotonic() >= obj['deadline_mono']:
                    self.rejected_commands += 1
                    emit_json(dict(event='error', error='queued operation expired; not executed'))
                    continue
                self.operation_busy = True
                try:
                    op = obj['op']
                    if op in ('chassis', 'posture', 'safety_reset'):
                        with self.lock:
                            self.v = self.w = self.cmd_until = 0.0
                    if op == 'chassis':
                        if obj.get('on'):
                            self.start_chassis()
                        else:
                            self.stop_chassis()
                    elif op == 'camera':
                        if obj.get('on'):
                            self.start_camera()
                        else:
                            self.stop_camera()
                    elif op == 'posture':
                        self.request_posture(bool(obj.get('stand')), deadline=obj['deadline_mono'])
                    elif op == 'safety_reset':
                        self.reset_pub.publish(Empty())
                    elif op == 'retrace':
                        self.link_lost('operator requested a return along the driven path', force=True)
                except Exception as error:
                    emit_json(dict(event='error', error='operation: %r' % error))
                finally:
                    self.operation_busy = False

    def control_worker(self):
        deadline = time.monotonic()
        while not self.shutdown_event.is_set():
            deadline += 0.05
            if self.shutdown_event.wait(max(0.0, deadline - time.monotonic())):
                return
            now = time.monotonic()
            if now - deadline > 0.05:
                deadline = now
            self.tick_interval_s = None if self.last_tick is None else now - self.last_tick
            self.last_tick = now
            try:
                self.tick()
            except Exception as error:
                emit_json(dict(event='error', error='control publisher: %r' % error))
                self.shutdown_event.set()
                return

    def start_chassis(self):
        if self.chassis_disabled:
            return emit_json(dict(event='chassis', ok=False, error='charging debug: chassis disabled'))
        if self.chassis is not None and self.chassis.poll() is None:
            return emit_json(dict(event='chassis', ok=True, note='already running'))
        if self.lidar is None or self.lidar.poll() is not None:
            return emit_json(dict(event='chassis', ok=False, error='lidar not running; obstacle guard needs it'))
        if not port_free('/dev/ttyAMA0'):
            return emit_json(dict(event='chassis', ok=False, error='/dev/ttyAMA0 already owned'))
        self.body = None
        self.safety = None
        self.safety_received_at = 0.0
        self.safety_clear_since = None
        self.posture_result = dict(state='idle', ok=None)
        self.chassis = spawn('chassis', [CHASSIS_EXE])
        emit_json(dict(event='chassis', ok=True, pid=self.chassis.pid))

    def stop_chassis(self):
        with self.lock:
            self.v = self.w = 0.0
            self.cmd_until = 0.0
        self.publish(0.0, 0.0)
        stop_child(self.chassis)
        self.chassis = None
        emit_json(dict(event='chassis', ok=True, stopped=True))

    def posture_block_reason(self):
        now = time.monotonic()
        if self.chassis_disabled:
            return 'chassis interface is locked'
        if self.chassis is None or self.chassis.poll() is not None:
            return 'chassis driver is not running'
        if self.body is None or now - self.body['t'] > 0.5:
            return 'waiting for fresh chassis posture feedback'
        if self.body.get('error'):
            return 'chassis error code %s' % self.body['error']
        sf = self.safety or {}
        if now - self.safety_received_at > 0.5:
            return 'waiting for fresh robot-side guard feedback'
        if sf.get('fresh') is not True or sf.get('imu_fresh') is not True:
            return 'waiting for LiDAR / IMU readiness'
        # The obstacle/latch gate and the continuous-clear window were removed: the
        # chassis guard is report-only now and the host layer owns avoidance, so
        # blocking a posture change just because something stood near became an
        # arbitrary rule that deadlocked the operator (0.366 m in front).
        return None

    def report_posture(self, stand, state, ok, note):
        self.posture_result = dict(state=state, ok=ok, stand=stand, note=note,
                                   t=time.time(), body=None if self.body is None else dict(self.body))
        emit_json(dict(event='posture', **self.posture_result))

    def request_posture(self, stand, deadline=None):
        """Send once within its lease; success requires three new body samples."""
        if self.chassis_disabled:
            return self.report_posture(stand, 'rejected', False, 'chassis interface is locked')
        deadline = time.monotonic() + 2.0 if deadline is None else deadline
        self.report_posture(stand, 'waiting_guard', None, 'waiting for robot-side posture admission (not yet executed)')
        while True:
            reason = self.posture_block_reason()
            if time.monotonic() >= deadline:
                return self.report_posture(stand, 'rejected', False, reason or 'posture request expired')
            if reason is None:
                break
            if self.shutdown_event.wait(0.05):
                return self.report_posture(stand, 'cancelled', False, 'bridge is shutting down')
        target_mode = 3 if stand else 2
        if self.body['robot_mode'] == target_mode:
            return self.report_posture(stand, 'confirmed', True, 'fresh feedback already shows the target posture; nothing sent')
        with self.lock:
            self.v = self.w = self.cmd_until = 0.0
            self.up = 1.0 if stand else 0.0
        self.publish(0.0, 0.0)
        message = MotionCtrl()
        message.mode_mark = True
        message.mode.stand_mode = stand
        sent_at = time.monotonic()
        if sent_at >= deadline:
            return self.report_posture(stand, 'rejected', False, 'posture request expired before sending')
        self.pub.publish(message)
        self.report_posture(stand, 'confirming', None, 'posture command sent once; waiting for the chassis to confirm')
        last_body_stamp = sent_at
        confirmed_samples = 0
        while not self.shutdown_event.wait(0.05):
            self.publish(0.0, 0.0)
            body = self.body
            now = time.monotonic()
            if self.chassis is None or self.chassis.poll() is not None:
                return self.report_posture(stand, 'failed', False, 'chassis driver exited while waiting for confirmation')
            if body is not None and body['t'] > last_body_stamp:
                last_body_stamp = body['t']
                valid = now - body['t'] < 0.5 and body['robot_mode'] == target_mode and body.get('error') == 0
                confirmed_samples = confirmed_samples + 1 if valid else 0
                if confirmed_samples >= 3:
                    return self.report_posture(stand, 'confirmed', True, 'three consecutive fresh chassis samples confirm the target posture')
                if body.get('error'):
                    return self.report_posture(stand, 'failed', False, 'chassis error code %s' % body['error'])
            if now - sent_at >= 8.0:
                return self.report_posture(stand, 'failed', False, 'target posture not confirmed within 8 s; not resent, check driver output and hardware warnings')
        self.report_posture(stand, 'cancelled', False, 'bridge closed before the posture was confirmed')

    def publish(self, v, w):
        if self.chassis_disabled:
            return
        m = MotionCtrl()
        m.value.forward = float(v)
        m.value.left = float(w)
        m.value.up = float(self.up)
        self.pub.publish(m)

    def tick(self):
        now = time.monotonic()
        with self.lock:
            alive = now - self.last_rx < KEEPALIVE_S
            active = alive and not self.operation_busy and now < self.cmd_until
            v, w = (self.v, self.w) if active else (0.0, 0.0)
            if active:
                self.zero_until = now + 1.0
        chassis_up = self.chassis is not None and self.chassis.poll() is None
        if chassis_up and not self.returning and (active or now < self.zero_until):
            self.publish(v, w)          # zeros keep flowing for 1 s after release

    def link_lost(self, reason, force=False):
        """Return along the driven path: on a lost link, or on operator request.

        The LiDAR, the chassis driver and its obstacle guard stay running.  Only
        the returned commands differ; every limit and the driver guard still apply.
        """
        with self.lock:
            if self.returning or self.return_done or self.chassis_disabled:
                return False
            self.returning = True
            self.return_force = force
            self.v = self.w = 0.0
            self.cmd_until = 0.0
            self.return_reason = reason
        emit_json(dict(event='link_loss', reason=reason, mode='return_along_path',
                       samples=len(self.applied_trace), driven_m=round(self.trace_distance, 1),
                       note='replaying the executed commands backwards; robot-side limits stay active'))
        self.publish(0.0, 0.0)
        threading.Thread(target=self.return_worker, name='bridge-return', daemon=True).start()
        return True

    def return_worker(self):
        """Replay the applied-command trace backwards with both channels negated."""
        samples = list(self.applied_trace)
        while samples and abs(samples[-1][1]) < 1e-6 and abs(samples[-1][2]) < 1e-6:
            samples.pop()          # the idle tail carries no motion to undo
        started = time.monotonic()
        distance = 0.0
        stopped_reason = 'back at the start of the recorded path (command history used up)'
        previous_stamp = None
        for stamp, forward, turn in reversed(samples):
            if self.shutdown_event.is_set():
                stopped_reason = 'bridge is shutting down'
                break
            if not self.return_force and time.monotonic() - self.last_rx < 2.0:
                stopped_reason = 'server link restored; control handed back'
                break
            guard = self.safety or {}
            if guard.get('fresh') is False or guard.get('blocked') or guard.get('latched'):
                stopped_reason = 'robot-side obstacle guard intervened; return stopped, holding'
                break
            if previous_stamp is not None:
                self.shutdown_event.wait(min(0.5, max(0.0, previous_stamp - stamp)))
            previous_stamp = stamp
            command_v = max(-RETRACE_SPEED, min(RETRACE_SPEED, -forward))
            command_w = max(-RETRACE_TURN, min(RETRACE_TURN, -turn))
            self.publish(command_v, command_w)
            distance += abs(command_v) * TRACE_PERIOD_S
            if distance > RETRACE_MAX_M or time.monotonic() - started > RETRACE_MAX_S:
                stopped_reason = 'return reached the %.0f m / %.0f s limit; stopped' % (RETRACE_MAX_M, RETRACE_MAX_S)
                break
        self.publish(0.0, 0.0)
        with self.lock:
            self.returning = False
            self.return_done = True
        self.return_state = dict(reason=stopped_reason, distance_m=round(distance, 2),
                                 seconds=round(time.monotonic() - started, 1))
        emit_json(dict(event='link_return', state='done', **self.return_state,
                       note='return finished; waiting for the server, the robot is released after a timeout'))

    def lidar_watchdog(self):
        """Restart the LiDAR node after a verified scan stall.

        The L1 stopped publishing scans while its IMU kept running (clouds 0/s, IMU
        218/s, process alive).  Both subscribers lost the scan stream, so the chassis
        driver latched its obstacle guard and kept everything but reverse blocked:
        a stalled scan stream ends the session even though the process looks healthy.
        The bridge zeroes its own command first and restarts only the scan node.
        """
        while not self.shutdown_event.wait(1.0):
            if self.lidar is None or self.lidar.poll() is not None:
                continue
            reference = self.last_cloud_mono if self.clouds else self.lidar_started_mono
            threshold = LIDAR_STALL_S if self.clouds else LIDAR_START_GRACE_S
            silent = time.monotonic() - reference
            if silent < threshold:
                continue
            if self.lidar_restarts >= LIDAR_RESTART_LIMIT:
                emit_json(dict(event='error', error='LiDAR scan stream stalled for %.0f s; restart limit %d reached'
                               % (silent, LIDAR_RESTART_LIMIT)))
                self.shutdown_event.wait(LIDAR_STALL_S)
                continue
            with self.lock:
                self.v = self.w = 0.0
                self.cmd_until = 0.0
            self.publish(0.0, 0.0)
            self.lidar_restarts += 1
            emit_json(dict(event='lidar_restart', stalled_s=round(silent, 1), attempt=self.lidar_restarts,
                           note='LiDAR scan stream stalled: motion zeroed, restarting the LiDAR node (IMU still fresh)'))
            stop_child(self.lidar)
            self.lidar = spawn('lidar', [LIDAR_EXE] + LIDAR_ARGS)
            self.last_cloud_mono = time.monotonic()
            self.lidar_started_mono = self.last_cloud_mono
            self.clouds = 0
            self.imus = 0
            emit_json(dict(event='lidar', ok=True, pid=self.lidar.pid, restarted=True))

    def report(self):
        ch = self.chassis
        transport = out_q.stats()
        emit_json(dict(event='status', t=time.time(), clouds=self.clouds, imus=self.imus,
                       dropped=sum(transport['dropped'].values()), transport=transport,
                       capabilities=['command-deadline-v1', 'clock-echo-v1', 'posture-confirmation-v1',
                                     'link-loss-return-v1'], chassis_disabled=self.chassis_disabled,
                       link_return=dict(active=self.returning, done=self.return_done,
                                        trigger=self.return_reason, result=self.return_state,
                                        trace_samples=len(self.applied_trace),
                                        driven_m=round(self.trace_distance, 1)),
                       command_rejected=self.rejected_commands, last_sequence=self.last_sequence,
                       control_interval_s=self.tick_interval_s, operation_busy=self.operation_busy,
                       posture_ready=self.posture_block_reason() is None,
                       posture_block_reason=self.posture_block_reason(), posture_result=dict(self.posture_result),
                       lidar_running=self.lidar is not None and self.lidar.poll() is None,
                       chassis_running=ch is not None and ch.poll() is None,
                       camera_running=self.camera is not None and self.camera.poll() is None,
                       cam_frames=self.cam_frames, auto_resets=self.auto_resets,
                       chassis_exit=None if ch is None else ch.poll(),
                       body=None if self.body is None else dict(self.body, age=time.monotonic() - self.body['t']),
                       battery=None if self.battery is None else dict(self.battery, age=time.monotonic() - self.battery['t']),
                       safety=self.safety, cmd=[self.v, self.w] if time.monotonic() < self.cmd_until else [0, 0],
                       max_v=MAX_V))


def main():
    global NODE
    # Leaving the SSH session must not kill a return along the path: run.sh uses
    # setsid and the bridge ignores SIGHUP.
    rclpy.init()
    node = Bridge()
    NODE = node
    threading.Thread(target=writer, daemon=True).start()
    stopping = node.shutdown_event

    def on_signal(*_):
        stopping.set()
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    def reader():
        for line in sys.stdin:
            try:
                node.handle_cmd(json.loads(line))
            except SystemExit:
                break
            except Exception as exc:  # malformed command: report, never move
                emit_json(dict(event='error', error='command: %s' % exc))
        stopping.set()
    threading.Thread(target=reader, daemon=True).start()

    def watchdog():
        # A half-dead TCP link never delivers stdin EOF; the server pings every
        # 0.5 s.  Prolonged silence starts the return along the driven path instead
        # of killing the session; the robot is only released after the return and
        # a further hold without a server.
        while not stopping.wait(1.0):
            with node.lock:
                silent = time.monotonic() - node.last_rx
            if silent <= ORPHAN_S:
                continue
            if node.return_done:
                if silent > ORPHAN_S + RETRACE_HOLD_S:
                    sys.stderr.write('server absent for %.1f s after the return; releasing the robot\n' % silent)
                    stopping.set()
                continue
            if node.returning:
                continue
            if not node.link_lost('no server traffic for %.1f s' % silent):
                # Nothing to return to (interface locked or already finished):
                # keep the previous behaviour instead of holding the robot forever.
                sys.stderr.write('no server traffic for %.1f s; shutting down\n' % silent)
                stopping.set()
    threading.Thread(target=watchdog, daemon=True).start()

    try:
        if not port_free('/dev/ttyUSB0'):
            emit_json(dict(event='error', error='/dev/ttyUSB0 already owned; lidar not started'))
        else:
            node.lidar = spawn('lidar', [LIDAR_EXE] + LIDAR_ARGS)
            emit_json(dict(event='lidar', ok=True, pid=node.lidar.pid))
        if os.environ.get('XT_CAMERA', '1') != '0':   # onboard default off (CPU); page can start it
            node.start_camera()
        else:
            emit_json(dict(event='camera', ok=True, note='camera off by default onboard; use the page to start it'))
        while rclpy.ok() and not stopping.is_set():
            rclpy.spin_once(node, timeout_sec=0.05)
    finally:
        stopping.set()
        node.camera_event.set()
        with node.operation_lock:
            try:
                node.stop_chassis()
            finally:
                stop_child(node.camera)
                stop_child(node.lidar)
        for worker in node.workers:
            worker.join(timeout=2)
        emit_json(dict(event='bye'))
        time.sleep(0.2)
        out_q.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

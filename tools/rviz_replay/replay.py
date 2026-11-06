#!/usr/bin/env python3
"""Replay recorded closed-loop simulation windows into a real RViz2 and record its window.

Nothing is re-simulated. Each recorded 100 ms window gives the pose published on TF; poses are linearly
interpolated between windows for display only. The vendor DIABLO URDF is shown by RobotModel through
robot_state_publisher. Leg joints stay at the URDF's zero pose and wheel spin is integrated from the recorded
v and w: both are display choices, not dynamics.

No robot topic is used and nothing here can command a robot: the script only publishes visualization data
on an isolated ROS domain limited to localhost (see run_scene.sh).

  replay.py SCENE --runs DIR --cloud map_xyz.npy --out OUT.mp4 --display :99 [--speed 1] [--fps 15] [--limit S]

SCENE is a flyhead.sim.loom_sim scenario (DIR/SCENE_brain.jsonl, DIR/SCENE_blind.jsonl) or `stage6`
(DIR/reflex_1.jsonl, DIR/planner_1.jsonl from flyhead.sim.reflex_sim).
"""
import argparse
import json
import math
import subprocess
import time
from pathlib import Path

import numpy as np
import rclpy
from geometry_msgs.msg import Point, TransformStamped
from rclpy.qos import DurabilityPolicy, QoSProfile
from sensor_msgs.msg import JointState, PointCloud2, PointField
from std_msgs.msg import ColorRGBA, Header
from tf2_ros import TransformBroadcaster
from visualization_msgs.msg import Marker, MarkerArray

STATE_RGB = {
    'FORWARD': (0.25, 0.73, 0.31), 'EXPLORE': (0.20, 0.72, 0.68), 'TURN_LEFT': (0.35, 0.65, 1.0),
    'TURN_RIGHT': (0.35, 0.65, 1.0), 'HOLD': (0.60, 0.62, 0.65), 'REST': (0.45, 0.47, 0.50),
    'FREEZE': (0.95, 0.80, 0.25), 'ESCAPE_PROGRAM': (0.97, 0.32, 0.29), 'BACK_OFF': (0.97, 0.55, 0.25),
    'FLEE': (0.86, 0.40, 0.90),
}
PLANNER_RGB = (0.35, 0.65, 1.0)
WHEEL_R = 0.094            # vendor mesh
HALF_TRACK = 0.25          # display only, for wheel spin
OBJECT_RADIUS = 0.25       # flyhead.sim.loom_sim: every scenario object is a 0.25 m cylinder
OBJECT_HEIGHT = 1.7        # display only
CEILING_M = 2.0
FLOOR_CUT_M = 0.12         # floor returns hide the walls; dropped for display only
REACH_M = 14.0
MAX_POINTS = 80000
VIEW_YAW = 3.6              # flyhead.rviz, Orbit Yaw
HUD_RIGHT = (-math.sin(VIEW_YAW) * 1.35, math.cos(VIEW_YAW) * 1.35)
HUD_TOP = 1.75
JOINTS = ['Rev1', 'Rev2', 'Rev3', 'Rev4', 'Rev5', 'Rev6', 'Rev7', 'Rev8']


def load(path):
    return [json.loads(line) for line in open(path, encoding='utf-8') if line.strip()]


def rows_of(path):
    return [r for r in load(path) if 't' in r and r.get('type') is None]


def spin(rows):
    """Wheel angles integrated from the recorded v and w."""
    left = right = 0.0
    prev = rows[0]['t']
    for r in rows:
        dt = r['t'] - prev
        prev = r['t']
        left += (r['v'] - r['w'] * HALF_TRACK) * dt / WHEEL_R
        right += (r['v'] + r['w'] * HALF_TRACK) * dt / WHEEL_R
        r['_wl'], r['_wr'] = left, right


def lerp_row(rows, t):
    i = min(max(int(np.searchsorted([r['t'] for r in rows[:0]] or T_CACHE[id(rows)], t, side='right')) - 1, 0), len(rows) - 1)
    a = rows[i]
    b = rows[min(i + 1, len(rows) - 1)]
    span = b['t'] - a['t']
    u = 0.0 if span <= 0 else min(max((t - a['t']) / span, 0.0), 1.0)
    dyaw = math.remainder(b['yaw'] - a['yaw'], 2 * math.pi)
    return a, i, dict(x=a['x'] + (b['x'] - a['x']) * u, y=a['y'] + (b['y'] - a['y']) * u, yaw=a['yaw'] + dyaw * u,
                      wl=a['_wl'] + (b['_wl'] - a['_wl']) * u, wr=a['_wr'] + (b['_wr'] - a['_wr']) * u)


T_CACHE = {}


def color(rgb, a=1.0):
    return ColorRGBA(r=float(rgb[0]), g=float(rgb[1]), b=float(rgb[2]), a=float(a))


class Replay:
    def __init__(self, a):
        self.a = a
        rclpy.init()
        self.node = rclpy.create_node('flyhead_rviz_replay')
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.cloud_pub = self.node.create_publisher(PointCloud2, '/site_cloud', latched)
        self.marker_pub = self.node.create_publisher(MarkerArray, '/replay_markers', 10)
        self.js = self.node.create_publisher(JointState, '/joint_states', 10)
        self.js_blind = self.node.create_publisher(JointState, '/blind/joint_states', 10)
        self.tf = TransformBroadcaster(self.node)

        runs = Path(a.runs)
        self.stage6 = a.scene == 'stage6'
        if self.stage6:
            self.A, self.B = rows_of(runs / 'reflex_1.jsonl'), rows_of(runs / 'planner_1.jsonl')
        else:
            self.A, self.B = rows_of(runs / f'{a.scene}_brain.jsonl'), rows_of(runs / f'{a.scene}_blind.jsonl')
        for rows in (self.A, self.B):
            spin(rows)
            T_CACHE[id(rows)] = np.array([r['t'] for r in rows])
        self.floor = self.publish_cloud()

    def now(self):
        return self.node.get_clock().now().to_msg()

    def publish_cloud(self):
        p = np.load(self.a.cloud)
        cx, cy = self.A[0]['x'], self.A[0]['y']
        near = np.hypot(p[:, 0] - cx, p[:, 1] - cy)
        local = p[near < 2.5]
        floor = float(np.percentile(local[:, 2], 3)) if len(local) > 50 else float(np.percentile(p[:, 2], 2))
        q = p[(near < REACH_M) & (p[:, 2] > floor + FLOOR_CUT_M) & (p[:, 2] < floor + CEILING_M)]
        if len(q) > MAX_POINTS:
            q = q[np.random.default_rng(0).choice(len(q), MAX_POINTS, replace=False)]
        q = q.astype(np.float32).copy()
        q[:, 2] -= floor
        self.cloud = PointCloud2(
            header=Header(frame_id='map', stamp=self.now()), height=1, width=len(q), is_dense=True, is_bigendian=False,
            point_step=12, row_step=12 * len(q), data=q.tobytes(),
            fields=[PointField(name=n, offset=4 * i, datatype=PointField.FLOAT32, count=1) for i, n in enumerate('xyz')])
        self.cloud_pub.publish(self.cloud)
        return floor

    def tf_of(self, child, s):
        m = TransformStamped()
        m.header.stamp = self.now()
        m.header.frame_id = 'map'
        m.child_frame_id = child
        m.transform.translation.x, m.transform.translation.y = float(s['x']), float(s['y'])
        m.transform.rotation.z, m.transform.rotation.w = math.sin(s['yaw'] / 2), math.cos(s['yaw'] / 2)
        return m

    def joints(self, pub, s):
        msg = JointState()
        msg.header.stamp = self.now()
        msg.name = JOINTS
        msg.position = [0.0, 0.0, 0.0, 0.0, float(s['wr']), 0.0, 0.0, float(-s['wl'])]
        pub.publish(msg)

    def marker(self, i, kind, ns='replay'):
        m = Marker()
        m.header.frame_id = 'map'
        m.header.stamp = self.now()
        m.ns, m.id, m.type, m.action = ns, i, kind, Marker.ADD
        m.pose.orientation.w = 1.0
        return m

    def state_of(self, r):
        if self.stage6:
            return r.get('brain_state') or ''
        return (r.get('intent') or {}).get('state', '')

    def objects_of(self, r):
        if self.stage6:
            return [r['person']] if r.get('person') else []
        return r.get('objects') or []

    def markers(self, i, ra, sa, j, sb):
        out = []
        # the path of the primary arm so far, coloured by decoder state (stage 6: by command source)
        path = self.marker(1, Marker.LINE_STRIP)
        path.scale.x = 0.05
        for r in self.A[:i + 1:max(1, (i + 1) // 400)]:
            path.points.append(Point(x=float(r['x']), y=float(r['y']), z=0.03))
            if self.stage6:
                rgb = STATE_RGB['ESCAPE_PROGRAM'] if r.get('source') == 'reflex' else PLANNER_RGB
            else:
                rgb = STATE_RGB.get(self.state_of(r), (0.6, 0.6, 0.6))
            path.colors.append(color(rgb))
        if len(path.points) >= 2:
            out.append(path)
        other = self.marker(2, Marker.LINE_STRIP)
        other.scale.x = 0.03
        other.color = color((0.75, 0.77, 0.80), 0.8)
        other.points = [Point(x=float(r['x']), y=float(r['y']), z=0.02) for r in self.B[:j + 1:max(1, (j + 1) // 400)]]
        if len(other.points) >= 2:
            out.append(other)
        objs = self.objects_of(ra)
        for k in range(4):
            o = self.marker(10 + k, Marker.CYLINDER)
            if k < len(objs):
                o.pose.position.x, o.pose.position.y, o.pose.position.z = float(objs[k][0]), float(objs[k][1]), OBJECT_HEIGHT / 2
                o.scale.x = o.scale.y = OBJECT_RADIUS * 2
                o.scale.z = OBJECT_HEIGHT
                o.color = color((1.0, 0.55, 0.15), 0.75)
            else:
                o.action = Marker.DELETE
            out.append(o)
        z = HUD_TOP
        for k, (text, size, rgb) in enumerate(self.labels(ra, sa, sb)):   # fixed screen side: the view never yaws
            m = self.marker(20 + k, Marker.TEXT_VIEW_FACING)
            m.pose.position.x, m.pose.position.y, m.pose.position.z = sa['x'] + HUD_RIGHT[0], sa['y'] + HUD_RIGHT[1], z
            z -= size * 1.35
            m.scale.z = size
            m.color = color(rgb)
            m.text = text
            out.append(m)
        arr = MarkerArray()
        arr.markers = out
        return arr

    def labels(self, r, sa, sb):
        """(text, size, rgb). RViz text markers draw very wide spaces, so each value is its own line without spaces."""
        white, blue = (0.92, 0.92, 0.92), (0.75, 0.85, 1.0)
        if self.stage6:
            src = r.get('source') or ''
            pm = r.get('person_m')
            big = ('BRAIN:' + (r.get('brain_state') or '')) if src == 'reflex' else 'PLANNER'
            return [(big, 0.22, STATE_RGB['ESCAPE_PROGRAM'] if src == 'reflex' else PLANNER_RGB),
                    ('nav=' + (r.get('nav_state') or '-'), 0.15, white),
                    ('takeovers=%d' % (r.get('reflex_count') or 0), 0.15, white),
                    ('person=' + ('-' if pm is None else '%.2fm' % pm), 0.15, white)]
        it = r.get('intent') or {}
        state = it.get('state', '')
        ex = r.get('executed') or [r.get('v', 0), r.get('w', 0)]
        loom = r.get('loom') or [0, 0]
        out = [(state, 0.22, STATE_RGB.get(state, white)),
               ('v=%+.2fm/s' % ex[0], 0.15, white), ('w=%+.2frad/s' % ex[1], 0.15, white),
               ('clearance=%.2fm' % (r.get('clearance') or 0), 0.15, white),
               ('GF=%.0fHz' % it.get('gf_hz', 0), 0.15, blue), ('MDN=%.0fHz' % it.get('mdn_hz', 0), 0.15, blue),
               ('P9=%.0fHz' % it.get('p9_hz', 0), 0.15, blue), ('loom=%.1f/%.1f' % (loom[0], loom[1]), 0.15, blue)]
        if r.get('contact'):
            out.append(('CONTACT', 0.2, (1.0, 0.3, 0.3)))
        return out

    def publish(self, t):
        ra, i, sa = lerp_row(self.A, t)
        _, j, sb = lerp_row(self.B, t)
        self.tf.sendTransform([self.tf_of('base_link', sa), self.tf_of('blind/base_link', sb)])
        self.joints(self.js, sa)
        self.joints(self.js_blind, sb)
        self.marker_pub.publish(self.markers(i, ra, sa, j, sb))
        rclpy.spin_once(self.node, timeout_sec=0)

    def grab(self):
        return subprocess.run(['xwd', '-root', '-silent', '-display', self.a.display], capture_output=True, check=True).stdout

    def run(self):
        a = self.a
        t0, t1 = self.A[0]['t'], self.A[-1]['t']
        if a.limit:
            t1 = min(t1, t0 + a.limit)
        for _ in range(int(a.warmup / 0.2)):           # RViz starts up; keep the latest state on the wire
            self.cloud_pub.publish(self.cloud)
            self.publish(t0)
            time.sleep(0.2)
        n = int((t1 - t0) * a.fps / a.speed)
        vf = "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='%s':x=w-tw-16:y=h-th-44:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=8" % a.caption.replace(':', r'\:').replace("'", '')
        ff = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'xwd_pipe', '-framerate', str(a.fps), '-i', '-', '-vf', vf + ',scale=1280:-2',
                               '-c:v', 'libx264', '-preset', 'medium', '-crf', str(a.crf), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', a.out], stdin=subprocess.PIPE)
        start = time.time()
        for f in range(n + int(a.fps)):                # one second of hold at the end
            t = min(t0 + f * a.speed / a.fps, t1)
            self.publish(t)
            time.sleep(a.settle)
            ff.stdin.write(self.grab())
            if f % 100 == 0:
                print('%s frame %d/%d  sim %.1f s  wall %.0f s' % (a.scene, f, n, t, time.time() - start), flush=True)
        ff.stdin.close()
        ff.wait()
        print('done', a.out, n, 'frames, wall %.0f s' % (time.time() - start), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('scene')
    ap.add_argument('--runs', required=True)
    ap.add_argument('--cloud', required=True, help='N x 3 float array of the saved site cloud')
    ap.add_argument('--out', required=True)
    ap.add_argument('--display', default=':99')
    ap.add_argument('--speed', type=float, default=1.0)
    ap.add_argument('--fps', type=int, default=15)
    ap.add_argument('--limit', type=float)
    ap.add_argument('--settle', type=float, default=0.25, help='seconds for RViz to draw before each capture')
    ap.add_argument('--warmup', type=float, default=20.0)
    ap.add_argument('--crf', type=int, default=29)
    ap.add_argument('--caption', default='RViz2 replay of recorded simulation')
    Replay(ap.parse_args()).run()


if __name__ == '__main__':
    main()

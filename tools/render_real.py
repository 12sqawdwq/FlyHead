"""Render demo material on a saved SLAM map package (a real site).

  mapbuild  OUT.mp4 PKG                  the mapping session replayed from PKG/trajectory.csv: the saved
                                         cloud appears as the robot's path comes within 8 m of it
  orbit     OUT.mp4 PKG                  3-D orbit of the saved cloud, coloured by height
  layers    OUT.png PKG [NAVLOG...]      navigation layers: occupancy, clearance + centreline (planner
                                         field), obstacle heights, and the routes from real tour logs
  navlog    OUT.mp4 PKG NAVLOG           a real autonomous tour replayed from the robot's own log
                                         (pose, planned route, goal, state, reason, fitness, command)
  scenarios OUT.png PKG RUN_DIR          brain vs. blind trajectories of every loom_sim scenario in RUN_DIR
  states    OUT.png RUN_DIR              decoder-state timelines of every brain run in RUN_DIR

NAVLOG files are the console observation logs (lines {"kind": "nav", "data": {...}}). The map packages
are floor plans of real buildings; publish renders only with the site owner's consent.
python tools/render_real.py MODE OUT ARGS... [--fps 10] [--speed S]
"""
import argparse
import glob
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.animation import FFMpegWriter  # noqa: E402
from matplotlib.patches import Circle, Patch  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

from flyhead.navigation import planning as P  # noqa: E402
from flyhead.slam import reloc as RL  # noqa: E402
from flyhead.slam.navmap import NavMap  # noqa: E402

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'Noto Sans CJK SC', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
REAL = 'REAL SITE - saved SLAM map %s'
NAV_COLORS = {'driving': '#2a9d8f', 'avoiding': '#e76f51', 'waiting': '#f4a261', 'stopped': '#c1121f',
              'planning': '#8d99ae', 'idle': '#adb5bd', 'arrived': '#2b9348', 'blocked': '#9d0208', 'no_path': '#6a040f'}
STATE_COLORS = {'FORWARD': '#4c9be8', 'EXPLORE': '#7fc8f8', 'TURN_LEFT': '#9b8de0', 'TURN_RIGHT': '#c08de0', 'HOLD': '#9e9e9e',
                'REST': '#c9c9c9', 'FREEZE': '#f2c14e', 'ESCAPE_PROGRAM': '#e4572e', 'BACK_OFF': '#f08a4b', 'FLEE': '#b0306a',
                'BLIND': '#666666'}


def writer(fps):
    return FFMpegWriter(fps=fps, codec='libx264', extra_args=['-pix_fmt', 'yuv420p', '-crf', '28', '-preset', 'slow'])


def base_image(ax, nm, view=None, alpha=1.0):
    """Free white, occupied dark, unknown grey (map.pgm), in map coordinates."""
    s = nm.static
    img = np.where(s == 0, 0.18, np.where(s == 254, 0.98, 0.85))
    x0, y0 = nm.origin
    ext = [x0, x0 + s.shape[0] * nm.res, y0, y0 + s.shape[1] * nm.res]
    ax.imshow(img.T, origin='lower', extent=ext, cmap='gray', vmin=0, vmax=1, interpolation='nearest', alpha=alpha)
    if view:
        ax.set_xlim(view[0], view[1]); ax.set_ylim(view[2], view[3])
    ax.set_aspect('equal')
    return ext


def known_view(nm, pad=1.0):
    ij = np.argwhere(nm.static != 205)
    xy = nm.origin + (ij + 0.5) * nm.res
    lo, hi = xy.min(0) - pad, xy.max(0) + pad
    return lo[0], hi[0], lo[1], hi[1]


def robot(ax, x, y, yaw, color='#d62828', r=0.35):
    ax.add_patch(Circle((x, y), r, fc=color, ec='white', lw=1.2, alpha=0.95, zorder=8))
    ax.plot([x, x + 0.6 * math.cos(yaw)], [y, y + 0.6 * math.sin(yaw)], color='white', lw=2.2, zorder=9)


def load_cloud(pkg, keep=150000, top=1.3):
    """Saved cloud below `top` m in the map frame (z = 0 at the mapping LiDAR height): walls and furniture, no ceiling."""
    pts = RL.load_points(str(Path(pkg) / 'map.ply'))
    pts = pts[pts[:, 2] < top]
    if len(pts) > keep:
        pts = pts[np.random.default_rng(0).choice(len(pts), keep, replace=False)]
    return pts


def mapbuild(out, pkg, fps=10, seconds=40):
    nm = NavMap(pkg)
    traj = np.genfromtxt(Path(pkg) / 'trajectory.csv', delimiter=',', skip_header=1)
    pts = load_cloud(pkg)
    z = pts[:, 2]
    lo, hi = np.percentile(z, 2), np.percentile(z, 98)
    n = fps * seconds
    idx = np.linspace(0, len(traj) - 1, n).astype(int)
    tree = cKDTree(pts[:, :2])
    first = np.full(len(pts), n, int)
    for k, i in enumerate(idx):
        for j in tree.query_ball_point(traj[i, 1:3], 4.0):
            if first[j] == n:
                first[j] = k
    order = np.argsort(first)
    pts, first = pts[order], first[order]
    view = known_view(nm)
    dist = np.r_[0, np.cumsum(np.hypot(*np.diff(traj[:, 1:3], axis=0).T))]
    fig, ax = plt.subplots(figsize=(12, 9), dpi=100)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.88, bottom=0.03)
    name = Path(pkg).name
    fig.text(0.02, 0.95, 'SLAM mapping session replayed: the saved point cloud appears as the robot passes (within 4 m)', fontsize=14, weight='bold')
    fig.text(0.02, 0.92, (REAL % name) + ' | trajectory.csv of the mapping session, cloud coloured by height', fontsize=10, color='#1d3557')
    sc = ax.scatter([], [], s=0.4, c=[], cmap='viridis', vmin=lo, vmax=hi)
    line, = ax.plot([], [], color='#d62828', lw=1.6, zorder=6)
    ax.set_xlim(view[0], view[1]); ax.set_ylim(view[2], view[3]); ax.set_aspect('equal'); ax.set_facecolor('#0b132b')
    ax.set_xticks([]); ax.set_yticks([])
    info = ax.text(0.01, 0.99, '', transform=ax.transAxes, va='top', color='white', fontsize=11, family='monospace')
    marker = []
    w = writer(fps)
    with w.saving(fig, out, 100):
        for k, i in enumerate(idx):
            m = np.searchsorted(first, k, side='right')
            sc.set_offsets(pts[:m, :2]); sc.set_array(pts[:m, 2])
            line.set_data(traj[:i + 1, 1], traj[:i + 1, 2])
            for p in marker:
                p.remove()
            marker = [ax.add_patch(Circle(traj[i, 1:3], 0.35, fc='#d62828', ec='white', zorder=8))]
            info.set_text('t %6.0f s   path %5.1f m   cloud points shown %7d' % (traj[i, 0] - traj[0, 0], dist[i], m))
            w.grab_frame()
        for _ in range(fps * 2):
            w.grab_frame()


def orbit(out, pkg, fps=10, seconds=24):
    pts = load_cloud(pkg, 90000)
    c = pts.mean(0)
    z = pts[:, 2]
    lo, hi = np.percentile(z, 2), np.percentile(z, 98)
    keep = (z > lo - 0.3) & (z < hi + 0.3)
    pts = pts[keep]
    fig = plt.figure(figsize=(12, 8), dpi=100)
    ax = fig.add_subplot(111, projection='3d')
    fig.subplots_adjust(left=-0.15, right=1.15, top=1.05, bottom=-0.15)
    fig.text(0.02, 0.95, 'Saved SLAM point cloud (3-D)', fontsize=14, weight='bold')
    fig.text(0.02, 0.92, REAL % Path(pkg).name + ' | %d points shown, coloured by height' % len(pts), fontsize=10, color='#1d3557')
    ax.scatter(pts[:, 0], pts[:, 1], pts[:, 2], s=0.3, c=pts[:, 2], cmap='viridis', vmin=lo, vmax=hi, depthshade=False)
    span = (pts[:, :2].max(0) - pts[:, :2].min(0)).max() / 2
    ax.set_xlim(c[0] - span, c[0] + span); ax.set_ylim(c[1] - span, c[1] + span); ax.set_zlim(lo, hi)
    ax.set_box_aspect((1, 1, max(0.08, (hi - lo) / (2 * span))), zoom=1.7)
    ax.set_axis_off()
    n = fps * seconds
    w = writer(fps)
    with w.saving(fig, out, 100):
        for k in range(n):
            ax.view_init(elev=35 - 15 * math.sin(2 * math.pi * k / n), azim=k * 360.0 / n)
            w.grab_frame()


def read_navlog(path):
    rows = []
    for line in open(path, encoding='utf-8'):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        d = r.get('data')
        if r.get('kind') == 'nav' and isinstance(d, dict) and d.get('pose'):
            rows.append((r.get('received_at', r.get('t')), d))
    return rows


def navlog(out, pkg, log, fps=8, speed=None):
    nm = NavMap(pkg)
    rows = read_navlog(log)
    t0 = rows[0][0]
    T = np.array([t - t0 for t, _ in rows])
    Pz = np.array([d['pose'] for _, d in rows])
    routes = [np.array(d['path']) for _, d in rows if d.get('path') and len(d['path']) > 1]
    allxy = np.vstack([Pz[:, :2]] + routes) if routes else Pz[:, :2]
    pad = 2.0
    view = (allxy[:, 0].min() - pad, allxy[:, 0].max() + pad, allxy[:, 1].min() - pad, allxy[:, 1].max() + pad)
    playback = (T[-1] / (len(rows) / fps)) if speed is None else speed
    fig = plt.figure(figsize=(16, 9), dpi=100)
    gs = fig.add_gridspec(3, 2, width_ratios=[1.6, 1], height_ratios=[1.2, 1, 1], left=0.03, right=0.98, top=0.86, bottom=0.07, hspace=0.45, wspace=0.12)
    ax = fig.add_subplot(gs[:, 0]); ax_txt = fig.add_subplot(gs[0, 1]); ax_cmd = fig.add_subplot(gs[1, 1]); ax_fit = fig.add_subplot(gs[2, 1])
    fig.text(0.03, 0.95, 'REAL ROBOT - autonomous tour (no fly brain), replayed from the robot\'s own navigation log', fontsize=14, weight='bold')
    fig.text(0.03, 0.92, (REAL % Path(pkg).name) + ' | log %s | %.0f s of driving, shown at about %.0fx' % (Path(log).name, T[-1], playback),
             fontsize=10, color='#1d3557')
    cmd = np.array([d.get('command') or [0, 0] for _, d in rows])
    fit = np.array([d.get('fitness') if d.get('fitness') is not None else np.nan for _, d in rows])
    states = [d.get('state') for _, d in rows]
    ax_cmd.plot(T, cmd[:, 0], color='#222', lw=1.2, label='v command (m/s)')
    ax_cmd.plot(T, cmd[:, 1], color='#2a9d8f', lw=1.0, label='w command (rad/s)')
    for i in range(len(T) - 1):
        ax_cmd.axvspan(T[i], T[i + 1], ymin=0.9, ymax=1.0, color=NAV_COLORS.get(states[i], '#ccc'), lw=0)
    ax_cmd.set_xlim(0, T[-1]); ax_cmd.legend(fontsize=8, loc='lower right'); ax_cmd.set_title('command and navigator state (band)', fontsize=10, loc='left')
    ax_fit.plot(T, fit, color='#1d3557', lw=1.2); ax_fit.set_ylim(0.5, 1.02); ax_fit.set_xlim(0, T[-1])
    ax_fit.axhline(0.8, color='#c1121f', ls=':', lw=1); ax_fit.set_title('localization fitness on the saved map (dotted: 0.8)', fontsize=10, loc='left')
    ax_fit.set_xlabel('time in the session (s)')
    cur = [ax_cmd.axvline(0, color='k'), ax_fit.axvline(0, color='k')]
    used = [s for s in NAV_COLORS if s in states]
    ax_cmd.legend(handles=ax_cmd.get_legend_handles_labels()[0] + [Patch(color=NAV_COLORS[s], label=s) for s in used],
                  fontsize=7, loc='upper center', bbox_to_anchor=(0.5, -0.12), ncol=4, frameon=False)
    ax_txt.axis('off')
    txt = ax_txt.text(0, 1, '', va='top', fontsize=11, fontfamily=['Microsoft YaHei', 'Noto Sans CJK SC', 'DejaVu Sans'])
    base_image(ax, nm, view); ax.set_xticks([]); ax.set_yticks([])
    route_ln, = ax.plot([], [], color='#457b9d', lw=2, alpha=0.8, zorder=4, label='planned route')
    path_ln, = ax.plot([], [], color='#d62828', lw=1.4, zorder=5, label='driven path')
    goal_mk, = ax.plot([], [], marker='*', ms=16, color='#ffb703', mec='black', zorder=7, ls='', label='goal')
    ax.legend(loc='lower right', fontsize=8)
    ax.set_title('map (grey = unknown), red = driven, blue = route, boxes = map changes (red added, green removed)', fontsize=9, loc='left')
    dyn = []
    w = writer(fps)
    with w.saving(fig, out, 100):
        for i, (t, d) in enumerate(rows):
            for a in dyn:
                a.remove()
            dyn = []
            p = np.array(d['path']) if d.get('path') and len(d['path']) > 1 else np.zeros((0, 2))
            route_ln.set_data(p[:, 0], p[:, 1])
            k = max(0, i - 600)
            path_ln.set_data(Pz[k:i + 1, 0], Pz[k:i + 1, 1])
            goal_mk.set_data(*([[d['goal'][0]], [d['goal'][1]]] if d.get('goal') else [[], []]))
            for c in (d.get('changes') or [])[-30:]:
                x0, y0, x1, y1 = c['bbox']
                dyn.append(ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False,
                                                      ec='#e63946' if c['kind'] == 'added' else '#2a9d8f', lw=1.2, zorder=6)))
            col = NAV_COLORS.get(d.get('state'), '#d62828')
            dyn.append(ax.add_patch(Circle((Pz[i, 0], Pz[i, 1]), 0.35, fc=col, ec='white', lw=1.2, alpha=0.95, zorder=8)))
            dyn += ax.plot([Pz[i, 0], Pz[i, 0] + 0.6 * math.cos(Pz[i, 2])], [Pz[i, 1], Pz[i, 1] + 0.6 * math.sin(Pz[i, 2])], color='white', lw=2.2, zorder=9)
            loop = d.get('loop') or {}
            txt.set_text('t          %7.1f s\nstate      %s\nreason     %s\nfitness    %s\ncommand    v %.2f  w %.2f\nlimits     v %.2f  w %.2f\n'
                         'posture    %s  (LiDAR %.2f m)\ntour       %s / %s waypoints left%s\nleg        %s' % (
                             t - t0, d.get('state'), (d.get('reason') or '-')[:28], d.get('fitness'),
                             *(d.get('command') or [0, 0]), d.get('v_max') or 0, d.get('w_max') or 0,
                             d.get('mode'), d.get('lidar_h') or 0, d.get('tour_left'), d.get('tour_total'),
                             ('\nloop       %.1f m perimeter' % loop['perimeter_m']) if loop.get('perimeter_m') else '', d.get('leg')))
            for c in cur:
                c.set_xdata([t - t0, t - t0])
            w.grab_frame()


def layers(out, pkg, logs=()):
    nm = NavMap(pkg)
    blocked = nm.blocked_for(0.32)
    clear = nm.clearance_for(0.32)
    med = P.medial_axis(blocked | (nm.static == 205), nm.res) & (clear >= 0.45)
    view = known_view(nm)
    fig, axs = plt.subplots(2, 2, figsize=(16, 13), dpi=100)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.92, bottom=0.02, wspace=0.05, hspace=0.12)
    fig.text(0.02, 0.965, 'Navigation layers of the saved SLAM map', fontsize=16, weight='bold')
    fig.text(0.02, 0.945, REAL % Path(pkg).name, fontsize=11, color='#1d3557')
    x0, y0 = nm.origin
    ext = [x0, x0 + blocked.shape[0] * nm.res, y0, y0 + blocked.shape[1] * nm.res]
    ax = axs[0, 0]; base_image(ax, nm, view); ax.set_title('1  occupancy grid map.pgm (0.05 m): free / occupied / unknown', loc='left')
    ax = axs[0, 1]
    im = ax.imshow(np.where(blocked | (nm.static == 205), np.nan, clear).T, origin='lower', extent=ext, cmap='magma', vmin=0, vmax=2.0)
    mi = np.argwhere(med); mxy = nm.origin + (mi + 0.5) * nm.res
    ax.scatter(mxy[:, 0], mxy[:, 1], s=0.6, c='#00f5d4', label='centreline (λ-medial axis, clearance ≥ 0.45 m)')
    ax.set_xlim(view[0], view[1]); ax.set_ylim(view[2], view[3]); ax.set_aspect('equal'); ax.legend(loc='lower right', fontsize=9)
    fig.colorbar(im, ax=ax, fraction=0.03, label='clearance (m)'); ax.set_title('2  planner field: clearance and the centreline routes follow', loc='left')
    ax = axs[1, 0]
    hmin = getattr(nm, 'hmin', None)
    if hmin is not None:
        h = np.where(np.isfinite(hmin) & (hmin < 3), hmin, np.nan).astype(float)
        base_image(ax, nm, view, alpha=0.35)
        im = ax.imshow(h.T, origin='lower', extent=ext, cmap='turbo', vmin=0, vmax=1.5, interpolation='nearest')
        fig.colorbar(im, ax=ax, fraction=0.03, label='lowest obstacle point above floor (m)')
    ax.set_title('3  height layer obst_hmin: what blocks a crouched vs. standing robot', loc='left')
    ax = axs[1, 1]; base_image(ax, nm, view)
    traj = np.genfromtxt(Path(pkg) / 'trajectory.csv', delimiter=',', skip_header=1)
    ax.plot(traj[:, 1], traj[:, 2], color='#adb5bd', lw=0.8, label='mapping session path')
    for c, log in zip(['#d62828', '#457b9d', '#2a9d8f', '#e76f51'], logs):
        rows = read_navlog(log)
        p = np.array([d['pose'] for _, d in rows])
        ax.plot(p[:, 0], p[:, 1], color=c, lw=1.6, label='real tour %s (%d s)' % (Path(log).stem[-15:], rows[-1][0] - rows[0][0]))
        longest = max((d['path'] for _, d in rows if d.get('path')), key=len, default=None)
        if longest:
            q = np.array(longest); ax.plot(q[:, 0], q[:, 1], color=c, lw=0.8, ls='--')
    ax.legend(loc='lower right', fontsize=9); ax.set_title('4  real runs: mapping path, autonomous tours (solid) and planned routes (dashed)', loc='left')
    for a in axs.flat:
        a.set_xticks([]); a.set_yticks([])
    fig.savefig(out, dpi=100)


def load_run(path):
    R = [json.loads(line) for line in open(path)]
    return [r for r in R if 't' in r and 'type' not in r]


def scenarios(out, pkg, run_dir):
    nm = NavMap(pkg)
    names = sorted({Path(f).stem.rsplit('_', 1)[0] for f in glob.glob(str(Path(run_dir) / '*_brain.jsonl'))})
    cols = 4
    rows_n = math.ceil(len(names) / cols)
    fig, axs = plt.subplots(rows_n, cols, figsize=(18, 4.8 * rows_n + 1), dpi=100, squeeze=False)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.9, bottom=0.03, wspace=0.04, hspace=0.25)
    fig.text(0.01, 0.965, 'Every simulation scenario on the real SLAM map: fly brain (coloured by decoder state) vs. blind baseline (grey)', fontsize=15, weight='bold')
    fig.text(0.01, 0.94, 'SIMULATION on ' + (REAL % Path(pkg).name) + ' | ray-cast LiDAR | full connectome on GPU, decoder V9 | person = orange track', fontsize=10, color='#b00020')
    for a, name in zip(axs.flat, names):
        B = load_run(Path(run_dir) / ('%s_brain.jsonl' % name))
        bl = Path(run_dir) / ('%s_blind.jsonl' % name)
        X = load_run(bl) if bl.exists() else []
        xy = np.array([[r['x'], r['y']] for r in B + X])
        objs = np.array([o for r in B for o in r.get('objects', [])]) if B[0].get('objects') else np.zeros((0, 2))
        allxy = np.vstack([xy, objs]) if len(objs) else xy
        pad = 1.8
        view = (allxy[:, 0].min() - pad, allxy[:, 0].max() + pad, allxy[:, 1].min() - pad, allxy[:, 1].max() + pad)
        base_image(a, nm, view)
        if X:
            a.plot([r['x'] for r in X], [r['y'] for r in X], color='#6c757d', lw=1.6, ls='--', label='blind')
        for i in range(1, len(B)):
            a.plot([B[i - 1]['x'], B[i]['x']], [B[i - 1]['y'], B[i]['y']], color=STATE_COLORS.get(B[i]['intent']['state'], '#222'), lw=2.4)
        if len(objs):
            a.plot(objs[:, 0], objs[:, 1], color='#fb8500', lw=1.2, alpha=0.8)
        a.plot(B[0]['x'], B[0]['y'], 'o', color='black', ms=6)
        cb = sum(r['contact'] for r in B); cx = sum(r['contact'] for r in X) if X else '-'
        mb = min(r['clearance'] for r in B)
        a.set_title('%s  (%.0f s)\nbrain: contacts %d, min clearance %.2f m | blind: contacts %s' % (name, B[-1]['t'], cb, mb, cx), fontsize=10, loc='left')
        a.set_xticks([]); a.set_yticks([])
    for a in list(axs.flat)[len(names):]:
        a.axis('off')
    used = [s for s in STATE_COLORS if s != 'BLIND']
    fig.legend(handles=[Patch(color=STATE_COLORS[s], label=s) for s in used] + [plt.Line2D([], [], color='#6c757d', ls='--', label='blind')],
               loc='lower center', ncol=len(used) + 1, fontsize=9, frameon=False)
    fig.savefig(out, dpi=100)


def states(out, run_dir):
    files = sorted(glob.glob(str(Path(run_dir) / '*_brain.jsonl')))
    fig, ax = plt.subplots(figsize=(16, 0.7 * len(files) + 2), dpi=100)
    fig.subplots_adjust(left=0.14, right=0.98, top=0.85, bottom=0.2)
    seen = set()
    for k, f in enumerate(files):
        R = load_run(f)
        for i, r in enumerate(R):
            t1 = R[i + 1]['t'] if i + 1 < len(R) else r['t'] + 0.1
            s = r['intent']['state']; seen.add(s)
            ax.barh(k, t1 - r['t'], left=r['t'], color=STATE_COLORS.get(s, '#222'), height=0.7)
    ax.set_yticks(range(len(files)), [Path(f).stem.replace('_brain', '') for f in files]); ax.invert_yaxis()
    ax.set_xlabel('time (s)')
    fig.text(0.01, 0.94, 'Decoder states of the fly brain in every scenario (simulation on the real SLAM map, decoder V9)', fontsize=13, weight='bold')
    ax.legend(handles=[Patch(color=STATE_COLORS[s], label=s) for s in STATE_COLORS if s in seen], loc='upper center',
              bbox_to_anchor=(0.5, -0.25), ncol=len(seen), fontsize=9, frameon=False)
    fig.savefig(out, dpi=100)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=['mapbuild', 'orbit', 'layers', 'navlog', 'scenarios', 'states'])
    ap.add_argument('out')
    ap.add_argument('inputs', nargs='*')
    ap.add_argument('--fps', type=int, default=10)
    ap.add_argument('--speed', type=float)
    a = ap.parse_args()
    if a.mode == 'mapbuild':
        mapbuild(a.out, a.inputs[0], a.fps)
    elif a.mode == 'orbit':
        orbit(a.out, a.inputs[0], a.fps)
    elif a.mode == 'layers':
        layers(a.out, a.inputs[0], a.inputs[1:])
    elif a.mode == 'navlog':
        navlog(a.out, a.inputs[0], a.inputs[1], a.fps, a.speed)
    elif a.mode == 'scenarios':
        scenarios(a.out, a.inputs[0], a.inputs[1])
    else:
        states(a.out, a.inputs[0])


if __name__ == '__main__':
    main()

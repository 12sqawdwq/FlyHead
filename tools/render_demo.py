"""Render demo videos / stills from simulation logs (no GPU needed; the logs hold the brain output).

  decision  OUT.mp4 RUN.jsonl          one loom_sim run (flyhead.sim.loom_sim ... brain): map + LiDAR,
                                      retina input rates, descending-neuron readouts, decoder state and
                                      command over time -- the whole decision chain, window by window
  reflex    OUT.mp4 PLANNER.jsonl REFLEX.jsonl
                                      stage 6 (flyhead.sim.reflex_sim): the two arms side by side
  still     OUT.png RUN.jsonl T       one frame of 'decision' at time T (s)

Maps are the synthetic arena (flyhead.sim.synthetic_map); pass --map for a recorded package.
Every frame is labelled as simulation. python tools/render_demo.py MODE OUT ARGS... [--map PKG] [--fps 10]
"""
import argparse
import json
import math
import tempfile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.animation import FFMpegWriter  # noqa: E402
from matplotlib.patches import Circle, Patch  # noqa: E402

from flyhead.sim import loom_sim  # noqa: E402
from flyhead.sim.synthetic_map import write as write_arena  # noqa: E402
from flyhead.slam.navmap import NavMap  # noqa: E402

INPUTS = ['LC4', 'LPLC2', 'LC9']
READOUTS = ['DNp01', 'DNp02', 'DNp04', 'DNp06', 'DNp11', 'DNp09', 'DNa01', 'DNa02', 'MDN']
READOUT_ROLE = {'DNp01': 'giant fibre (escape)', 'DNp02': 'loom', 'DNp04': 'loom', 'DNp06': 'loom',
                'DNp11': 'loom', 'DNp09': 'P9 (walk)', 'DNa01': 'steer', 'DNa02': 'steer', 'MDN': 'moonwalk (back)'}
STATES = ['FORWARD', 'EXPLORE', 'TURN_LEFT', 'TURN_RIGHT', 'HOLD', 'REST', 'FREEZE', 'ESCAPE_PROGRAM', 'BACK_OFF', 'FLEE', 'BLIND']
COLORS = {'FORWARD': '#4c9be8', 'EXPLORE': '#7fc8f8', 'TURN_LEFT': '#9b8de0', 'TURN_RIGHT': '#c08de0', 'HOLD': '#9e9e9e',
          'REST': '#c9c9c9', 'FREEZE': '#f2c14e', 'ESCAPE_PROGRAM': '#e4572e', 'BACK_OFF': '#f08a4b', 'FLEE': '#b0306a',
          'BLIND': '#666666'}
LEFT_C, RIGHT_C = '#3a7bd5', '#e07a2f'
SIM_LABEL = 'SIMULATION - synthetic arena, ray-cast LiDAR; full FlyWire v783 connectome (138,639 LIF neurons) on GPU'
REAL_MAP_LABEL = SIM_LABEL.replace('synthetic arena', 'saved SLAM map of a real site')


def load(path):
    rows = [json.loads(line) for line in open(path)]
    return [r for r in rows if 't' in r and 'type' not in r], next((r for r in rows if r.get('type') == 'setup'), None)


def arena(map_pkg):
    pkg = map_pkg or str(write_arena(tempfile.mkdtemp(prefix='flyhead_arena_')))
    return pkg, NavMap(pkg)


def draw_map(ax, nm, view=None):
    occ = nm.blocked_for(0.32)
    x0, y0 = nm.origin
    ext = [x0, x0 + occ.shape[0] * nm.res, y0, y0 + occ.shape[1] * nm.res]
    ax.imshow(np.where(occ, 0.15, 0.97).T, origin='lower', extent=ext, cmap='gray', vmin=0, vmax=1, interpolation='nearest')
    if view:
        ax.set_xlim(view[0], view[1]); ax.set_ylim(view[2], view[3])
    ax.set_aspect('equal'); ax.set_xticks([]); ax.set_yticks([])


def robot(ax, x, y, yaw, color='#222222'):
    ax.add_patch(Circle((x, y), loom_sim.BODY_R if hasattr(loom_sim, 'BODY_R') else 0.3, fc=color, ec='white', lw=1.0, alpha=0.9, zorder=5))
    ax.plot([x, x + 0.45 * math.cos(yaw)], [y, y + 0.45 * math.sin(yaw)], color='white', lw=2.2, zorder=6)


def side_vals(d, names):
    return [d.get(n + '_left', 0.0) for n in names], [d.get(n + '_right', 0.0) for n in names]


def decision(out, run, map_pkg=None, fps=10, still_t=None):
    R, _ = load(run)
    pkg, nm = arena(map_pkg)
    loom_sim.PKG = pkg
    world = loom_sim.World([])
    ts = np.array([r['t'] for r in R])
    xs = np.array([r['x'] for r in R]); ys = np.array([r['y'] for r in R])
    pad = 2.6
    view = (min(xs.min(), min(o[0] for r in R for o in r.get('objects', [])) if R[0].get('objects') else xs.min()) - pad,
            max(xs.max(), max(o[0] for r in R for o in r.get('objects', [])) if R[0].get('objects') else xs.max()) + pad,
            ys.min() - pad - 0.5, ys.max() + pad + 0.5)
    fig = plt.figure(figsize=(16, 9), dpi=100)
    gs = fig.add_gridspec(3, 3, width_ratios=[1.25, 1, 1], height_ratios=[1, 1, 0.9], hspace=0.45, wspace=0.28,
                          left=0.03, right=0.98, top=0.84, bottom=0.09)
    ax_map = fig.add_subplot(gs[0:2, 0]); ax_in = fig.add_subplot(gs[0, 1]); ax_dn = fig.add_subplot(gs[0:2, 2])
    ax_cmd = fig.add_subplot(gs[1, 1]); ax_tl = fig.add_subplot(gs[2, :])
    fig.text(0.03, 0.96, 'FlyHead decision chain:  LiDAR -> loom retina (LC4 / LPLC2 / LC9) -> connectome -> descending neurons -> decoder -> command',
             fontsize=14, weight='bold')
    fig.text(0.03, 0.93, SIM_LABEL if map_pkg is None else REAL_MAP_LABEL, fontsize=10, color='#b00020')
    head = fig.text(0.03, 0.895, '', fontsize=12, family='monospace')

    # timeline (static) + cursor
    for i, r in enumerate(R):
        t1 = R[i + 1]['t'] if i + 1 < len(R) else r['t'] + 0.1
        ax_tl.axvspan(r['t'], t1, ymin=0.72, ymax=1.0, color=COLORS.get(r['intent']['state'], '#888'), lw=0)
    ax_tl.plot(ts, [r['executed'][0] for r in R], color='#222', lw=1.4, label='v executed (m/s)')
    ax_tl.plot(ts, [r['executed'][1] for r in R], color='#2a9d8f', lw=1.2, label='w executed (rad/s)')
    ax_tl.plot(ts, [r['clearance'] for r in R], color='#999', lw=1.0, ls='--', label='clearance (m)')
    ax_tl.set_xlim(ts[0], ts[-1]); ax_tl.set_ylim(-1.1, 2.6)
    used = [s for s in STATES if any(r['intent']['state'] == s for r in R)]
    handles = ax_tl.get_legend_handles_labels()[0] + [Patch(color=COLORS[s], label=s) for s in used]
    ax_tl.legend(handles=handles, loc='upper center', bbox_to_anchor=(0.5, -0.32), fontsize=8, ncol=len(handles), frameon=False)
    ax_tl.set_title('4  decoder state over the run (colour band) and executed command; black line = now', fontsize=10, loc='left')
    cursor = ax_tl.axvline(ts[0], color='black', lw=1.5)

    def frame(i):
        r = R[i]
        ax_map.clear(); ax_in.clear(); ax_dn.clear(); ax_cmd.clear()
        draw_map(ax_map, nm, view)
        world.objects = [[o[0], o[1], 0.25, 0, 0, 0] for o in r.get('objects', [])]
        lid = np.array([r['x'] + loom_sim.LIDAR_AHEAD * math.cos(r['yaw']), r['y'] + loom_sim.LIDAR_AHEAD * math.sin(r['yaw'])])
        pts = world.scan(lid, r['t'])
        ax_map.scatter(pts[:, 0], pts[:, 1], s=2, c='#00a86b', zorder=3, label='LiDAR returns')
        k = max(0, i - 400)
        ax_map.plot(xs[k:i + 1], ys[k:i + 1], color='#4c9be8', lw=1.5, zorder=4)
        for o in r.get('objects', []):
            ax_map.add_patch(Circle(o, 0.25, fc='#e4572e', ec='black', lw=1, zorder=5))
            ax_map.text(o[0], o[1] + 0.38, 'person', ha='center', fontsize=9)
        robot(ax_map, r['x'], r['y'], r['yaw'], COLORS.get(r['intent']['state'], '#222'))
        ax_map.set_title('world (top-down), robot coloured by decoder state', fontsize=10, loc='left')

        L, Rr = side_vals(r.get('inputs', {}), INPUTS)
        y = np.arange(len(INPUTS))
        ax_in.barh(y + 0.2, L, 0.38, color=LEFT_C, label='left cells')
        ax_in.barh(y - 0.2, Rr, 0.38, color=RIGHT_C, label='right cells')
        ax_in.set_yticks(y, INPUTS); ax_in.set_xlim(0, 220); ax_in.invert_yaxis()
        ax_in.set_xlabel('Poisson input rate (Hz), anatomical side of the cells'); ax_in.legend(fontsize=8, loc='lower right')
        ax_in.set_title('1  engineered LiDAR retina -> input cells (registry)', fontsize=10, loc='left')

        L, Rr = side_vals(r.get('readouts', {}), READOUTS)
        y = np.arange(len(READOUTS))
        ax_dn.barh(y + 0.2, L, 0.38, color=LEFT_C, label='left (anatomical)')
        ax_dn.barh(y - 0.2, Rr, 0.38, color=RIGHT_C, label='right (anatomical)')
        ax_dn.set_yticks(y, ['%s\n%s' % (n, READOUT_ROLE[n]) for n in READOUTS], fontsize=8)
        ax_dn.set_xlim(0, 260); ax_dn.invert_yaxis(); ax_dn.legend(fontsize=8, loc='lower right')
        ax_dn.set_xlabel('spike rate in this 100 ms window (Hz)')
        ax_dn.set_title('2  descending neurons (model output)', fontsize=10, loc='left')

        it = r['intent']
        names = ['giant fibre', 'P9 (smoothed)', 'MDN', 'DNa02 R-L']
        vals = [it.get('gf_hz', 0), it.get('p9_smooth_hz', it.get('p9_hz', 0)), it.get('mdn_hz', 0), it.get('dna02_r_minus_l_hz', 0)]
        ax_cmd.bar(range(4), vals, color=['#e4572e', '#4c9be8', '#b0306a', '#2a9d8f'])
        ax_cmd.set_xticks(range(4), names, fontsize=8); ax_cmd.set_ylim(-80, 260); ax_cmd.axhline(0, color='#555', lw=0.6)
        ax_cmd.set_ylabel('Hz')
        env = ' | envelope: %s' % r['envelope'] if r.get('envelope') else ''
        ax_cmd.set_title('3  decoder features -> %s  (v %.2f m/s, w %.2f rad/s)%s' % (it['state'], r['executed'][0], r['executed'][1], env),
                         fontsize=10, loc='left', color=COLORS.get(it['state'], '#000'))
        cursor.set_xdata([r['t'], r['t']])
        head.set_text('t = %5.1f s   window %d / %d   decoder V%s   brain compute %s ms per 100 ms window' %
                      (r['t'], i + 1, len(R), it.get('decoder_version', 1), r.get('brain_ms', '-')))

    if still_t is not None:
        frame(int(np.argmin(np.abs(ts - still_t))))
        fig.savefig(out, dpi=100)
        return
    writer = FFMpegWriter(fps=fps, codec='libx264', extra_args=['-pix_fmt', 'yuv420p', '-crf', '28', '-preset', 'slow'])
    with writer.saving(fig, out, 100):
        for i in range(len(R)):
            frame(i); writer.grab_frame()


def reflex(out, planner_path, reflex_path, map_pkg=None, fps=10, step=3):
    runs = [('planner arm: brain in shadow, never acts', *load(planner_path)),
            ('reflex arm: brain takes over on FREEZE / ESCAPE', *load(reflex_path))]
    _, nm = arena(map_pkg)
    allx = [r['x'] for _, R, _ in runs for r in R] + [s['goal'][0] for _, _, s in runs]
    ally = [r['y'] for _, R, _ in runs for r in R] + [s['goal'][1] for _, _, s in runs]
    view = (min(allx) - 1.5, max(allx) + 1.5, min(ally) - 1.0, max(ally) + 1.0)
    n = max(len(R) for _, R, _ in runs)
    fig, axes = plt.subplots(1, 2, figsize=(16, 9), dpi=100)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.83, bottom=0.04, wspace=0.05)
    fig.text(0.02, 0.95, 'Stage 6: SLAM planner + fly-brain reflexes (same seed, same person)', fontsize=15, weight='bold')
    fig.text(0.02, 0.915, (SIM_LABEL if map_pkg is None else REAL_MAP_LABEL) + '; brain service over TCP, decoder V9', fontsize=10, color='#b00020')
    fig.text(0.02, 0.885, 'blue path = planner command, red = brain (reflex) command; robot colour = decoder state; star = goal',
             fontsize=10)

    def frame(i):
        for ax, (title, R, setup) in zip(axes, runs):
            ax.clear(); draw_map(ax, nm, view)
            j = min(i, len(R) - 1); r = R[j]
            for k in range(1, j + 1):
                ax.plot([R[k - 1]['x'], R[k]['x']], [R[k - 1]['y'], R[k]['y']],
                        color='#e4572e' if R[k]['source'] == 'reflex' else '#4c9be8', lw=2)
            ax.plot(*setup['goal'], marker='*', ms=18, color='#f2c14e', mec='black')
            if r['person'] is not None:
                ax.add_patch(Circle(r['person'], 0.25, fc='#e4572e', ec='black', zorder=5))
                ax.text(r['person'][0], r['person'][1] + 0.4, 'person', ha='center', fontsize=9)
            robot(ax, r['x'], r['y'], r['yaw'], COLORS.get(r['brain_state'], '#222'))
            done = j == len(R) - 1
            ax.set_title('%s\nt %5.1f s | brain %s | %s | takeovers %d | person %s%s' % (
                title, r['t'], r['brain_state'], 'REFLEX DRIVES' if r['takeover'] else 'planner drives',
                r['reflex_count'], '-' if r['person_m'] is None else '%.2f m' % r['person_m'], ' | ARRIVED' if done else ''),
                fontsize=10, loc='left')

    writer = FFMpegWriter(fps=fps, codec='libx264', extra_args=['-pix_fmt', 'yuv420p', '-crf', '28', '-preset', 'slow'])
    with writer.saving(fig, out, 100):
        for i in range(0, n + step, step):
            frame(i); writer.grab_frame()
        for _ in range(fps * 2):
            writer.grab_frame()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=['decision', 'reflex', 'still'])
    ap.add_argument('out')
    ap.add_argument('inputs', nargs='+')
    ap.add_argument('--map')
    ap.add_argument('--fps', type=int, default=10)
    a = ap.parse_args()
    if a.mode == 'decision':
        decision(a.out, a.inputs[0], a.map, a.fps)
    elif a.mode == 'still':
        decision(a.out, a.inputs[0], a.map, still_t=float(a.inputs[1]))
    else:
        reflex(a.out, a.inputs[0], a.inputs[1], a.map, a.fps)


if __name__ == '__main__':
    main()

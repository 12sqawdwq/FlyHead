"""README banner: title plus three labelled tiles (real robot, real-site SLAM map, brain decision chain).

python tools/render_banner.py OUT.png REAL.png MAP.png DECISION.png
Inputs are frames taken from the published clips (see docs/demo.md).
"""
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.image as mpimg  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'Noto Sans CJK SC', 'DejaVu Sans']
BG, FG, MUTED, ACCENT = '#0d1117', '#f0f6fc', '#8b949e', '#f78166'


def crop(img, x0, x1, y0, y1):
    h, w = img.shape[:2]
    return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def main(out, real, slam, decision):
    tiles = [
        ('REAL', 'brain drives the robot', crop(mpimg.imread(real), 0.18, 0.82, 0.05, 0.95)),
        ('REAL SITE', 'saved SLAM map', crop(mpimg.imread(slam), 0.06, 0.62, 0.17, 0.95)),
        ('SIM', 'connectome decision chain', crop(mpimg.imread(decision), 0.40, 0.99, 0.12, 0.70)),
    ]
    fig = plt.figure(figsize=(16, 5), dpi=100, facecolor=BG)
    fig.text(0.035, 0.70, 'FlyHead', fontsize=46, weight='bold', color=FG)
    fig.text(0.035, 0.585, '蝇首', fontsize=30, color=ACCENT)
    fig.text(0.035, 0.44, 'A whole-brain fruit-fly connectome\nas the head of a wheel-legged robot', fontsize=14.5, color=FG, linespacing=1.4)
    fig.text(0.035, 0.27, '138,639 LIF neurons · FlyWire v783 · PyTorch/CUDA\nLiDAR SLAM navigation · ROS 2 · DIABLO robot', fontsize=10.5, color=MUTED, linespacing=1.6)
    fig.text(0.035, 0.11, 'LiDAR loom → LC4 / LPLC2 / LC9 → descending neurons → escape', fontsize=10, color=ACCENT)
    x, w, gap = 0.335, 0.205, 0.016
    for k, (label, caption, img) in enumerate(tiles):
        left = x + k * (w + gap)
        ax = fig.add_axes([left, 0.17, w, 0.72])
        ax.imshow(img, aspect='auto')
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color('#30363d'); s.set_linewidth(1.5)
        fig.patches.append(FancyBboxPatch((left, 0.065), 0.075, 0.065, boxstyle='round,pad=0.004,rounding_size=0.01',
                                          transform=fig.transFigure, fc=ACCENT if label != 'SIM' else '#58a6ff', ec='none'))
        fig.text(left + 0.0375, 0.0975, label, fontsize=9.5, weight='bold', color=BG, ha='center', va='center')
        fig.text(left + 0.083, 0.0975, caption, fontsize=10, color=MUTED, va='center')
    fig.savefig(out, dpi=100, facecolor=BG)


if __name__ == '__main__':
    main(*sys.argv[1:5])

"""README banner as a two-ink printed editorial page (mono-color recipe: chromatic + black).

Recipe
  substrate   Cool Gray #E9E9E5 (technology subject)
  inks        Electric Blue #173AE3 (plate 1: halftone robot, wordmark)
              Carbon #242321       (plate 2: phrase, labels, ruled data strip, one circled fact)
  layout      image field: the robot photo, screened at 45 deg, bleeds off the right and bottom edges;
              the wordmark collides with it; the upper left stays open paper
  type        serif editorial voice + monospaced utility voice, ~11.6x scale jump
  imperfections  1 px plate misregistration and slight dot-size jitter (fixed seed)

python tools/render_banner.py OUT.png FRAME.png
FRAME is a still from docs/media/real/stage5_004_brain_drive_escape.mp4 (the robot on one wheel).
"""
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.image as mpimg  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Ellipse  # noqa: E402

W, H = 2400, 750
PAPER = np.array([0xE9, 0xE9, 0xE5]) / 255
BLUE = np.array([0x17, 0x3A, 0xE3]) / 255
CARBON = np.array([0x24, 0x23, 0x21]) / 255
SERIF = ['Georgia', 'Cambria', 'Times New Roman', 'DejaVu Serif']
MONO = ['Consolas', 'Courier New', 'DejaVu Sans Mono']
CJK = ['SimSun', 'Microsoft YaHei', 'Noto Serif CJK SC']
RNG = np.random.default_rng(20261102)


def halftone(gray, cell=11.0, angle=45.0, gamma=1.15):
    """Ink coverage (0..1) of a rotated amplitude-modulated dot screen for a darkness image (0..1)."""
    h, w = gray.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    a = np.radians(angle)
    u = (xx * np.cos(a) + yy * np.sin(a)) / cell
    v = (-xx * np.sin(a) + yy * np.cos(a)) / cell
    cu, cv = np.floor(u) + 0.5, np.floor(v) + 0.5
    # darkness sampled at the cell centre, so each dot is one tone
    cx = (cu * np.cos(a) - cv * np.sin(a)) * cell
    cy = (cu * np.sin(a) + cv * np.cos(a)) * cell
    ix = np.clip(cx.astype(int), 0, w - 1); iy = np.clip(cy.astype(int), 0, h - 1)
    d = np.clip(gray[iy, ix], 0, 1) ** gamma
    d = d * (1 + 0.06 * RNG.standard_normal(d.shape).reshape(d.shape))     # controlled dot-size jitter
    r = np.sqrt(np.clip(d, 0, 1) / np.pi) * 1.08                           # dot area ~ darkness
    dist = np.hypot(u - cu, v - cv)
    cov = np.clip((r - dist) * cell, 0, 1)                                  # 1 px antialiased edge
    cov[r * cell < 0.9] = 0                                                 # tiny dots drop out: paper shows
    return cov


def text_mask(draw):
    """Render text/lines in black on a transparent canvas of the banner size; return coverage 0..1."""
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis('off')
    draw(fig, ax)
    fig.canvas.draw()
    a = np.asarray(fig.canvas.buffer_rgba())[..., 3] / 255.0
    plt.close(fig)
    return a


def main(out, frame):
    img = mpimg.imread(frame)[..., :3]
    h0, w0 = img.shape[:2]
    # crop around the robot (frame at 48 s: robot on one wheel, shadow to the right)
    crop = img[int(0.04 * h0):int(1.00 * h0), int(0.04 * w0):w0]
    lum = crop @ np.array([0.299, 0.587, 0.114])
    floor = np.percentile(lum, 70)
    dark = np.clip((floor - lum) / (floor - np.percentile(lum, 2)), 0, 1)        # floor -> paper
    dark = np.clip(dark * 1.45 - 0.22, 0, 1)
    # place: robot zone 1150 px tall, bleeding off the right and bottom edges
    th = 1240
    tw = int(th * dark.shape[1] / dark.shape[0])
    ys = (np.linspace(0, dark.shape[0] - 1, th)).astype(int)
    xs = (np.linspace(0, dark.shape[1] - 1, tw)).astype(int)
    big = dark[np.ix_(ys, xs)]
    canvas = np.zeros((H, W))
    x0, y0 = 875, -250                                      # robot's leg crosses the wordmark
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    ww = min(W - dx0, tw - sx0); hh = min(H - dy0, th - sy0)
    canvas[dy0:dy0 + hh, dx0:dx0 + ww] = big[sy0:sy0 + hh, sx0:sx0 + ww]
    # soften into paper on the left edge of the image zone (an open, unresolved edge)
    fade = np.clip((np.arange(W) - (dx0 - 40)) / 260.0, 0, 1)
    canvas *= fade[None, :]
    blue = halftone(canvas)

    def wordmark(fig, ax):
        ax.text(132, 520, 'FlyHead', fontsize=220, family=SERIF, weight='bold', va='baseline', ha='left')

    blue = np.maximum(blue, text_mask(wordmark))

    def carbon_layer(fig, ax):
        ax.text(140, 118, 'a fly brain, at the wheel.', fontsize=40, family=SERIF, style='italic', va='baseline')
        ax.text(142, 176, '蝇首  /  WHOLE-BRAIN FLYWIRE v783 CONNECTOME  /  DIABLO WHEEL-LEGGED ROBOT', fontsize=19, family=MONO + CJK, va='baseline')
        y = 640
        ax.plot([140, 1440], [y - 38, y - 38], color='black', lw=1.6)
        ax.plot([140, 1440], [y + 24, y + 24], color='black', lw=1.6)
        ax.text(142, y, '138,639 NEURONS  15,091,983 CONNECTIONS  LOOM > LC4/LPLC2/LC9 > DNs > ESCAPE',
                fontsize=19, family=MONO, va='baseline')
        # the one manual gesture: a loose hand-drawn circle around the neuron count
        t = np.linspace(0.15, 2 * np.pi + 0.55, 200)
        rx, ry, cx, cy = 55, 27, 188, y - 8
        wob = 1 + 0.035 * np.sin(3 * t + 0.7) + 0.02 * np.sin(7 * t)
        ax.plot(cx + rx * wob * np.cos(t), cy + ry * wob * np.sin(t) + 3 * (t / t[-1]), color='black', lw=2.2, solid_capstyle='round')

    carbon = text_mask(carbon_layer)

    def ink(base, cov, color):
        return base * (1 - cov[..., None] * (1 - color[None, None, :] / np.maximum(base, 1e-6)).clip(0, 1))

    page = np.ones((H, W, 3)) * PAPER
    blue_shift = np.zeros_like(blue); blue_shift[1:, 1:] = blue[:-1, :-1]          # 1 px misregistration
    page = page * (1 - blue_shift[..., None] * (1 - BLUE[None, None, :]))       # multiply: overprint
    page = page * (1 - carbon[..., None] * (1 - CARBON[None, None, :]))
    fibre = 1 - 0.012 * RNG.random((H, W))                                      # faint paper tooth
    page = np.clip(page * fibre[..., None], 0, 1)
    plt.imsave(out, page)


if __name__ == '__main__':
    main(*sys.argv[1:3])

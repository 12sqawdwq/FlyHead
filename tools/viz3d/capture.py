"""Render a scenario exported by export_scene.py to an MP4: every frame is drawn by render.html (three.js, WebGL in a
headless Chrome) and screenshotted, then encoded with ffmpeg. Deterministic: frame i always shows the same moment.

  python tools/viz3d/capture.py runs/viz3d_data/person_front.json docs/media/realmap3d/decision_person_front.mp4
         [--fps 20] [--speed 1] [--gif docs/media/cards/x.gif] [--still 4.2 --still-out x.png]

Needs the Python Playwright package and Chrome (channel "chrome"; falls back to Playwright's Chromium) and ffmpeg.
"""
import argparse
import functools
import http.server
import subprocess
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(REPO))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('scene')
    ap.add_argument('out')
    ap.add_argument('--page', default='rviz', choices=('rviz', 'render'), help='rviz: RViz2-style window (default); render: dark showcase style')
    ap.add_argument('--fps', type=int, default=20)
    ap.add_argument('--speed', type=float, default=1.0, help='playback speed factor (1 = real time)')
    ap.add_argument('--gif', help='also write a 640x360 GIF preview (first 12 s of the video)')
    ap.add_argument('--still', type=float, help='also save one frame at this simulation time (s)')
    ap.add_argument('--still-out')
    a = ap.parse_args()
    srv = serve()
    scene_url = '/' + Path(a.scene).resolve().relative_to(REPO).as_posix()
    url = 'http://127.0.0.1:%d/tools/viz3d/%s.html?scene=%s&fps=%d&speed=%g' % (srv.server_port, a.page, scene_url, a.fps, a.speed)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        args = ['--ignore-gpu-blocklist', '--enable-gpu-rasterization', '--use-angle=d3d11']
        try:
            browser = p.chromium.launch(channel='chrome', args=args)
        except Exception:                       # noqa: BLE001 - no Chrome: Playwright's own Chromium
            browser = p.chromium.launch(args=args)
        page = browser.new_page(viewport={'width': 1600, 'height': 900}, device_scale_factor=1)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url)
        page.wait_for_function('window.READY === true', timeout=120000)
        n = page.evaluate('window.NFRAMES')
        if a.still is not None:
            f = int(round(a.still / a.speed * a.fps))
            page.evaluate('f => window.setFrame(f)', f)
            page.screenshot(path=a.still_out or str(out.with_suffix('.png')))
        enc = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', str(a.fps), '-i', '-',
                                '-vf', 'scale=1280:-2:flags=lanczos', '-c:v', 'libx264', '-preset', 'slow', '-crf', '27',
                                '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                                str(out)], stdin=subprocess.PIPE)
        for f in range(n):
            page.evaluate('f => window.setFrame(f)', f)
            enc.stdin.write(page.screenshot(type='jpeg', quality=94))
            if f % 100 == 0:
                print('  frame %d / %d' % (f, n), flush=True)
        enc.stdin.close()
        enc.wait()
        browser.close()
    srv.shutdown()
    if errors:
        raise SystemExit('page errors: %s' % errors[:3])
    print('%s: %d frames at %d fps (%.1f s), speed %gx' % (out, n, a.fps, n / a.fps, a.speed))
    if a.gif:
        Path(a.gif).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-t', '12', '-i', str(out), '-vf',
                        'fps=10,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4',
                        a.gif], check=True)
        print('gif', a.gif, Path(a.gif).stat().st_size // 1024, 'KB')


if __name__ == '__main__':
    main()

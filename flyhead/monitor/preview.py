"""Operator console: serve the web UI locally and tunnel to the compute server API.

Runs on the operator PC. Nothing on the robot or the compute server is started:
the SSH tunnel only forwards 127.0.0.1:<tunnel-port> to the server's API port, and
reconnects every 3 s while the link is down. Closing this process closes the tunnel.
"""
import argparse
import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import threading
from urllib.parse import urlencode
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
WEB = Path(__file__).resolve().parent / 'web'


class PreviewServer(ThreadingHTTPServer):
    allow_reuse_address = os.name != 'nt'

    def server_bind(self):
        if os.name == 'nt':
            # Refuse to share the port with a second console instead of silently splitting traffic.
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class PreviewHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/__console_info':
            payload = json.dumps(self.server.console_info).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compute-host', default=os.environ.get('XT_COMPUTE_HOST', 'compute'), help='SSH alias of the compute server (env XT_COMPUTE_HOST)')
    parser.add_argument('--remote-port', type=int, default=8091, help='compute API port on the server')
    parser.add_argument('--port', type=int, default=18101, help='local web UI port')
    parser.add_argument('--tunnel-port', type=int, default=18102, help='local end of the API tunnel')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()

    server = PreviewServer(('127.0.0.1', args.port), partial(PreviewHandler, directory=str(WEB)))
    server.daemon_threads = True
    server.console_info = dict(application='flyhead-monitor', root=str(ROOT),
                               pid=os.getpid(), compute_host=args.compute_host,
                               remote_port=args.remote_port, tunnel_port=args.tunnel_port)
    command = ['ssh', '-N', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
               '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=15',
               '-o', 'ServerAliveCountMax=3',
               '-L', '127.0.0.1:%d:127.0.0.1:%d' % (args.tunnel_port, args.remote_port),
               args.compute_host]
    stopping = threading.Event()
    tunnel_lock = threading.Lock()
    tunnel = None

    def watch_tunnel():
        nonlocal tunnel
        while not stopping.is_set():
            with tunnel_lock:
                if stopping.is_set():
                    return
                print('Opening API tunnel to ' + args.compute_host, flush=True)
                try:
                    tunnel = subprocess.Popen(
                        command, stdin=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                except OSError as error:
                    print('SSH launch failed: ' + str(error), flush=True)
                    tunnel = None
                current = tunnel
            if current is not None:
                code = current.wait()
                if stopping.is_set():
                    return
                print('SSH tunnel exited with code %d.' % code, flush=True)
            # Keep the local UI available during outages; never replay a task or command.
            print('API offline; local UI retained, retrying in 3 s.', flush=True)
            stopping.wait(3.0)

    threading.Thread(target=watch_tunnel, daemon=True).start()
    url = 'http://127.0.0.1:%d/?%s' % (args.port, urlencode({'backend': 'http://127.0.0.1:%d' % args.tunnel_port}))
    print('Web UI files: %s' % WEB, flush=True)
    print('Console URL: ' + url, flush=True)
    try:
        if not args.no_browser:
            webbrowser.open(url)
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stopping.set()
        server.server_close()
        with tunnel_lock:
            if tunnel is not None and tunnel.poll() is None:
                tunnel.terminate()
                try:
                    tunnel.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    tunnel.kill()
                    tunnel.wait()


if __name__ == '__main__':
    main()

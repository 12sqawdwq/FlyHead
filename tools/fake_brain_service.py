"""Stub for the brain service's TCP protocol, for testing the server's control ownership offline.

NOT the connectome and not a neural decision: every received `rates` line is answered with a fixed
FORWARD intent (v 0.06 m/s, w 0.10 rad/s), so brain drive has something to forward. Only for
tools/arbiter_scenarios.py; the real service is flyhead.fly.service (scripts/start_brain_service.sh).

  python tools/fake_brain_service.py --port 18095
"""
import argparse
import json
import socket
import threading
import time


def serve(conn):
    buf, window = b'', 0
    with conn:
        while True:
            data = conn.recv(65536)
            if not data:
                return
            buf += data
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get('type') != 'rates':
                    continue
                window += 1
                conn.sendall((json.dumps(dict(type='intent', window=window, stub=True, stale=False, brain_ms=0.1,
                                              input_age_s=max(0.0, time.time() - float(row.get('t', time.time()))),
                                              intent=dict(state='FORWARD', v=0.06, w=0.10))) + '\n').encode())


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', type=int, default=18095)
    a = ap.parse_args()
    srv = socket.create_server(('127.0.0.1', a.port))
    print('stub brain service on', a.port, flush=True)
    while True:
        c, _ = srv.accept()
        threading.Thread(target=serve, args=(c,), daemon=True).start()

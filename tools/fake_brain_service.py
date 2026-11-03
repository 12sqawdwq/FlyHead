"""Stub for the brain service's TCP protocol, for testing the server's control ownership offline.

NOT the connectome and not a neural decision: every received `rates` line is answered with a fixed
FORWARD intent (v 0.06 m/s, w 0.10 rad/s), so brain drive has something to forward. A crude stand-in
reaction exercises the stimulus panel: when any input rate rises 50 % (+5 Hz) above its running
baseline, the stub reports ESCAPE_PROGRAM for 1.5 s with a made-up GF rate. Only for
tools/arbiter_scenarios.py; the real service is flyhead.fly.service (scripts/start_brain_service.sh).

  python tools/fake_brain_service.py --port 18095
"""
import argparse
import json
import socket
import threading
import time


def serve(conn):
    buf, window, base, escape_until = b'', 0, {}, 0.0
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
                rates = row.get('rates') or {}
                jump = any(v > base.get(k, v) * 1.5 + 5.0 for k, v in rates.items())
                for k, v in rates.items():
                    base[k] = v if k not in base else 0.95 * base[k] + 0.05 * v
                now = time.time()
                if jump and window > 20:
                    escape_until = now + 1.5
                esc = now < escape_until
                intent = dict(state='ESCAPE_PROGRAM', v=-0.1, w=0.0, gf_hz=120.0, mdn_hz=40.0, p9_hz=0.0, arousal=0.9) if esc \
                    else dict(state='FORWARD', v=0.06, w=0.10, gf_hz=0.0, mdn_hz=0.0, p9_hz=10.0, arousal=0.3)
                conn.sendall((json.dumps(dict(type='intent', window=window, stub=True, stale=False, brain_ms=0.1,
                                              input_age_s=max(0.0, now - float(row.get('t', now))),
                                              inputs_hz=dict(rates),
                                              readouts_hz={'GF_stub': intent['gf_hz']},
                                              intent=intent)) + '\n').encode())


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', type=int, default=18095)
    a = ap.parse_args()
    srv = socket.create_server(('127.0.0.1', a.port))
    print('stub brain service on', a.port, flush=True)
    while True:
        c, _ = srv.accept()
        threading.Thread(target=serve, args=(c,), daemon=True).start()

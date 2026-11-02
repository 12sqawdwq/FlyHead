"""Live brain service (stage 4/5): retina rates in over local TCP, one decoded intent per window out.

Runs on the GPU host in the brain environment, listening on 127.0.0.1:PORT (JSON lines).
Client -> service:  {"type": "rates", "seq": int, "t": source time (s, server clock), "rates": {"LC4_left": Hz, ...}}
Service -> client:  {"type": "intent", "window": n, "seq": seq used or null, "source_t": t, "input_age_s": ...,
                     "stale": bool, "intent": {...}, "readouts_hz": {...}, "brain_ms": ..., "all_spikes": ...}
The service never talks to the robot. Windows run back to back (each about 110 ms on the shared
GPU); a window uses the newest rates if they are younger than STALE_SCAN_S at window start,
otherwise no input. Every window is appended to RUN_DIR/brain_windows.jsonl.
python -m flyhead.fly.service RUN_DIR [--port 8095] [--decoder 9]
(LOOM_DECODER=<n> is still honoured when --decoder is not given.)
"""

import argparse
import json
import os
import socket
import threading
import time
from pathlib import Path

from flyhead import paths
from flyhead.fly.decoders.loom import decode, make_decoder
from flyhead.fly.encoders.lidar_loom import STALE_SCAN_S, input_indices, rates_vector

port = 8095
latest = {'msg': None, 'received': 0.0}
clients = []
lock = threading.Lock()


def serve():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port)); srv.listen(2)
    while True:
        conn, _ = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        with lock:
            clients.append(conn)
        threading.Thread(target=reader, args=(conn,), daemon=True).start()


def reader(conn):
    buf = b''
    try:
        while True:
            data = conn.recv(65536)
            if not data:
                break
            buf += data
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                msg = json.loads(line)
                if msg.get('type') == 'rates':
                    with lock:
                        latest['msg'], latest['received'] = msg, time.time()
    except (OSError, ValueError):
        pass
    with lock:
        if conn in clients:
            clients.remove(conn)


def broadcast(obj):
    data = (json.dumps(obj) + '\n').encode()
    with lock:
        for c in list(clients):
            try:
                c.sendall(data)
            except OSError:
                clients.remove(c)


def main():
    global port
    ap = argparse.ArgumentParser(description='Fly-brain service: retina rates in, decoded intents out (no robot I/O)')
    ap.add_argument('run_dir', help='new run directory (must not exist)')
    ap.add_argument('--port', type=int, default=8095)
    ap.add_argument('--decoder', type=int, default=int(os.environ.get('LOOM_DECODER', '4')))
    ap.add_argument('--registry', default=str(paths.registry_path()))
    a = ap.parse_args()
    from flyhead.fly.model import Brain        # torch is needed only here
    run = Path(a.run_dir); run.mkdir(parents=True, exist_ok=False)
    port = a.port
    reg = paths.load_registry(a.registry)
    threading.Thread(target=serve, daemon=True).start()
    brain = Brain(reg, input_indices(reg))
    decoder = make_decoder(a.decoder)
    loop(run, reg, brain, decoder, a.registry)


def loop(run, reg, brain, decoder, registry_name):
    log = open(run / 'brain_windows.jsonl', 'w')
    (run / 'SERVICE.json').write_text(json.dumps(dict(port=port, started=time.time(), window_s=brain.window_s,
                                                      stale_scan_s=STALE_SCAN_S, registry=str(registry_name), decoder_version=decoder.VERSION if decoder else 1,
                                                      mode='SERVICE_NO_ROBOT_IO')))
    print('brain service ready on 127.0.0.1:%d' % port, flush=True)
    n = 0
    while True:
        start = time.time()
        with lock:
            msg = latest['msg']
        age = None if msg is None else start - msg['t']
        stale = msg is None or age is None or age > STALE_SCAN_S or age < -0.5
        rates = {} if stale else {tuple(k.rsplit('_', 1)): float(v) for k, v in msg['rates'].items()}
        delta, all_spikes, ms = brain.step(rates_vector(reg, rates))
        hz = {k: v / brain.window_s for k, v in brain.readouts_by_type(delta).items()}
        decoded = decoder.decode(hz, start) if decoder else decode(hz)
        intent = decoded if not stale else dict(decoded, state='HOLD', v=0.0, w=0.0, stale_input=True)
        n += 1
        row = dict(type='intent', window=n, seq=None if msg is None else msg.get('seq'), source_t=None if msg is None else msg['t'],
                   input_age_s=None if age is None else round(age, 3), stale=stale, window_start=round(start, 3),
                   window_end=round(time.time(), 3), intent=intent, readouts_hz={'%s_%s' % k: round(v, 1) for k, v in hz.items() if v},
                   inputs_hz={'%s_%s' % k: round(v, 1) for k, v in rates.items() if v}, brain_ms=round(ms, 1), all_spikes=all_spikes)
        broadcast(row)
        log.write(json.dumps(row) + '\n')
        if n % 50 == 0:
            log.flush()


if __name__ == '__main__':
    main()

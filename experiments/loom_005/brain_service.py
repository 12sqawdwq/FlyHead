"""Live brain service (stage 4/5): retina rates in over local TCP, one decoded intent per window out.

Runs in the flywire_lif_001 environment on the 5090D, listening on 127.0.0.1:PORT (JSON lines).
Client -> service:  {"type": "rates", "seq": int, "t": source time (s, server clock), "rates": {"LC4_left": Hz, ...}}
Service -> client:  {"type": "intent", "window": n, "seq": seq used or null, "source_t": t, "input_age_s": ...,
                     "stale": bool, "intent": {...}, "readouts_hz": {...}, "brain_ms": ..., "all_spikes": ...}
The service never talks to the robot. Windows run back to back (each about 110 ms on the shared
GPU); a window uses the newest rates if they are younger than STALE_SCAN_S at window start,
otherwise no input. Every window is appended to RUN_DIR/brain_windows.jsonl.
python brain_service.py RUN_DIR [PORT]
"""
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from brain import Brain  # noqa: E402
from decoder import DecoderV2, DecoderV3, DecoderV4, DecoderV5, DecoderV6, DecoderV7, DecoderV8, DecoderV9, decode  # noqa: E402
from retina import STALE_SCAN_S, input_indices, rates_vector  # noqa: E402

run = Path(sys.argv[1]); run.mkdir(parents=True, exist_ok=False)
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8095
reg = json.loads((ROOT / 'config/loom_registry.json').read_text())
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


threading.Thread(target=serve, daemon=True).start()
brain = Brain(reg, input_indices(reg), ROOT / 'cache')
decoder = {'2': DecoderV2, '3': DecoderV3, '4': DecoderV4, '5': DecoderV5, '6': DecoderV6, '7': DecoderV7, '8': DecoderV8, '9': DecoderV9}.get(os.environ.get('LOOM_DECODER', '4'), lambda: None)()
log = open(run / 'brain_windows.jsonl', 'w')
(run / 'SERVICE.json').write_text(json.dumps(dict(port=port, started=time.time(), window_s=brain.window_s,
                                                  stale_scan_s=STALE_SCAN_S, registry='config/loom_registry.json', decoder_version=decoder.VERSION if decoder else 1,
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

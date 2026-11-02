"""Bounded, foreground, own-process-only supervisor for the locked GPU probe."""
from pathlib import Path
import datetime
import json
import os
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
receipt_path = ROOT / 'evidence/EXECUTION.json'
if receipt_path.exists():
    raise SystemExit('REFUSE_USED_EXECUTION_SLOT')
log_dir = ROOT / 'evidence'
log_dir.mkdir(exist_ok=True)
started = time.monotonic()
with (log_dir / 'probe_stdout.txt').open('x') as out, (log_dir / 'probe_stderr.txt').open('x') as err:
    environment = dict(os.environ, OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='4', MKL_NUM_THREADS='4',
                       PYTHONDONTWRITEBYTECODE='1', CUDA_VISIBLE_DEVICES='0')
    child = subprocess.Popen([sys.executable, '-B', str(ROOT / 'tools/run_neural_probe.py')],
                             cwd=ROOT, stdout=out, stderr=err, env=environment, start_new_session=True)
    receipt = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'pid': child.pid,
               'status': 'RUNNING', 'scope': 'synthetic full-graph mapping probe; no robot I/O'}
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    stop_reason = None
    while child.poll() is None:
        if time.monotonic() - started > 300:
            stop_reason = 'WALLCLOCK_300S'
        try:
            available = next(int(x.split()[1]) * 1024 for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))
            rss = next(int(x.split()[1]) * 1024 for x in Path('/proc/{}/status'.format(child.pid)).read_text().splitlines() if x.startswith('VmRSS:'))
            if available < 12 * 1024**3 or rss > 12 * 1024**3:
                stop_reason = 'MEMORY_GUARD'
        except (OSError, StopIteration):
            pass
        if stop_reason:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)
            break
        time.sleep(0.2)
    receipt.update(status='COMPLETE' if child.returncode == 0 else 'FAILED', returncode=child.returncode,
                   wall_seconds=time.monotonic() - started, stop_reason=stop_reason)
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
raise SystemExit(0 if receipt['status'] == 'COMPLETE' else 1)

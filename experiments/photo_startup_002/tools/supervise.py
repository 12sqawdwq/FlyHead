"""Own-process-only resource and wall-time supervisor; single execution slot."""
from pathlib import Path
import datetime
import json
import os
import signal
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
receipt=ROOT/'evidence/EXECUTION.json'
if receipt.exists() or (ROOT/'run_001').exists():raise SystemExit('EXECUTION_SLOT_OCCUPIED')
start=time.monotonic()
env=dict(os.environ,OMP_NUM_THREADS='4',OPENBLAS_NUM_THREADS='4',MKL_NUM_THREADS='4',CUDA_VISIBLE_DEVICES='0',PYTHONDONTWRITEBYTECODE='1')
with (ROOT/'evidence/stdout.txt').open('x') as out,(ROOT/'evidence/stderr.txt').open('x') as err:
    child=subprocess.Popen([sys.executable,'-B',str(ROOT/'tools/run_experiment.py')],cwd=ROOT,env=env,stdout=out,stderr=err,start_new_session=True)
    data={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':child.pid,'status':'RUNNING'}
    receipt.write_text(json.dumps(data,indent=2)+'\n')
    stop=None;peak=0
    while child.poll() is None:
        if time.monotonic()-start>300:stop='WALL_LIMIT'
        try:
            available=next(int(s.split()[1])*1024 for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:'))
            rss=next(int(s.split()[1])*1024 for s in Path('/proc/{}/status'.format(child.pid)).read_text().splitlines() if s.startswith('VmRSS:'))
            peak=max(peak,rss)
            if available<12*1024**3 or rss>6*1024**3:stop='MEMORY_LIMIT'
        except (OSError,StopIteration):pass
        if stop:
            try:os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5)
            break
        time.sleep(.2)
    data.update(status='COMPLETE' if child.returncode==0 else 'FAILED',returncode=child.returncode,wall_seconds=time.monotonic()-start,stop_reason=stop,observed_peak_rss_bytes=peak)
    receipt.write_bytes((json.dumps(data,indent=2)+'\n').encode())
print(json.dumps(data,indent=2))
raise SystemExit(0 if child.returncode==0 else 1)

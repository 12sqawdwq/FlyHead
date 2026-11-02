"""Double-click launcher (Windows): start console/preview.py in the background, open the UI.

Only local preview/SSH processes are started, never acquisition or motion. A repeated
launch reuses the running console of this checkout instead of opening a second tunnel.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
COMPUTE_HOST = os.environ.get('XT_COMPUTE_HOST', 'compute')    # SSH alias, same default as preview.py
URL = 'http://127.0.0.1:18101/?backend=http%3A%2F%2F127.0.0.1%3A18102'
INFO_URL = 'http://127.0.0.1:18101/__console_info'
LOG = ROOT / 'logs' / 'monitor.log'


def existing_console():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(INFO_URL, timeout=1) as response:
            info = json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return None
    if (info.get('application') == 'flyhead-monitor'
            and Path(info.get('root', '')).resolve() == ROOT.resolve()
            and info.get('compute_host') == COMPUTE_HOST
            and info.get('remote_port') == 8091
            and info.get('tunnel_port') == 18102):
        return info
    raise RuntimeError('Port 18101 is occupied by another console; it was not stopped')


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    info = existing_console()
    if info is None:
        interpreter = Path(sys.executable)
        windowless = interpreter.with_name('pythonw.exe')
        if os.name == 'nt' and windowless.is_file():
            interpreter = windowless
        command = [str(interpreter), '-u', str(ROOT / 'flyhead' / 'monitor' / 'preview.py'), '--no-browser']
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0
        with LOG.open('ab') as output:
            process = subprocess.Popen(command, cwd=str(ROOT), stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT, creationflags=flags)
        until = time.monotonic() + 15
        while time.monotonic() < until:
            info = existing_console()
            if info is not None:
                break
            if process.poll() is not None:
                raise RuntimeError('Preview startup exited; see %s' % LOG)
            time.sleep(.2)
        if info is None:
            raise RuntimeError('Preview startup acknowledgement timed out; see %s' % LOG)
    record = dict(pid=info['pid'], url=URL, log=str(LOG),
                  compute_host=COMPUTE_HOST, remote_port=8091,
                  windows_no_console=os.name == 'nt',
                  sensors_started=False, physical_motion_started=False,
                  status='Local HTTP startup acknowledged; remote functionality not checked by launcher')
    (ROOT / 'logs' / 'monitor.json').write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    if '--no-browser' not in sys.argv:
        webbrowser.open(URL)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open('a', encoding='utf-8') as output:
            traceback.print_exc(file=output)
        sys.exit(1)

"""One entry point for operating FlyHead, written for people and for coding agents (Codex, Claude Code).

  python -m flyhead.ops <command> [--json]

Every command says which safety tier it belongs to:

  tier 0  read only, run any time                doctor, status, lock show
  tier 1  offline, own processes and ports only  test, offline up | check | down | run, collect
  tier 2  live stack, robot stays still          live up locked, live down, lock acquire | release
  tier 3  live stack with motion opt-ins         live up motion | turbo   (needs --operator-present)

Commands:
  doctor                 environment report: Python packages, configs/local.env, map, ports, tmux sessions,
                         live server, robot SSH reachability, GPU
  status                 compact live summary from GET /diagnostics (owner, navigation, robot, battery, brain)
  test                   the unit tests (pytest -q)
  offline run            start a private control server with a simulated robot and a stub brain, run the
                         two-console control scenarios against it, stop it; exit code 0 when every check passes
  offline up|check|down  the same in steps (check needs a running offline stack)
  collect [RUN ...]      bundle live runs for the record (tools/collect_run.py)
  live up MODE           scripts/fieldtest.sh up MODE   (MODE: locked | motion | turbo)
  live down              scripts/fieldtest.sh down      (ends the robot session)
  lock show|acquire|release   advisory lock over the live stack between agents (runs/agent_lock.json)

The offline stack never connects to the robot: its robot command is tools/fake_bridge.py (XT_ROBOT_CMD) and its
brain is tools/fake_brain_service.py, a stub that is not the connectome. Default ports 18091 (API) and 18095
(stub brain) keep it away from the live 8091 / 8095.
"""
import argparse
import json
import os
import platform
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from flyhead import paths

REPO = paths.REPO
RUNS = paths.runs_dir()
LOCK = RUNS / 'agent_lock.json'
AUDIT = RUNS / 'ops_audit.jsonl'
OFFLINE_STATE = RUNS / 'offline_stack.json'
WINDOWS = os.name == 'nt'


# ------------------------------------------------------------------ helpers
def load_env():
    """configs/local.env (KEY=VALUE lines) merged under the process environment."""
    env = {}
    p = REPO / 'configs' / 'local.env'
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"\'')
    env.update({k: v for k, v in os.environ.items() if k.startswith(('XT_', 'FLYHEAD_'))})
    return env


def port_open(port, host='127.0.0.1'):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def http_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def run(cmd, timeout=None, **kw):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, repr(error)


def audit(action, **kw):
    RUNS.mkdir(parents=True, exist_ok=True)
    with open(AUDIT, 'a', encoding='utf-8') as f:
        f.write(json.dumps(dict(t=time.time(), time=time.strftime('%Y-%m-%d %H:%M:%S'), action=action,
                                agent=os.environ.get('FLYHEAD_AGENT', 'unknown'), **kw)) + '\n')


def emit(report, as_json):
    if as_json:
        print(json.dumps(report, indent=1, ensure_ascii=False, default=str))
    else:
        for k, v in report.items():
            print('%-22s %s' % (k, v if not isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False, default=str)))


# ------------------------------------------------------------------ tier 0
def cmd_doctor(a):
    env = load_env()
    rep = dict(tier=0, host=platform.node(), platform=platform.platform(), python=sys.version.split()[0],
               repo=str(REPO), git=run(['git', '-C', str(REPO), 'log', '--oneline', '-1'])[1])
    mods = {}
    for m in ('numpy', 'scipy', 'aiohttp', 'kiss_icp', 'torch', 'pytest', 'matplotlib'):
        try:
            __import__(m)
            mods[m] = 'ok'
        except Exception as error:          # noqa: BLE001 - report every failure kind
            mods[m] = 'missing (%s)' % type(error).__name__
    rep['packages'] = mods
    rep['local_env'] = (REPO / 'configs' / 'local.env').exists()
    rep['settings'] = {k: env.get(k) for k in ('XT_ROBOT_HOST', 'XT_ROBOT_ROOT', 'XT_MAP', 'XT_PYTHON',
                                               'FLYHEAD_BRAIN_PYTHON', 'XT_BRAIN_PORT')}
    if env.get('XT_MAP'):
        mp = Path(env['XT_MAP']) if Path(env['XT_MAP']).is_absolute() else REPO / env['XT_MAP']
        rep['map_package'] = 'ok' if (mp / 'map.ply').exists() else 'missing %s' % mp
    rep['ports'] = {p: port_open(p) for p in (8091, 8095, 18091, 18095)}
    if shutil.which('tmux'):
        rep['tmux'] = run(['tmux', 'ls'])[1] or 'no sessions'
    try:
        d = http_json('http://127.0.0.1:%s/diagnostics' % env.get('XT_API_PORT', '8091'), timeout=3)
        rep['live_server'] = 'up, session %s, %d console(s)' % (d.get('session_running'), d.get('control_clients') or 0)
    except Exception as error:              # noqa: BLE001
        rep['live_server'] = 'not reachable here (%s)' % type(error).__name__
    if env.get('XT_ROBOT_HOST') and shutil.which('ssh'):
        code, out = run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', env['XT_ROBOT_HOST'], 'true'], timeout=15)
        rep['robot_ssh'] = 'ok' if code == 0 else 'failed: %s' % out[-160:]
    if shutil.which('nvidia-smi'):
        rep['gpu'] = run(['nvidia-smi', '--query-gpu=name,memory.used,memory.total,utilization.gpu',
                          '--format=csv,noheader'])[1]
    rep['offline_stack'] = json.loads(OFFLINE_STATE.read_text()) if OFFLINE_STATE.exists() else None
    rep['agent_lock'] = json.loads(LOCK.read_text()) if LOCK.exists() else None
    emit(rep, a.json)


def summarize(d):
    s = d.get('status') or {}
    r = s.get('robot') or {}
    nav = d.get('navigation') or {}
    ctl = s.get('control') or {}
    br = s.get('brain') or {}
    sl = s.get('slam') or {}
    bat = r.get('battery') or {}
    body = r.get('body') or {}
    return dict(
        session=d.get('session_running'), run=s.get('run'), consoles=d.get('control_clients'),
        charging_lock=s.get('chassis_disabled'), speed_ceiling=s.get('speed_limit_max'),
        control=dict(owner=ctl.get('owner', 'n/a (server without arbiter)'), controller=ctl.get('controller'),
                     reason=ctl.get('reason'), halts=ctl.get('halts')),
        navigation=dict(active=nav.get('active'), state=nav.get('state'), reason=nav.get('reason'),
                        progress_m=nav.get('tour_progress_m'), length_m=nav.get('tour_length_m')),
        localization=dict(state=(sl.get('reloc') or {}).get('state'), fitness=sl.get('fitness'), pose=sl.get('pose')),
        robot=dict(lidar=r.get('lidar_running'), chassis=r.get('chassis_running'),
                   posture={2: 'crouched', 3: 'standing'}.get(body.get('robot_mode'), body.get('robot_mode')),
                   battery_pct=bat.get('pct'), battery_v=bat.get('voltage'), cmd=r.get('cmd'),
                   last_posture=(r.get('posture_result') or {}).get('state')),
        brain=dict(mode=br.get('mode'), connected=br.get('connected'), state=(br.get('last') or {}).get('state')),
        rates=s.get('rates'), fault=(s.get('pipeline') or {}).get('fault'), errors=d.get('errors') or None)


def cmd_status(a):
    try:
        d = http_json(a.url + '/diagnostics')
    except Exception as error:              # noqa: BLE001
        emit(dict(tier=0, url=a.url, reachable=False, error=repr(error)), a.json)
        return 1
    emit(dict(tier=0, url=a.url, **summarize(d)), a.json)
    return 0


# ------------------------------------------------------------------ tier 1
def cmd_test(a):
    return subprocess.call([sys.executable, '-m', 'pytest', '-q'], cwd=REPO)


def offline_map(requested):
    """A map package (map.ply + map.pgm/yaml + layers) in the simulated robot's start frame."""
    if requested:
        return Path(requested)
    real = RUNS / 'real_console_map'               # the real-site package moved to a start frame, if present
    if (real / 'map.ply').exists():
        return real
    synth = RUNS / 'offline_synthetic_map'
    if not (synth / 'nav' / 'map.ply').exists():
        sys.path.insert(0, str(REPO / 'tools'))
        import make_synthetic_raw as MSR
        MSR.write_base(synth)
        shutil.copy2(synth / 'map.ply', synth / 'nav' / 'map.ply')
    return synth / 'nav'


def spawn(cmd, log, env):
    kw = dict(cwd=REPO, env=env, stdout=open(log, 'ab'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if WINDOWS:
        kw['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    else:
        kw['start_new_session'] = True
    return subprocess.Popen(cmd, **kw).pid


def kill_tree(pid):
    if WINDOWS:
        run(['taskkill', '/T', '/F', '/PID', str(pid)])
    else:
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass


def cmd_offline_up(a):
    if OFFLINE_STATE.exists():
        st = json.loads(OFFLINE_STATE.read_text())
        if port_open(st['port']):
            print('offline stack already running: %s (offline down first)' % st['url'])
            return 1
    if port_open(a.port) or port_open(a.brain_port):
        print('port %d or %d is in use; choose others with --port / --brain-port' % (a.port, a.brain_port))
        return 1
    mp = offline_map(a.map)
    out = RUNS / ('offline_%s' % time.strftime('%Y%m%dT%H%M%S'))
    out.mkdir(parents=True)
    py = sys.executable
    env = dict(os.environ, PYTHONPATH=str(REPO), PYTHONUTF8='1', OPENBLAS_NUM_THREADS='2',
               XT_BRAIN_ENABLED='1', XT_BRAIN_PORT=str(a.brain_port), XT_CHASSIS_DISABLED='0',
               XT_REMOTE_MOTION_ENABLED='1', XT_MAX_V=str(a.max_v),
               XT_ROBOT_CMD=' '.join(shlex.quote(str(x)) for x in (
                   py, REPO / 'tools' / 'fake_bridge.py', '--map', mp, '--log', out / 'ops.jsonl')))
    pids = [spawn([py, str(REPO / 'tools' / 'fake_brain_service.py'), '--port', str(a.brain_port)],
                  out / 'brain_stub.log', env)]
    pids.append(spawn([py, '-m', 'flyhead.server.app', '--robot-host', 'fake', '--robot-root', '/unused',
                       '--base', str(mp / 'map.ply'), '--nav', str(mp), '--port', str(a.port),
                       '--record-reserve-mib', '1024'], out / 'server.log', env))
    url = 'http://127.0.0.1:%d' % a.port
    for _ in range(60):
        if port_open(a.port):
            break
        time.sleep(1)
    st = dict(url=url, port=a.port, brain_port=a.brain_port, pids=pids, dir=str(out), map=str(mp),
              started=time.strftime('%Y-%m-%d %H:%M:%S'), ready=port_open(a.port))
    OFFLINE_STATE.write_text(json.dumps(st, indent=1))
    print(json.dumps(st, indent=1))
    if st['ready']:
        print('console page (static files from a running flyhead/monitor/preview.py, which serves on 18101): '
              'http://127.0.0.1:18101/?backend=%s' % url.replace(':', '%3A').replace('/', '%2F'))
    return 0 if st['ready'] else 1


def cmd_offline_check(a):
    if not OFFLINE_STATE.exists():
        print('no offline stack (offline up first)')
        return 1
    st = json.loads(OFFLINE_STATE.read_text())
    time.sleep(3)                                   # base map load
    return subprocess.call([sys.executable, str(REPO / 'tools' / 'arbiter_scenarios.py'), '--url', st['url'],
                            '--ops', str(Path(st['dir']) / 'ops.jsonl'), '--out', st['dir']], cwd=REPO,
                           env=dict(os.environ, PYTHONUTF8='1'))


def cmd_offline_down(a):
    if not OFFLINE_STATE.exists():
        print('no offline stack recorded')
        return 0
    st = json.loads(OFFLINE_STATE.read_text())
    for pid in reversed(st['pids']):
        kill_tree(pid)
    OFFLINE_STATE.unlink()
    print('offline stack stopped; record in %s' % st['dir'])
    return 0


def cmd_offline_run(a):
    code = cmd_offline_up(a)
    if code:
        cmd_offline_down(a)
        return code
    try:
        code = cmd_offline_check(a)
    finally:
        cmd_offline_down(a)
    return code


def cmd_collect(a):
    return subprocess.call([sys.executable, str(REPO / 'tools' / 'collect_run.py'), *a.rest], cwd=REPO)


# ------------------------------------------------------------------ tier 2 / 3
def lock_holder():
    if not LOCK.exists():
        return None
    st = json.loads(LOCK.read_text())
    if time.time() > st.get('expires', 0):
        return None
    return st


def cmd_lock(a):
    me = a.agent or os.environ.get('FLYHEAD_AGENT')
    held = lock_holder()
    if a.action == 'show':
        emit(dict(tier=0, lock=held), a.json)
        return 0
    if not me:
        print('set --agent or FLYHEAD_AGENT')
        return 2
    if a.action == 'acquire':
        if held and held['agent'] != me and not a.force:
            print('live stack held by %s since %s: %s' % (held['agent'], held['since'], held.get('note')))
            return 1
        st = dict(agent=me, since=time.strftime('%Y-%m-%d %H:%M:%S'), note=a.note,
                  expires=time.time() + a.minutes * 60)
        RUNS.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(json.dumps(st, indent=1))
        audit('lock acquire', note=a.note, minutes=a.minutes)
        print('lock held by %s for %d min' % (me, a.minutes))
        return 0
    if held and held['agent'] != me and not a.force:
        print('lock is held by %s; not releasing' % held['agent'])
        return 1
    if LOCK.exists():
        LOCK.unlink()
    audit('lock release')
    print('lock released')
    return 0


def cmd_live(a):
    if WINDOWS:
        print('live commands run on the compute host (ssh <compute-alias> and run them there)')
        return 2
    me = os.environ.get('FLYHEAD_AGENT') or a.agent
    held = lock_holder()
    if held and held['agent'] != me:
        print('live stack held by %s (%s); ask them or the user first' % (held['agent'], held.get('note')))
        return 1
    if a.action == 'up':
        if a.mode in ('motion', 'turbo') and not a.operator_present:
            print('mode %s enables remote motion: needs --operator-present (a person with the RC at the robot, '
                  'confirmed by the user in this conversation)' % a.mode)
            return 2
        audit('live up', mode=a.mode)
        return subprocess.call(['bash', 'scripts/fieldtest.sh', 'up', a.mode], cwd=REPO)
    if a.action == 'down':
        audit('live down')
        return subprocess.call(['bash', 'scripts/fieldtest.sh', 'down'], cwd=REPO)
    return subprocess.call(['bash', 'scripts/fieldtest.sh', 'status'], cwd=REPO)


# ------------------------------------------------------------------ cli
def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m flyhead.ops', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('doctor', help='tier 0: environment report')
    p.add_argument('--json', action='store_true')
    p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser('status', help='tier 0: live summary')
    p.add_argument('--url', default='http://127.0.0.1:%s' % load_env().get('XT_API_PORT', '8091'))
    p.add_argument('--json', action='store_true')
    p.set_defaults(fn=cmd_status)
    p = sub.add_parser('test', help='tier 1: unit tests')
    p.set_defaults(fn=cmd_test)
    p = sub.add_parser('offline', help='tier 1: private server + simulated robot + stub brain')
    p.add_argument('action', choices=('up', 'check', 'down', 'run'))
    p.add_argument('--port', type=int, default=18091)
    p.add_argument('--brain-port', type=int, default=18095)
    p.add_argument('--map', help='map package in the start frame (default: runs/real_console_map, else synthetic)')
    p.add_argument('--max-v', type=float, default=0.10, help='simulated speed ceiling')
    p.set_defaults(fn=lambda a: dict(up=cmd_offline_up, check=cmd_offline_check, down=cmd_offline_down,
                                     run=cmd_offline_run)[a.action](a))
    p = sub.add_parser('collect', help='tier 1: bundle runs (arguments go to tools/collect_run.py)')
    p.add_argument('rest', nargs=argparse.REMAINDER)
    p.set_defaults(fn=cmd_collect)
    p = sub.add_parser('lock', help='tier 0 / 2: advisory live-stack lock between agents')
    p.add_argument('action', choices=('show', 'acquire', 'release'))
    p.add_argument('--agent')
    p.add_argument('--note', default='')
    p.add_argument('--minutes', type=int, default=60)
    p.add_argument('--force', action='store_true')
    p.add_argument('--json', action='store_true')
    p.set_defaults(fn=cmd_lock)
    p = sub.add_parser('live', help='tier 2 / 3: the live stack on the compute host')
    p.add_argument('action', choices=('up', 'down', 'status'))
    p.add_argument('mode', nargs='?', default='locked', choices=('locked', 'motion', 'turbo'))
    p.add_argument('--operator-present', action='store_true')
    p.add_argument('--agent')
    p.set_defaults(fn=cmd_live)
    a = ap.parse_args(argv)
    return a.fn(a) or 0


if __name__ == '__main__':
    raise SystemExit(main())

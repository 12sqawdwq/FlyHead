"""Collect field runs into self-describing bundles for the record and for later publication.

  python tools/collect_run.py                      # every runs/live_* not yet collected
  python tools/collect_run.py live_20261102T214717 --raw --robot
  bash scripts/fieldtest.sh collect [...]          # same, with configs/local.env loaded

Per run, field_records/<run>/ holds
  manifest.json       run window, git commit, settings, map, and size + sha256 of every file
  summary.md          tables: duration, distance, control-owner time, ownership transitions,
                      refusals and stops, brain states, posture results, faults
  timeline.csv        1 Hz: owner, controller, navigation state, fitness, pose, commanded (v, w), brain state
  events.jsonl        the server's event messages (includes every "Control:" transition)
  navigation.jsonl.gz the full per-tick telemetry
  BASE.json, cloud_map/   as the server wrote them
  raw.xt              only with --raw (hard link when possible; the sensor stream can be replayed)
  robot_logs/         with --robot: robot-side logs written during the run window (over SSH)
  logs/               the compute host's control-server and brain-service logs (gzip)
Bundles are only added to, never rewritten: an existing bundle is skipped unless --force.
Nothing here labels what the robot did; the operator adds notes.md (media, observations) by hand.
"""
import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import shutil
import subprocess
import tarfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def git(*args):
    try:
        return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None


def fmt_t(t):
    return time.strftime('%H:%M:%S', time.localtime(t)) if t else '-'


def read_run(path):
    """One pass over navigation.jsonl: events, a 1 Hz timeline and the counters for the summary."""
    events, timeline, owners, brain_states = [], [], Counter(), Counter()
    t_first = t_last = None
    last_row_t, last_ctrl_t, last_pose = -1e9, None, None
    dist, brain = 0.0, {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            t = r.get('t')
            if isinstance(t, (int, float)):
                t_first = t if t_first is None else t_first
                t_last = t
            kind = r.get('type')
            if kind == 'event':
                events.append(r)
            elif kind == 'brain':
                brain = r
                brain_states[(r.get('mode'), r.get('state'))] += 1
            elif kind == 'control':
                owner = r.get('owner', 'n/a (before the arbiter)')
                if last_ctrl_t is not None and t - last_ctrl_t < 1.0:
                    owners[owner] += t - last_ctrl_t
                last_ctrl_t = t
                pose = r.get('pose')
                if pose and last_pose:
                    step = math.hypot(pose[0] - last_pose[0], pose[1] - last_pose[1])
                    if step < 0.5:                       # ignore relocalization jumps
                        dist += step
                last_pose = pose or last_pose
                if t - last_row_t >= 1.0:
                    last_row_t = t
                    cmd = r.get('requested_command') or [0, 0]
                    timeline.append(dict(
                        t=round(t, 2), clock=fmt_t(t), owner=owner, controller=r.get('controller'),
                        reflex=r.get('reflex'), nav_active=r.get('active'), nav_reason=r.get('reason'),
                        fitness=None if r.get('fitness') is None else round(r['fitness'], 3),
                        x=pose[0] if pose else None, y=pose[1] if pose else None, yaw=pose[2] if pose else None,
                        v=round(cmd[0], 3), w=round(cmd[1], 3), fault=r.get('pipeline_fault'),
                        brain_mode=brain.get('mode'), brain_state=brain.get('state'),
                        brain_v=brain.get('v'), brain_w=brain.get('w'), brain_withheld=brain.get('withheld')))
    return dict(events=events, timeline=timeline, owners=owners, brain_states=brain_states,
                t_first=t_first, t_last=t_last, distance_m=dist)


def summary_md(run, d, manifest):
    ev = d['events']
    dur = (d['t_last'] or 0) - (d['t_first'] or 0)
    texts = [e.get('text', '') for e in ev]
    def count(prefix):
        return sum(1 for x in texts if x.startswith(prefix))
    L = ['# %s' % run, '',
         'Collected %s from commit `%s`%s. Times are local to the compute host.' % (
             manifest['collected'], manifest['git']['commit'], ' (uncommitted changes)' if manifest['git']['dirty'] else ''),
         '', '## Run', '', '| Item | Value |', '| --- | --- |',
         '| Window | %s to %s |' % (fmt_t(d['t_first']), fmt_t(d['t_last'])),
         '| Duration | %.1f min |' % (dur / 60),
         '| Distance (localized pose, jumps > 0.5 m excluded) | %.1f m |' % d['distance_m'],
         '| Base map | %s |' % (manifest.get('base') or '-'),
         '| Speed ceiling / charging lock | %s / %s |' % (manifest['settings'].get('XT_MAX_V', '-'),
                                                        manifest['settings'].get('XT_CHASSIS_DISABLED', '-')),
         '| Events | %d |' % len(ev),
         '', '## Control owner time', '', '| Owner | Time (s) | Share |', '| --- | ---: | ---: |']
    total = sum(d['owners'].values()) or 1.0
    for k, v in d['owners'].most_common():
        L.append('| %s | %.0f | %.0f %% |' % (k, v, 100 * v / total))
    L += ['', '## Ownership transitions and refusals', '', '| Time | Event |', '| --- | --- |']
    keys = ('Control', 'Refused', 'Brain drive ended', 'Navigation stopped', 'Navigation cancelled', 'Battery',
            'Stand request', 'Crouch request', 'robot: {"event": "posture"', 'Pipeline fault', 'Relocaliz')
    shown = [e for e in ev if e.get('text', '').startswith(keys)]
    for e in shown[:400]:
        L.append('| %s | %s |' % (fmt_t(e['t']), e['text'].replace('|', '/')[:200]))
    if len(shown) > 400:
        L.append('| ... | %d more in events.jsonl |' % (len(shown) - 400))
    L += ['', '## Counts', '', '| Kind | Count |', '| --- | ---: |',
          '| Ownership transitions | %d |' % count('Control:'),
          '| Refused requests | %d |' % count('Refused'),
          '| Emergency stops | %d |' % sum(1 for x in texts if 'emergency stop' in x.lower()),
          '| Posture confirmed / failed | %d / %d |' % (sum('"confirmed"' in x for x in texts), sum('"failed"' in x for x in texts)),
          '', '## Brain windows by mode and decoded state', '',
          'Decoded states of the fly-brain model (shadow: logged, not sent; drive / reflex: sent within the envelope).',
          '', '| Mode | State | Windows |', '| --- | --- | ---: |']
    for (mode, state), n in sorted(d['brain_states'].items(), key=lambda kv: -kv[1])[:30]:
        L.append('| %s | %s | %d |' % (mode, state, n))
    L += ['', '## Files', '', '| File | Bytes | sha256 |', '| --- | ---: | --- |']
    for f in manifest['files']:
        L.append('| %s | %d | `%s` |' % (f['path'], f['bytes'], f['sha256'][:16]))
    return '\n'.join(L) + '\n'


def robot_logs(dest, t0, t1):
    host, root = os.environ.get('XT_ROBOT_HOST'), os.environ.get('XT_ROBOT_ROOT')
    if not (host and root):
        return 'XT_ROBOT_HOST / XT_ROBOT_ROOT not set'
    since = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t0 - 120))
    cmd = ('cd %s/logs 2>/dev/null && find . -maxdepth 1 -type f -newermt "%s" -print0 | tar --null -czf - -T -'
           % (root, since))
    try:
        out = subprocess.run(['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', host, cmd],
                             capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        return repr(error)
    if out.returncode != 0 or not out.stdout:
        return 'ssh: %s' % out.stderr.decode(errors='replace')[-300:]
    dest.mkdir(parents=True, exist_ok=True)
    tgz = dest / 'robot_logs.tgz'
    tgz.write_bytes(out.stdout)
    with tarfile.open(tgz) as tar:
        tar.extractall(dest, filter='data')
    tgz.unlink()
    return None


def collect(run_dir, out_root, raw=False, robot=False, force=False):
    run = run_dir.name
    dest = out_root / run
    if dest.exists() and not force:
        print('skip %s (already collected)' % run)
        return
    nav = run_dir / 'navigation.jsonl'
    if not nav.exists():
        print('skip %s (no navigation.jsonl)' % run)
        return
    dest.mkdir(parents=True, exist_ok=True)
    d = read_run(nav)
    with open(dest / 'events.jsonl', 'w', encoding='utf-8') as f:
        for e in d['events']:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
    with open(dest / 'timeline.csv', 'w', newline='', encoding='utf-8') as f:
        if d['timeline']:
            w = csv.DictWriter(f, fieldnames=list(d['timeline'][0]))
            w.writeheader()
            w.writerows(d['timeline'])
    with open(nav, 'rb') as src, gzip.open(dest / 'navigation.jsonl.gz', 'wb', compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)
    for name in ('BASE.json', 'summary.json'):
        if (run_dir / name).exists():
            shutil.copy2(run_dir / name, dest / name)
    if (run_dir / 'cloud_map').is_dir():
        shutil.copytree(run_dir / 'cloud_map', dest / 'cloud_map', dirs_exist_ok=True)
    if raw and (run_dir / 'raw.xt').exists():
        try:
            os.link(run_dir / 'raw.xt', dest / 'raw.xt')
        except OSError:
            shutil.copy2(run_dir / 'raw.xt', dest / 'raw.xt')
    (dest / 'logs').mkdir(exist_ok=True)
    for name in ('control_server.log', 'brain_service.log'):
        p = ROOT / 'logs' / name
        if p.exists():
            with open(p, 'rb') as src, gzip.open(dest / 'logs' / (name + '.gz'), 'wb') as dst:
                shutil.copyfileobj(src, dst)
    robot_note = robot_logs(dest / 'robot_logs', d['t_first'] or 0, d['t_last'] or 0) if robot else 'not requested'
    base = None
    if (run_dir / 'BASE.json').exists():
        base = json.loads((run_dir / 'BASE.json').read_text()).get('base')
    files = []
    for p in sorted(dest.rglob('*')):
        if p.is_file() and p.name not in ('manifest.json', 'summary.md', 'notes.md'):
            files.append(dict(path=p.relative_to(dest).as_posix(), bytes=p.stat().st_size, sha256=sha256(p)))
    manifest = dict(
        run=run, collected=time.strftime('%Y-%m-%d %H:%M:%S'), host=os.uname().nodename if hasattr(os, 'uname') else None,
        window=dict(start=d['t_first'], end=d['t_last'], start_local=fmt_t(d['t_first']), end_local=fmt_t(d['t_last'])),
        git=dict(commit=git('rev-parse', '--short', 'HEAD'), dirty=bool(git('status', '--porcelain', '--untracked-files=no'))),
        settings={k: os.environ.get(k) for k in ('XT_MAX_V', 'XT_CHASSIS_DISABLED', 'XT_REMOTE_MOTION_ENABLED',
                                                 'XT_MAP', 'XT_BRAIN_PORT', 'LOOM_DECODER')},
        base=base, distance_m=round(d['distance_m'], 2), events=len(d['events']),
        owner_seconds={k: round(v, 1) for k, v in d['owners'].items()},
        robot_logs=robot_note or 'collected', raw_included=bool(raw), files=files,
        note='Settings are those of the collecting shell (fieldtest.sh loads configs/local.env), not necessarily of the run.')
    (dest / 'manifest.json').write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    (dest / 'summary.md').write_text(summary_md(run, d, manifest), encoding='utf-8')
    notes = dest / 'notes.md'
    if not notes.exists():
        notes.write_text('# %s: operator notes\n\n| Item | Value |\n| --- | --- |\n| Operator / RC supervisor | |\n'
                         '| Site and conditions | |\n| Task(s) run | |\n| Phone / screen recordings (file, start time) | |\n'
                         '| Anything unusual | |\n' % run, encoding='utf-8')
    print('collected %s: %.1f min, %.1f m, %d events -> %s' % (
        run, ((d['t_last'] or 0) - (d['t_first'] or 0)) / 60, d['distance_m'], len(d['events']), dest))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('runs', nargs='*', help='run directory names under runs/ (default: every live_* run)')
    ap.add_argument('--out', default=str(ROOT / 'field_records'))
    ap.add_argument('--raw', action='store_true', help='include raw.xt (hard link when on the same disk)')
    ap.add_argument('--robot', action='store_true', help='fetch robot-side logs of the run window over SSH')
    ap.add_argument('--force', action='store_true', help='rebuild an existing bundle')
    a = ap.parse_args()
    names = a.runs or sorted(p.name for p in (ROOT / 'runs').glob('live_*') if p.is_dir())
    for name in names:
        collect(ROOT / 'runs' / name, Path(a.out), raw=a.raw, robot=a.robot, force=a.force)


if __name__ == '__main__':
    main()

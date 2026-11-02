"""Drive a test control server (fake bridge, stub brain) through the control-ownership scenarios with
two consoles, and record what happened. Never point this at the live server: it starts the chassis,
stands, drives and retraces.

  python tools/arbiter_scenarios.py --url http://127.0.0.1:18091 --ops runs/X/ops.jsonl --out runs/X

Each check prints PASS / FAIL; the record (scenarios.json: checks, control history, events) goes to --out.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

import aiohttp


ALL = []


class Console:
    def __init__(self, label):
        self.label, self.ws, self.status, self.events, self.you = label, None, {}, [], None
        ALL.append(self)

    async def open(self, http, url):
        self.ws = await http.ws_connect(url.replace('http', 'ws') + '/ws', heartbeat=5)
        self.task = asyncio.create_task(self.read())

    async def read(self):
        async for msg in self.ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            m = json.loads(msg.data)
            if m.get('type') == 'status':
                self.status = m
            elif m.get('type') == 'event':
                self.events.append((time.time(), m.get('text')))
            elif m.get('type') == 'hello':
                self.you = m.get('you')

    async def send(self, **m):
        await self.ws.send_str(json.dumps(m))

    async def close(self):
        await self.ws.close()

    def control(self):
        return self.status.get('control') or {}

    def saw(self, text, since):
        return any(text in e for t, e in self.events if t >= since)


class Run:
    def __init__(self, ops):
        self.ops, self.checks = Path(ops), []

    def check(self, name, ok, detail=''):
        self.checks.append(dict(name=name, ok=bool(ok), detail=detail))
        print('%s  %s  %s' % ('PASS' if ok else 'FAIL', name, detail), flush=True)

    def ops_since(self, t):
        out = []
        if self.ops.exists():
            for line in self.ops.read_text().splitlines():
                r = json.loads(line)
                if r['t'] >= t:
                    out.append(r)
        return out


async def wait(pred, timeout, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        await asyncio.sleep(step)
    return pred()


async def hold_manual(c, v, w, seconds):
    end = time.time() + seconds
    while time.time() < end:
        await c.send(t='cmd', v=v, w=w)
        await asyncio.sleep(0.1)


async def main(a):
    r = Run(a.ops)
    http = aiohttp.ClientSession()
    A, B = Console('A'), Console('B')
    await A.open(http, a.url)
    await B.open(http, a.url)
    await asyncio.sleep(1.0)
    r.check('consoles named by the server', A.you and B.you and A.you != B.you, '%s / %s' % (A.you, B.you))

    # --- setup: session on the base map, chassis on
    await A.send(t='session', on=True, base=True)
    ok = await wait(lambda: ((A.status.get('slam') or {}).get('attached')), 90)
    r.check('relocalized on the base map', ok, json.dumps(((A.status.get('slam') or {}).get('reloc') or {}).get('fitness')))
    await A.send(t='chassis', on=True)
    ok = await wait(lambda: (A.status.get('robot') or {}).get('chassis_running'), 10)
    r.check('fake chassis running', ok)
    await asyncio.sleep(1.0)

    # --- 1 posture: owner posture until confirmed, nothing moves meanwhile
    t0 = time.time()
    await A.send(t='posture', stand=True)
    ok = await wait(lambda: A.control().get('owner') == 'posture', 3)
    r.check('stand request takes the posture owner', ok, A.control().get('reason', ''))
    await A.send(t='cmd', v=0.08, w=0.0)
    await asyncio.sleep(0.3)
    r.check('manual drive refused during posture', A.saw('Refused', t0) and A.control().get('owner') == 'posture')
    ok = await wait(lambda: A.control().get('owner') == 'idle', 6)
    body = ((A.status.get('robot') or {}).get('body') or {})
    r.check('posture confirmed releases to idle; robot standing', ok and body.get('robot_mode') == 3,
            'owner %s, robot_mode %s' % (A.control().get('owner'), body.get('robot_mode')))
    moving = [o for o in r.ops_since(t0) if o['op'] == 'cmd' and o['accepted'] and (o.get('v') or o.get('w'))]
    r.check('no motion command reached the robot during the transition', not moving, '%d accepted' % len(moving))

    # --- 2 manual: A drives; B is an observer
    t0 = time.time()
    await hold_manual(A, 0.06, 0.0, 1.0)
    r.check('manual drive owner A', A.control().get('owner') == 'manual' and A.control().get('controller') == A.you,
            json.dumps(A.control().get('controller')))
    await B.send(t='cmd', v=0.0, w=0.5)
    await B.send(t='goal', x=1.0, y=0.0)
    await asyncio.sleep(0.3)
    r.check('observer B refused (drive and goal)', B.saw('holds control', t0) and A.control().get('owner') == 'manual')
    accepted = [o for o in r.ops_since(t0) if o['op'] == 'cmd' and o['accepted'] and o.get('w')]
    r.check('no command from B reached the robot', not accepted, '%d with w != 0' % len(accepted))
    ok = await wait(lambda: A.control().get('owner') == 'idle', 2.5)
    r.check('manual ownership lapses about 1 s after the last input', ok)

    # --- 3 brain drive, conflicts, then the controlling console disconnects
    await A.send(t='brain', mode='shadow')
    await asyncio.sleep(1.5)
    t0 = time.time()
    await A.send(t='brain', mode='drive')
    ok = await wait(lambda: A.control().get('owner') == 'brain', 3)
    r.check('brain drive takes the brain owner', ok, A.control().get('reason', ''))
    ok = await wait(lambda: any(o['op'] == 'cmd' and o['accepted'] for o in r.ops_since(t0)), 4)
    r.check('stub brain intents reach the robot in brain drive', ok)
    await A.send(t='posture', stand=False)
    await B.send(t='posture', stand=False)
    await asyncio.sleep(0.4)
    r.check('posture refused during brain drive (A: brain active, B: observer)',
            A.saw('brain is active', t0) and B.saw('holds control', t0) and A.control().get('owner') == 'brain')
    t_drop = time.time()
    await A.close()
    ok = await wait(lambda: B.control().get('owner') == 'idle', 2)
    r.check('controlling console lost ends brain drive', ok and (B.status.get('brain') or {}).get('mode') == 'shadow',
            'owner %s, brain %s' % (B.control().get('owner'), (B.status.get('brain') or {}).get('mode')))
    await asyncio.sleep(1.0)
    late = [o for o in r.ops_since(t_drop + 0.5) if o['op'] == 'cmd' and o['accepted'] and (o.get('v') or o.get('w'))]
    r.check('no motion accepted 0.5 s after the console was lost', not late, '%d accepted' % len(late))

    # --- 4 a new console takes over; navigation; brain refused; manual takeover
    A2 = Console('A2')
    await A2.open(http, a.url)
    await asyncio.sleep(1.0)
    t0 = time.time()
    await A2.send(t='brain', mode='drive')
    ok = await wait(lambda: A2.control().get('owner') == 'brain', 3)
    r.check('console B held no control: new console A2 gets brain drive', ok and A2.control().get('controller') == A2.you)
    await B.send(t='stop_motion')
    ok = await wait(lambda: A2.control().get('owner') == 'idle', 2)
    r.check('Stop from observer B ends brain drive', ok)
    pose = ((A2.status.get('slam') or {}).get('pose') or [0, 0, 0, 0])
    await A2.send(t='goal', x=round(pose[0] + 0.8, 2), y=round(pose[1], 2))
    await asyncio.sleep(0.5)
    await A2.send(t='nav', on=True)
    ok = await wait(lambda: A2.control().get('owner') == 'nav', 3)
    r.check('navigation takes the nav owner', ok, A2.control().get('reason', ''))
    t1 = time.time()
    await A2.send(t='brain', mode='drive')
    await asyncio.sleep(0.4)
    r.check('brain drive refused during navigation', (A2.saw('nav is active', t1) or A2.saw('Brain drive refused', t1)) and A2.control().get('owner') == 'nav')
    await hold_manual(A2, 0.0, 0.3, 0.6)
    r.check('manual input takes over from navigation', A2.control().get('owner') == 'manual',
            A2.control().get('reason', ''))
    ok = await wait(lambda: A2.control().get('owner') == 'idle', 2.5)
    r.check('manual lapses to idle; navigation stays cancelled', ok)

    # --- 5 retrace ends brain drive; nothing else commands during it
    await A2.send(t='brain', mode='drive')
    await wait(lambda: A2.control().get('owner') == 'brain', 3)
    t0 = time.time()
    await A2.send(t='retrace')
    ok = await wait(lambda: A2.control().get('owner') == 'retrace', 2)
    r.check('retrace ends brain drive and takes the retrace owner', ok
            and (A2.status.get('brain') or {}).get('mode') == 'shadow')
    await asyncio.sleep(0.5)
    during = [o for o in r.ops_since(t0 + 0.3) if o['op'] == 'cmd' and (o.get('v') or o.get('w'))]
    r.check('no server motion command during the retrace', not during, '%d' % len(during))
    ok = await wait(lambda: A2.control().get('owner') == 'idle', 8)
    r.check('retrace finished releases to idle', ok)

    # --- 6 explicit take-over
    await B.send(t='take_control')
    ok = await wait(lambda: B.control().get('controller') == B.you, 2)
    r.check('B takes control explicitly', ok)
    t0 = time.time()
    await A2.send(t='cmd', v=0.05, w=0.0)
    await asyncio.sleep(0.3)
    r.check('previous controller A2 is now an observer', A2.saw('holds control', t0))

    # --- 7 battery below 15 %: latched halt; motion refused, crouch still allowed; clears when charged
    bat = Path(str(r.ops) + '.battery')
    await B.send(t='brain', mode='drive')
    await wait(lambda: B.control().get('owner') == 'brain', 3)
    t0 = time.time()
    bat.write_text('10')
    ok = await wait(lambda: B.control().get('owner') == 'halt', 3)
    r.check('battery low halts brain drive', ok and (B.status.get('brain') or {}).get('mode') == 'shadow',
            '; '.join(B.control().get('halts') or []))
    await hold_manual(B, 0.05, 0.0, 0.4)
    r.check('manual drive refused while halted', B.saw('motion halted', t0) and B.control().get('owner') == 'halt')
    late = [o for o in r.ops_since(t0 + 0.5) if o['op'] == 'cmd' and o['accepted'] and (o.get('v') or o.get('w'))]
    r.check('no motion accepted during the halt', not late, '%d' % len(late))
    bat.write_text('60')
    ok = await wait(lambda: B.control().get('owner') == 'idle', 3)
    r.check('halt clears when the battery recovers', ok)
    bat.unlink()

    # --- 8 every console gone during navigation: the task continues on the server (by design)
    pose = ((B.status.get('slam') or {}).get('pose') or [0, 0, 0, 0])
    await B.send(t='goal', x=round(pose[0] - 0.8, 2), y=round(pose[1], 2))
    await asyncio.sleep(0.5)
    await B.send(t='nav', on=True)
    nav_ok = await wait(lambda: B.control().get('owner') == 'nav', 3)
    await B.close()
    await A2.close()
    await asyncio.sleep(1.0)
    async with http.get(a.url + '/diagnostics') as resp:
        d = await resp.json()
    owner = ((d.get('status') or {}).get('control') or {}).get('owner')
    r.check('navigation continues with no console connected', nav_ok and owner in ('nav', 'idle')
            and d.get('control_clients') == 0, 'owner %s, nav %s' % (owner, (d.get('navigation') or {}).get('state')))
    B = Console('B2')
    await B.open(http, a.url)
    await asyncio.sleep(1.0)
    await B.send(t='stop_motion')
    await wait(lambda: B.control().get('owner') == 'idle', 3)

    # --- teardown: crouch, chassis off, session end
    t0 = time.time()
    await B.send(t='posture', stand=False)
    took = await wait(lambda: B.control().get('owner') == 'posture', 3)
    ok = await wait(lambda: B.control().get('owner') == 'idle', 6)
    r.check('final crouch confirmed and released', took and ok and 'posture confirmed' in (B.control().get('reason') or ''),
            B.control().get('reason', ''))
    await B.send(t='chassis', on=False)
    await asyncio.sleep(1.0)
    await B.send(t='session', on=False)
    await asyncio.sleep(3.0)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rec = dict(checks=r.checks, passed=sum(c['ok'] for c in r.checks), total=len(r.checks),
               control_history=B.control().get('history'), events=sorted(set(e for c in ALL for e in c.events)))
    (out / 'scenarios.json').write_text(json.dumps(rec, indent=1, ensure_ascii=False))
    print('%d / %d checks passed; record %s' % (rec['passed'], rec['total'], out / 'scenarios.json'))
    await B.close()
    await http.close()
    return rec['passed'] == rec['total']


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--url', default='http://127.0.0.1:18091')
    ap.add_argument('--ops', required=True, help='the fake bridge --log file')
    ap.add_argument('--out', required=True)
    raise SystemExit(0 if asyncio.run(main(ap.parse_args())) else 1)

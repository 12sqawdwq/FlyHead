#!/usr/bin/env python3
"""Drive one supervised whole-route tour through the compute API (port 8091).

The tool only talks to the compute API: it starts the chassis, keeps or reaches
the requested posture, starts the whole-route tour, then watches the run until it
arrives, stops or breaks one of the limits below.  Status comes from /diagnostics;
each command opens a short /ws connection (a long-lived one that is never read misses
the server's heartbeat and is dropped).  The server's navigator and command lease stay
in charge of the motion.

    python3 tools/auto_tour.py --api http://127.0.0.1:8091 --v 0.30 --w 0.45

Limits (all of them stop the run and print why):
  --max-minutes        total wall clock
  --no-progress-minutes  no route progress
  --guard-minutes      chassis guard continuously reporting blocked or latched
  --battery-floor      battery percentage
  --battery-start      refuse to start below this percentage

Receipts: <logs>/auto_tour_<timestamp>.json (summary) and .jsonl (samples).
Nothing is started when a preflight check fails.
"""
import argparse
import asyncio
import json
from pathlib import Path
import time
import urllib.request

import aiohttp

DEFAULT_LOGS = Path(__file__).resolve().parents[1] / 'logs'


def diagnostics(api):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(api + '/diagnostics', timeout=8) as response:
        return json.load(response)


def robot(state):
    return state['status'].get('robot') or {}


def navigation(state):
    return state.get('navigation') or {}


def slam(state):
    return state['status'].get('slam') or {}


def battery(state):
    return (robot(state).get('battery') or {}).get('pct')


async def send(api, *messages):
    """Send control messages over a short-lived /ws connection."""
    async with aiohttp.ClientSession(trust_env=False) as client:
        async with client.ws_connect(api.replace('http', 'ws', 1) + '/ws') as ws:
            await ws.receive(timeout=5)          # hello
            for message in messages:
                await ws.send_json(message)
            await asyncio.sleep(0.2)


def guard_clear(state):
    """Only the guard reporting live is required: it is report-only, the host layer and
    its live obstacle layer hold the avoidance authority."""
    guard = robot(state).get('safety') or {}
    return bool(guard.get('fresh'))


class Runner:
    def __init__(self, args):
        self.args = args
        stamp = time.strftime('%Y%m%dT%H%M%S')
        self.summary_path = Path(args.logs) / ('auto_tour_%s.json' % stamp)
        self.samples_path = Path(args.logs) / ('auto_tour_%s.jsonl' % stamp)
        self.result = dict(started_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'), v=args.v, w=args.w,
                           outcome=None, abort=None, progress_m=None, planned_m=None, elapsed_s=None)
        self.progress = None
        self.planned = None
        self.samples = 0

    def record(self, item):
        with self.samples_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(item, ensure_ascii=False) + '\n')
        print(json.dumps(item, ensure_ascii=False), flush=True)

    async def wait_for(self, predicate, seconds, description, poll=0.5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            await asyncio.sleep(poll)
            state = await asyncio.get_running_loop().run_in_executor(None, diagnostics, self.args.api)
            if predicate(state):
                return state
        raise RuntimeError('timeout waiting for ' + description)

    async def run(self):
        args = self.args
        state = await asyncio.get_running_loop().run_in_executor(None, diagnostics, args.api)
        preflight = dict(session_running=state['session_running'], run=state['status'].get('run'),
                         lidar=robot(state).get('lidar_running'), chassis=robot(state).get('chassis_running'),
                         chassis_disabled=robot(state).get('chassis_disabled'),
                         nav_active=navigation(state).get('active'), cmd=state['status'].get('cmd'),
                         fault=state['pipeline'].get('fault'),
                         clock_ready=(state['transport_contract'].get('remote_clock') or {}).get('ready'),
                         slam_attached=slam(state).get('attached'), fitness=slam(state).get('fitness'))
        self.result['preflight'] = preflight
        self.record(dict(event='preflight', **preflight))
        assert preflight['session_running'], 'no active session'
        assert preflight['lidar'], 'lidar is not running'
        assert preflight['chassis_disabled'] is False, 'chassis interface is locked'
        assert preflight['clock_ready'], 'robot clock is not ready'
        assert preflight['fault'] is None, 'pipeline fault is latched'
        assert not preflight['nav_active'], 'navigation is already active'
        assert preflight['cmd'] == [0, 0], 'unexpected command is active'
        assert preflight['slam_attached'], 'slam is not attached to the base map'
        assert (preflight['fitness'] or 0) >= args.min_fitness, 'map fitness below %.2f' % args.min_fitness

        await send(args.api, {'t': 'chassis', 'on': True})
        await self.wait_for(lambda s: robot(s).get('chassis_running'), 40, 'chassis start')
        await self.wait_for(lambda s: (robot(s).get('body') or {}).get('age', 9) < 0.5
                            and battery(s) is not None, 40, 'chassis telemetry')
        await self.wait_for(guard_clear, args.guard_start_seconds, 'clear obstacle guard')
        state = await asyncio.get_running_loop().run_in_executor(None, diagnostics, args.api)
        assert (battery(state) or 0) >= args.battery_start, 'battery below %d%%' % args.battery_start
        posture = 3 if args.posture == 'stand' else 2
        if (robot(state).get('body') or {}).get('robot_mode') != posture:
            await send(args.api, {'t': 'posture', 'stand': posture == 3})
            await self.wait_for(lambda s: (robot(s).get('body') or {}).get('robot_mode') == posture
                                and (robot(s).get('posture_result') or {}).get('state') == 'confirmed',
                                args.posture_seconds, 'posture confirmation')
        self.record(dict(event='ready', battery=battery(state),
                         guard=(robot(state).get('safety') or {}),
                         body=robot(state).get('body')))
        await send(args.api, {'t': 'tour', 'v': args.v, 'w': args.w})
        state = await self.wait_for(lambda s: navigation(s).get('active'), args.plan_seconds,
                                    'tour start (route planning)')
        self.planned = navigation(state).get('tour_length_m')
        self.record(dict(event='tour_started', planned_m=self.planned, v=args.v, w=args.w))
        await self.monitor()

    async def monitor(self):
        args = self.args
        started = time.monotonic()
        progress_at = started
        latched_since = None
        while True:
            await asyncio.sleep(args.poll)
            state = await asyncio.get_running_loop().run_in_executor(None, diagnostics, args.api)
            now = time.monotonic()
            elapsed = now - started
            nav = navigation(state)
            guard = robot(state).get('safety') or {}
            progress = nav.get('tour_progress_m')
            self.samples += 1
            if progress is not None and (self.progress is None or progress > self.progress + 0.05):
                self.progress = progress
                progress_at = now
            if guard.get('latched') or guard.get('blocked'):
                latched_since = latched_since or now
            else:
                latched_since = None
            if self.samples % 5 == 1:
                self.record(dict(event='sample', t=round(elapsed, 1), active=nav.get('active'),
                                 state=nav.get('state'), reason=nav.get('reason'), progress_m=progress,
                                 planned_m=nav.get('tour_length_m'), fitness=nav.get('fitness'),
                                 battery=battery(state), cmd=state['status'].get('cmd'),
                                 guard_blocked=guard.get('blocked'), guard_latched=guard.get('latched'),
                                 detour_count=nav.get('detour_count'), detour_reason=nav.get('detour_reason')))
            failure = None
            if state['pipeline'].get('fault'):
                failure = 'pipeline fault: %s' % state['pipeline']['fault']
            elif (battery(state) or 100) < args.battery_floor:
                failure = 'battery %.0f%% below floor %.0f%%' % (battery(state), args.battery_floor)
            elif latched_since is not None and now - latched_since > args.guard_minutes * 60.0:
                failure = 'obstacle guard held for %.0f s' % (now - latched_since)
            elif now - progress_at > args.no_progress_minutes * 60.0:
                failure = 'no progress for %.0f s' % (now - progress_at)
            elif elapsed > args.max_minutes * 60.0:
                failure = 'time limit %.0f min' % args.max_minutes
            if failure:
                self.result['abort'] = failure
                self.record(dict(event='abort', reason=failure, progress_m=self.progress,
                                 elapsed_s=round(elapsed, 1)))
                await send(args.api, {'t': 'nav', 'on': False}, {'t': 'stop_motion'})
                await asyncio.sleep(3)
                self.result['outcome'] = 'aborted'
                break
            if not nav.get('active'):
                arrived = nav.get('state') == 'arrived'
                self.result['outcome'] = 'arrived' if arrived else 'stopped'
                if not arrived:
                    self.result['abort'] = nav.get('reason')
                self.record(dict(event='finished', arrived=arrived, reason=nav.get('reason'),
                                 progress_m=self.progress, elapsed_s=round(elapsed, 1)))
                await send(args.api, {'t': 'stop_motion'})
                break
        self.result['progress_m'] = self.progress
        self.result['planned_m'] = self.planned
        self.result['elapsed_s'] = round(time.monotonic() - started, 1)
        self.result['samples'] = self.samples
        self.summary_path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('SUMMARY', self.summary_path, json.dumps(
            {k: self.result[k] for k in ('outcome', 'abort', 'progress_m', 'planned_m', 'elapsed_s')},
            ensure_ascii=False), flush=True)


def stop_everything(api):
    """Best effort: stop the task and the motion after any failure."""
    try:
        asyncio.run(send(api, {'t': 'nav', 'on': False}, {'t': 'stop_motion'}))
    except Exception as error:
        print('stop after failure did not reach the server:', repr(error), flush=True)


def main():
    parser = argparse.ArgumentParser(description='Supervised automatic whole-route tour.')
    parser.add_argument('--api', default='http://127.0.0.1:8091')
    parser.add_argument('--logs', default=str(DEFAULT_LOGS))
    parser.add_argument('--v', type=float, default=0.30, help='route speed limit m/s')
    parser.add_argument('--w', type=float, default=0.45, help='hard-turn angular limit rad/s')
    parser.add_argument('--posture', choices=('stand', 'crouch'), default='stand')
    parser.add_argument('--min-fitness', type=float, default=0.6)
    parser.add_argument('--battery-start', type=float, default=35.0)
    parser.add_argument('--battery-floor', type=float, default=26.0)
    parser.add_argument('--max-minutes', type=float, default=90.0)
    parser.add_argument('--no-progress-minutes', type=float, default=4.0)
    parser.add_argument('--guard-minutes', type=float, default=1.0)
    parser.add_argument('--guard-start-seconds', type=float, default=60.0,
                        help='wait this long for fresh guard telemetry after the chassis starts')
    parser.add_argument('--plan-seconds', type=float, default=120.0)
    parser.add_argument('--posture-seconds', type=float, default=40.0)
    parser.add_argument('--poll', type=float, default=2.0)
    args = parser.parse_args()
    runner = Runner(args)
    try:
        asyncio.run(runner.run())
    except Exception as error:
        stop_everything(args.api)
        runner.result['outcome'] = 'error'
        runner.result['abort'] = repr(error)
        runner.summary_path.write_text(json.dumps(runner.result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('FAILED', repr(error), flush=True)
        raise SystemExit(2)


if __name__ == '__main__':
    main()

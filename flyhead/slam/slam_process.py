"""Process boundary for SLAM. The child never owns a robot/control connection.

One in-flight RPC is allowed. The caller is the existing latest-scan worker,
not the asyncio thread. Small status/display snapshots are cached in the parent;
map exports are explicit executor operations. Spawn avoids forking native pools.
"""
import multiprocessing as mp
import os
import threading
import time
import traceback
from pathlib import Path


from . import reloc as RL
from . import lidar_slam as SL

STATE_FIELDS = (
    'frames', 'frame_stamp', 'proc_ms', 'stage_ms', 'pending_dropped',
    'input_received_at', 'processing_started_at', 'attached', 'last_error',
    'mode', 'fitness',
)
RPC_TIMEOUT_S = 180.0


def _worker(connection, stop_event, output, base_path, masks, mode):
    engine = None
    try:
        # Leave at least one available CPU outside the native compute pool.
        # No realtime priority, system-wide setting, or other project's affinity.
        if hasattr(os, 'sched_getaffinity'):
            available = sorted(os.sched_getaffinity(0))
            if len(available) >= 4:
                os.sched_setaffinity(0, available[1:])
        if hasattr(os, 'nice'):
            os.nice(5)
        base = None if base_path is None else RL.BaseMap(RL.load_points(base_path))
        engine = SL.SlamEngine(Path(output), base=base, stop_event=stop_event)
        if masks is not None:
            engine.self_masks = masks
        engine.mode = mode
        captured = [None]

        def on_frame(*values):
            captured[0] = values

        engine.on_frame = on_frame

        def snapshot():
            values = {name: getattr(engine, name) for name in STATE_FIELDS}
            values.update(pending=bool(engine.pending), summary=engine.summary())
            return values

        connection.send(('ready', snapshot(), os.getpid()))
        while True:
            operation, argument = connection.recv()
            started = time.monotonic()
            try:
                if operation == 'shutdown':
                    break
                if operation == 'input':
                    if stop_event.is_set():
                        raise RuntimeError('SLAM engine is closed')
                    samples, batch, received_at, mode = argument
                    engine.mode = mode
                    captured[0] = None
                    engine.add_imu(samples, process_pending=batch is None)
                    if batch is not None:
                        engine.input_received_at = received_at
                        engine.acc = []
                        for stamp, points in batch:
                            engine.add_cloud(stamp, points)
                    result = dict(state=snapshot(), frame=captured[0],
                                  pose=engine.take_pose(), reset=engine.take_reset())
                elif operation == 'reloc_hint':
                    engine.set_reloc_hint(*argument)
                    result = None
                elif operation == 'masks':
                    result = engine.self_masks
                elif operation == 'save':
                    result = engine.save(output=argument[0], frozen_summary=argument[1])
                else:
                    raise ValueError('Unknown SLAM operation: %s' % operation)
                connection.send(('ok', result, time.monotonic() - started))
            except Exception:
                connection.send(('error', traceback.format_exc(), time.monotonic() - started))
    except EOFError:
        pass
    except Exception:
        try:
            connection.send(('fatal', traceback.format_exc(), 0.0))
        except (BrokenPipeError, OSError):
            pass
    finally:
        if engine is not None:
            engine.close()
        connection.close()


class SlamProcess:
    """Cached parent facade; construction and RPCs belong off the event loop."""

    def __init__(self, out_dir, base=None, base_path=None, masks=None, mode='crouch'):
        self.out = Path(out_dir)
        self.base = base
        self.on_frame = None
        self.mode = mode
        self.last_error = None
        self.closed = False
        self.disposed = False
        self.saved_output = None
        self.pose = None
        self.reset_view = False
        self.rpc_wall_ms = 0.0
        self.worker_wall_ms = 0.0
        self.lock = threading.Lock()
        self.rpc_lock = threading.Lock()
        self.context = mp.get_context('spawn')
        self.stop_event = self.context.Event()
        self.connection, child = self.context.Pipe()
        self.process = self.context.Process(
            target=_worker,
            args=(child, self.stop_event, str(self.out), base_path, masks, mode),
            name='slam-compute', daemon=True,
        )
        self.process.start()
        child.close()
        try:
            kind, state, self.worker_pid = self._receive()
            if kind != 'ready':
                raise RuntimeError(state)
            self._install(state)
        except Exception:
            self.process.terminate()
            self.process.join(timeout=5)
            self.connection.close()
            raise

    def _receive(self):
        deadline = time.monotonic() + RPC_TIMEOUT_S
        while not self.connection.poll(0.2):
            if not self.process.is_alive():
                raise RuntimeError('SLAM process exited: %s' % self.process.exitcode)
            if time.monotonic() >= deadline:
                # Protocol cannot safely resume after an unanswered operation.
                self.stop_event.set()
                self.process.terminate()
                raise TimeoutError('SLAM process RPC timeout; raw recording remains authoritative')
        return self.connection.recv()

    def _request(self, operation, argument=None):
        with self.rpc_lock:
            if self.disposed:
                raise RuntimeError('SLAM process has been disposed')
            started = time.monotonic()
            self.connection.send((operation, argument))
            kind, result, duration = self._receive()
            self.rpc_wall_ms = (time.monotonic() - started) * 1000
            self.worker_wall_ms = duration * 1000
            if kind != 'ok':
                self.last_error = str(result)
                raise RuntimeError(result)
            return result

    def _install(self, state):
        summary = state.pop('summary')
        self.__dict__.update(state)
        self._summary = summary

    def process_input(self, samples, batch, received_at):
        if self.closed:
            return
        result = self._request('input', (samples, batch, received_at, self.mode))
        if self.closed:
            return
        self._install(result['state'])
        with self.lock:
            if result['pose'] is not None:
                self.pose = result['pose']
            self.reset_view = self.reset_view or result['reset']
        if result['frame'] is not None and self.on_frame is not None:
            self.on_frame(*result['frame'])

    def set_reloc_hint(self, x, y, yaw=None):
        return self._request('reloc_hint', (x, y, yaw))

    def recovery_masks(self):
        return self._request('masks')

    def close(self):
        # Nonblocking, including when a native registration is still in flight.
        self.closed = True
        self.stop_event.set()

    def dispose(self):
        self.close()
        with self.rpc_lock:
            if self.disposed:
                return
            try:
                if self.process.is_alive():
                    self.connection.send(('shutdown', None))
                    self.process.join(timeout=5)
                if self.process.is_alive():
                    self.process.terminate()
                    self.process.join(timeout=5)
            finally:
                self.connection.close()
                self.disposed = True

    def summary(self):
        return dict(self._summary, error=self.last_error,
                    compute_process=dict(pid=self.worker_pid, alive=self.process.is_alive(),
                                         rpc_ms=self.rpc_wall_ms, worker_ms=self.worker_wall_ms))

    def take_reset(self):
        with self.lock:
            reset, self.reset_view = self.reset_view, False
        return reset

    def take_pose(self):
        with self.lock:
            pose, self.pose = self.pose, None
        return pose

    def save(self, output=None, wait_until_idle=None, frozen_summary=None):
        if wait_until_idle is not None:
            wait_until_idle()
        if self.disposed:
            if self.saved_output is None:
                raise RuntimeError('No saved SLAM archive')
            return str(self.saved_output)
        result = self._request('save', (None if output is None else str(output), frozen_summary))
        self.saved_output = Path(result)
        return result

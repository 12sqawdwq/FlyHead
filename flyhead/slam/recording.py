"""Bounded, ordered raw recording without disk writes in the asyncio thread."""
import json
import shutil
import threading
import time
from collections import deque
from pathlib import Path


class RawRecorder:
    """Never silently discard accepted records. Overflow latches an explicit fault.

    tell() is the accepted logical offset, not a durability acknowledgement.
    close() drains accepted records and writes a completion manifest. A faulted
    recording is an incomplete prefix and must not be advertised as lossless.
    """

    def __init__(self, path, capacity_bytes=16 * 1024 * 1024, reserve_bytes=64 * 1024 * 1024):
        self.path = Path(path).resolve()
        self.capacity = capacity_bytes
        self.reserve_bytes = reserve_bytes
        self.disk_free_bytes = shutil.disk_usage(self.path.parent).free
        if self.disk_free_bytes < reserve_bytes + capacity_bytes:
            raise OSError('Insufficient recording space: %d free; %d reserved including queue' % (
                self.disk_free_bytes, reserve_bytes + capacity_bytes))
        self.condition = threading.Condition()
        self.records = deque()
        self.queued_bytes = 0
        self.accepted_bytes = 0
        self.written_bytes = 0
        self.high_water_bytes = 0
        self.error = None
        self.closing = False
        self.started_at = time.time()
        # Open failures propagate before the robot bridge is launched.
        self.stream = self.path.open('xb', buffering=1024 * 1024)
        self.thread = threading.Thread(target=self._run, name='raw-recorder', daemon=True)
        self.thread.start()

    def write(self, record):
        with self.condition:
            if self.error is not None or self.closing:
                return False
            if self.queued_bytes + len(record) > self.capacity:
                self.error = 'Raw recording backlog exceeded %d bytes' % self.capacity
                return False
            self.records.append(record)
            self.queued_bytes += len(record)
            self.accepted_bytes += len(record)
            self.high_water_bytes = max(self.high_water_bytes, self.queued_bytes)
            self.condition.notify()
        return True

    def tell(self):
        return self.accepted_bytes

    def status(self):
        with self.condition:
            return dict(path=str(self.path), queued_bytes=self.queued_bytes,
                        accepted_bytes=self.accepted_bytes, written_bytes=self.written_bytes,
                        high_water_bytes=self.high_water_bytes, capacity_bytes=self.capacity,
                        disk_free_bytes=self.disk_free_bytes, reserve_bytes=self.reserve_bytes,
                        error=self.error, closing=self.closing, writer_alive=self.thread.is_alive())

    def _run(self):
        try:
            while True:
                with self.condition:
                    while not self.records and not self.closing:
                        self.condition.wait()
                    if not self.records:
                        break
                    record = self.records.popleft()
                # Check on the writer, never in the event loop. Reserve space for
                # filesystem operation and session archives rather than filling /.
                self.disk_free_bytes = shutil.disk_usage(self.path.parent).free
                if self.disk_free_bytes < self.reserve_bytes + len(record):
                    raise OSError('Recording stopped before disk reserve was consumed')
                # Keep the in-flight record charged against capacity until written.
                self.stream.write(record)
                with self.condition:
                    self.written_bytes += len(record)
                    self.queued_bytes -= len(record)
            self.stream.flush()
        except Exception as error:
            with self.condition:
                self.error = 'Raw recording failed: %r' % error
        finally:
            try:
                self.stream.close()
            except Exception as error:
                with self.condition:
                    self.error = 'Raw recording close failed: %r' % error

    def close(self):
        with self.condition:
            self.closing = True
            self.condition.notify_all()
        self.thread.join(timeout=30)
        if self.thread.is_alive():
            raise TimeoutError('Raw recorder still draining: %s' % self.path)
        state = self.status()
        state.update(started_at=self.started_at, closed_at=time.time(),
                     complete=self.error is None and self.written_bytes == self.accepted_bytes,
                     durable_fsync=False)
        self.path.with_suffix('.recording.json').write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

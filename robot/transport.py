"""Bounded bridge output scheduling. Never wait for a pipe in a ROS callback."""
import struct
import threading
import time
from collections import deque


class FrameMailbox:
    def __init__(self):
        self.condition = threading.Condition()
        self.events = deque()
        self.status = None
        self.camera = None
        self.sensors = {1: deque(), 2: deque()}
        self.limits = {1: 8, 2: 512}
        self.dropped = {1: 0, 2: 0, 3: 0, 4: 0}
        self.high_water = {1: 0, 2: 0}
        self.closed = False

    def put(self, kind, payload, latest_status=False):
        item = (time.monotonic(), b'XT' + struct.pack('<BI', kind, len(payload)) + payload)
        with self.condition:
            if self.closed:
                return
            if kind in self.sensors:
                entries = self.sensors[kind]
                if len(entries) >= self.limits[kind]:
                    entries.popleft()
                    self.dropped[kind] += 1
                entries.append(item)
                self.high_water[kind] = max(self.high_water[kind], len(entries))
            elif kind == 4:
                if self.camera is not None:
                    self.dropped[4] += 1
                self.camera = item
            elif latest_status:
                if self.status is not None:
                    self.dropped[3] += 1
                self.status = item
            else:
                if len(self.events) >= 64:
                    self.events.popleft()
                    self.dropped[3] += 1
                self.events.append(item)
            self.condition.notify()

    def get(self, wait=True):
        with self.condition:
            while True:
                now = time.monotonic()
                for kind, entries in self.sensors.items():
                    while entries and now - entries[0][0] > 0.75:
                        entries.popleft()
                        self.dropped[kind] += 1
                if self.status is not None:
                    item, self.status = self.status, None
                    return item[1]
                if self.events:
                    return self.events.popleft()[1]
                available = [(entries[0][0], kind) for kind, entries in self.sensors.items() if entries]
                if available:
                    _, kind = min(available)
                    return self.sensors[kind].popleft()[1]
                if self.camera is not None:
                    item, self.camera = self.camera, None
                    if now - item[0] <= 0.75:
                        return item[1]
                    self.dropped[4] += 1
                if not wait or self.closed:
                    return None
                self.condition.wait()

    def stats(self):
        with self.condition:
            return dict(queued={str(k): len(q) for k, q in self.sensors.items()},
                        dropped={str(k): n for k, n in self.dropped.items()},
                        high_water={str(k): n for k, n in self.high_water.items()},
                        latest_status=self.status is not None, latest_camera=self.camera is not None)

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()

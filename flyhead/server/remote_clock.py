"""Conservative SSH request/reply clock bounds, not synchronized clock epochs.

Only freshness and command expiry use this mapping. SLAM/IMU integration and
raw recordings keep original robot timestamps. Actuator authorization is
controlled independently of this clock estimator.
"""
import math
import secrets
import time


class RemoteClock:
    MAX_RTT = 0.2
    MAX_AGE = 1.0
    DRIFT_PER_SECOND = 0.002

    def __init__(self):
        self.pending = {}
        self.anchor = None
        self.rejected = 0

    def ping(self):
        token = secrets.token_hex(12)
        self.pending[token] = (time.monotonic(), time.time())
        while len(self.pending) > 16:
            self.pending.pop(next(iter(self.pending)))
        return token

    def accept(self, packet):
        sent = self.pending.pop(packet.get('clock_token'), None)
        if sent is None:
            return False
        received_mono, received_wall = time.monotonic(), time.time()
        robot_mono, robot_wall = packet.get('mono'), packet.get('wall')
        rtt = received_mono - sent[0]
        if (not all(isinstance(value, (int, float)) and math.isfinite(value)
                    for value in (robot_mono, robot_wall))
                or not 0 <= rtt <= self.MAX_RTT
                or abs((received_wall - sent[1]) - rtt) > 0.02):
            self.rejected += 1
            return False
        self.anchor = dict(sent_mono=sent[0], sent_wall=sent[1],
                           received_mono=received_mono, received_wall=received_wall,
                           robot_mono=robot_mono, robot_wall=robot_wall, rtt_s=rtt)
        return True

    def age(self):
        if self.anchor is None:
            return float('inf')
        return time.monotonic() - self.anchor['received_mono']

    def ready(self):
        if self.anchor is None or not 0 <= self.age() <= self.MAX_AGE:
            return False
        wall_elapsed = time.time() - self.anchor['received_wall']
        return abs(wall_elapsed - self.age()) <= 0.02

    def margin(self):
        return 0.005 + self.DRIFT_PER_SECOND * max(0.0, self.age())

    def deadline(self, local_deadline):
        if not self.ready():
            return None
        # The pong must have been emitted before it was received. Subtracting
        # the full return delay rather than half an RTT cannot renew a lease.
        return (self.anchor['robot_mono'] + local_deadline
                - self.anchor['received_mono'] - self.margin())

    def source_time(self, robot_stamp):
        if robot_stamp is None or not self.ready():
            return None
        # Request send time is before the robot samples its wall clock. This
        # lower-bound mapping makes evidence older, never younger due to RTT.
        return (robot_stamp + self.anchor['sent_wall']
                - self.anchor['robot_wall'] - self.margin())

    def status(self):
        return dict(ready=self.ready(), age_s=None if self.anchor is None else self.age(),
                    rejected=self.rejected, anchor=self.anchor,
                    max_rtt_s=self.MAX_RTT, max_age_s=self.MAX_AGE,
                    drift_assumption_s_per_s=self.DRIFT_PER_SECOND,
                    clock_only_not_actuator_authorization=True)

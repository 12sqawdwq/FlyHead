"""Reader for raw.xt session recordings, shared by replay and the offline tools.

Every record is the robot bridge frame (see robot/bridge.py) prefixed with the
server receive time:

    f64 receive wall time | b'XT' | u8 kind | u32 payload length | payload

Payloads by kind:
    1 CLOUD  f64 stamp, u32 n, n * (x, y, z, intensity, time) float32
    2 IMU    f64 stamp, 10 float32 (qx, qy, qz, qw, gx, gy, gz, ax, ay, az)
    3 JSON   UTF-8 status / event object
    4 JPEG   f64 stamp, JPEG bytes
"""
import struct

import numpy as np

CLOUD, IMU, JSON, JPEG = 1, 2, 3, 4
RECORD_HEADER = struct.Struct('<d2sBI')   # 15 bytes
IMU_RECORD = struct.Struct('<d10f')


def read_records(path):
    """Yield (receive_wall_time, kind, payload); stop at EOF or a truncated record."""
    with open(path, 'rb') as stream:
        while True:
            header = stream.read(RECORD_HEADER.size)
            if len(header) < RECORD_HEADER.size:
                return
            wall, _, kind, length = RECORD_HEADER.unpack(header)
            payload = stream.read(length)
            if len(payload) < length:
                return
            yield wall, kind, payload


def decode_cloud(payload):
    """Return (stamp, points[n, 5]) for a CLOUD payload."""
    stamp, count = struct.unpack('<dI', payload[:12])
    return stamp, np.frombuffer(payload, '<f4', offset=12, count=count * 5).reshape(count, 5)


def decode_imu(payload):
    """Return the 11-tuple (stamp, qx, qy, qz, qw, gx, gy, gz, ax, ay, az)."""
    return IMU_RECORD.unpack(payload)

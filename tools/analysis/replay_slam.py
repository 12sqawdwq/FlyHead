#!/usr/bin/env python3
"""Re-run the SLAM engine on a recorded raw.xt as fast as possible.

  venv/bin/python server/offline.py runs/<id>/raw.xt runs/<id>_offline
"""
import struct
import time
import sys
from pathlib import Path

import numpy as np

from flyhead.slam import lidar_slam as S


def frames(path):
    with open(path, 'rb') as f:
        while True:
            r = f.read(15)
            if len(r) < 15:
                return
            kind, n = struct.unpack('<BI', r[10:15])
            yield kind, f.read(n)


def main(raw, out, base=None):
    from flyhead.slam import reloc as RL
    e = S.SlamEngine(Path(out), base=RL.BaseMap(RL.load_points(base)) if base else None)
    imus = []
    for kind, p in frames(raw):
        if kind == 2:
            imus.append(struct.unpack('<d10f', p))
            if len(imus) >= 25:
                e.add_imu(imus)
                imus = []
        elif kind == 1:
            stamp, n = struct.unpack('<dI', p[:12])
            e.add_cloud(stamp, np.frombuffer(p, '<f4', offset=12, count=n * 5).reshape(n, 5))
            if base and not e.attached:
                time.sleep(0.12)        # real-time pace until relocalised
    e.close()
    e.save()
    print(e.summary())


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)

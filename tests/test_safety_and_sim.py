"""Safety envelope, map layers and the synthetic arena (no GPU, no robot)."""
import numpy as np

from flyhead.safety.envelope import BODY_R, limit
from flyhead.slam.navmap import NavMap


def test_envelope_stops_toward_close_obstacle():
    wall = np.c_[np.full(30, BODY_R + 0.05), np.linspace(-0.3, 0.3, 30)]
    v, w, why = limit(wall, 0.2, 0.0)
    assert v == 0.0 and why
    v_back, _, _ = limit(wall, -0.1, 0.0)                 # moving away is still allowed
    assert v_back < 0.0


def test_envelope_never_adds_motion():
    rng = np.random.default_rng(0)
    for _ in range(200):
        pts = rng.uniform(-3, 3, size=(50, 2))
        v, w = rng.uniform(-0.3, 0.3), rng.uniform(-1, 1)
        v2, w2, _ = limit(pts, v, w)
        assert abs(v2) <= abs(v) + 1e-12 and abs(w2) <= abs(w) + 1e-12
        assert v2 == 0.0 or np.sign(v2) == np.sign(v)


def test_synthetic_arena(tmp_path):
    from flyhead.sim.synthetic_map import write
    nm = NavMap(str(write(tmp_path / 'arena')))
    clear = nm.clearance_for(0.32)
    i, j = nm.to_ij(np.array([7.0, -1.1]))
    assert clear[i, j] >= 2.0                              # roam_open start has room, as designed
    i, j = nm.to_ij(np.array([5.6, 6.45]))
    assert clear[i, j] >= 1.0
    # the navigator needs the floor layer for the LiDAR height; without it brain_link drops every scan
    assert np.isfinite(nm.floor_at(np.array([[7.0, -1.1]]))[0])
    assert np.array_equal(nm.blocked_for(0.32), nm.static == 0)    # height layers block what the grid blocks

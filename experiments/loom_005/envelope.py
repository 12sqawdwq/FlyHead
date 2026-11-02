"""Safety envelope for brain mode: may only reduce or zero the brain's command, never add motion.

The body disc (radius BODY_R about the turning point) is swept along the commanded arc (v, w)
for up to SWEEP_M of travel, forward or backward with the sign of v. The free travel before it
touches a return sets the allowed speed with the host chain's stop rule
(v * REACT_S + v^2 / (2 * BRAKE_DECEL) + STOP_MARGIN_M <= free). A return within BACKSTOP_M of
the body edge stops all motion toward it; turning in place is allowed only if no return is
inside the disc swept by the rotation (BODY_R + ROTATE_MARGIN_M).
Points: (N, 2) body frame (x forward, y left) relative to the turning point.
"""
import math

import numpy as np

BODY_R = 0.35
SWEEP_M = 2.5
STEP_M = 0.05
REACT_S = 0.6
BRAKE_DECEL = 0.20
STOP_MARGIN_M = 0.15
BACKSTOP_M = 0.10
ROTATE_MARGIN_M = 0.05
MIN_SPEED = 0.03          # below this the cap is a stop


def stop_speed(free_m):
    free_m -= STOP_MARGIN_M
    if free_m <= 0:
        return 0.0
    a, b = 1.0 / (2.0 * BRAKE_DECEL), REACT_S
    return (-b + math.sqrt(b * b + 4.0 * a * free_m)) / (2.0 * a)


def free_travel(points, v, w):
    """Travel (m) along the arc of (v, w) before the body disc touches a return."""
    if len(points) == 0:
        return SWEEP_M
    direction = 1.0 if v >= 0 else -1.0
    kappa = 0.0 if abs(v) < 1e-6 else w / abs(v)            # curvature of the path (1/m)
    near = points[np.hypot(points[:, 0], points[:, 1]) < SWEEP_M + BODY_R + 0.5]
    if len(near) == 0:
        return SWEEP_M
    for s in np.arange(STEP_M, SWEEP_M + 1e-9, STEP_M):
        if abs(kappa) < 1e-6:
            cx, cy, th = direction * s, 0.0, 0.0
        else:
            th = kappa * s
            cx = direction * math.sin(th) / kappa
            cy = (1 - math.cos(th)) / kappa
        d = np.hypot(near[:, 0] - cx, near[:, 1] - cy)
        if (d < BODY_R).any():
            return float(s - STEP_M)
    return SWEEP_M


def limit(points, v, w):
    """(v, w) after the envelope, and the reason when it changed the command."""
    r = np.hypot(points[:, 0], points[:, 1]) if len(points) else np.zeros(0)
    edge = r - BODY_R
    if v != 0.0:
        ahead = points[:, 0] * (1.0 if v > 0 else -1.0) > 0 if len(points) else np.zeros(0, bool)
        if len(points) and ((edge < BACKSTOP_M) & ahead).any():
            v_new, why = 0.0, 'backstop'
        else:
            free = free_travel(points, v, w)
            cap = stop_speed(free)
            v_new = math.copysign(min(abs(v), cap), v) if cap >= MIN_SPEED else 0.0
            why = None if v_new == v else 'sweep %.2f m' % free
    else:
        v_new, why = 0.0, None
    w_new = w
    if v_new == 0.0 and w != 0.0 and len(points) and (r < BODY_R + ROTATE_MARGIN_M).any():
        w_new, why = 0.0, (why or '') + ' no room to turn'
    if v_new == 0.0 and v != 0.0 and w_new == w:
        # forward/backward blocked: keep the brain's turn (it may be turning away)
        pass
    return v_new, w_new, why

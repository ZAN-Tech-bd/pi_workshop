"""Module 7 — inverse kinematics for the 4-DOF arm (deck slides 36-38).

The arm in one picture (side view, base at the left):

                 elbow                 L2 = elbow -> gripper
                ●──────gripper
               /
              / L1 = shoulder -> elbow
     base ●──● shoulder pivot, Z_BASE above the table

Given (x, y, z) mm from the base center, solve_ik() returns joint angles:
the base turns to face the point, then shoulder + elbow solve a 2-link
triangle in the vertical plane (the classic "elbow-up" solution).

Measure YOUR arm once, edit the three constants, then verify:
    python3 ik.py        # ik -> fk round-trip must land back on the target
"""

import math

L1 = 100.0      # mm, shoulder pivot -> elbow axis
L2 = 100.0      # mm, elbow axis -> gripper tip
Z_BASE = 60.0   # mm, shoulder pivot height above the table

# Servo conventions (match them to YOUR kit with module 3's calibrate.py):
#   base     : 90 = facing +x direction, 0/180 = facing +-y
#   shoulder : degrees above the horizontal (90 = straight up)
#   elbow    : interior angle (180 = arm straight, 90 = right angle)


def solve_ik(x, y, z):
    """(x, y, z) mm -> (base, shoulder, elbow) degrees, or None if unreachable."""
    r = math.hypot(x, y)                       # horizontal distance from base
    tz = z - Z_BASE                            # target height above the pivot
    d = math.hypot(r, tz)
    if d > L1 + L2 or d < abs(L1 - L2) or r < 1:
        return None                            # out of reach (or dead center)

    base = math.degrees(math.atan2(y, x))
    beta = math.atan2(tz, r)                   # target line above horizontal
    alpha = math.acos((L1 * L1 + d * d - L2 * L2) / (2 * L1 * d))
    omega = math.acos((L1 * L1 + L2 * L2 - d * d) / (2 * L1 * L2))

    return (round(base),
            round(math.degrees(beta + alpha)),   # elbow-up shoulder
            round(math.degrees(omega)))          # interior elbow angle


def fk(base, shoulder, elbow):
    """Forward kinematics — where the gripper ends up. Used by the selftest."""
    phi_s = math.radians(shoulder)
    phi_l = phi_s - math.radians(180 - elbow)  # lower arm, absolute angle
    reach = L1 * math.cos(phi_s) + L2 * math.cos(phi_l)
    height = L1 * math.sin(phi_s) + L2 * math.sin(phi_l) + Z_BASE
    b = math.radians(base)
    return (round(reach * math.cos(b), 1),
            round(reach * math.sin(b), 1),
            round(height, 1))


if __name__ == "__main__":
    print(f"arm model: L1={L1}  L2={L2}  Z_BASE={Z_BASE}  (edit for YOUR kit)\n")
    tol = 2.5      # mm — angle rounding to whole degrees costs ~1-2 mm
    ok = True
    for x, y, z in [(100, 60, 40), (120, -80, 60), (60, 60, 80), (199, 0, 60)]:
        sol = solve_ik(x, y, z)
        if sol is None:
            print(f"({x:3},{y:3},{z:2})  -> UNREACHABLE (unexpected)")
            ok = False
            continue
        back = fk(*sol)
        good = all(abs(b - t) <= tol for b, t in zip(back, (x, y, z)))
        ok &= good
        print(f"({x:3},{y:3},{z:2}) -> J,{sol[0]},{sol[1]},{sol[2]}  "
              f"fk-check {back}  {'OK' if good else 'WRONG'}")

    far = solve_ik(250, 0, 60)                 # clearly beyond L1+L2
    near = solve_ik(0.5, 0, 60)                # r < 1: base angle undefined
    ok &= far is None and near is None
    print(f"out-of-reach  (250,0,60) -> {far}   {'OK' if far is None else 'WRONG'}")
    print(f"singularity   (0.5,0,60) -> {near}  {'OK' if near is None else 'WRONG'}")
    # note: with L1 == L2 the arm can fold fully, so small r IS solvable —
    # keep a keep-out zone around the base in the caller if your arm
    # physically collides when folded.
    print("ik selftest:", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)

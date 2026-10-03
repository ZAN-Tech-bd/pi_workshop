"""Module 8 — the gesture brain: 21 hand landmarks -> one named gesture.

MediaPipe Hands gives 21 landmarks per hand (x, y in 0..1 of the picture, z a
relative depth). This file turns them into a gesture with two kinds of
classifier, scored on ONE scale (0..1, a gesture counts at >= its threshold):

  built-in  plain geometry you can read — which fingers are out, and where the
            index finger or the thumb points. Every condition is a fuzzy truth
            value 0..1; a rule's score is its weakest condition (fuzzy AND).
  taught    your own examples (few-shot learning): the live hand is normalized
            (wrist at 0, palm length 1) and compared with every recorded example
            of the gesture — k nearest neighbours. score 1 = identical,
            0.5 = exactly at the match radius, 0 = twice as far.

Taught gestures are checked first: your examples beat the generic rules.

No mediapipe import here, so this runs (and self-tests) with plain numpy:

    python3 gestures.py --selftest      # 29 labelled hands from fixtures/hands.json
"""

import json
import math
import os
import re

import numpy as np

# landmark indexes (MediaPipe hand model)
WRIST = 0
THUMB = (1, 2, 3, 4)                    # CMC, MCP, IP, TIP
FINGERS = {"index": (5, 6, 7, 8), "middle": (9, 10, 11, 12),
           "ring": (13, 14, 15, 16), "pinky": (17, 18, 19, 20)}
CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
               (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18),
               (18, 19), (19, 20), (0, 17)]

KEYS = {"F": "forward", "B": "backward", "L": "left", "R": "right", "G": "front-left",
        "I": "front-right", "H": "back-left", "J": "back-right", "S": "stop"}
SPEEDS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "q"]       # q = turbo (the firmware's 255)
Z_WEIGHT = 0.5                         # MediaPipe's depth is noisier than x/y: it counts half


def clamp01(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else float(v)


def ramp(v, lo, hi):
    """0 at lo, 1 at hi, linear between (works for hi < lo too)."""
    return clamp01((v - lo) / (hi - lo))


def _angle(u, v):
    c = float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-9))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def heading(vec):
    """Image direction of a 2D vector in degrees, clockwise from straight up."""
    return math.degrees(math.atan2(vec[0], -vec[1])) % 360


# --------------------------------------------------------------------------- one observed hand

class Hand:
    """One detected hand, measured once: finger states, directions, features.

    lm: 21 x [x, y, z] as MediaPipe gives them (0..1), in the DISPLAYED picture
    (already mirrored when the dashboard mirrors). w, h: picture size, so x and
    y get the same units. handed: "Left" / "Right" as seen by the person.
    """

    def __init__(self, lm, w, h, handed="Right"):
        self.lm = np.asarray(lm, float)
        self.handed = handed
        p = self.lm * [w, h, w]                         # isotropic pixels (z uses x's scale)
        self.p = p
        self.palm = float(np.linalg.norm(p[9] - p[0])) or 1e-6   # wrist -> middle knuckle

        ext = {}
        for name, (mcp, pip, dip, tip) in FINGERS.items():
            # a straight finger: tip far beyond the middle knuckle, and little bend
            ratio = np.linalg.norm(p[tip] - p[0]) / (np.linalg.norm(p[pip] - p[0]) + 1e-9)
            bend = _angle(p[pip] - p[mcp], p[dip] - p[pip]) + _angle(p[dip] - p[pip], p[tip] - p[dip])
            ext[name] = 0.5 * ramp(ratio, 1.0, 1.25) + 0.5 * ramp(bend, 100, 40)
        # the thumb is "out" when its tip is clear of every other finger joint
        gap = min(np.linalg.norm(p[4] - p[j]) for j in range(5, 21)) / self.palm
        ext["thumb"] = ramp(gap, 0.40, 0.58)
        self.ext = ext
        self.point_dir = heading(p[8] - p[5])           # index knuckle -> tip
        self.thumb_dir = heading(p[4] - p[2])           # thumb knuckle -> tip
        self.pinch = float(np.linalg.norm(p[4] - p[8]) / self.palm)
        self.feat = features(p)

    def summary(self):
        """What the page draws in the Think panel."""
        e = self.ext
        return {"handed": self.handed,
                "pts": [[round(float(x), 4), round(float(y), 4)] for x, y, _ in self.lm],
                "norm": [[round(float(x), 3), round(float(y), 3)] for x, y, _ in self.feat],
                "fingers": [round(e[k], 2) for k in ("thumb", "index", "middle", "ring", "pinky")],
                "point_dir": round(self.point_dir), "thumb_dir": round(self.thumb_dir)}


def features(p):
    """21 x 3: wrist at the origin, palm length 1, depth at half weight.

    Not rotated: "point left" and "point right" must stay different gestures.
    """
    p = np.asarray(p, float)
    q = (p - p[0]) / (np.linalg.norm(p[9] - p[0]) or 1e-6)
    q[:, 2] *= Z_WEIGHT
    return q


def rms(a, b):
    """Mean landmark distance, in palm lengths (the wrist is 0 in both)."""
    return float(np.sqrt(np.mean(np.sum((a[1:] - b[1:]) ** 2, axis=1))))


# --------------------------------------------------------------------------- built-in rules

def _dir(angle, target, full=15, zero=45):
    d = abs((angle - target + 180) % 360 - 180)        # 0..180 degrees off
    return ramp(d, zero, full) - d / 2000               # 1 within `full`, 0 at `zero`; nearer wins ties


def _up(h, *names):
    return [h.ext[n] for n in names]


def _down(h, *names):
    return [1 - h.ext[n] for n in names]


FOUR = ("index", "middle", "ring", "pinky")


def _point(target):
    return lambda h: min(_up(h, "index") + _down(h, "middle", "ring", "pinky") + [_dir(h.point_dir, target)])


def _thumb(target):   # only 4 thumb directions, so a thumb may lean further (a fist rarely sits straight)
    return lambda h: min(_up(h, "thumb") + _down(h, *FOUR) + [_dir(h.thumb_dir, target, 25, 65)])


# id -> (name, emoji, rule). Directions are on the picture the person sees.
BUILTINS = {
    "open_palm":   ("Open palm", "✋", lambda h: min(_up(h, *FOUR))),
    "fist":        ("Fist", "✊", lambda h: min(_down(h, "thumb", *FOUR))),
    "thumb_up":    ("Thumbs up", "👍", _thumb(0)),
    "thumb_down":  ("Thumbs down", "👎", _thumb(180)),
    "thumb_left":  ("Thumb left", "👈", _thumb(270)),
    "thumb_right": ("Thumb right", "👉", _thumb(90)),
    "point_up":    ("Point up", "☝️", _point(0)),
    "point_up_right":   ("Point up-right", "↗️", _point(45)),
    "point_right": ("Point right", "👉", _point(90)),
    "point_down_right": ("Point down-right", "↘️", _point(135)),
    "point_down":  ("Point down", "👇", _point(180)),
    "point_down_left":  ("Point down-left", "↙️", _point(225)),
    "point_left":  ("Point left", "👈", _point(270)),
    "point_up_left":    ("Point up-left", "↖️", _point(315)),
    "victory":     ("Victory", "✌️", lambda h: min(_up(h, "index", "middle") + _down(h, "ring", "pinky"))),
    "three":       ("Three fingers", "🖖", lambda h: min(_up(h, "index", "middle", "ring") + _down(h, "pinky"))),
    "rock":        ("Rock on", "🤘", lambda h: min(_up(h, "index", "pinky") + _down(h, "thumb", "middle", "ring"))),
    "love_you":    ("Love you", "🤟", lambda h: min(_up(h, "thumb", "index", "pinky") + _down(h, "middle", "ring"))),
    "call_me":     ("Call me", "🤙", lambda h: min(_up(h, "thumb", "pinky") + _down(h, "index", "middle", "ring"))),
    "ok":          ("OK", "👌", lambda h: min(_up(h, "middle", "ring", "pinky") + [ramp(h.pinch, 0.45, 0.25)])),
}


def builtin_scores(hand):
    return {bid: round(max(0.0, rule(hand)), 3) for bid, (_n, _e, rule) in BUILTINS.items()}


# --------------------------------------------------------------------------- taught gestures

def sample_feat(sample, mirror):
    """A stored example as features for the CURRENT mirror setting.

    Examples remember whether the picture was mirrored when they were taken; if
    that changed since, flip them so "point left" still means the person's left.
    """
    f = np.asarray(sample["p"], float).reshape(21, 3)
    hand = sample.get("hand", "Right")
    if bool(sample.get("m", True)) != bool(mirror):
        f = f * [-1, 1, 1]
        hand = {"Left": "Right", "Right": "Left"}.get(hand, hand)
    return f, hand


def make_sample(hand, mirror):
    return {"hand": hand.handed, "m": bool(mirror),
            "p": [round(float(v), 3) for v in hand.feat.reshape(-1)]}


def taught_score(hand, gesture, radius, mirror, k=3):
    """(score, distance, index of the nearest example) — or None without examples."""
    feats = [sample_feat(s, mirror)[0] for s in gesture.get("samples", [])]
    if not feats:
        return None
    d = np.array([rms(hand.feat, f) for f in feats])
    order = np.argsort(d)
    dist = float(np.mean(d[order[:min(k, len(d))]]))     # k nearest: one odd example can't decide
    return clamp01(1 - 0.5 * dist / radius), dist, int(order[0])


# --------------------------------------------------------------------------- the classifier

def hand_ok(g, hand):
    return g.get("hand", "any") == "any" or g["hand"].capitalize() == hand.handed


def classify(cfg, hand):
    """Score every gesture for one hand and pick the winner.

    Returns {"scores": {id: score}, "winner": id or None, "why": text,
             "nearest": {"id", "index", "dist"} for the best taught gesture}.
    """
    scores, nearest = {}, None
    rules = builtin_scores(hand)
    best_taught, best_rule = (None, 0.0), (None, 0.0)
    for g in cfg["gestures"]:
        fits = hand_ok(g, hand)
        if g["kind"] == "builtin":
            s = rules.get(g["rule"], 0.0) if fits else 0.0
            scores[g["id"]] = s
            if g["on"] and s >= cfg["rule_min"] and s > best_rule[1]:
                best_rule = (g["id"], s)
        else:
            r = taught_score(hand, g, cfg["radius"], cfg["mirror"]) if fits else None
            s = r[0] if r else 0.0
            scores[g["id"]] = round(s, 3)
            if r and (nearest is None or r[1] < nearest["dist"]):
                nearest = {"id": g["id"], "index": r[2], "dist": round(r[1], 3)}
            if g["on"] and r and s >= 0.5 and s > best_taught[1]:
                best_taught = (g["id"], s)
    if best_taught[0]:
        return {"scores": scores, "winner": best_taught[0], "why": "taught", "nearest": nearest}
    if best_rule[0]:
        return {"scores": scores, "winner": best_rule[0], "why": "rule", "nearest": nearest}
    return {"scores": scores, "winner": None, "why": "no gesture fits", "nearest": nearest}


# --------------------------------------------------------------------------- config

PALETTE = ["#2fae4e", "#2f6df0", "#e86e4b", "#9b4dff", "#0ea5e9", "#e2557a", "#f2c418", "#ff8a2a",
           "#12a1a1", "#d4372c", "#c2410c", "#4d7c0f"]
DEFAULT_SET = [  # (built-in rule, action) — point where you want to go, palm or fist to stop
    ("thumb_up", {"type": "key", "key": "F"}),
    ("thumb_down", {"type": "key", "key": "B"}),
    ("point_left", {"type": "key", "key": "L"}),
    ("point_right", {"type": "key", "key": "R"}),
    ("open_palm", {"type": "key", "key": "S"}),
    ("fist", {"type": "key", "key": "S"}),
    ("victory", {"type": "step", "d": 1}),
    ("love_you", {"type": "step", "d": -1}),
]


def default_config():
    gestures = [{"id": rule, "name": BUILTINS[rule][0], "kind": "builtin", "rule": rule, "hand": "any",
                 "color": PALETTE[i % len(PALETTE)], "on": True, "action": action}
                for i, (rule, action) in enumerate(DEFAULT_SET)]
    return {"gestures": gestures, "hold": 3, "radius": 0.35, "rule_min": 0.6, "mirror": True,
            "model": 0, "workers": 2, "nothing": {"type": "key", "key": "S"}}


def _num(v, lo, hi, default, cast=float):
    try:
        v = cast(float(v)) if cast is int else float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def clean_action(a, keys_only=False):
    if not isinstance(a, dict):
        return {"type": "key", "key": "S"} if keys_only else {"type": "none"}
    t = a.get("type")
    if t == "key" and a.get("key") in KEYS:
        return {"type": "key", "key": a["key"]}
    if keys_only:
        return {"type": "key", "key": "S"}
    if t == "speed" and str(a.get("n")) in SPEEDS:
        return {"type": "speed", "n": str(a["n"])}
    if t == "step" and a.get("d") in (1, -1, "1", "-1"):
        return {"type": "step", "d": int(a["d"])}
    return {"type": "none"}


def clean_sample(s):
    if not isinstance(s, dict) or not isinstance(s.get("p"), list) or len(s["p"]) != 63:
        return None
    try:
        p = [round(max(-20.0, min(20.0, float(v))), 3) for v in s["p"]]
    except (TypeError, ValueError):
        return None
    return {"hand": "Left" if s.get("hand") == "Left" else "Right", "m": bool(s.get("m", True)), "p": p}


MAX_GESTURES, MAX_SAMPLES = 24, 60


def clean_config(cfg, old=None):
    """Validate a config from the page or the disk.

    Examples are only ever added by recording, so when the page sends a gesture
    without "samples", the ones already stored for that id are kept.
    """
    base = default_config()
    if not isinstance(cfg, dict):
        return base
    kept = {g["id"]: g.get("samples", []) for g in (old or {}).get("gestures", []) if g.get("kind") == "taught"}
    out = {"hold": _num(cfg.get("hold"), 1, 30, base["hold"], int),
           "radius": round(_num(cfg.get("radius"), 0.1, 1.0, base["radius"]), 3),
           "rule_min": round(_num(cfg.get("rule_min"), 0.5, 0.95, base["rule_min"]), 3),
           "mirror": bool(cfg.get("mirror", True)),
           "model": 1 if cfg.get("model") in (1, "1") else 0,
           "workers": 1 if cfg.get("workers") in (1, "1") else 2,     # MediaPipe threads (Pi 4 cores)
           "nothing": clean_action(cfg.get("nothing"), keys_only=True), "gestures": []}
    seen = set()
    for i, g in enumerate((cfg.get("gestures") or [])[:MAX_GESTURES]):
        if not isinstance(g, dict):
            continue
        gid = g.get("id") if isinstance(g.get("id"), str) and re.fullmatch(r"[\w-]{1,24}", g["id"]) else f"g{i + 1}"
        while gid in seen:
            gid += "_"
        seen.add(gid)
        kind = "builtin" if g.get("kind") == "builtin" and g.get("rule") in BUILTINS else "taught"
        name = (str(g.get("name") or "").strip() or (BUILTINS[g["rule"]][0] if kind == "builtin" else gid))[:28]
        color = g.get("color") if isinstance(g.get("color"), str) and re.fullmatch(r"#[0-9a-fA-F]{6}", g["color"]) else PALETTE[i % len(PALETTE)]
        item = {"id": gid, "name": name, "kind": kind,
                "hand": g.get("hand") if g.get("hand") in ("any", "left", "right") else "any",
                "color": color.lower(), "on": bool(g.get("on", True)), "action": clean_action(g.get("action"))}
        if kind == "builtin":
            item["rule"] = g["rule"]
        else:
            raw = g["samples"] if isinstance(g.get("samples"), list) else kept.get(gid, [])
            item["samples"] = [s for s in map(clean_sample, raw[-MAX_SAMPLES:]) if s]
        out["gestures"].append(item)
    return out


def public_config(cfg):
    """The config without the bulky example vectors (the page edits this)."""
    out = dict(cfg)
    out["gestures"] = []
    for g in cfg["gestures"]:
        g = dict(g)
        if g["kind"] == "taught":
            s = g.pop("samples")
            g["examples"] = len(s)
            g["hands"] = sorted({sample_feat(x, cfg["mirror"])[1] for x in s})
            if s:                                       # the average pose: drawn on the gesture's card
                mean = np.mean([sample_feat(x, cfg["mirror"])[0] for x in s], axis=0)
                g["preview"] = [[round(float(x), 3), round(float(y), 3)] for x, y, _ in mean]
        out["gestures"].append(g)
    return out


def describe(action):
    t = action.get("type")
    if t == "key":
        return f"{action['key']} · {KEYS[action['key']]}"
    if t == "speed":
        return "turbo" if action["n"] == "q" else f"speed {action['n']}"
    if t == "step":
        return "faster" if action["d"] > 0 else "slower"
    return "nothing"


# --------------------------------------------------------------------------- self-test

def load_fixture():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "hands.json")) as f:
        return json.load(f)["hands"]


def jittered(d, rng, turn, noise, scramble=False):
    """A fixture hand turned by up to `turn` degrees, rescaled, with shaky joints."""
    w, h = d["w"], d["h"]
    p = np.array(d["lm"], float) * [w, h, w]
    a = math.radians(rng.uniform(-turn, turn))
    rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    p[:, :2] = (p[:, :2] - p[0, :2]) @ rot.T * rng.uniform(0.85, 1.15) + p[0, :2]
    p += rng.normal(0, noise * np.linalg.norm(p[9] - p[0]), p.shape)
    if scramble:
        p = p[0] + rng.permutation(p - p[0])
    return Hand(p / [w, h, w], w, h, d["hand"])


def selftest():
    hands = load_fixture()
    ok = True
    print("== built-in rules on labelled MediaPipe test hands")
    for d in hands:
        h = Hand(d["lm"], d["w"], d["h"], d["hand"])
        sc = builtin_scores(h)
        best = max(sc, key=sc.get)
        good = best == d["truth"] and sc[best] >= 0.6
        ok &= good
        fing = " ".join(f"{k[0]}{v:.1f}" for k, v in h.ext.items())
        print(f"{d['img']:20s} rot {d['rot']:5d}  {d['truth']:17s} -> {best:17s} {sc[best]:.2f}  [{fing}]",
              "OK" if good else "WRONG")

    print("== taught gestures: one example per hand, then that hand again, turned and shaky")
    rng = np.random.default_rng(7)
    cfg = default_config()
    cfg["gestures"] = []
    for i, d in enumerate(hands):
        h = Hand(d["lm"], d["w"], d["h"], d["hand"])
        cfg["gestures"].append({"id": f"h{i}", "name": d["truth"], "kind": "taught", "hand": "any", "on": True,
                                "action": {"type": "none"}, "samples": [make_sample(h, True)]})
    truth = {f"h{i}": d["truth"] for i, d in enumerate(hands)}
    hits = total = 0
    for d in hands:
        for _ in range(6):
            r = classify(cfg, jittered(d, rng, turn=10, noise=0.04))
            total += 1
            hits += truth.get(r["winner"]) == d["truth"]
    print(f"taught: {hits}/{total} jittered hands (±10°, ±15% size, shaky joints) matched their own pose")
    ok &= hits >= total * 0.95
    far = classify(cfg, jittered(hands[0], rng, turn=0, noise=0.0, scramble=True))
    print("a scrambled non-hand matches nothing:", "OK" if far["winner"] is None else f"WRONG ({far['winner']})")
    ok &= far["winner"] is None

    # mirroring an example must keep its meaning
    d = next(x for x in hands if x["truth"] == "point_left")
    h = Hand(d["lm"], d["w"], d["h"], d["hand"])
    s = make_sample(h, mirror=False)
    f, hand = sample_feat(s, mirror=True)
    flip_ok = f[8][0] > 0 and hand != d["hand"]
    print("mirror flip of a stored example:", "OK" if flip_ok else "WRONG")
    ok &= flip_ok
    print("selftest:", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(0 if selftest() else 1)
    print(__doc__)

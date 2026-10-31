#!/usr/bin/env python3
"""Turn knots.json (from build_curve.py) into the compact file the /age page loads.

Everything is delta-encoded integers so it gzips well:
  base        ISO date that day offsets count from
  k.d / k.h   day-knots: day offset deltas, highest-id deltas
  r.i / r.d   every tracked id (deltas) and the day offset of its own first sighting
"""
import sys
from datetime import date, datetime
import orjson

src = sys.argv[1] if len(sys.argv) > 1 else "knots.json"
dst = sys.argv[2] if len(sys.argv) > 2 else "../age/data.json"

d = orjson.loads(open(src, "rb").read())
base = date.fromisoformat(d["tracking_start"])


def deltas(xs):
    out, prev = [], 0
    for x in xs:
        out.append(x - prev)
        prev = x
    return out


kd = [(date.fromisoformat(k[0]) - base).days for k in d["knots"]]
kh = [k[2] for k in d["knots"]]
raw = sorted((int(s), (datetime.fromisoformat(v[0]).date() - base).days) for s, v in d["raw"].items())

out = {
    "built": d["built"],
    "base": base.isoformat(),
    "n": d["n_ids"],
    "k": {"d": deltas(kd), "h": deltas(kh)},
    "r": {"i": deltas([r[0] for r in raw]), "d": [r[1] for r in raw]},
}
open(dst, "wb").write(orjson.dumps(out))
print(f"wrote {dst}: {len(kd)} knots, {len(raw)} ids")

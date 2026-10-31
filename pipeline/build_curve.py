#!/usr/bin/env python3
"""Merge state-*.json from extract_first_seen.py into an ID -> date curve.

Key idea: structure IDs are allocated in increasing order, so anchor(x) <= anchor(y)
whenever x < y, and every first-seen time is an upper bound on its own anchor time.
Therefore anchor(x) <= min(first_seen(y) for y >= x). That suffix minimum ("envelope")
removes the censoring problem: old structures that only showed up when tracking began
(or when they went public later) get pulled down by newer IDs that were seen promptly.

Output: curve.csv with one knot per day: day, max_id_seen_by_that_day, n_ids
and knots.json used by estimate.py.
"""
import glob, heapq, sys
from datetime import datetime, timezone
import orjson


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def merge(paths):
    ids = {}
    for p in paths:
        s = orjson.loads(open(p, "rb").read())
        for k, v in s["ids"].items():
            sid = int(k)
            cand = [v["first"]] + ([v["ef"]] if v.get("ef") else [])
            fs = min(parse(c) for c in cand)
            r = ids.get(sid)
            if r is None or fs < r["fs"]:
                ids[sid] = {"fs": fs, "type": v.get("type"), "sys": v.get("sys")}
            else:
                r["type"] = r["type"] or v.get("type")
                r["sys"] = r["sys"] or v.get("sys")
    return ids


def main():
    paths = sys.argv[1:] or sorted(glob.glob("state-*.json"))
    ids = merge(paths)
    sids = sorted(ids)
    # Robust suffix envelope: the K-th smallest first-seen among all IDs >= x.
    # A plain minimum is too aggressive because IDs are handed out in blocks per server
    # node, so a single higher ID can legitimately predate a few lower ones. Requiring K
    # independent witnesses ignores those isolated inversions.
    K = int(__import__("os").environ.get("ENVELOPE_K", "5"))
    env = [None] * len(sids)
    heap = []  # max-heap (negated timestamps) of the K smallest seen so far
    for i in range(len(sids) - 1, -1, -1):
        t = ids[sids[i]]["fs"].timestamp()
        if len(heap) < K:
            heapq.heappush(heap, -t)
        elif t < -heap[0]:
            heapq.heapreplace(heap, -t)
        env[i] = datetime.fromtimestamp(-heap[0], timezone.utc)
    # One knot per calendar day: the highest ID whose envelope date falls on that day.
    # "By the end of day D, IDs up to K existed."
    knots = {}
    for sid, e in zip(sids, env):
        d = e.date().isoformat()
        k = knots.get(d)
        if k is None:
            knots[d] = [sid, sid, 1]
        else:
            k[1] = max(k[1], sid)
            k[0] = min(k[0], sid)
            k[2] += 1
    days = sorted(knots)
    tracking_start = min(ids[s]["fs"] for s in sids).date().isoformat()
    out = {
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tracking_start": tracking_start,
        "n_ids": len(sids),
        "min_id": sids[0],
        "max_id": sids[-1],
        # [day, lowest id, highest id, count]
        "knots": [[d, knots[d][0], knots[d][1], knots[d][2]] for d in days],
        "raw": {str(s): [ids[s]["fs"].isoformat(timespec="seconds"), ids[s]["type"], ids[s]["sys"]] for s in sids},
    }
    open("knots.json", "wb").write(orjson.dumps(out))
    with open("curve.csv", "w") as f:
        f.write("day,min_id,max_id,n_ids\n")
        for d in days:
            f.write(f"{d},{knots[d][0]},{knots[d][1]},{knots[d][2]}\n")
    print(f"{len(sids)} ids, {len(days)} day-knots, tracking start {tracking_start}, "
          f"id range {sids[0]}..{sids[-1]}")
    print("first knots:", out["knots"][:3])
    print("last knots:", out["knots"][-3:])


if __name__ == "__main__":
    main()

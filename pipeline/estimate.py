#!/usr/bin/env python3
"""Estimate when an Upwell structure was anchored from its item ID.

Usage:
  python3 estimate.py 1045000000000
  python3 estimate.py "<url=showinfo:35832//1045000000000>Some Astrahus</url>"
  python3 estimate.py --anchors anchors.csv 1045000000000   # private exact anchors (id,iso_date)

Methods (same vocabulary as eveapex.com/structure-age):
  anchor-table      exact date from your private anchors file
  exact             this ID is in the dataset and was seen promptly
  interpolate       between the nearest day-knots on the ID curve
  extrapolate-head  older than tracking start; upper bound only
  extrapolate-tail  newer than any tracked ID; projected using recent ID rate
  unknown
"""
import argparse, bisect, csv, json, re, sys
from datetime import date, datetime, timedelta, timezone
import orjson

LAG_PAD_DAYS = 2  # first-seen lags anchoring (24h anchor timer + going public + poll interval)
TAIL_WINDOW_DAYS = 60
TAIL_MAX_DAYS = 45  # refuse to project further than this past the newest knot


class Curve:
    def __init__(self, path="knots.json"):
        d = orjson.loads(open(path, "rb").read())
        self.tracking_start = date.fromisoformat(d["tracking_start"])
        self.min_id, self.max_id = d["min_id"], d["max_id"]
        self.days = [date.fromisoformat(k[0]) for k in d["knots"]]
        self.hi = [k[2] for k in d["knots"]]
        self.raw = d["raw"]
        self.built = d["built"]

    def estimate(self, sid, anchors=None):
        if anchors and sid in anchors:
            return {"method": "anchor-table", "anchoredAt": anchors[sid].isoformat()}
        if sid > self.max_id:
            return self._tail(sid)
        i = bisect.bisect_left(self.hi, sid)  # first knot whose highest id >= sid
        end = self.days[i]
        if end <= self.tracking_start:
            return {"method": "extrapolate-head", "rangeEnd": end.isoformat()}
        prev_day, prev_hi = (self.days[i - 1], self.hi[i - 1]) if i else (end, sid)
        span = (end - prev_day).days
        frac = (sid - prev_hi) / max(1, self.hi[i] - prev_hi)
        mid = prev_day + timedelta(days=round(span * frac)) if span else end
        own = self.raw.get(str(sid))
        method = "interpolate"
        if own:
            own_day = datetime.fromisoformat(own[0]).date()
            if own_day <= end:  # its own first sighting is a hard upper bound for this id
                method, end = "exact", own_day
                mid = min(mid, end)
                prev_day = min(prev_day, end)
        start = prev_day - timedelta(days=LAG_PAD_DAYS)
        return {
            "method": method,
            "mid": mid.isoformat(),
            "rangeStart": start.isoformat(),
            "rangeEnd": end.isoformat(),
            "daysWide": (end - start).days,
            "type_id": own[1] if own else None,
            "solar_system_id": own[2] if own else None,
        }

    def _tail(self, sid):
        last_day, last_hi = self.days[-1], self.hi[-1]
        j = bisect.bisect_left(self.days, last_day - timedelta(days=TAIL_WINDOW_DAYS))
        dd = (last_day - self.days[j]).days
        rate = (last_hi - self.hi[j]) / dd if dd else 0  # ids per day
        if rate <= 0:
            return {"method": "unknown"}
        ahead = (sid - last_hi) / rate
        if ahead > TAIL_MAX_DAYS:
            return {"method": "unknown", "note": f"~{ahead:.0f} days past newest data; likely not a real id yet"}
        mid = last_day + timedelta(days=round(ahead))
        return {"method": "extrapolate-tail", "mid": mid.isoformat(),
                "rangeStart": last_day.isoformat(), "rangeEnd": (mid + timedelta(days=3)).isoformat(),
                "daysWide": (mid - last_day).days + 3, "idsPerDay": round(rate)}


def parse_id(raw):
    """Accept a bare id or a show-info link like <url=showinfo:35832//1045000000000>."""
    m = re.search(r"showinfo:(\d+)//(\d+)", raw)
    if m:
        return int(m.group(2))
    m = re.search(r"\b(1\d{12})\b", raw)
    return int(m.group(1)) if m else None


def load_anchors(path):
    out = {}
    with open(path) as f:
        for row in csv.reader(f):
            if row and row[0].strip().isdigit():
                out[int(row[0])] = date.fromisoformat(row[1].strip()[:10])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--curve", default="knots.json")
    ap.add_argument("--anchors")
    a = ap.parse_args()
    c = Curve(a.curve)
    anchors = load_anchors(a.anchors) if a.anchors else None
    for raw in a.inputs:
        sid = parse_id(raw)
        res = c.estimate(sid, anchors) if sid else {"method": "unknown", "note": "no structure id found"}
        print(json.dumps({"structureId": sid, **res}))


if __name__ == "__main__":
    main()

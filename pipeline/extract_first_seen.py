#!/usr/bin/env python3
"""Stream EVE Ref structure history and record when each structure ID was first seen.

Sources (https://data.everef.net/structures/history/):
  - structures-YYYY.tar.xz   yearly archives (streamed, never extracted to disk)
  - YYYY/YYYY-MM-DD/*.json.bz2  daily snapshot files for the current year

Snapshot formats:
  - *.json     : list of public structure IDs (ESI /universe/structures)
  - *.v2.json  : dict id -> details (type_id, solar_system_id, first_seen, ...)

Output: state.json with, per structure ID:
  first  - earliest snapshot timestamp containing the ID
  last   - latest snapshot timestamp containing the ID
  n      - number of snapshots containing it
  type, sys - type_id / solar_system_id (from v2 files, if any)
  ef     - earliest EVE Ref `first_seen` value seen in any v2 file
Processed sources are recorded so the script can be re-run to resume / pick up new days.
"""
import bz2, io, os, re, subprocess, sys, tarfile, time
import orjson
from concurrent.futures import ThreadPoolExecutor

BASE = "https://data.everef.net/structures/history"
YEARS_TAR = [2023, 2024, 2025]
STATE = os.environ.get("STATE", "state.json")
TS_RE = re.compile(r"structures-(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def load_state():
    if os.path.exists(STATE):
        s = orjson.loads(open(STATE, "rb").read())
        s["ids"] = {int(k): v for k, v in s["ids"].items()}
        s["done"] = set(s["done"])
        return s
    return {"ids": {}, "done": set()}


def save_state(s):
    tmp = STATE + ".tmp"
    out = {"ids": {str(k): v for k, v in s["ids"].items()}, "done": sorted(s["done"])}
    open(tmp, "wb").write(orjson.dumps(out))
    os.replace(tmp, STATE)


def ts_from_name(name):
    m = TS_RE.search(name)
    if not m:
        return None
    d, hh, mm, ss = m.groups()
    return f"{d}T{hh}:{mm}:{ss}Z"


def ingest(state, name, raw):
    ts = ts_from_name(name)
    if ts is None:
        return 0
    try:
        data = orjson.loads(raw)
    except orjson.JSONDecodeError:
        log("bad json", name)
        return 0
    ids = state["ids"]
    if isinstance(data, list):
        items = ((int(x), None) for x in data)
    elif isinstance(data, dict):
        items = ((int(k), v) for k, v in data.items())
    else:
        return 0
    n = 0
    for sid, info in items:
        if not (1_000_000_000_000 <= sid < 2_000_000_000_000):
            continue  # Upwell structure range only
        r = ids.get(sid)
        if r is None:
            r = ids[sid] = {"first": ts, "last": ts, "n": 0}
        if ts < r["first"]:
            r["first"] = ts
        if ts > r["last"]:
            r["last"] = ts
        r["n"] += 1
        if isinstance(info, dict):
            if info.get("type_id") and "type" not in r:
                r["type"] = info["type_id"]
            if info.get("solar_system_id") and "sys" not in r:
                r["sys"] = info["solar_system_id"]
            ef = info.get("first_seen")
            if ef and (r.get("ef") is None or ef < r["ef"]):
                r["ef"] = ef
        n += 1
    return n


def curl_stream(url):
    return subprocess.Popen(["curl", "-sSfL", "--retry", "5", url], stdout=subprocess.PIPE, bufsize=1 << 20)


def do_tar(state, year):
    key = f"tar:{year}"
    if key in state["done"]:
        return
    url = f"{BASE}/structures-{year}.tar.xz"
    log("streaming", url)
    p = curl_stream(url)
    files = 0
    with tarfile.open(fileobj=p.stdout, mode="r|xz") as tf:
        for m in tf:
            if not m.isfile() or "structures-" not in m.name:
                continue
            f = tf.extractfile(m)
            raw = f.read()
            if m.name.endswith(".bz2"):
                raw = bz2.decompress(raw)
            ingest(state, m.name, raw)
            files += 1
            if files % 500 == 0:
                log(f"  {year}: {files} files, {len(state['ids'])} ids, at {m.name.rsplit('/',1)[-1]}")
    if p.wait() != 0:
        raise SystemExit(f"curl failed for {url}")
    state["done"].add(key)
    save_state(state)
    log(f"done {year}: {files} files, {len(state['ids'])} ids")


def list_links(url, pat):
    html = subprocess.run(["curl", "-sSfL", url], capture_output=True, check=True).stdout.decode()
    return sorted(set(re.findall(pat, html)))


def do_daily(state, year, every=1):
    days = list_links(f"{BASE}/{year}/", rf'href="/structures/history/{year}/({year}-\d\d-\d\d)/"')
    today = time.strftime("%Y-%m-%d", time.gmtime())
    for day in days:
        key = f"day:{day}"
        if key in state["done"]:
            continue
        files = list_links(f"{BASE}/{year}/{day}/", r'href="/structures/history/[^"]+/(structures-[^"]+\.json\.bz2)"')
        files = files[::every]

        def fetch(fn):
            raw = subprocess.run(["curl", "-sSfL", "--retry", "5", f"{BASE}/{year}/{day}/{fn}"],
                                 capture_output=True, check=True).stdout
            return fn, bz2.decompress(raw)

        with ThreadPoolExecutor(6) as ex:
            for fn, raw in ex.map(fetch, files):
                ingest(state, fn, raw)
        if day < today:  # don't mark today complete; more files will appear
            state["done"].add(key)
        save_state(state)
        log(f"day {day}: {len(files)} files, {len(state['ids'])} ids")


def main():
    state = load_state()
    years = [int(a) for a in sys.argv[1:]] or YEARS_TAR + [int(time.strftime("%Y", time.gmtime()))]
    for y in years:
        if y in YEARS_TAR:
            do_tar(state, y)
        else:
            do_daily(state, y)
    save_state(state)
    log("all done", len(state["ids"]), "ids")


if __name__ == "__main__":
    main()

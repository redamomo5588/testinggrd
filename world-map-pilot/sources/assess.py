"""Score every catalogued source and verify that its URL is reachable.

python sources/assess.py            # probe all URLs + score -> sources/catalog.csv, sources/SUMMARY.md
python sources/assess.py --no-probe # re-score from cached probe results
"""
import argparse
import csv
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
COLS = ["name", "provider", "scope", "region", "type", "resolution", "year", "license", "commercial", "access", "url",
        "topology"]
CATEGORIES = {
    "roads": "Roads (and crossroads, derived from road topology)",
    "buildings": "Building footprints / built-up",
    "building_heights": "Building heights",
    "terrain": "Terrain / elevation",
    "forest_canopy": "Forest cover / canopy height",
    "land_cover": "Land cover",
    "water_bodies": "Water bodies / rivers / wetlands",
    "water_points": "Water points (wells, springs, taps, boreholes)",
}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


def load():
    rows = []
    for cat in CATEGORIES:
        for line in (HERE / "catalog" / f"{cat}.psv").read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("|")
            assert len(parts) == len(COLS), (cat, line)
            rows.append({"category": cat, **dict(zip(COLS, parts))})
    return rows


def probe(url):
    """Two attempts; the egress proxy rejects bursts, so a single failure is not trusted."""
    res = _probe(url)
    if res[0] in ("blocked_here", "error", "timeout"):
        time.sleep(2)
        res = _probe(url)
    return res


def _probe(url):
    p = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-L", "--max-redirs", "5", "--max-time", "25",
                        "-A", UA, "-r", "0-0", "-w", "%{http_code}", url], capture_output=True, text=True)
    code, err = p.stdout.strip()[-3:], p.stderr.strip()
    if "CONNECT tunnel failed" in err or "response 403" in err and code == "000":
        return "blocked_here", code
    if code.startswith(("2", "3")) or code == "416":
        return "ok", code
    if code in ("401", "403", "405", "429"):
        return "reachable_restricted", code
    if code in ("404", "410"):
        return "broken_link", code
    if code.startswith("5"):
        return "server_error", code
    if p.returncode == 28:
        return "timeout", code
    return "error", (err[:80] or code)


def score(r):
    s = {"G": 30, "C": 18, "N": 10, "S": 4}.get(r["scope"], 0)
    lic = r["license"].lower()
    s += {"Y": 20, "R": 10, "N": 6, "P": 4}.get(r["commercial"], 0)
    y = int(r["year"]) if r["year"].isdigit() else 0
    s += 20 if y >= 2024 else 15 if y >= 2022 else 9 if y >= 2018 else 3
    s += {"dl": 20, "api": 17, "reg": 12, "com": 6, "req": 3}.get(r["access"], 0)
    s += {"ok": 10, "reachable_restricted": 7, "blocked_here": 5, "timeout": 3, "server_error": 2}.get(r["probe"], 0)
    return s, ("non-commercial" in lic or "-nc" in lic or "nc " in lic)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-probe", action="store_true")
    a = ap.parse_args()
    rows = load()
    cache_f = HERE / "probe_cache.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
    if not a.no_probe:
        urls = sorted({r["url"] for r in rows})
        with ThreadPoolExecutor(6) as ex:
            for u, res in zip(urls, ex.map(probe, urls)):
                cache[u] = res
        cache_f.write_text(json.dumps(cache, indent=0, sort_keys=True))
    for r in rows:
        r["probe"], r["http"] = cache.get(r["url"], ("not_probed", ""))
        r["score"], nc = score(r)
        r["tier"] = "A" if r["score"] >= 80 else "B" if r["score"] >= 60 else "C"
        r["flags"] = ";".join(f for f, c in [
            ("NON-COMMERCIAL", nc or r["commercial"] == "N"), ("PAID", r["commercial"] == "P"),
            ("SHARE-ALIKE", "odbl" in r["license"].lower() or "-sa" in r["license"].lower()),
            ("STALE<2018", r["year"].isdigit() and int(r["year"]) < 2018),
            ("NOT-GLOBAL", r["scope"] in ("N", "S")), ("URL-BROKEN", r["probe"] == "broken_link")] if c)
    rows.sort(key=lambda r: (list(CATEGORIES).index(r["category"]), -r["score"], r["name"]))
    out_cols = ["category", "tier", "score", "name", "provider", "scope", "region", "type", "resolution", "year",
                "license", "commercial", "access", "probe", "http", "flags", "topology", "url"]
    with open(HERE / "catalog.csv", "w", newline="") as f:
        w = csv.DictWriter(f, out_cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} sources")
    for cat in CATEGORIES:
        rs = [r for r in rows if r["category"] == cat]
        pr = {k: sum(r["probe"] == k for r in rs) for k in
              ("ok", "reachable_restricted", "blocked_here", "broken_link", "server_error", "timeout", "error")}
        tiers = {t: sum(r["tier"] == t for r in rs) for t in "ABC"}
        glob_open = sum(r["scope"] == "G" and r["commercial"] == "Y" and r["access"] in ("dl", "api") for r in rs)
        print(f"{cat:17s} n={len(rs):3d} tiers={tiers} global+open+commercial={glob_open:2d} probe={pr}")


if __name__ == "__main__":
    main()

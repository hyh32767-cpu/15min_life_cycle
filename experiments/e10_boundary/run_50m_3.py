# -*- coding: utf-8 -*-
"""3 城 50m 网格补全(洛阳/深圳/天津)"""
import sys, json, math, os, time, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core import baidu_client as bc
from core import cache as wcache
from experiments.e4_sampling.run_e4 import grid_points

CITIES = [
    ("luoyang", "洛阳·老城", "LZ50"),
    ("shenzhen", "深圳·华强北", "SZ50"),
    ("tianjin", "天津·五大道", "TJ50"),
]

for slug, name, eid in CITIES:
    d = json.load(open(f'experiments/results/e10_boundary/e10x_{slug}.json', encoding='utf-8'))
    CENTER = tuple(d['center'])
    g = grid_points(CENTER, 50, 500)
    todo = [p for p in g if wcache.get(CENTER, p) is None]
    print(f"\n===== {name}: {len(g)} pts, uncached {len(todo)} =====", flush=True)
    done = 0
    for i in range(0, len(todo), 50):
        chunk = todo[i:i+50]
        for attempt in range(4):
            r = bc.routematrix("walking", [CENTER], chunk, experiment_id=eid)
            if r.ok: break
            if r.status in (401, 302) and attempt < 3:
                time.sleep([15,30,60][attempt]); continue
            if "network" in str(r.message) or "SSL" in str(r.message):
                time.sleep(20); continue
            raise RuntimeError(f"matrix {r.status} {r.message}")
        for p, it in zip(chunk, bc.matrix_items(r)):
            if it.get("duration_s") is not None:
                wcache.put(CENTER, p, it["duration_s"], it.get("distance_m"))
        done += len(chunk)
        if done % 150 < 50:
            print(f"  progress: {done}/{len(todo)}", flush=True)
        time.sleep(0.3)
    n_cov = sum(1 for p in g if wcache.get(CENTER, p) is not None)
    d['grid50_covered'] = n_cov
    json.dump(d, open(f'experiments/results/e10_boundary/e10x_{slug}.json', 'w',
                      encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"  covered {n_cov}/{len(g)}", flush=True)

con = sqlite3.connect('experiments/logs/calls.db')
t = con.execute("SELECT COUNT(*), SUM(n_pairs) FROM calls WHERE ts>='2026-09-02'").fetchone()
print(f"\ntoday: {t[0]} req / {t[1]} pairs")

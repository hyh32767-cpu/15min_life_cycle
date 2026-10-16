# -*- coding: utf-8 -*-
"""只读导出历史实验案例到 demo-data/v1/cases。

用法:
    python3 tools/demo/export_cases.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.coord import bd09_to_wgs84  # noqa: E402

TARGETS = {
    "harbin": ("experiments/results/e10_boundary/e10x_harbin.json", "哈尔滨·道外"),
    "guilin": ("experiments/results/e10_boundary/e10x_guilin.json", "桂林"),
    "lanzhou": ("experiments/results/e10_boundary/e10x_lanzhou.json", "兰州"),
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def export_case(slug: str, source_rel: str, title: str) -> Dict:
    source_path = ROOT / source_rel
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    center = raw["center"]  # [lat, lng] BD09
    wgs = bd09_to_wgs84(float(center[1]), float(center[0]))
    return {
        "schemaVersion": 1,
        "caseId": slug,
        "title": title,
        "source": {
            "path": source_rel,
            "sha256": _sha256(source_path),
            "format": "e10x_boundary",
            "crs": "BD09",
        },
        "center": {"lat": center[0], "lng": center[1], "crs": "BD09"},
        "centerWgs84": {"lng": wgs[0], "lat": wgs[1], "crs": "WGS84"},
        "radii": raw.get("radii", {}),
        "pockets": raw.get("pockets", []),
        "metrics": raw.get("metrics", {}),
        "limits": [
            "历史实验样本与口径不等同于当前比赛应用的新功能准确率。",
            "POI/边界为研究期百度API缓存重建，不代表百度现实全量。",
            "只读导出；原始 experiments/ 文件未被修改。",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "demo-data" / "v1" / "cases"))
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    index = []
    for slug, (source_rel, title) in TARGETS.items():
        payload = export_case(slug, source_rel, title)
        (out_dir / f"{slug}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        index.append({
            "caseId": slug,
            "title": title,
            "sourcePath": source_rel,
            "sourceHash": payload["source"]["sha256"],
            "centerWgs84": payload["centerWgs84"],
            "file": f"{slug}.json",
        })

    (out_dir / "index.json").write_text(
        json.dumps({"schemaVersion": 1, "cases": index}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps({"out": str(out_dir), "cases": len(index)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

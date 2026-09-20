# -*- coding: utf-8 -*-
"""core/terrain.py · 地形感知模块(2026-09-02 定稿;生产定位见末尾)

三层信号(全部实验验证,无效信号已剔除):

测前(零 API):
  DEM std≥5.3m → 复杂城(LOO 90%)→ 16/32 起步
  类型先验 → 兜底(LOO 75%)

测中(免费附带):
  路名匹配:direction API steps[].name 含地形关键词 → 标记方位
  (唯一可靠 API 地形信号:兰州"中山桥"4/4、平原城 0/4)

测后(少量 API):
  ρ 弦探针(已有管线)
  POI 地形要素(独立池,~4 次,需类型过滤)

无效(已实验否定):
  ✗ 路线折线偏角/横偏 → 城市底噪(91% 误报,8 城验证)
  ✗ 纯几何偏向(α/二阶差分)→ 14/20 城变差
"""
import math
import re

# 地形路名关键词(从 8 城实验标定)
ROAD_KEYWORDS = re.compile(r"桥|隧道|滨河|沿江|沿河|江边|河边|高架|立交|过街|地下道")

# POI 地形类型过滤(排除"水泥河沙建材"类噪声)
POI_TERRAIN_HINTS = {"桥": ["桥梁", "跨河", "人行天桥", "立交桥"],
                     "河": ["河流", "湖泊", "水域", "滨江"],
                     "隧道": ["隧道"]}


def preflight_complexity(dem_std=None, type_label=None):
    """测前判断:该社区是否复杂地形(需要 16/32 起步)。

    参数:
      dem_std: 社区 1.5km 高程标准差(AWS terrarium z13,~30KB)
      type_label: 社区类型字符串(如"山城"/"老市井"/"科技园")
    返回:
      (is_complex: bool, confidence: str, reason: str)
    """
    if dem_std is not None and dem_std >= 5.3:
        return True, "90%", f"DEM std={dem_std:.1f}m ≥5.3"
    if dem_std is not None and dem_std < 5.3:
        if type_label and any(k in type_label for k in ("山", "江", "河", "谷")):
            return True, "75%", f"类型'{type_label}'含地形关键词"
        return False, "90%", f"DEM std={dem_std:.1f}m <5.3"
    if type_label:
        if any(k in type_label for k in ("山", "江", "河", "谷", "古城", "老城", "市井")):
            return True, "75%", f"类型'{type_label}'→复杂"
        return False, "75%", f"类型'{type_label}'→简单"
    return True, "低", "无信号,保守判复杂"


def scan_road_names(direction_response):
    """测中:从 direction API 响应中提取地形路名信号。

    参数: bc.direction() 的响应对象(需 .ok=True)
    返回: [{"bearing_hint": str, "road": str, "keyword": str}] 或 []
    """
    if not direction_response.ok:
        return []
    routes = direction_response.data.get("result", {}).get("routes", [])
    if not routes:
        return []
    hits = []
    for step in routes[0].get("steps", []):
        name = step.get("name", "")
        if name:
            m = ROAD_KEYWORDS.search(name)
            if m:
                hits.append({"road": name, "keyword": m.group()})
    return hits


def classify_terrain(rho_median=None, n_pockets=0, n_gaps=0, n_corridor_dev=0):
    """测后:综合地形分类(用于走廊偏差预测)。

    返回: (has_corridor_risk: bool, signals: dict)
    实验验证:召回 86%、精确 60%(自然地形好,城市峡谷需路名补充)
    """
    signals = {"rho": rho_median, "pockets": n_pockets,
               "gaps": n_gaps, "terrain_feat": n_pockets + n_gaps}
    pred = (n_pockets + n_gaps >= 2) or (rho_median and rho_median >= 1.7)
    return pred, signals


def terrain_profile(dem_std=None, type_label=None,
                    road_hits=None, rho_median=None,
                    n_pockets=0, n_gaps=0):
    """一站式地形感知(生产管线调用入口)。

    返回 dict:
      complexity: 'complex'|'simple'
      confidence: str
      road_terrain: [路名命中]
      corridor_risk: bool
      signals: 全部信号值
      recommended_rays: 16|8
    """
    is_cx, conf, reason = preflight_complexity(dem_std, type_label)
    corridor_risk, sig = classify_terrain(rho_median, n_pockets, n_gaps)
    return {
        "complexity": "complex" if is_cx else "simple",
        "confidence": conf,
        "reason": reason,
        "road_terrain": road_hits or [],
        "corridor_risk": corridor_risk,
        "signals": sig,
        "recommended_rays": 16 if (is_cx or corridor_risk) else 8,
    }


# ============================================================
# 生产定位(2026-09-02 终审)
#
# 测前信号(DEM/类型)适用于离线分析和批量预标注,
# 但在生产环境(实时查询、大范围、中国网络)难以落地:
#   - DEM 下载在中国不稳定;批量查询=几千次下载
#   - 类型先验需人工维护或 LLM 调用
#
# 生产环境的地形感知 = 自适应管线本身:
#   8 向起步(64 对) → aniso8/弦差自判(69%,误判代价≈0) →
#   加密链自动响应(弦长>200m / mid 违规) → 路名标记 → 复通带
#
# 本模块的 preflight_complexity() 适用于:
#   - 离线批量分析(哪些社区优先做)
#   - 报告生成(标注难度来源)
#   - 实验/研究(对比不同信号源)
# ============================================================

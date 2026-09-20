"""六城综合地图 v2 —— 所有实验结果的同图展示(零 API,全部坐标经纬度统一)

图层(自下而上):
  1  OSM 步行路网(浅灰)
  2  时间场等值带(tricontourf,5/10/15/20min)+ 15min 黑粗线
  3  全部采样点散点(按时长着色:网格点/射线轨迹点/H3 中心,形状区分)
  4  射线轨迹线(中心→边界点,红;8 向橙)与边界端点
  5  H3 六边形(仅社区 A:res9 粗格/边界带 res10/深加密 res11,线宽区分)
  6  方法多边形:红虚=成品射线多边形;橙点线=8 向;蓝点划=OSMnx 等时线
  7  色标 + 指标框(F1/IoU/对数)
纵横比较正:ax.set_aspect(1/cos(lat)),米→度的等距近似。
"""
import bisect
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import networkx as nx
import numpy as np
import osmnx as ox

from core.coord import bd09_to_wgs84, dest_at
from experiments.e4_sampling.analyze_e4 import replay_bisect
from experiments.e4_sampling.run_e4 import cls_metrics, grid_points, key
from experiments.osmnx.run_osmnx_truth import OsmOracle, V_MS

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAPDIR = os.path.join(ROOT, "experiments", "results", "maps")
TH = 900
CITIES = [
    ("A", "e4_sampling/e4.json", "北京A·王府井", "m4_radii", None),
    ("B", "e4_sampling/e4b.json", "北京B·东花市", "radii_final", None),
    ("shanghai", "e10_boundary/e10x_shanghai.json", "上海·陆家嘴", "radii", None),
    ("guangzhou", "e10_boundary/e10x_guangzhou.json", "广州·上下九", "radii", None),
    ("chengdu", "e10_boundary/e10x_chengdu.json", "成都·九眼桥", "radii",
     ("e10_boundary/e10_8ray.json", "chengdu")),
    ("harbin", "e10_boundary/e10x_harbin.json", "哈尔滨·道外", "radii",
     ("e10_boundary/e10_8ray.json", "harbin")),
    ("xian", "e10_boundary/e10x_xian.json", "西安·钟楼", "radii", None),
    ("chongqing", "e10_boundary/e10x_chongqing.json", "重庆·解放碑", "radii", None),
    ("changsha", "e10_boundary/e10x_changsha.json", "长沙·五一广场", "radii", None),
    ("wuhan", "e10_boundary/e10x_wuhan.json", "武汉·江汉路", "radii", None),
    ("luoyang", "e10_boundary/e10x_luoyang.json", "洛阳·老城", "radii", None),
    ("kunshan", "e10_boundary/e10x_kunshan.json", "昆山·人民路", "radii", None),
    ("guilin", "e10_boundary/e10x_guilin.json", "桂林·东西巷", "radii", None),
    ("zunyi", "e10_boundary/e10x_zunyi.json", "遵义·老城", "radii", None),
    ("yiwu", "e10_boundary/e10x_yiwu.json", "义乌·稠城", "radii", None),
    ("huilongguan", "e10_boundary/e10x_huilongguan.json", "北京·回龙观", "radii", None),
    ("zhangjiang", "e10_boundary/e10x_zhangjiang.json", "上海·张江", "radii", None),
    ("zhujiangxincheng", "e10_boundary/e10x_zhujiangxincheng.json", "广州·珠江新城", "radii", None),
    ("yulin_cd", "e10_boundary/e10x_yulin_cd.json", "成都·玉林", "radii", None),
    ("qunli", "e10_boundary/e10x_qunli.json", "哈尔滨·群力", "radii", None),
    ("tianjin", "e10_boundary/e10x_tianjin.json", "天津·五大道", "radii", None),
    ("shenzhen", "e10_boundary/e10x_shenzhen.json", "深圳·华强北", "radii", None),
    ("kunming", "e10_boundary/e10x_kunming.json", "昆明·翠湖", "radii", None),
    ("lanzhou", "e10_boundary/e10x_lanzhou.json", "兰州·中山桥", "radii", None),
    ("xiamen", "e10_boundary/e10x_xiamen.json", "厦门·中山路", "radii", None),
    ("shenyang", "e10_boundary/e10x_shenyang.json", "沈阳·中街", "radii", None),
    ("qingdao", "e10_boundary/e10x_qingdao.json", "青岛·栈桥", "radii", None),
    ("suzhou", "e10_boundary/e10x_suzhou.json", "苏州·观前街", "radii", None),
    ("changchun", "e10_boundary/e10x_changchun.json", "长春·重庆路", "radii", None),
    ("fuzhou", "e10_boundary/e10x_fuzhou.json", "福州·三坊七巷", "radii", None),
]
# 按用户指示(2026-09-01):后续社区一律不下载 OSM 路网(无底图/无 OSMnx 参照线,其余图层同风格)
# 已缓存的十城图继续使用;E12 路由的 OSM 特征仅限既有十城,不再扩充
NO_NET = {"luoyang", "kunshan", "guilin", "zunyi", "yiwu", "nanchang",
          "huilongguan", "zhangjiang", "zhujiangxincheng", "yulin_cd", "qunli",
          "tianjin", "shenzhen", "kunming", "lanzhou", "xiamen",
          "shenyang", "qingdao", "suzhou", "changchun", "fuzhou"}
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False


def get_graph(slug, center):
    """路网获取:信任本地缓存(已是多端点择优结果);仅无缓存时下载;小城市跳过。"""
    if slug in NO_NET:
        return None
    gp = os.path.join(ROOT, "experiments", "logs", f"osm_{slug}.graphml")
    wlat, wlng = to_wgs(center)
    G = None
    if os.path.exists(gp):
        try:
            G = ox.load_graphml(gp)
        except Exception:
            G = None
    if G is None:
        best = None
        for m in (None, "https://lz4.overpass-api.de/api/interpreter",
                  "https://overpass.private.coffee/api/interpreter",
                  "https://overpass.kumi.systems/api/interpreter",
                  "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
                  "https://overpass.osm.jp/api/interpreter"):
            try:
                ox.settings.requests_timeout = 120
                if m:
                    ox.settings.overpass_url = m
                G2 = ox.graph.graph_from_point((wlat, wlng), dist=1600,
                                               network_type="walk")
                if best is None or len(G2.nodes) > len(best.nodes):
                    best = G2
                print(f"  [{slug}] 下载 {len(G2.nodes)} 节点"
                      f"({'官方' if m is None else m.split('/')[2]})")
            except Exception as e:
                print(f"  [{slug}] 端点失败:{str(e)[:50]}")
        G = best
        if G is not None:
            ox.save_graphml(G, gp)
    if G is None:
        return None
    for u, v, k, d in G.edges(keys=True, data=True):
        if "tt" not in d:
            d["tt"] = d["length"] / V_MS
    return G


def load_field(center):
    import sqlite3
    db = os.path.join(ROOT, "experiments", "logs", "cache.db")
    out = {}
    with sqlite3.connect(db) as c:
        for d_lat, d_lng, dur in c.execute(
                "SELECT d_lat,d_lng,duration_s FROM walk_times WHERE o_lat=? AND o_lng=?",
                (round(center[0], 6), round(center[1], 6))):
            if dur is not None:
                out[(d_lat, d_lng)] = dur
    return out


def to_wgs(p):
    w = bd09_to_wgs84(p[1], p[0])
    return w[1], w[0]        # (lat, lng)


def r_at(brg, radii):
    ks = sorted(radii)
    i = bisect.bisect_right(ks, brg) - 1
    b0, b1 = ks[i % len(ks)], ks[(i + 1) % len(ks)]
    db_ = (b1 - b0) % 360 or 360
    t = ((brg - b0) % 360) / db_
    return radii[b0] * (1 - t) + radii[b1] * t


def poly_wgs(center, radii, n=240):
    lat, lng = [], []
    for i in range(n + 1):
        b = i * 360 / n
        p = dest_at(center[1], center[0], b, r_at(b, radii))
        la, ln = to_wgs(p)
        lat.append(la)
        lng.append(ln)
    return lng, lat


def replay_bisect_traj(field, center, bearings, tol):
    """重放二分轨迹(全部点应已在缓存),返回 {bearing: [轨迹点(按距离)]}。"""
    lo_m = {b: 200.0 for b in bearings}
    hi_m = {b: 1400.0 for b in bearings}
    traj = {b: [] for b in bearings}

    def t_at(b, d):
        p = dest_at(center[1], center[0], b, d)
        t = field.get(key(p))
        if t is not None and t != t_at_cache.setdefault((b, round(d, 3)), t):
            pass
        return t

    t_at_cache = {}
    for b in bearings:
        p = dest_at(center[1], center[0], b, 800)
        t = field.get(key(p))
        if t is not None:
            traj[b].append((800.0, t))
    active = list(bearings)
    while active:
        nxt = []
        for b in active:
            m = (lo_m[b] + hi_m[b]) / 2
            p = dest_at(center[1], center[0], b, m)
            t = field.get(key(p))
            if t is None:
                continue
            traj[b].append((m, t))
            if t <= TH:
                lo_m[b] = m
            else:
                hi_m[b] = m
            if hi_m[b] - lo_m[b] > tol:
                nxt.append(b)
        active = nxt
    for b in traj:
        traj[b].sort()
    return traj


def h3_cells_A(field, center):
    """社区 A 的 MH H3 AMR 方案重建(粗 res9 → 边界带 res10 → 深加密 res11)。"""
    import h3
    from core.coord import wgs84_to_bd09 as w2b

    def cell_center_bd09(cell):
        la, ln = h3.cell_to_latlng(cell)
        dlng, dlat = w2b(ln, la)
        return (dlat, dlng)

    wlat, wlng = to_wgs(center)
    origin = h3.latlng_to_cell(wlat, wlng, 9)
    coarse = list(h3.grid_disk(origin, 4))
    band = (720, 1080)

    def T_of(cell):
        t = field.get(key(cell_center_bd09(cell)))
        return t

    coarse_ok = [c for c in coarse if T_of(c) is not None]
    band_cells = [c for c in coarse_ok if band[0] <= T_of(c) <= band[1]]
    fine = []
    for c in band_cells:
        fine += list(h3.cell_to_children(c, 10))
    fine_ok = [c for c in fine if T_of(c) is not None]
    deep_band = [c for c in fine_ok if band[0] <= T_of(c) <= band[1]]
    deep = []
    for c in deep_band[:18]:
        deep += list(h3.cell_to_children(c, 11))
    deep_ok = [c for c in deep if T_of(c) is not None]
    return coarse_ok, band_cells, fine_ok, deep_ok


def main():
    os.makedirs(MAPDIR, exist_ok=True)
    only = set(sys.argv[1:])
    table = {}
    for slug, fname, label, rkey, extra in CITIES:
        if only and slug not in only:
            continue
        fpath = os.path.join(ROOT, "experiments", "results", fname)
        if not os.path.exists(fpath):
            print(f"== {label}:结果文件不存在,跳过 ==")
            continue
        d = json.load(open(fpath, encoding="utf-8"))
        center = tuple(d["center"])
        radii = {float(k): v for k, v in d[rkey].items()}
        field = load_field(center)
        print(f"\n== {label} == 缓存场 {len(field)} 点")

        # 8向/16向:轨迹前缀重放(全城缓存命中,零 API;统一 tol15 口径)
        def radii_from_traj(traj):
            out = {}
            for b, seq in traj.items():
                lo, hi = 200.0, 1400.0
                for dd, t in seq:
                    if t <= TH:
                        lo = max(lo, dd)
                    else:
                        hi = min(hi, dd)
                out[b] = (lo + hi) / 2
            return out

        radii8 = radii_from_traj(
            replay_bisect_traj(field, center, [i * 45.0 for i in range(8)], 15.0))
        radii16 = radii_from_traj(
            replay_bisect_traj(field, center, [i * 22.5 for i in range(16)], 15.0))
        # A 的"自适应16起步"= 其 m4 自适应成品;16 向均匀重放仅作基线

        # v5 加密链(2026-09-01):触发器=弦违规/长弦>200m/与场阶梯边界差>60m(双向),
        # 插向半径取"场阶梯首穿越"(实测边界线,任意方位可取)→ 向实测收敛,天然收敛。
        def _bs_idx(ks, target):
            import bisect as _b2
            i = _b2.bisect_right(ks, target)
            return i % len(ks) if i > 0 else 0

        def refine_adaptive(cur, full):
            klat = 111320.0
            klng = 111320.0 * math.cos(math.radians(center[0]))

            def brg_of(p):
                return math.degrees(math.atan2((p[1] - center[1]) * klng,
                                               (p[0] - center[0]) * klat)) % 360

            def dist_of(p):
                return math.hypot((p[0] - center[0]) * klat,
                                  (p[1] - center[1]) * klng)

            def chord_len(b0, b1, r0, r1):
                x0, y0 = r0 * math.sin(math.radians(b0)), r0 * math.cos(math.radians(b0))
                x1, y1 = r1 * math.sin(math.radians(b1)), r1 * math.cos(math.radians(b1))
                return math.hypot(x1 - x0, y1 - y0)

            # 违规证据库 + 逐向阶梯(直接从缓存场自算,与 50m 场线同源)
            ev = [(brg_of(p), dist_of(p)) for p, t in field.items() if t > TH]
            fpts = [(math.degrees(math.atan2((p[1] - center[1]) * klng,
                                             (p[0] - center[0]) * klat)) % 360,
                     math.hypot((p[0] - center[0]) * klat,
                                (p[1] - center[1]) * klng), t)
                    for p, t in field.items()]
            # v5 参考 = 场阶梯首穿越(缓存的实测边界线,任意方位可取):
            # 低估自检直接对"实测边界"做,不再依赖成品/网格,天然收敛且可修任意方位
            # 间隔带/复通带扇区表(这些方位由楔形层表示,射线层 ladder 会误触发)
            _wedge_skip = []
            for _g in (d.get("interior_gaps") or []):
                _wedge_skip.append((_g["bearing"], (_g.get("wedge_deg") or 1.2) + 1.0))
            for _g in (d.get("pockets") or []):
                if isinstance(_g.get("gap"), list):
                    _wedge_skip.append((_g["bearing"], (_g.get("wedge_deg") or 5.0) + 1.0))

            def ladder_r(b, tol_deg=0.3):   # ±0.3°=±4m@800m,不跨建筑(±1.2° 会混入邻向街道)
                for _wb, _ww in _wedge_skip:
                    if min(abs(b - _wb) % 360, 360 - (abs(b - _wb)) % 360) <= _ww:
                        return None          # P1 修复:污染扇区不提供参考
                seq = sorted((dd, t) for bb, dd, t in fpts
                             if min(abs(bb - b) % 360, 360 - (abs(bb - b)) % 360) <= tol_deg)
                ok = 0.0
                for dd, t in seq:
                    if t <= TH:
                        ok = max(ok, dd)
                    else:
                        return (ok + dd) / 2
                return None

            # v4 密度开关(用户指出密区细刺可忽略):
            #   k ≥ 40 → 只回应大障碍(超时点深入 ≥60m);物理下限:弦长 ≥120m(≈2 格)
            # 完整管线模式:不设 MAX_K 密区开关,梯度制自身收敛(弧减半→梯度减半)
            MIN_CHORD = 100.0   # 质量预算旋钮(100m=标准档)
            for _ in range(12):
                ks = sorted(cur)
                inserts = []
                for a, b in zip(ks, ks[1:] + [ks[0] + 360]):
                    a0 = a % 360
                    arc = (b - a) % 360 or 360
                    if arc < 1e-6:
                        continue
                    mb0 = ((a + b) / 2) % 360
                    r_mid = r_at(mb0, cur)
                    min_arc = max(2.0, math.degrees(MIN_CHORD / max(1.0, r_mid)))
                    if arc < min_arc:
                        continue                   # 密度保护:过细不采
                    L = ladder_r(mb0)
                    if L is None:
                        continue                   # 无实测阶梯的方位:不判
                    cands = [mb0] if abs(L - r_at(mb0, cur)) > 1e-9 else []
                    if not cands:
                        continue
                    # ① 弦违规:扇区内实测超时点深入多边形 ≥40m(v6:
                    #    v5 用"落入即触发"+全场点,网格超时点几乎每弦都触发,
                    #    池约束解除后成为密度暴涨主推手)
                    viol = any(((bb - a0) % 360) < arc and dd < r_at(bb, cur) - 40
                               for bb, dd in ev)
                    # ② 长弦:端点直线距离 >200m
                    long_chord = chord_len(a0, b % 360,
                                           cur[a0], cur[b % 360]) > 200
                    # ③ 低估/高估自检:弦中点方位与实测边界差 >60m(双向!)
                    lowbias = abs(r_at(mb0, cur) - L) > 60
                    # ④ 梯度规则(S5G 同源):dz/arc > 12 m/° → 陡弦(2026-09-02 统一)
                    grad = abs(cur[a0] - cur[b % 360]) / max(arc, 0.1) > 12
                    if viol or long_chord or lowbias or grad:
                        inserts.append(mb0)
                if not inserts:
                    break
                for bb in inserts:
                    L = ladder_r(bb)
                    if L is None:
                        continue
                    # 凸出封顶:插入值不能比两侧邻向最大值高 60m 以上
                    # (防止单点跳变造成多边形尖刺——上海 146.2° 凸 127m 实证)
                    ks2 = sorted(cur)
                    idx = _bs_idx(ks2, bb)
                    left = cur[ks2[(idx - 1) % len(ks2)]]
                    right = cur[ks2[(idx + 1) % len(ks2)]]
                    cap = max(left, right) + 60
                    cur[bb] = min(L, cap)
            return cur

        # v5:参考集 = 场阶梯实测边界(见 refine_adaptive 内),无需 full 集合
        radii8r = refine_adaptive(dict(radii8), None)
        print(f"  8向+弦规则加密 → {len(radii8r)} 向")

        G = get_graph(slug, center)
        oracle = OsmOracle(G, center) if G else None
        clat, clng = to_wgs(center)

        if G is not None:
            fig, ax = ox.plot_graph(G, bgcolor="white", node_size=0, edge_color="#d8d8d8",
                                    edge_linewidth=0.4, show=False, close=False,
                                    figsize=(10, 10), dpi=300)
        else:
            fig, ax = plt.subplots(figsize=(10, 10), dpi=300)
            ax.set_facecolor("white")
            print("  ℹ️ 无 OSM 底图" + ("(小城市按指示跳过路网)" if slug in NO_NET
                                       else "(端点全失败)"))
        ax.set_aspect(1 / math.cos(math.radians(clat)))

        # ---- 2. 时间场等值带(背景,全部采样点)+ 按网格分辨率分色的实测 15min 线 ----
        pts = list(field.keys())
        xs = np.array([to_wgs(p)[1] for p in pts])
        ys = np.array([to_wgs(p)[0] for p in pts])
        ts = np.array([field[p] for p in pts])
        try:
            ax.tricontourf(xs, ys, ts, levels=[0, 300, 600, 900, 1200, 2600],
                           cmap="RdYlGn_r", alpha=0.35)
        except Exception as e:
            print("  等值带失败:", str(e)[:60])

        grid_n = {}

        def grid_contour(spacing, half, color, ls_, lw, label):
            """规则格网 marching-squares 15min 线 + 覆盖范围框;缺失格掩码跳过。"""
            n = int(2 * half // spacing)
            idx = range(-n // 2, n // 2 + 1)
            X, Y, Z, miss = [], [], [], 0
            for i in idx:
                lat0, lng0 = dest_at(center[1], center[0], 0, i * spacing)
                rx, ry, rz = [], [], []
                for j in idx:
                    p = dest_at(lng0, lat0, 90, j * spacing)
                    la, ln = to_wgs(p)
                    rx.append(ln)
                    ry.append(la)
                    v = field.get(key(p))
                    rz.append(v if v is not None else np.nan)
                    if v is None:
                        miss += 1
                X.append(rx)
                Y.append(ry)
                Z.append(rz)
            total = (n + 1) ** 2
            grid_n[spacing] = total - miss     # 该方法实际调用对数
            if total - miss < 40:
                print(f"  {label}:有效点不足,跳过")
                return
            Zm = np.ma.masked_invalid(np.array(Z))
            Xa, Ya = np.array(X), np.array(Y)
            try:
                ax.contour(Xa, Ya, Zm, levels=[TH], colors=[color],
                           linewidths=[lw], linestyles=[ls_])
            except Exception as e:
                print(f"  {label}失败:{str(e)[:50]}")
                return
            # 覆盖范围框(浅灰点线)
            bx0 = min(Xa[0][0], Xa[-1][0]); bx1 = max(Xa[0][0], Xa[-1][0])
            by0 = min(Ya[0][0], Ya[-1][0]); by1 = max(Ya[0][0], Ya[-1][0])
            ax.plot([bx0, bx1, bx1, bx0, bx0], [by0, by0, by1, by1, by0],
                    color="#bbbbbb", lw=0.7, ls=":", zorder=3)
            print(f"  {label}:覆盖 {total-miss}/{total}")

        # ---- 重建场 15min 线(50m 分辨率,Delaunay over 全部实测样本)----
        # 50m 实测框(±500m)在多数城市整体处于边界以内,测不到 900s 交点;
        # 等时线必须来自覆盖全域的重建场:E6 选型 Delaunay 线性插值到 50m 格。
        from scipy.interpolate import griddata as _gd
        fx = np.array([to_wgs(p)[1] for p in pts])
        fy = np.array([to_wgs(p)[0] for p in pts])
        ft = ts
        gx, gy, gz = [], [], []
        for i in range(-23, 24):
            for j in range(-23, 24):
                p = dest_at(center[1], center[0],
                            math.degrees(math.atan2(j, i)) if (i or j) else 0,
                            math.hypot(i, j) * 50)
                la, ln = to_wgs(p)
                gx.append(ln)
                gy.append(la)
        gz = _gd(np.column_stack([fx, fy]), ft, np.column_stack([gx, gy]), method="linear")
        # 弦验证式约束:格点到中心距离超过该向成品边界+80m 时置 NaN,
        # 防止 Delaunay 在射线稀疏扇区外推出假凹陷/假延伸(成都曾凹到 426m)
        kcos = math.cos(math.radians(clat))
        n_clip = 0
        for k2, (ln_, la_) in enumerate(zip(gx, gy)):
            dd = math.hypot((la_ - clat) * 111320,
                            (ln_ - clng) * 111320 * kcos)
            bb = math.degrees(math.atan2((ln_ - clng) * kcos, la_ - clat)) % 360
            if dd > r_at(bb, radii) + 80:
                gz[k2] = np.nan
                n_clip += 1
        print(f"  重建场:弦约束裁掉 {n_clip} 格(超出该向边界+80m)")
        n_half = 47
        Xr = np.array(gx).reshape(n_half, n_half)
        Yr = np.array(gy).reshape(n_half, n_half)
        Zr = np.ma.masked_invalid(np.array(gz).reshape(n_half, n_half))
        try:
            ax.contour(Xr, Yr, Zr, levels=[TH], colors=["k"], linewidths=[2.6])
            print("  重建场 15min 线(50m 分辨率)✓")
        except Exception as e:
            print("  重建场线失败:", str(e)[:60])
        # 50m 方法=黑重建场线(全样本 Delaunay),不再另画灰实测框线
        spacing = d.get("metrics", {}).get("truth_spacing") or 100
        coarse_sp = 100 if slug == "A" else (150 if slug == "B" else spacing)
        grid_contour(coarse_sp, 1050 if coarse_sp == 150 else 1000,
                     "#8c564b", "--", 2.0, f"{coarse_sp}m 网格")
        if slug == "A":
            grid_contour(200, 1000, "#7f7f7f", ":", 2.0, "200m 网格 15min 线")

        # ---- 3. 采样点散点(区分网格/射线/H3)----
        # 网格点:50m/真值格点上
        grid_keys = set()
        for sp in (50, 100, 150, 200, 250):
            for p in grid_points(center, sp, 1050 if sp == 150 else 1000):
                grid_keys.add(key(p))
        # 射线轨迹点(成品 tol15 + 8向 tol50)
        traj16 = replay_bisect_traj(field, center, sorted(radii), 15.0)
        # 统一口径(重放探针):每算法 = 其全部向的 tol15 二分阶梯长度
        # (轨迹前缀性:tol15 阶梯 ⊇ tol50,重放零 API 且不含格点噪声)
        c16 = sum(len(s) for s in traj16.values())    # 自适应16起步
        traj16u = replay_bisect_traj(field, center,
                                     [i * 22.5 for i in range(16)], 15.0)
        c16u = sum(len(s) for s in traj16u.values())  # 16向均匀
        traj8u = replay_bisect_traj(field, center,
                                    [i * 45.0 for i in range(8)], 15.0)
        c8u = sum(len(s) for s in traj8u.values())    # 8向均匀
        traj8r = replay_bisect_traj(field, center, sorted(radii8r), 15.0)
        c8r = sum(len(s) for s in traj8r.values())    # 8向+加密
        traj_keys = set()
        for b, seq in traj16.items():
            for dd, _ in seq:
                traj_keys.add(key(dest_at(center[1], center[0], b, dd)))
        g_x = [to_wgs(p)[1] for p in pts if key(p) in grid_keys and key(p) not in traj_keys]
        g_y = [to_wgs(p)[0] for p in pts if key(p) in grid_keys and key(p) not in traj_keys]
        g_t = [field[p] for p in pts if key(p) in grid_keys and key(p) not in traj_keys]
        sc = ax.scatter(g_x, g_y, c=g_t, cmap="RdYlGn_r", vmin=0, vmax=1800,
                        s=9, marker="s", edgecolors="none", zorder=5)

        # ---- 4. 射线轨迹与探针点(基线/加密分色分线型,点与线分开)----
        UNIF = [i * 22.5 for i in range(16)]

        def near_unif(b):
            return any(min(abs(b - u) % 360, 360 - abs(b - u) % 360) < 1.5
                       for u in UNIF)

        def draw_ray(b, r, color, lw, ls_="-", alpha=0.85):
            pp = dest_at(center[1], center[0], b, r)
            ax.plot([clng, to_wgs(pp)[1]], [clat, to_wgs(pp)[0]],
                    color=color, lw=lw, ls=ls_, alpha=alpha, zorder=6)

        def draw_probe(b, dd, marker, color, ms):
            pp = dest_at(center[1], center[0], b, dd)
            ax.plot(to_wgs(pp)[1], to_wgs(pp)[0], marker,
                    color=color, ms=ms, alpha=0.75, zorder=6, ls="none")

        # S5b 插入向标记(非 22.5° 网格、非 8 向均匀、非 v6 加密集 = S5b/REBAL 渲染增强)
        _grid_set = {round(i * 22.5, 2) for i in range(16)}
        _s5b_set = {b for b in radii
                    if min(abs(b - round(b / 22.5) * 22.5) % 360,
                           360 - (abs(b - round(b / 22.5) * 22.5)) % 360) > 0.6
                    and b not in radii8r}

        for b, seq in sorted(traj16.items()):
            if b in _s5b_set:
                continue      # S5b 渲染增强向:不画射线(数据保留,图降噪)
            if near_unif(b):
                # 16 向均匀基线:射线(绿实)+ 探针点(绿点)
                if b in radii16:
                    draw_ray(b, radii16[b], "#2ca02c", 0.9)
                    for dd, _ in seq:
                        draw_probe(b, dd, "o", "#2ca02c", 3)
                # 自适应成品同向:红实细线
                draw_ray(b, r_at(b, radii), "#cc3333", 0.8)
            else:
                # 加密向(自适应新增,非 S5b):深红虚线 + 深红三角探针
                draw_ray(b, r_at(b, radii), "#8b1a1a", 1.3, "--")
                for dd, _ in seq:
                    draw_probe(b, dd, "^", "#8b1a1a", 4)
        # ---- 4b. 每向多个 15min 穿越点 + 复通带楔形(垂直凹陷的完整轮廓)----
        klat2 = 111320.0
        klng2 = 111320.0 * math.cos(math.radians(center[0]))

        def pb(p):
            return (math.hypot((p[0] - center[0]) * klat2, (p[1] - center[1]) * klng2),
                    math.degrees(math.atan2((p[1] - center[1]) * klng2,
                                            (p[0] - center[0]) * klat2)) % 360)

        lad = {}
        for p, t in field.items():
            dd, bb = pb(p)
            nb = min(radii, key=lambda x: min(abs(x - bb), 360 - abs(x - bb)))
            if min(abs(nb - bb), 360 - abs(nb - bb)) <= 1.2:
                lad.setdefault(nb, []).append((dd, t))
        n_cross = 0
        for b, seq in lad.items():
            seq.sort()
            for (d1, t1), (d2, t2) in zip(seq, seq[1:]):
                if (t1 <= TH) != (t2 <= TH):
                    pp = dest_at(center[1], center[0], b, (d1 + d2) / 2)
                    ax.plot(to_wgs(pp)[1], to_wgs(pp)[0], "X",
                            color="#b0006d", ms=5, zorder=7.5, ls="none")
                    n_cross += 1
        n_band = 0
        for pk in (d.get("pockets") or []):
            if not isinstance(pk.get("gap"), list) or not pk.get("outer"):
                continue
            b, w = pk["bearing"], pk.get("wedge_deg", 2.8)
            xs, ys = [], []
            for k2 in range(11):
                bb2 = b - w + 2 * w * k2 / 10
                q = dest_at(center[1], center[0], bb2, pk["gap"][1])
                xs.append(to_wgs(q)[1])
                ys.append(to_wgs(q)[0])
            for k2 in range(11):
                bb2 = b + w - 2 * w * k2 / 10
                q = dest_at(center[1], center[0], bb2, pk["outer"])
                xs.append(to_wgs(q)[1])
                ys.append(to_wgs(q)[0])
            ax.fill(xs, ys, facecolor="#008b8b", alpha=0.25,
                    edgecolor="#008b8b", lw=1.2, zorder=5)
            n_band += 1
        # 圈内间隔楔形(OK-X-OK 的实测超时带,边界内不可达楔)
        from matplotlib.patches import Patch as _Patch
        n_inner = 0
        for pk in (d.get("interior_gaps") or []):
            g = pk.get("gap") or []
            if len(g) != 2 or g[1] - g[0] < 20:
                continue
            b, w = pk["bearing"], pk.get("wedge_deg", 1.2)
            xs, ys = [], []
            for k2 in range(7):
                bb2 = b - w + 2 * w * k2 / 6
                q = dest_at(center[1], center[0], bb2, g[0])
                xs.append(to_wgs(q)[1]); ys.append(to_wgs(q)[0])
            for k2 in range(7):
                bb2 = b + w - 2 * w * k2 / 6
                q = dest_at(center[1], center[0], bb2, g[1])
                xs.append(to_wgs(q)[1]); ys.append(to_wgs(q)[0])
            ax.fill(xs, ys, facecolor="#7f1d1d", alpha=0.4,
                    edgecolor="#7f1d1d", lw=1.0, hatch="//", zorder=5)
            n_inner += 1
        print(f"  15min 穿越点 {n_cross} 个 | 复通带 {n_band} 个 | 圈内间隔楔 {n_inner} 个")

        bx = [to_wgs(dest_at(center[1], center[0], b, r_at(b, radii)))[1] for b in radii]
        by = [to_wgs(dest_at(center[1], center[0], b, r_at(b, radii)))[0] for b in radii]
        ax.scatter(bx, by, s=22, color="#cc3333", zorder=7, edgecolors="k", linewidths=0.4)

        if radii8:
            t8 = replay_bisect_traj(field, center, sorted(radii8), 50.0)
            for b, seq in t8.items():
                draw_ray(b, r_at(b, radii8), "#ff8c00", 1.6)  # 8向:橙实粗线
                for dd, _ in seq:
                    draw_probe(b, dd, "o", "#ff8c00", 3)
        # 8向+加密(v6 新增向):橙色虚线(与 8 向均匀区分)
        if radii8r:
            for b in sorted(set(radii8r) - set(radii8)):
                draw_ray(b, radii8r[b], "#e69500", 1.1, "--")
        # 统一重放口径对数(见上方 c16 定义):每算法自己的 tol15 二分阶梯
        print(f"  对数:自适应16起步 {c16} | 16向均匀 {c16u} | 8向均匀 {c8u} | "
              f"8向+加密 {c8r}({len(radii8r)}向)")

        # ---- 5. H3 六边形(仅 A)----
        h3_txt = ""
        h3_cnt = 0
        if slug == "A":
            try:
                import h3
                coarse_ok, band_cells, fine_ok, deep_ok = h3_cells_A(field, center)

                def draw_cells(cells, ec, lw, alpha, fc="none"):
                    for c in cells:
                        bnd = h3.cell_to_boundary(c)
                        lngs = [x[1] for x in bnd] + [bnd[0][1]]
                        lats = [x[0] for x in bnd] + [bnd[0][0]]
                        ax.fill(lngs, lats, facecolor=fc, edgecolor=ec, lw=lw,
                                alpha=alpha, zorder=4)

                draw_cells(coarse_ok, "#2ca02c", 0.7, 0.5)
                draw_cells(fine_ok, "#2ca02c", 0.4, 0.8)
                draw_cells(deep_ok, "#9467bd", 0.5, 0.9)
                h3_cnt = len(coarse_ok) + len(fine_ok) + len(deep_ok)
                h3_txt = f"H3:粗{len(coarse_ok)}+加密{len(fine_ok)}+深{len(deep_ok)}格"
                print(f"  {h3_txt}")
            except Exception as e:
                print("  H3 绘制失败:", str(e)[:80])

        # ---- 6. 方法多边形 ----
        px, py = poly_wgs(center, radii)
        ax.plot(px, py, "--", color="#d62728", lw=2.0, zorder=8)
        if radii8:
            p8x, p8y = poly_wgs(center, radii8)
            ax.plot(p8x, p8y, ":", color="#ff8c00", lw=2.4, zorder=8)
        if radii8r and len(radii8r) > len(radii8):
            p8rx, p8ry = poly_wgs(center, radii8r)
            ax.plot(p8rx, p8ry, "-", color="#ff8c00", lw=1.8, zorder=8)
        if radii16:
            p16x, p16y = poly_wgs(center, radii16)
            ax.plot(p16x, p16y, "-.", color="#2ca02c", lw=2.0, zorder=8)
        if oracle:
            oxl, oyl = [], []
            for b in range(0, 361, 2):
                lo, hi = 200.0, 1400.0
                for _ in range(9):
                    m = (lo + hi) / 2
                    pp = dest_at(center[1], center[0], b, m)
                    la, ln = to_wgs(pp)
                    if oracle.t_of(la, ln) <= TH:
                        lo = m
                    else:
                        hi = m
                la, ln = to_wgs(dest_at(center[1], center[0], b, (lo + hi) / 2))
                oxl.append(ln)
                oyl.append(la)
            ax.plot(oxl, oyl, "-.", color="#1f77b4", lw=1.6, zorder=8)

        # ---- 7. 指标 + 图例 + 色标 ----
        spacing = d.get("metrics", {}).get("truth_spacing") or 100
        eval_pts = [p for p in pts if key(p) in grid_keys]
        yt = [field[key(p)] <= TH for p in eval_pts]

        def m_of(rr):
            yp = []
            for p in eval_pts:
                dd = math.hypot((p[0] - center[0]) * 111320,
                                (p[1] - center[1]) * 111320
                                * math.cos(math.radians(center[0])))
                b = math.degrees(math.atan2(p[1] - center[1], p[0] - center[0])) % 360
                yp.append(dd < r_at(b, rr))
            _, _, _, f1 = cls_metrics(yt, yp)
            iou = (sum(1 for a, b2 in zip(yt, yp) if a and b2) /
                   max(1, sum(1 for a, b2 in zip(yt, yp) if a or b2)))
            return round(f1, 3), round(iou, 3)

        rows = {"自适应16起步": m_of(radii)}
        if radii16:
            rows["16向均匀(基线)"] = m_of(radii16)
        if radii8:
            rows["8向均匀(基线)"] = m_of(radii8)
        if radii8r and len(radii8r) > len(radii8):
            rows[f"自适应8起步({len(radii8r)}向)"] = m_of(radii8r)
        if oracle:
            yp = [oracle.t_of(*to_wgs(p)) <= TH for p in eval_pts]
            _, _, _, f1 = cls_metrics(yt, yp)
            iou = (sum(1 for a, b2 in zip(yt, yp) if a and b2) /
                   max(1, sum(1 for a, b2 in zip(yt, yp) if a or b2)))
            rows["OSMnx(参照)"] = (round(f1, 3), round(iou, 3))
        table[label] = rows

        ax.plot(clng, clat, "k*", markersize=15, zorder=9)
        handles = [
            Line2D([], [], color="#d62728", ls="--", lw=2,
                   label=f"自适应扇形·16起步({c16} 对)"),
            Line2D([], [], color="#2ca02c", ls="-.", lw=1.6,
                   label=f"16向均匀·基线({c16u} 对)"),
            Line2D([], [], color="#ff8c00", ls=":", lw=2.4,
                   label=f"8向均匀·基线({c8u} 对)"),
            Line2D([], [], color="#ff8c00", ls="-", lw=1.8,
                   label=f"自适应扇形·8起步→{len(radii8r)}向({c8r} 对)"),
            Line2D([], [], color="k", lw=2.6,
                   label=f"50m 网格·重建(全样本 {len(field)} 对)"),
            Line2D([], [], color="#8c564b", ls="--", lw=2,
                   label=f"{coarse_sp}m 网格({grid_n.get(coarse_sp, 0)} 对)"),
            Line2D([], [], color="#1f77b4", ls="-.", lw=1.6,
                   label="OSMnx 等时线(参照)"),
            Line2D([], [], color="#2ca02c", lw=1,
                   label="16向均匀·射线(绿)"),
            Line2D([], [], color="#ff8c00", lw=1.6,
                   label="8向均匀·射线(橙)"),
            Line2D([], [], color="#e69500", ls="--", lw=1.1,
                   label="8向加密新增向(橙虚)"),
            Line2D([], [], color="#cc3333", lw=1,
                   label="自适应16起步·射线(红)"),
            Line2D([], [], color="#8b1a1a", ls="--", lw=1.3,
                   label="自适应加密向(深红虚)"),
            Line2D([], [], color="#b0006d", lw=0, marker="X", ms=6,
                   label="15min 穿越点(每向可多个)"),
            Line2D([], [], color="#008b8b", lw=1.2, alpha=0.6,
                   label="复通带(隔离带外桥廊复通)"),
            _Patch(facecolor="#7f1d1d", alpha=0.4, edgecolor="#7f1d1d",
                   hatch="//", label="圈内间隔楔(实测不可达)"),
            Line2D([], [], marker="s", color="w", markerfacecolor="yellow",
                   markersize=7, label="采样点(按时长)"),
        ]
        if slug == "A":
            handles += [Line2D([], [], color="#7f7f7f", ls=":", lw=2,
                               label=f"200m 网格({grid_n.get(200, 0)} 对)"),
                        Line2D([], [], color="#2ca02c", lw=1,
                               label=f"H3 AMR·粗+带+深({h3_cnt} 对)"),
                        Line2D([], [], color="#9467bd", lw=1, label="H3 深加密格")]
        ax.legend(handles=handles, loc="upper right", fontsize=8, framealpha=0.9)
        txt = (f"{label} | 采样点 {len(field)} | 评估点 {len(eval_pts)}\n"
               + "\n".join(f"{k}: F1={v[0]} IoU={v[1]}" for k, v in rows.items())
               + ("\n" + h3_txt if h3_txt else ""))
        ax.text(0.02, 0.02, txt, transform=ax.transAxes, fontsize=9, va="bottom",
                bbox=dict(boxstyle="round", fc="white", ec="#888", alpha=0.9))
        fig.colorbar(sc, ax=ax, shrink=0.65, label="步行时长 (s)")

        out_png = os.path.join(MAPDIR, f"{slug}.png")
        fig.savefig(out_png, dpi=300, bbox_inches="tight")
        plt.close(fig)
        print(f"  已保存 {out_png}")

    mpath = os.path.join(ROOT, "experiments", "results", "maps", "map_metrics.json")
    prev = {}
    if only and os.path.exists(mpath):   # 局部重跑才增量合并;全量重跑整体重写
        try:
            prev = json.load(open(mpath, encoding="utf-8"))
        except Exception:
            prev = {}
    prev.update(table)
    json.dump(prev, open(mpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写入 map_metrics.json")


if __name__ == "__main__":
    main()

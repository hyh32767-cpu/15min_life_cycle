# -*- coding: utf-8 -*-
"""构建《15分钟生活圈 · 实验总集》ipynb(离线安全,零 API)

每节 = Markdown 说明 + 代码单元(读 results/json 与台账,现场重算展示)。
构建:python experiments/notebooks/build_notebook.py
执行:由 nbclient 逐格运行并内联输出(表/图),产物 实验总集.ipynb。
"""
import os
import sys

import nbformat as nbf

HERE = os.path.dirname(os.path.abspath(__file__))
NB_PATH = os.path.join(HERE, "实验总集.ipynb")

nb = nbf.v4.new_notebook()
md = lambda s: nbf.v4.new_markdown_cell(s)
code = lambda s: nbf.v4.new_code_cell(s)
C = []

# ---------- S0 总览 ----------
C.append(md("""# 15 分钟生活圈健康体检 · 实验总集

> 基于百度地图开放平台(直连 API)+ OSMnx 双仪器的等时圈方法学实验。
> 二十社区(直辖/省会/地级/县级)、全台账可审计(~2 万对调用)、本 notebook **全部离线重放,零 API**。
> 数据:`experiments/results/`;台账:`experiments/logs/calls.db`;报告:`docs/01-13`。"""))

C.append(md("""## 0.1 最终算法(一页纸)

```text
等时圈 = 射线二分(8 向起步×tol50) + 弦规则加密(实测超时证据/θ≥30°,收敛 k=16~87)
      + 多 15min 点(复通带 pocket={r, gap:[g0,g1], outer})
      + 多边形判定(边界) + Delaunay(时间场,50m 分辨率重建)
复杂地形 = 地形感知加向 + mid/ρ 双探针 + 弦差再平衡(Δ>150m 必插)
降级兜底 = 直线 × 城市绕行系数 ρ / 4.2 km/h
验证 = OSM 双仪器交叉(分层采信;落址前百度破平) + 弦/mid 探针作收敛判据(不是 F1)
成本 = 自适应8起步 104-212 对/城(低于 16 起步);含真值与验证 317-1034 对/城
```"""))

C.append(code("""import sys, os, json, math
import pandas as pd
sys.path.insert(0, os.path.abspath(os.path.join(os.getcwd(), '..', '..')))
from experiments.paths import RESULTS, LOGS

FILES = {'A': ('e4_sampling', 'e4.json', 'm4_radii'), 'B': ('e4_sampling', 'e4b.json', 'radii_final')}
SLUGS = ['A','B','shanghai','guangzhou','chengdu','harbin','xian','chongqing',
         'changsha','wuhan','luoyang','kunshan','guilin','zunyi','yiwu',
         'nanchang','huilongguan','zhangjiang','zhujiangxincheng','yulin_cd']
def load(slug):
    sub, fn, rk = FILES.get(slug, ('e10_boundary', f'e10x_{slug}.json', 'radii'))
    d = json.load(open(os.path.join(RESULTS, sub, fn), encoding='utf-8'))
    return d, {float(k): v for k, v in d[rk].items()}

rows = []
for s in SLUGS:
    d, r = load(s)
    m = d.get('metrics', {})
    fu = m.get('fusion', {})
    aniso = d.get('anisotropy') or round(max(r.values()) / max(1e-9, min(r.values())), 2)
    rows.append({
        '城市': d.get('city') or d.get('community') or s,
        '类型': d.get('type') or ('胡同步行街' if s == 'A' else '老居住区' if s == 'B' else ''),
        '射线': len(r), '各向异性': aniso,
        '半径m': f"{d['radius_range'][0]}-{d['radius_range'][1]}" if d.get('radius_range')
                else f"{min(r.values()):.0f}-{max(r.values()):.0f}",
        'IoU多边形': m.get('iou'), 'IoU融合+复通带': fu.get('R2并+口袋'),
        '带外误差': m.get('out_band_errors'), '复通带': len(d.get('pockets') or []),
        '总对数': d.get('pairs_used')})
df = pd.DataFrame(rows)
df"""))

C.append(md("""## 0.2 一图流结论

- **难度主变量是地形/水系,不是城市规模**:小城桂林(漓江)各向异性 4.62 二十社区之最,超过山城重庆 3.14
- **8 向起步+弦规则加密**十城全面省于 16 起步且收敛同形;k 值即城市难度(昆山 23 → 长沙 84)
- **F1/IoU 会说谎,弦/mid 探针才是收敛判据**(哈尔滨 8向 F1 反超成品;四城违规清零 IoU 一字不变)
- **OSM 只能初筛**:教育选址 OSM 100% → 百度实测 8.7%,换址后 87%——落址前必须百度破平"""))

# ---------- S1 仪器 ----------
C.append(md("""## 1. 仪器标定(E0-E2 + E3 并发)

回答:AK/签名/坐标系/批量测距可信吗?并发上限在哪?

- 五服务体检 + SN 签名踩坑(逗号安全表)+ IP 白名单切换 → `docs/01`
- 坐标系:BD-09(百度)/GCJ-02/WGS-84(OSM、H3)三系转换,`core/coord.py`(迭代逆推)
- 批量 routematrix:50 对/请求,~50× 加速;二分收敛阈值 15m 内时长 σ=0"""))

C.append(code("""e3 = json.load(open(os.path.join(RESULTS, 'e0_instrument', 'e3_concurrency.json'), encoding='utf-8'))
pd.DataFrame([{'档位QPS': k, **{kk: vv for kk, vv in v.items() if kk != 'statuses'},
               '状态分布': v['statuses']} for k, v in e3['tiers'].items()])"""))

C.append(code("""import sqlite3
con = sqlite3.connect(os.path.join(LOGS, 'calls.db'))
tot = pd.read_sql("SELECT COUNT(*) AS 次数, SUM(n_pairs) AS 对数 FROM calls", con)
by_eid = pd.read_sql(\"\"\"SELECT experiment_id AS EID, COUNT(*) AS 次数, SUM(n_pairs) AS 对数,
                       MIN(ts) AS 起, MAX(ts) AS 止 FROM calls GROUP BY 1 ORDER BY 对数 DESC\"\"\", con)
display(tot); by_eid.head(25)"""))

# ---------- S2 E4 ----------
C.append(md("""## 2. 采样策略对比(E4,杀手表)

七方法同场竞技(社区 A):均匀网格 50-250m / 射线 16-32 / 自适应扇形 / H3 AMR。
三轮口径修正(IDW→多边形→Delaunay)后的结论:**射线+多边形判定 ≈ 全网格,而调用数少 4 倍**。"""))

C.append(code("""ea = json.load(open(os.path.join(RESULTS, 'e4_sampling', 'e4_analysis.json'), encoding='utf-8'))
pd.json_normalize(ea)"""))

# ---------- S3 插值与绕行 ----------
C.append(md("""## 3. 插值选型(E6)与绕行系数(E5,二十社区 ρ 表)

- Delaunay 线性插值胜出(IDW 高次在凹口震荡;多边形分类快但无场)——即地图黑线"50m 网格·重建"
- ρ = 实际步行时长 / 直线时长@4.2km/h,降级兜底用;二十社区中位 1.29-1.98(桂林 0.91 为端点吸附效应,仅参考)"""))

C.append(code("""rho_rows = []
for s in SLUGS:
    d, _ = load(s)
    rho = d.get('rho') or {}
    rho_rows.append({'城市': d.get('city', s), 'ρ中位': rho.get('median'),
                     'τ(P75)': rho.get('tau_p75'),
                     '热弦数': len(rho.get('hot_chords') or [])})
pd.DataFrame(rho_rows)"""))

# ---------- S4 E10 ----------
C.append(md("""## 4. 极端边界与三防线(E10)+ 复通带

墙/河/铁路造成的幻影边界如何防:
1. **mid 探针**(弦中点 0.97r)抓凹口;2. **ρ 探针**抓跨障弦;3. **孤岛抽检** K 点终审。
收敛判据从"3 轮"改为**违规清零或预算耗尽**(四城续跑清零:西安 28/重庆 41/长沙 84/武汉 54 向)。
**复通带**:一根射线上 15min 线多次穿越(垂直凹腔),表示为 pocket={r, gap, outer},全二十社区共 6 条(哈×2/渝/沙/桂/遵)。"""))

C.append(code("""pk_rows = []
for s in SLUGS:
    d, r = load(s)
    for pk in (d.get('pockets') or []):
        if isinstance(pk.get('gap'), list):
            pk_rows.append({'城市': d.get('city', s), '方位°': pk['bearing'],
                            '主边界r': pk.get('r'), '隔离带m': f"{pk['gap'][0]}-{pk['gap'][1]}",
                            '复通至': pk.get('outer'), '半宽°': pk.get('wedge_deg')})
pd.DataFrame(pk_rows)"""))

# ---------- S5 地图 ----------
C.append(md("""## 5. 二十社区地图(v6 图层)

图例(方法本名+实际对数):自适应扇形·16/8起步、16/8 向均匀基线、50m 网格·重建(黑,
Delaunay+弦约束)、粗网格线、H3 AMR(仅A)、OSMnx 参照、射线(基线/加密分色)、
**玫红 X=每向全部 15min 穿越点**、**青绿楔=复通带**。小城五城按指示无 OSM 底图。"""))

C.append(code("""from IPython.display import Image, display
from PIL import Image as PILImage
os.makedirs('assets', exist_ok=True)
def show(slug, w=1000):
    src = os.path.join(RESULTS, 'maps', f'{slug}.png')
    dst = os.path.join('assets', f'{slug}_s.png')
    im = PILImage.open(src); im.thumbnail((w, w)); im.save(dst)
    display(Image(dst))
show('harbin')   # 最难:k=42,含 2 条复通带"""))
C.append(code("show('guilin')   # 各向异性之最 4.62(漓江),1 条复通带"))
C.append(code("show('kunshan')   # 最易:平原县级市,k=23,IoU 0.967"))
C.append(code("""# 多阈值等时线(5/10/15/20min,缓存重放零 API)与规模-难度回归
for f in ['multi_threshold_harbin.png', 'multi_threshold_kunshan.png',
          'multi_threshold_guilin.png', 'size_difficulty.png']:
    src = os.path.join(RESULTS, 'maps', f); dst = os.path.join('assets', f)
    im = PILImage.open(src); im.thumbnail((900, 900)); im.save(dst)
    display(Image(dst))"""))

# ---------- S6 优化与事故 ----------
C.append(md("""## 6. 边界优化三役与事故复盘(docs/13)

| 役 | 动作 | 二十社区平均 IoU |
|---|---|---|
| 基线 | 射线多边形 R0 | 0.904 |
| 一 | 融合分类器(多边形∪重建场,留出选优) | 0.933 |
| 二 | ρ 热弦插向 + 弦差再平衡(义乌针→有宽度凹槽) | 0.933 |
| 三 | 复通带并入(R2并+口袋) | **0.933** |

义乌"针"复盘:95.6°=486m vs 邻 842/805m——三射线距离阶梯证实为**真实窄槽**(铁路),
算法错在单射线渲染成针;弦差再平衡(Δ>150m 必插)修复。

**两次实现事故(教训:截断≠失败,必须显式暴露)**:
1. REBAL v1 预算按全局 EID 计数 → 首城耗尽后 14 城 bisect 零探针仍写盘(135 条 800m 假半径,已清);
2. BAND v1 二分方向写反(已重写)。v2 均加"零消耗批次整批丢弃"守卫。"""))

C.append(code("""rules = ['R0多边形', 'R1场', 'R2并', 'R3交', 'R4带内多边形+带外场', 'R2并+口袋']
agg = {r: [] for r in rules}
for s in SLUGS:
    d, _ = load(s)
    fu = d.get('metrics', {}).get('fusion', {})
    for r in rules:
        if fu.get(r) is not None:
            agg[r].append(fu[r])
pd.DataFrame([{'规则': r, '二十社区平均IoU': round(sum(v)/len(v), 3), '城数': len(v)}
              for r, v in agg.items()]).sort_values('二十社区平均IoU', ascending=False)"""))

# ---------- S7 OSMnx ----------
C.append(md("""## 7. OSMnx 双仪器交叉验证

OSM 作"参照真值"必须分层采信:一致性 r 从 0.12(陆家嘴,OSM 失真反例)到 0.93;
哈尔滨路网 943 节点经多端点重下复核(845)确认为棚改区真实肌理。详见 `docs/05/06`。"""))

C.append(code("""oc = json.load(open(os.path.join(RESULTS, 'osmnx', 'osmnx_cities.json'), encoding='utf-8'))
pd.json_normalize(oc).head(10) if isinstance(oc, list) else pd.json_normalize(oc)"""))

# ---------- S8 体检→处方→E8 ----------
C.append(md("""## 8. 体检 → 处方 → 一键管线(E7/E9/E10/E8)

哈尔滨·道外全链路(养老词表补全后 v2):
- **体检 94.1/100**(养老 0→6 家,单关键词→taxonomy 召回实证)
- **处方**(OSM 初筛+百度破平):养老 3 站百度口径 **98.5%**;教育换址 **87%**(旧址 OSM 100%→百度 8.7%)
- **E8 管线** `python experiments/pipeline.py`:地址→等时圈→体检→评分→选址→报告,**二跑零调用断言通过**"""))

C.append(code("""poi = json.load(open(os.path.join(RESULTS, 'poi', 'poi_harbin.json'), encoding='utf-8'))
W = {'医疗': .25, '教育': .20, '购物': .20, '药店': .15, '养老': .20}
n_in = poi['grid_blind']['n_inside_cells']
rows = []
for c, w in W.items():
    blind = poi['grid_blind']['by_cat'][c]['blind_gt15']
    rows.append({'类目': c, '权重': w, '格网覆盖率': f"{(n_in-blind)/n_in*100:.1f}%",
                 '15min内/总数': f"{poi['categories'][c]['n_in15']}/{poi['categories'][c]['n_total']}"})
dfp = pd.DataFrame(rows); display(dfp)
score = sum(w * (n_in - poi['grid_blind']['by_cat'][c]['blind_gt15']) / n_in * 100
            for c, w in W.items())
print(f"综合评分 {score:.1f} / 100(与 docs/09 手算一致)")"""))

C.append(code("""bk = json.load(open(os.path.join(RESULTS, 'osmnx', 'mclp_baidu_check.json'), encoding='utf-8'))
rows = []
for pname, blk in bk['results'].items():
    for site in blk['sites']:
        rows.append({'问题': pname, 'k': site['k'], '选址': tuple(site['site']),
                     'OSM%': site['osm_cum_pct'], '百度%': site['baidu_cum_pct']})
pd.DataFrame(rows)"""))

# ---------- S9 展望 ----------
C.append(md("""## 9. 已排期实验(docs/11 追加设计)与遗留

- **E11 邻近点缓存(跨源复用)**:离线用异源数据标定 ΔT(d) 包络 → 在线 A/B;预期省 20-40%
- **E12 起步向数路由**:免费信号(OSM aniso/河网/规模)+ 二十社区 k 标签 → 8/16 决策规则
- REBAL 未做的 7 城(上海/武汉/广州/B/昆山/A/成都,预算触顶,~250 对)
- 第二社区体检泛化(~30 对);盲区 20 格人工街景核对(人工)
- 配额:2026-08-31 单日 4770/5000 对,全台账 `calls.db` 可审计"""))

nb.cells = C
nb.metadata.kernelspec = {"name": "python3", "display_name": "Python 3 (.venv)"}
nbf.write(nb, NB_PATH)
print("built", NB_PATH, len(C), "cells")

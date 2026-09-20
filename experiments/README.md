# experiments/ 总索引(按实验阶段分包,与 docs/ 章节同构)

> **找东西的规则**:脚本在 `experiments/<阶段>/`,对应结果在 `experiments/results/<同名阶段>/`,
> 报告在 `docs/<编号-标题>.md`。三者一一对应。
> 新脚本取路径请 `from experiments.paths import RESULTS, LOGS, MAPS`。
> `logs/`(cache.db / calls.db / osm_*.graphml)被 `core/cache.py`、`core/ledger.py` 硬编码引用,勿移动。

| 阶段目录 | 回答的问题 | 脚本 | 主要产物(results/同名目录) | 报告 |
|---|---|---|---|---|
| `e0_instrument/` | AK/签名/坐标系/批量测距,仪器可信吗 | run_e0, run_e1, run_e2, **run_e3_concurrency**(2/4/8/16 QPS 测绘) | e0/e1/e2/derived/e3_concurrency.json | docs/01 |
| `e4_sampling/` | 七种采样方法谁准谁省(网格/射线/H3/自适应) | run_e4, run_e4b, run_e4_h3, run_50m_grids, analyze_e4, analyze_m9 | e4/e4b/e4_analysis/eval_setup/e50m_summary.json | docs/02 |
| `e5e6_interp/` | 空间插值选型 + 六城绕行系数 | analyze_e5e6 | e5e6.json | docs/03 |
| `e10_boundary/` | 极端边界与三防线;8向vs16向;新四城 | run_e10_cities, run_e10_topup, run_e10c_chord, analyze_e10_barrier, run_8ray_test, run_new4, **run_mid_clear**(违规清零), **run_small5**(小城五城), **run_rebalance**(弦差再平衡 v2), **run_bands**(复通带精测), **fix_metrics**(统一评估+融合选优), **analyze_offline_pack**(多阈值/ρ15城/规模-难度) | e10x_*.json ×8, e10c_chord/e10_barrier/e10_8ray.json | docs/04、08 |
| `osmnx/` | 独立参照真值、多城交叉验证、MCLP 选址 | run_osmnx_truth, run_osmnx_cities, analyze_mclp_harbin, **check_mclp_baidu**(百度复核), recheck_harbin_graph(路网复核) | osmnx_truth/osmnx_cities/mclp_harbin/mclp_baidu_check/mclp_edu_baidu.json | docs/05、06、10 |
| `poi/` | 哈尔滨 POI 盲区体检(养老/教育;含关键词缓存) | run_poi_harbin | poi_harbin.json, poi_search_cache.json | docs/09 |
| `maps/` | 十城综合地图(v5)+ 等值线诊断 | plot_maps, diag_contour | **results/maps/**:十城 png + map_metrics.json | docs/08 |
| —(根) | **E8 端到端管线**:`pipeline.py` 一键 地址→等时圈→体检→评分→选址→报告;缓存模式二跑零调用 | pipeline.py | docs/12 + logs/geocodes.json | docs/12 |
| `notebooks/` | **实验总集 ipynb**(26 格:说明+代码+内联表图,离线零 API);`build_notebook.py` 可重建 | 实验总集.ipynb | 内联结果 + assets 缩图 | 全部 docs |
| `notebooks/` | **从零开始·单城全流程演示 ipynb**(20 格,南昌·八一广场,真实 API 从 geocode 到成图);`build_demo_notebook.py` 可重建,重跑零成本 | 从零开始-单城全流程演示.ipynb | nanchang_demo.png + 内联结果 | docs/12 |

## 快查

- **"图在哪"** → `results/maps/*.png`(10 城,300dpi)+ `map_metrics.json`
- **"某城的边界射线数据"** → `results/e10_boundary/e10x_<城市>.json`(radii/metrics)
- **"全部原始调用记录"** → `logs/calls.db`(ledger)/ `logs/cache.db`(按 (origin,dest) 缓存)
- **"评估基准(留出点)"** → `results/e4_sampling/eval_setup.json`
- 城市代码:A/B=北京王府井/东花市,shanghai/guangzhou/chengdu/harbin/xian/chongqing/changsha/wuhan

## 重构备注(2026-08-26)

原为 22 个脚本 + 24 个 JSON 全部平铺;现按阶段分包,脚本内路径推导统一为三层 `dirname`,
脚本间 import 已改新包名(`experiments.e4_sampling.run_e4` 等)。全部脚本 `py_compile` 通过,
`plot_maps`/`diag_contour` 离线烟雾验证通过(零 API)。待配额恢复后如需复跑 run_*,注意
`run_osmnx_truth` 在 import 时即读取 results(`e4_sampling/e4.json` 等),缺文件会 ImportError。

# API 与算法预检报告

日期：2026-09-22。状态：**预检通过，应用已进入纯 live 交付基线**。本报告保留 API 适配基础与纯算法内核的预检证据，不替代当前 M0—M5 的全量验收；全量状态见 [docs/20](20-比赛演示与验收.md) 与 [docs/22](22-代码审查报告与修改方案.md)。

## 1. 预检目标与边界

- 目标：确认百度真实 API、现有 `core/` 适配层和等时圈算法在可复核的最小场景中可用；该预检已作为当前 live 服务的基础证据。
- 范围：地理编码/逆地理编码、Place 搜索/详情、步行 direction、步行方向矩阵、调用账本；CRS 往返、坐标采样、等时圈二分与“失败不伪造半径”。
- 不在本报告范围：同源 UI、缓存命中后的产品体验、多任务规划、社区体检和完整 M0—M5 验收。预检通过不等于功能完成。

## 2. 环境与隔离

| 项 | 结果 |
|---|---|
| Python | 3.9.6 |
| 服务端依赖 | 预检脚本只用标准库和仓库现有代码，未安装新依赖 |
| 百度认证 | `BAIDU_MAP_AK` 已配置；`BAIDU_MAP_SK` 为空，运行 AK-only 模式 |
| 历史台账 | `experiments/logs/calls.db` 仍为 7,582 次 / 38,699 对；预检未写入历史库 |
| 历史缓存 | `experiments/logs/cache.db` 仍为 31,408 条；预检未写入历史库 |

预检通过 `LEDGER_DB` / `CACHE_DB` 指向临时库，并要求核心代码支持该覆盖；因此新增的 live 调用不会混入历史实验台账。

## 3. 执行命令与结果

### 3.1 算法预检

```bash
python3 tools/preflight/algorithm_checks.py
```

结果：`Ran 11 tests ... OK`。覆盖：

- BD09 / GCJ02 / WGS84 往返误差 < 1m；
- `dest_at` 与 `haversine` 在 200—2000m、6 个方位角上相对误差 < 0.3%；
- 新纯函数 `core.isochrone.bisect_ray` 在合成线性测时上恢复 800m 阈值半径（tol 1m）；
- 初始探针缺失、二分中点缺失、下界内全超时、上界内全可达四种场景均返回 `failed + radius_m=None`，不写固定 800m 假半径；
- 现有研究函数 `bisect_rays`、历史 `replay_bisect` 在注入的实测场中恢复同一合成半径；后者仅是研究对照函数，不属于当前 live 运行链路；
- direction 矩阵响应、Place v3 `results[0]` / v2 `result` 的归一化。

### 3.2 真实百度 API 预检

```bash
python3 tools/preflight/api_smoke.py --report /tmp/15min_api_smoke_report.json
```

结果：`"ok": true`，7 次 live 请求全部 `status=0`，未使用缓存命中。

| # | 调用 | 结果摘要 |
|---|---|---|
| 1 | geocode `北京市昌平区回龙观` | 返回 BD09 坐标；confidence=25，precise=0 |
| 2 | reverse geocode | 返回 `北京市昌平区回龙观街道Y471` |
| 3 | place v2 search `药店` | `total=2`，返回 2 条；首条 UID/名称/坐标完整 |
| 4 | place v3 detail | `results[0]` 返回详情；有 `detail_info`、`navi_location`、非空 `shop_hours` |
| 5 | walking direction S→P | 575s / 674m；5 steps；path 可展平为 38 个点 |
| 6 | walking direction P→S | 575s / 674m（本次恰好对称，但实现不假设方向等价） |
| 7 | walking routematrix [S,P]×[P,S] | 4 个方向对；S→P=568s、P→S=568s，两条对角线为 0 |

账本核验：7 行记录，类型/状态/`n_pairs` 正确；成功 walking 行包含 `duration_s=575`、`distance_m=674`；matrix 行 `n_pairs=4`。这要求本次修正 `direction()` 在写账本前提取 duration/distance。

## 4. 发现并修正的问题

| 问题 | 处理 |
|---|---|
| Place v3 detail 返回 `results[0]`，原客户端只读 `result`，导致详情解析为空 | 新增 `place_detail()` 与 `place_detail_item()`，兼容 v3 `results[0]` 和 v2 `result` |
| walking direction 账本行只有 latency，没有 duration/distance | `get()` 增加 `metric_extractor`，`direction()` 在写账本前提取同一响应的 duration/distance |
| 产品/预检调用可能写入历史实验台账与缓存 | `core/ledger.py`、`core/cache.py` 支持 `LEDGER_DB` / `CACHE_DB` 覆盖，默认行为不变 |
| 研究二分遇到缺失探针时可能回退到区间中点，形成假半径风险 | 新增 `core/isochrone.py` 的 `bisect_ray`：缺失/异常返回 failed，不生成半径；M2 产品路径应使用该语义 |
| direction 只暴露动态属性，不便下游读取几何 | `ApiResult` 增加 `route`/`routes`，`direction()` 显式保存原始 route |

## 5. 仍未验证 / 下一步

- 未测试 SN 签名模式（当前 `SK` 为空），未覆盖 401 限流、302 配额、超时和拒绝权限等负路径；这些应在 M1 契约测试中用构造响应与受控实测补齐，不引入 replay 运行模式。
- Place 搜索的 `total` 只代表百度可检索结果，不代表现实全量；UI 必须使用“百度可检索 N 家”的措辞。
- `core/isochrone.py` 只完成单射线纯函数；M2 还需实现多射线批量、预算守卫、mid 探针、复通带和 `partial/degraded` 状态。
- 该预检阶段之后已完成 M0—M5 的产品骨架、live provider、真实响应缓存、账本和基础页面；当前未闭环项不再通过 replay 补齐，按 docs/20、docs/22 的纯 live 收尾清单处理。

## 6. 产物与命令留存

- 算法预检：`tools/preflight/algorithm_checks.py`
- API 预检：`tools/preflight/api_smoke.py`
- 纯算法内核：`core/isochrone.py`
- 适配层修正：`core/baidu_client.py`
- 账本/缓存隔离：`core/ledger.py`、`core/cache.py`
- 预检 JSON（临时）：`/tmp/15min_api_smoke_report.json`；命令和关键结果已固化在本文。

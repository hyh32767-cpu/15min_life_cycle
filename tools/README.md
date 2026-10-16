# 工具导航

从项目根目录运行Python模块，例如 `.venv/bin/python -m tools.demo.benchmark_planner --runs 30`。本页只提供入口，不会替你启动真实API实验。

## 日常开发

| 工具 | 用途 | 是否联网 |
| --- | --- | --- |
| `make api-test` / `make web-check` | 后端、前端单测与静态检查 | 测试禁止外网 |
| `make web-e2e` | 模拟业务接口的浏览器检查 | 不调用真实地图业务API |
| `tools.preflight.algorithm_checks` | 纯算法预检 | 否 |
| `tools.demo.benchmark_planner --runs 30` | 确定性合成OD下的规划器性能 | 否；不能当作完整算路时间 |
| `tools.demo.scan_release` | 检查候选发布目录的凭据、数据库误入 | 否；不替代全Git历史检查 |
| `tools.demo.build_release` | 从明确允许的文件生成本地源码包 | 否；不自动推送 |

`make setup`安装产品开发依赖，另有网络下载；这些依赖不包含全部研究绘图、PDF和配音工具。

## 算法研究

### 离线分析

| 模块 | 输入与产物 |
| --- | --- |
| `tools.demo.compare_outside_in_grid --group first` / `--group second` | 只读历史OD，两组五城AMR实验；默认输出到固定历史目录 |
| `tools.demo.compare_grid100_all` | 只读历史OD，盘点2×2公里100米格的数据完整性 |
| `tools.demo.replay_grid_frontier` | 从前一项的王府井参考结果构建方形前沿逐批记录 |
| `tools.demo.replay_disk_frontier` | 从方形参考结果生成圆盘过程数据和地图页 |
| `tools.demo.check_lanzhou_frontier` | 默认只读缓存复查；增加 `--live` 会发真实请求 |
| `tools.demo.render_fresh_timing` / `tools.demo.summarize_two_sites` | 读取已完成测速结果，生成图和汇总，不重新算路 |

这些不是干净源码安装后必然可运行的演示：需要历史私有数据和额外科学计算依赖，部分字体路径与本机有关；若要复现，先阅读脚本开头和[研究导航](../docs/research/README.md)。默认输出目录可能已有原始报告，先在副本中更改输出路径，再重算，避免用当前代码覆盖历史版本证据。

### 会消耗真实额度的实验

| 模块 | 开始前要知道 |
| --- | --- |
| `tools.demo.benchmark_frontier_vs_fan` | 按给定坐标比较网格与扇形；没有默认离线模式，可能数百对OD |
| `tools.demo.benchmark_fixed_grid` / `tools.demo.benchmark_grid75` | 网格测速，费用随位置数增加 |
| `tools.demo.benchmark_video_isochrone` | 视频示例中心的真实圈测量 |
| `tools.demo.benchmark_matrix_envelope --run-live` | 探测矩阵发送窗口，可能触发限流或配额上限 |
| `tools.preflight.product_live` / `community_live` / `route_band_live` | 真实链路检查，不属于默认单测 |
| `tools.demo.test_go_recommendations` | 使用本机Go登录测试模型，会消耗模型额度 |

不要批量执行全部实验脚本。先确定账号额度、坐标系、预算、缓存是否隔离与输出路径；记录成功、失败、缓存命中和请求对数，不能只留成功耗时。密钥从本地环境读取，不能进入结果、终端输出或公开包。

## 展示材料

| 文件 | 用途 |
| --- | --- |
| `demo/capture_release_video.cjs` | Playwright实际界面录制，需要运行前后端；界面操作会触发真实查询 |
| `demo/render_release_video.py` | 读取录屏、剪辑表与配音稿，生成视频和字幕；配音会联网 |
| `demo/build_project_intro_pdf.py` | 从实录截图与测点生成介绍PDF，不重新查地图 |
| `demo/export_cases.py` | 导出历史案例摘要供产品展示 |
| `demo/serve_prototype.py` | 原型预览工具 |

视频和PDF脚本保留这次制作参数及本机工具路径，不是通用安装器。缺少录屏、字体、ReportLab、FFmpeg或配音依赖时，需要先按脚本说明配置。精选展示文件见 [docs/media](../docs/media/README.md)，生成工作目录为 `output/`。

## 部署

腾讯云相关脚本与配置位于 [deploy/tencent/](deploy/tencent/)。阅读脚本参数和部署记录后再运行；部署与源码整理是独立操作。不要把运行凭据、证书、SSH密钥或持久数据库打进程序包。

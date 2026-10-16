# 第三方归属与许可边界

MIT 许可证适用于项目原创代码，不授予百度地图服务、地图瓦片、POI、路线响应、赛事材料或第三方依赖的再许可权。百度数据仅供本应用按开发者账户和平台服务协议使用；交付包不含服务器密钥、API 原始缓存或研究数据库。

主要组件：Vue / Vue Router / Pinia / Vite / TypeScript / Vitest / Playwright / FastAPI / Pydantic / Uvicorn；ECharts 使用 Apache-2.0，其余多数为 MIT 或 BSD。精确版本和完整传递依赖以 `web/package-lock.json`、`api/requirements*.txt` 为准，单个组件以其随附许可证为准，不以本表替代。

沿途范围几何并集使用 Shapely 2.2.0（BSD-3-Clause）及其 NumPy 依赖；Shapely 官方 wheel 随附 GEOS（LGPLv2.1），许可证保存在安装包的 `LICENSE_GEOS`。本源码 ZIP 不重打包这些二进制，通过锁文件安装原发行包并保留其归属；若另行分发二进制，应遵守随附许可。当前归属清单包含 281 npm 与 29 Python 包。

`demo-data/v1/cases/` 是已有研究结果摘要，标为历史案例，不能视作当前百度事实或新算法准确率。源码包不携带 `赛题.pdf`；赛题原文由用户本地提供，仅用于验收核对。

完整 npm / Python 依赖归属清单由 `python -m tools.demo.dependency_notices` 生成，见 `docs/dependency-notices.json`。遇到许可证缺失或非标准表达式需人工确认后再公开；第三方署名和许可证文件不能移除。

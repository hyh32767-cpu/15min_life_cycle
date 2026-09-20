# -*- coding: utf-8 -*-
"""experiments 统一路径出口(新脚本请从这里取路径,替代各脚本自行 dirname 推导)。

阶段子目录与脚本目录同名镜像:
    results/e0_instrument | e4_sampling | e5e6_interp | e10_boundary | osmnx | poi | maps
"""
import os

EXP = os.path.dirname(os.path.abspath(__file__))                # experiments/
ROOT = os.path.dirname(EXP)                                     # 项目根
RESULTS = os.path.join(EXP, "results")
LOGS = os.path.join(EXP, "logs")            # cache.db / calls.db / osm_*.graphml(core 依赖此位置)
MAPS = os.path.join(RESULTS, "maps")       # 十城图 + map_metrics.json

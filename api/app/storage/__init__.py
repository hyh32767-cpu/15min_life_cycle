# -*- coding: utf-8 -*-
"""产品缓存与调用账本。

M0 先固定独立目录边界;M1 实现请求规范化 hash、接口版本、cache hit
和本次 live 调用汇总,禁止混用历史 experiments 台账。
"""

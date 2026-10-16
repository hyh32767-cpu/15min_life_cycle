# -*- coding: utf-8 -*-
"""适配层公共异常。"""


class AdapterError(RuntimeError):
    """外部 API/数据适配失败,由路由层映射为结构化错误。"""

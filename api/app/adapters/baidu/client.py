# -*- coding: utf-8 -*-
"""百度 API 薄适配器(M0)。

方法返回 `core.baidu_client.ApiResult`;调用方负责把原始响应转换为
领域对象并落产品缓存/账本。M1 会在此层增加请求规范化、错误码映射
和产品级缓存/账本,而不是在路由里直接拼参数。
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from ..base import AdapterError


class BaiduAdapter:
    def __init__(self, request_timeout_s: float = 10.0,
                 app_key: str = "", sign_key: str = "") -> None:
        self.request_timeout_s = request_timeout_s
        self.app_key = app_key
        self.sign_key = sign_key

    @property
    def configured(self) -> bool:
        # F40：百度请求必须带 AK；SK 只是可选签名密钥，不能单独视为已配置。
        return bool(self.app_key.strip())

    def _invoke(self, method, *args, **kwargs):
        if not self.configured:
            raise AdapterError("live 模式未配置百度 AK（SK 不能替代 AK）")
        from core import baidu_client as bc  # 延迟导入；密钥经显式参数注入，不读模块全局

        with bc.product_context(self.app_key, self.sign_key):
            return getattr(bc, method)(*args, **kwargs)

    def geocode(self, address: str, *, city: Optional[str] = None,
                experiment_id: str = "api") -> Any:
        return self._invoke("geocode", address, city=city, experiment_id=experiment_id,
                                      timeout=self.request_timeout_s)

    def reverse_geocode(self, location: Tuple[float, float], *,
                        experiment_id: str = "api") -> Any:
        return self._invoke("reverse_geocode", location, experiment_id=experiment_id,
                                              timeout=self.request_timeout_s)

    def place_search(self, query: str, *, region: Optional[str] = None,
                     location: Optional[Tuple[float, float]] = None,
                     radius: Optional[int] = None, page_num: int = 0,
                     page_size: int = 20, experiment_id: str = "api") -> Any:
        return self._invoke("place_search",
            query, region=region, location=location, radius=radius,
            page_num=page_num, page_size=page_size, experiment_id=experiment_id,
            timeout=self.request_timeout_s,
        )

    def place_detail(self, uid: str, *, experiment_id: str = "api") -> Any:
        return self._invoke("place_detail", uid, experiment_id=experiment_id,
                                           timeout=self.request_timeout_s)

    def walking(self, origin: Tuple[float, float], destination: Tuple[float, float], *,
                experiment_id: str = "api") -> Any:
        return self._invoke("walking", origin, destination, experiment_id=experiment_id,
                                      timeout=self.request_timeout_s)

    def routematrix(self, origins: List[Tuple[float, float]],
                    destinations: List[Tuple[float, float]], *,
                    experiment_id: str = "api") -> Any:
        return self._invoke("routematrix",
            "walking", origins, destinations, experiment_id=experiment_id,
            timeout=self.request_timeout_s)

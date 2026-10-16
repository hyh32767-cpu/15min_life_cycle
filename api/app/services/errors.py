# -*- coding: utf-8 -*-
"""服务层结构化错误。"""
from __future__ import annotations

from typing import Any, Optional


class ServiceError(RuntimeError):
    def __init__(self, code: str, message: str, *, http_status: int = 400,
                 details: Optional[Any] = None, retryable: bool = False,
                 retry_after: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details
        self.retryable = retryable
        self.retry_after = retry_after

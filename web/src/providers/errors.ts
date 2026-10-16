export class ApiError extends Error {
  constructor(message: string, public readonly code: string, public readonly status = 0,
    public readonly retryable = false, public readonly retryAfterSeconds: number | null = null) {
    super(message)
    this.name = 'ApiError'
  }
}

export const apiErrorMessages: Record<string, string> = {
  CONFIG_ERROR: '地图服务尚未配置，请联系维护者',
  UPSTREAM_AUTH: '地图服务授权或配置异常，请联系维护者',
  QUOTA_EXCEEDED: '地图查询额度暂时用尽，已有有效结果仍可使用',
  RATE_LIMITED: '地图查询较多，请稍后重试',
  SERVICE_BUSY: '查询正在排队，请稍后重试',
  UPSTREAM_NETWORK: '地图服务连接失败，请稍后重试',
  UPSTREAM_TIMEOUT: '地图查询超时，请稍后重试',
  UPSTREAM_UNAVAILABLE: '地图服务暂时不可用，请稍后重试',
  UPSTREAM_RESPONSE: '地图服务返回不完整，请稍后重试',
  UPSTREAM_ARGUMENT: '地点查询参数无效，请重新选择地点',
  NO_ROUTE: '暂未查到可用的步行路线，请换个地点试试',
  NO_RESULT: '暂未找到地点，请输入完整地址或在地图选择',
  VALIDATION_ERROR: '请检查填写的信息后重试',
}

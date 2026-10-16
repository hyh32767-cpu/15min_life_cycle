import type { SourceKind } from './types'

/** T210：来源徽标点开后的解释文案。数据层（core/planner → api → types）已带全 sourceKind，这里只做展示映射。 */
export const SOURCE_COPY: Record<string, { label: string; detail: string }> = {
  'live-api': {
    label: '地图实时数据',
    detail: '来自本次百度地图查询的路线、距离和地点信息。',
  },
  'api-cache': {
    label: '已保存的地图数据',
    detail: '复用此前查询且仍在有效期内的百度地图结果。',
  },
  'user-input': {
    label: '用户输入',
    detail: '你填写的值（出发/截止时间、停留分钟、手动地点等）。',
  },
  'synthetic-assumption': {
    label: '模拟假设',
    detail: '排队、店内停留或临时事件的模拟值，可以调整。',
  },
  derived: {
    label: '计算结果',
    detail: '根据路线与安排计算的到达时间、办完时间和剩余时间。',
  },
  // F65：矩阵多批次部分命中缓存时的顶层聚合标记；各 cell 真实来源见 cell.sourceKind。
  mixed: {
    label: '混合来源',
    detail: '部分路段使用本次查询结果，部分复用有效期内的地图数据。',
  },
  unknown: {
    label: '未知',
    detail: '地图暂未提供这项信息。未提供营业时间时，请出发前确认。',
  },
}

export function sourceKindLabel(sourceKind: string | null | undefined): string {
  const key = sourceKind ?? 'unknown'
  return SOURCE_COPY[key]?.label ?? SOURCE_COPY.unknown.label
}

export function isochroneStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    complete: '已完成',
    partial: '部分完成',
    degraded: '范围不完整',
    failed: '测量失败',
  }
  return labels[status] ?? '状态未知'
}

export interface SourceDetail {
  title: string
  source: string
  detail: string
}

const KIND_TITLE: Record<string, string> = {
  travel: '路段用时',
  wait: '等待用时',
  service: '服务用时',
  returnTravel: '返程用时',
  departure: '出发时刻',
  deadline: '最晚到达',
  window: '营业窗口',
  slack: '剩余时间',
  totalTravel: '总路程（各段之和）',
  arrival: '到达时刻',
  finish: '办完时刻',
}

export function describeSource(
  kind: string,
  value: string,
  sourceKind: string | null | undefined,
): SourceDetail {
  const key = sourceKind ?? 'unknown'
  const copy = SOURCE_COPY[key] ?? SOURCE_COPY.unknown
  return {
    title: KIND_TITLE[kind] ?? kind,
    source: copy.label,
    detail: `${value}。${copy.detail}`,
  }
}

/** T212：无解原因码 → 人话。 planner._RELAXATION_HINTS 的前端镜像，只做展示。 */
const REASON_COPY: Record<string, string> = {
  OD_UNAVAILABLE: '部分路段用时查询未完成，请稍后重试',
  NO_ROUTE: '部分地点之间没有可用的步行路线',
  NO_RETURN_ROUTE: '没有可用的返程步行路线',
  DEADLINE: '按当前安排会超过最晚到达时间',
  CLOSED: '无法在关门前办完',
  EXTRA_BUDGET: '超过允许的绕行时间',
  PRECEDENCE_CYCLE: '地点先后顺序冲突，请调整',
  NO_OPTIONS: '还未选择要去的地点',
  NO_WALK_DISTANCE: '部分路段距离未查到，暂时无法比较步行距离',
  REQUIRED_TASK_CLOSED: '必去的地点已关闭，请更换地点或调整时间',
  NO_SOLUTION: '这些地点暂时无法一起安排',
  NO_TASKS: '还没有要去的地点',
  OVER_BUDGET: '超过时间预算',
  NO_REMAINING_TASKS: '已完成所有地点，可以前往终点',
  INVALID_INPUT: '输入信息不完整或格式不正确',
  EXTRA_BUDGET_EXCEEDED: '超过允许的绕行时间',
  ARRIVES_AFTER_DEADLINE: '预计到达终点时已超过最晚到达时间',
}

export function reasonLabel(reason: string): string {
  return REASON_COPY[reason] ?? '暂时无法安排，请调整地点或时间后重试'
}

const TIMELINE_KIND: Record<string, string> = {
  departure: '出发',
  travel: '路段',
  arrival: '到达',
  wait: '等待',
  service: '办理',
  taskFinish: '办完',
  returnTravel: '返程',
  homeArrival: '到家',
  deadline: '截止',
}

export function timelineKindLabel(kind: string): string {
  return TIMELINE_KIND[kind] ?? kind
}

export type { SourceKind }

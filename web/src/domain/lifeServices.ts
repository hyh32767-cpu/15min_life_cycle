import type { PlaceRef } from './types'

export type ServiceGroup = 'basic' | 'quality' | 'public'
export interface LifeService {
  id: string
  label: string
  group: ServiceGroup
  terms: string[]
  excludes?: string[]
  priority?: boolean
  note?: string
}

export const SERVICE_MATCH_VERSION = 'broad-related-v1'
export const SERVICE_MATCH_NOTE = '按相关生活服务设施宽口径统计，同一设施可计入多个类别'

// 保留服务分组，匹配使用用户指定的相关设施宽口径；查询别名和报告统一。
export const serviceGroups: { id: ServiceGroup; label: string }[] = [
  { id: 'basic', label: '基本便民' }, { id: 'quality', label: '品质生活' }, { id: 'public', label: '公共配套' },
]
export const lifeServices: LifeService[] = [
  { id: 'convenience', label: '便利店', group: 'basic', terms: ['便利店', '便民商店', '小卖部', '超市', '食杂店', '副食店', '杂货店'], priority: true },
  { id: 'supermarket', label: '综合超市', group: 'basic', terms: ['超市', '综合超市', '生鲜超市', '社区超市', '平价商店'] },
  { id: 'market', label: '菜市场', group: 'basic', terms: ['菜市场', '农贸市场', '农副产品市场', '菜场', '生鲜', '蔬菜店', '超市'], priority: true,
    note: '包含可购买生鲜蔬菜的超市、菜店' },
  { id: 'fresh', label: '生鲜菜店', group: 'basic', terms: ['生鲜', '蔬菜', '菜店', '水果店', '果蔬', '农贸市场', '超市'] },
  { id: 'breakfast', label: '早餐', group: 'basic', terms: ['早餐', '早点', '包子', '粥店', '小吃', '面馆', '快餐', '豆浆', '饼店'], priority: true,
    note: '按早餐及相关小吃快餐设施统计，未核验早餐营业时段' },
  { id: 'laundry', label: '洗衣洗染', group: 'basic', terms: ['洗衣', '干洗', '洗染', '洗护', '洗鞋', '皮具护理'] },
  { id: 'beauty', label: '美容美发', group: 'basic', terms: ['理发', '美发', '美容', '美甲', '美睫', '造型', '美体'] },
  { id: 'printing', label: '照相文印', group: 'basic', terms: ['照相', '摄影', '打印', '复印', '图文', '文印', '数码快印'] },
  { id: 'housekeeping', label: '家政', group: 'basic', terms: ['家政', '保洁', '清洁服务', '月嫂', '保姆', '家电清洗', '搬家服务'] },
  { id: 'repair', label: '小修小补', group: 'basic', terms: ['小修小补', '修鞋', '配钥匙', '维修', '修理', '开锁', '缝补', '改衣'], priority: true },
  { id: 'pharmacy', label: '药店', group: 'basic', terms: ['药店', '药房', '医药零售', '药品', '中药店', '大药房'], excludes: ['兽药', '宠物'], priority: true },
  { id: 'postal', label: '邮政快递', group: 'basic', terms: ['邮政', '邮局', '快递', '驿站', '收发室', '物流服务', '包裹'] },
  { id: 'recycling', label: '回收', group: 'basic', terms: ['再生资源', '废品', '回收', '旧物', '二手回收'], excludes: ['垃圾转运', '污水'] },
  { id: 'warehouse', label: '前置仓', group: 'basic', terms: ['前置仓', '生鲜配送', '配送站', '配送中心', '社区团购', '自提点'], note: '含配送及自提设施' },
  { id: 'car-wash', label: '洗车', group: 'basic', terms: ['洗车', '汽车美容', '汽车养护', '汽车保养', '汽车服务'] },
  { id: 'elderly', label: '养老', group: 'quality', terms: ['养老', '敬老', '日间照料', '老年护理', '老年活动中心', '康养', '老年公寓', '老年康护'],
    priority: true, note: '含老年活动、康养及照料场所' },
  { id: 'dining', label: '餐饮', group: 'quality', terms: ['餐厅', '饭店', '餐饮', '美食', '小吃', '快餐', '食堂'] },
  { id: 'bakery', label: '烘焙', group: 'quality', terms: ['蛋糕', '面包', '烘焙', '糕点', '甜品', '西点', '饼屋'] },
  { id: 'bookstore', label: '书店', group: 'quality', terms: ['书店', '书屋', '图书馆', '阅读', '阅览', '书吧', '图书'], note: '含图书馆及公共阅读场所' },
  { id: 'fitness', label: '健身', group: 'quality', terms: ['健身', '运动馆', '体育馆', '游泳', '球馆', '瑜伽', '舞蹈', '运动场'], excludes: ['体育用品'] },
  { id: 'childcare', label: '托育托管', group: 'quality', terms: ['托育', '托儿所', '幼儿托管', '幼儿园'], priority: true,
    note: '本项目按广义幼儿照护口径统计，包含幼儿园' },
  { id: 'training', label: '教育培训', group: 'quality', terms: ['培训', '教育', '学校', '学习中心', '辅导', '艺术', '文化宫'], note: '含学校及相关学习场所' },
  { id: 'tourism', label: '旅游服务', group: 'quality', terms: ['旅行社', '旅游', '旅行服务', '游客中心', '票务', '旅游咨询'] },
  { id: 'wellness', label: '保健养生', group: 'quality', terms: ['养生', '保健', '按摩', '推拿', '足疗', '足浴', '理疗'] },
  { id: 'florist', label: '鲜花礼品', group: 'quality', terms: ['花店', '鲜花', '花艺', '礼品', '花卉', '花坊'] },
  { id: 'cafe', label: '茶咖', group: 'quality', terms: ['咖啡', '茶馆', '茶艺', '奶茶', '茶饮', '饮品'] },
  { id: 'pet', label: '宠物服务', group: 'quality', terms: ['宠物', '动物医院', '兽医', '猫舍', '犬舍'] },
  { id: 'medical', label: '社区医疗', group: 'public', terms: ['社区卫生', '卫生服务', '卫生院', '诊所', '医院', '门诊', '卫生室', '口腔'],
    excludes: ['宠物', '兽医', '动物医院'], note: '含综合医院、专科及口腔医疗设施' },
  { id: 'primary-school', label: '小学', group: 'public', terms: ['小学', '实验学校', '中心学校', '九年一贯制学校'], excludes: ['培训', '辅导'], note: '含综合学校，未逐项核验小学学段' },
]

/** 同一服务用$做同义词并集；每组遵守百度圆形检索10词/45字符限制。 */
export function serviceQueries(service: LifeService): string[] {
  const queries: string[] = []
  let terms: string[] = []
  for (const term of service.terms) {
    if (terms.length === 10 || [...terms, term].join('$').length > 45) {
      queries.push(terms.join('$')); terms = []
    }
    terms.push(term)
  }
  if (terms.length) queries.push(terms.join('$'))
  return queries
}

/** 只使用名称/真实类别标签，不用地址附近的学校、医院等文字当作服务证据。 */
export function serviceMatch(service: LifeService, place: PlaceRef): 'matched' | 'excluded' | 'uncertain' {
  const text = [place.name, ...(place.tags ?? [])].join(' ')
  if (service.excludes?.some(term => text.includes(term))) return 'excluded'
  if (service.terms.some(term => text.includes(term))) return 'matched'
  return 'uncertain'
}

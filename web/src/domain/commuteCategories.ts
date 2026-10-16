export interface CommuteCategory {
  id: string
  label: string
  group: string
  query?: string
}

export const commuteCategories: CommuteCategory[] = [
  { id: '菜市场', label: '买菜', group: '吃喝购物', query: '菜市场$农贸市场$生鲜超市$蔬菜店' },
  { id: '美食', label: '吃饭', group: '吃喝购物' },
  { id: '药店', label: '买药', group: '健康护理' },
  { id: '超市', label: '购物', group: '吃喝购物' },
  { id: '快递', label: '取快递', group: '日常办事', query: '快递驿站$快递柜$邮政快递$快递' },
  { id: '便利店', label: '便利店', group: '吃喝购物' },
  { id: '早餐', label: '吃早餐', group: '吃喝购物', query: '早餐$早点$包子铺$粥店$小吃' },
  { id: '咖啡', label: '咖啡茶饮', group: '吃喝购物', query: '咖啡$奶茶$茶饮' },
  { id: '面包店', label: '面包甜点', group: '吃喝购物', query: '面包店$蛋糕店$甜品店' },
  { id: '水果店', label: '买水果', group: '吃喝购物' },
  { id: '商场', label: '逛商场', group: '吃喝购物' },
  { id: '洗衣店', label: '洗衣洗鞋', group: '日常办事', query: '洗衣店$干洗店$洗鞋店' },
  { id: '美容美发', label: '理发美容', group: '健康护理' },
  { id: '打印店', label: '打印复印', group: '日常办事', query: '打印店$复印店$图文快印' },
  { id: '手机维修', label: '手机维修', group: '日常办事' },
  { id: '银行', label: '银行', group: '日常办事' },
  { id: 'ATM', label: '取现金', group: '日常办事' },
  { id: '邮局', label: '寄信寄件', group: '日常办事' },
  { id: '卫生间', label: '找厕所', group: '日常办事', query: '公共厕所$卫生间' },
  { id: '医院', label: '医院', group: '健康护理' },
  { id: '宠物医院', label: '宠物护理', group: '健康护理', query: '宠物医院$宠物店$宠物美容' },
  { id: '书店', label: '逛书店', group: '休闲运动' },
  { id: '图书馆', label: '去图书馆', group: '休闲运动' },
  { id: '健身房', label: '运动健身', group: '休闲运动', query: '健身房$游泳馆$球馆' },
  { id: '公园', label: '公园散步', group: '休闲运动' },
]

export const shortcutCategoryIds = ['菜市场', '美食', '药店', '超市', '快递']
export const commuteCategoryGroups = ['吃喝购物', '日常办事', '健康护理', '休闲运动']
export function commuteCategoryLabel(id: string): string {
  return commuteCategories.find(item => item.id === id)?.label ?? id
}
export function commuteCategoryQueries(id: string): string[] {
  return [commuteCategories.find(item => item.id === id)?.query ?? id]
}

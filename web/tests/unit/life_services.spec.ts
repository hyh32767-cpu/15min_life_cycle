import { describe, expect, it } from 'vitest'
import { lifeServices, serviceMatch, serviceQueries } from '@/domain/lifeServices'
import type { PlaceRef } from '@/domain/types'

const place = (name: string, tags: string[] = [], address = ''): PlaceRef => ({ name, tags, address,
  coord: { lng: 116.36, lat: 40.09, crs: 'BD09' }, source: 'live-api' })
const service = (id: string) => lifeServices.find(item => item.id === id)!
describe('service semantics', () => {
  it('uses category evidence for brand names, never nearby address text', () => {
    expect(serviceMatch(service('pharmacy'), place('同仁堂', ['医疗;药店']))).toBe('matched')
    expect(serviceMatch(service('pharmacy'), place('同仁堂', [], '药店旁'))).toBe('uncertain')
    expect(serviceMatch(service('medical'), place('某宠物诊所', ['诊所']))).toBe('excluded')
    expect(serviceMatch(service('pharmacy'), place('宠物药房'))).toBe('excluded')
    expect(serviceMatch(service('elderly'), place('老年活动中心'))).toBe('matched')
    expect(serviceMatch(service('elderly'), place('街道日间照料中心'))).toBe('matched')
    expect(serviceMatch(service('elderly'), place('街道养老驿站'))).toBe('matched')
  })
  it('includes kindergartens in childcare while preserving other service boundaries', () => {
    expect(serviceMatch(service('market'), place('综合超市'))).toBe('matched')
    expect(serviceMatch(service('market'), place('街道农贸市场'))).toBe('matched')
    expect(serviceMatch(service('childcare'), place('某幼儿园'))).toBe('matched')
    expect(serviceMatch(service('childcare'), place('三一国际儿童学院', ['教育培训;幼儿园']))).toBe('matched')
    expect(serviceMatch(service('childcare'), place('某小学'))).toBe('uncertain')
    expect(serviceMatch(service('childcare'), place('某幼儿园托育中心'))).toBe('matched')
    expect(serviceMatch(service('primary-school'), place('小学辅导班'))).toBe('excluded')
    expect(serviceMatch(service('supermarket'), place('某生鲜超市'))).toBe('matched')
  })
  it('batches synonyms into bounded union queries without losing aliases', () => {
    for (const category of lifeServices) {
      const queries = serviceQueries(category)
      expect(queries.flatMap(query => query.split('$'))).toEqual(category.terms)
      expect(queries.every(query => query.length <= 45 && query.split('$').length <= 10)).toBe(true)
    }
    expect(serviceQueries(service('market'))).toEqual(['菜市场$农贸市场$农副产品市场$菜场$生鲜$蔬菜店$超市'])
    expect(lifeServices.every(item => serviceQueries(item).length === 1)).toBe(true)
  })
  it.each([
    ['convenience', '街角食杂店'], ['market', '社区生鲜超市'], ['fresh', '鲜果水果店'],
    ['breakfast', '沙县小吃'], ['laundry', '洗鞋护理'], ['beauty', '美甲美睫工作室'],
    ['printing', '摄影工作室'], ['housekeeping', '月嫂中心'], ['repair', '钟表修理'],
    ['pharmacy', '医药零售店'], ['postal', '社区收发室'], ['recycling', '旧物回收'],
    ['warehouse', '社区自提点'], ['car-wash', '汽车养护中心'], ['elderly', '老年活动中心'],
    ['dining', '社区食堂'], ['bakery', '甜品屋'], ['bookstore', '社区图书馆'],
    ['fitness', '社区体育馆'], ['training', '实验学校'], ['tourism', '游客中心'],
    ['wellness', '推拿理疗'], ['florist', '花卉中心'], ['cafe', '奶茶店'],
    ['pet', '动物医院'], ['medical', '口腔门诊'], ['primary-school', '九年一贯制学校'],
  ])('accepts related facilities for %s', (id, name) => {
    expect(serviceMatch(service(id), place(name))).toBe('matched')
    expect(serviceMatch(service(id), place('无明显类别的门店', [name]))).toBe('matched')
  })
})

import { createRouter, createWebHistory } from 'vue-router'
import { useIsochroneStore } from '@/stores/isochrone'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'commute', component: () => import('@/features/commute/CommutePage.vue') },
    { path: '/isochrone', redirect: '/community' },
    // 今天安排与执行已合并进通勤页 PlanPanel（零跳转）；旧路由重定向回收。
    { path: '/plan', redirect: '/' },
    { path: '/plans/:id', redirect: '/' },
    { path: '/plans/:id/run', redirect: '/' },
    { path: '/explore', redirect: '/' },
    {
      path: '/community',
      name: 'community',
      component: () => import('@/features/community/CommunityPage.vue'),
    },
    { path: '/cases', name: 'cases', component: () => import('@/features/cases/CasesPage.vue') },
  ],
})

router.beforeEach(() => !useIsochroneStore().busy)

export default router

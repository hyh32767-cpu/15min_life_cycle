<script setup lang="ts">
import { useMapRouteStore } from '@/stores/mapRoute'
import { formatDurationSeconds } from '@/domain/time'
const route = useMapRouteStore()
defineEmits<{ waypoint: []; destination: [] }>()
</script>
<template>
  <section
    v-if="route.destination"
    class="map-route-card"
    aria-label="地图地点路线"
  >
    <header>
      <strong>{{ route.destination.name }}</strong><button
        type="button"
        aria-label="关闭地图路线"
        @click="route.clear"
      >
        ✕
      </button>
    </header>
    <p v-if="route.destination.address">
      {{ route.destination.address }}
    </p>
    <p
      v-if="route.loading"
      role="status"
    >
      正在规划去这里的路线…
    </p>
    <p
      v-if="route.error"
      role="alert"
    >
      {{ route.error }}
    </p>
    <p v-if="route.result">
      <strong>步行 {{ formatDurationSeconds(route.result.route.durationSeconds) }}</strong> · {{ Math.round(route.result.route.distanceM) }} 米
    </p>
    <div class="map-route-card__actions">
      <button
        type="button"
        :disabled="route.loading"
        @click="$emit('destination')"
      >
        设为终点
      </button>
      <button
        type="button"
        class="primary"
        :disabled="route.loading"
        @click="$emit('waypoint')"
      >
        添加途经点
      </button>
      <button
        v-if="route.error && route.origin"
        type="button"
        @click="route.open(route.destination, route.origin, Boolean(route.destination.uid))"
      >
        重试路线
      </button>
    </div>
  </section>
</template>
<style scoped>
.map-route-card{position:absolute;bottom:12px;left:12px;right:12px;z-index:30;display:grid;gap:8px;padding:12px;border-radius:16px;background:white;color:#26344c;box-shadow:0 4px 20px #0f172a33;font-size:13px}header{display:flex;align-items:center;justify-content:space-between;gap:10px}header strong{min-width:0;overflow-wrap:anywhere}p{margin:0;color:#718098;line-height:1.5}.map-route-card__actions{display:flex;gap:8px;flex-wrap:wrap}button{font:inherit;min-height:44px;padding:8px 12px;border:1px solid #dfe5ef;border-radius:10px;background:white;color:inherit;cursor:pointer}.primary{background:#477beb;color:white;border-color:#477beb}button:disabled{opacity:.5}button:focus-visible{outline:3px solid #8cafff;outline-offset:2px}
</style>

<style scoped>
header strong { font-size: 17px; line-height: 1.5; }
</style>

<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 20 })
const paths: Record<string, string> = {
  search: 'm21 21-4.4-4.4M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  close: 'm6 6 12 12M18 6 6 18',
  bookmark: 'M6 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16l-6-4-6 4Z',
  circle: 'M21 12a9 9 0 1 1-9-9M12 7v5l3 2M17 3h4v4',
  route: 'M5 5h10a4 4 0 0 1 0 8H9a4 4 0 0 0 0 8h10M2 5h0M22 21h0',
  location: 'M12 2v3m0 14v3M2 12h3m14 0h3M19 12a7 7 0 1 1-14 0 7 7 0 0 1 14 0M14 12a2 2 0 1 1-4 0 2 2 0 0 1 4 0',
  plus: 'M12 5v14M5 12h14',
  minus: 'M5 12h14',
  check: 'm5 12 4 4L19 6',
  pin: 'M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0ZM15 10a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
  layers: 'm3 7 9-4 9 4-9 4-9-4Zm0 5 9 4 9-4M3 17l9 4 9-4',
}
</script>

<template>
  <svg
    class="app-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path :d="paths[name] || paths.pin" />
  </svg>
</template>

<style scoped>
.app-icon{display:inline-block;flex:none;vertical-align:middle}
</style>

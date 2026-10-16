<script setup lang="ts">
const emit = defineEmits<{
  (e: 'exit-prototype'): void
}>()
</script>

<template>
  <div class="proto-fullscreen-host">
    <iframe
      src="/prototype.html"
      title="顺路 15分钟生活圈全屏重构交互原型"
      class="proto-iframe"
    />
    <button
      type="button"
      class="exit-floating-btn"
      @click="emit('exit-prototype')"
    >
      切换旧版工程表单视图
    </button>
  </div>
</template>

<style scoped>
.proto-fullscreen-host {
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100vh;
  z-index: 9999;
  background: #fff;
}
.proto-iframe {
  width: 100%;
  height: 100%;
  border: 0;
  display: block;
}
.exit-floating-btn {
  position: fixed;
  bottom: 16px;
  left: 438px;
  z-index: 10000;
  border: 1px solid #cbd5e1;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(12px);
  color: #334155;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.10);
}
@media (max-width: 820px) {
  .exit-floating-btn {
    top: 52px;
    bottom: auto;
    left: auto;
    right: 12px;
  }
}
</style>

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import './styles/base.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
// Do not expose interactive shell controls until the initial lazy route is ready.
// Otherwise its completion can close a search dialog the user has just opened.
void router.isReady().then(() => app.mount('#app'))

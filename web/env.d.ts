/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 百度 JSAPI 底图用浏览器端 AK（可选；缺失时走 /api/maps/config 运行时获取） */
  readonly VITE_BAIDU_MAP_AK_BROWSER?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

# 腾讯云HTTPS与证书续期

日期：2026-10-13。用户要求线上HTTPS，服务器配置及公网验收已完成。

## 配置

- Let's Encrypt正式受信任IP证书，SAN为82.156.242.155，签发机构YE2，到期2026-10-20 00:34:16 UTC；未使用自签名证书或跳过证书校验。
- Certbot5.8.0独立环境 `/opt/shunshou/certbot-venv`；采用webroot及shortlived profile。官方说明：[Certbot IP证书支持](https://letsencrypt.org/2026/03/11/shorter-certs-certbot.html)。
- Nginx提供80/443入口，HTTP308跳转HTTPS并保留路径及查询参数；ACME挑战目录例外，用于无停机续期。后端仅监听127.0.0.1:18080，仍由专用用户和原环境/缓存运行。
- `shunshou-certbot.timer`每小时检查到期状态，随机延迟最多5分钟；renew成功后检查并重载Nginx。证书私钥仅在服务器权限目录，不进入源码包。
- 配置源位于 `tools/deploy/tencent/`：最终nginx.conf、后端服务与续期service/timer；nginx-http.conf用于首次申请前的HTTP代理。
- 最初公网443未放行，临时保留HTTP访问。用户控制台放行后，公网HTTPS校验成功，再启用308跳转。原应用及其它服务未更改。

入口：[通勤](https://82.156.242.155/)、[生活圈](https://82.156.242.155/community)。

## 验证

- 公网首页/生活圈HTTPS200，健康200、live及地图凭据配置状态正常；curl正常信任链验证结果0，IP SAN与有效期正确。
- HTTP生活圈308且Location保留/community。Nginx语法检查通过，应用/Nginx/续期定时器active，timer已开机启用。
- Certbot staging模拟续期成功，deploy hook执行Nginx检查和reload通过。此次使用--no-random-sleep-on-renew避免人工验收长等待，正常timer保留随机延迟。
- Playwright390×844真实浏览器：secureContext=true，geolocation可用，定位按钮存在，地图canvas=1，SDK可用，无横向溢出、页面错误或失败资源。未跳过TLS校验。第一次关闭网络代理的底图加载不成功，按环境正常代理复验，等待20秒截图确认道路、地名及POI底图加载完成。
- 两个初始化业务请求被验收拦截，未到达后端/百度；未读取真实设备位置，未做新增POI/路线/等时圈查询。真实设备定位成功及原生Computer Use未宣称通过。

HTTPS已解除浏览器安全上下文对定位入口的限制，实际位置仍需用户在自己的浏览器允许定位。

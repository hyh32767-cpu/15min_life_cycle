# 部署配置

完整步骤见 [安装与部署指南](../../../docs/deployment.md)。本目录不存放任何实际API密钥、SSH密钥或证书。

| 文件 | 用途 |
| --- | --- |
| `build_runtime.py` | 允许目录构建运行ZIP并扫描；不自动上传或部署 |
| `shunshou.service` | systemd服务，应用监听127.0.0.1:18080；内部旧命名保留兼容 |
| `nginx-domain-http.conf.example` | 首次HTTP连通模板，替换example.com |
| `nginx-domain-https.conf.example` | 正式HTTPS与HTTP跳转模板，替换域名及证书路径 |
| `nginx.conf` / `nginx-http.conf` | 原IP服务器配置记录，新服务器不要直接照用其中地址 |
| `shunshou-certbot.service` / `.timer` | 原服务器证书续期任务，依赖其专用环境和已签发证书；不是首次签发工具 |

服务凭据通过 `/etc/shunshou.env` 注入，持久缓存和账本在 `/var/lib/shunshou/`。升级只更换程序目录，保留这两处和证书。首次新建配置时不要覆盖已有部署的环境文件。

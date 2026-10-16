# 安装与部署指南

本文对应当前Vue前端与FastAPI后端，覆盖本地运行和Linux服务器首次部署。示例密钥全部留空，服务器名使用SSH别名 `shunlu-server`，域名使用 `example.com`，操作时替换为自己的配置。本文不要求公开仓库或上传原始地图数据。

## 1. 准备环境

本地安装Python 3.12、Node.js 22.12+、npm、make、Git；服务器准备Python 3.12及venv、systemd、Nginx和unzip。下面服务器命令以可使用sudo的Linux环境为例，不在Windows或macOS直接执行systemd命令。

```bash
git clone https://github.com/hyh32767-cpu/15min_life_cycle.git
cd 15min_life_cycle
make setup
cp .env.example .env
```

`make setup`创建 `.venv`，安装 `api/requirements-dev.txt`、前端锁定依赖及Playwright Chromium。生产服务器只需运行依赖，不需要浏览器测试环境；Node可以只安装在构建机器上。

## 2. 填写本地配置

编辑根目录 `.env`。下面是配置结构，空值须在自己的文件中填写，不要复制真实值到文档：

```dotenv
BAIDU_MAP_AK=
BAIDU_MAP_SK=
VITE_BAIDU_MAP_AK_BROWSER=
BAIDU_TIMEOUT_S=10
BAIDU_HTTP_TRANSPORT=system
BAIDU_MAX_QPS=10
BAIDU_MATRIX_PAIRS_PER_SECOND=3
BAIDU_INTERFACE_QPS=3
SHUNLU_LLM_API_KEY=
SHUNLU_LLM_MODEL=deepseek-v4.1-flash
```

| 配置 | 要求 |
| --- | --- |
| 百度服务端AK | 业务查询必填；根据访问方式配置服务端校验和所需接口权限 |
| 百度SK | 仅SN校验时使用的签名密钥，可选；不能把AK误填到SK变量 |
| 百度浏览器AK | 独立浏览器应用凭据，服务于JS API底图，配置实际访问地址的Referer白名单 |
| 大模型密钥 | 可选；当前接入OpenCode Go，填写该服务的访问密钥 |
| 大模型名称 | 默认 `deepseek-v4.1-flash`，需为对应账号可使用的模型 |

后端固定调用 `https://opencode.ai/zen/go/v1/chat/completions`，目前没有可配置的模型Base URL；不要填写其他厂商密钥并期待自动兼容。大模型密钥只在后端读取，不能加 `VITE_` 前缀。生产模式不会读取本机个人OpenCode登录。

浏览器AK按设计会发送给浏览器，并依赖Referer约束；服务端AK/SK和模型密钥不应出现在前端、构建包或浏览器请求头中。提交截图、日志或问题反馈时，把凭据值替换为 `[已隐藏]`，签名URL及Authorization头也应去掉。示例文件的空值不是可用密钥。

进程环境变量优先于 `.env`，后端配置修改后重启生效。`API_PORT`是启动和代理参数，单独修改根 `.env`不会改写已经运行的命令；如需换端口，给前后端启动命令同时传入同一值。

矩阵限流按OD路线对数计算，默认3对每秒；可选窗口变量见 [.env.example](../.env.example)。不要直接照抄历史实验的最高发送速率。模型请求设有超时、缓存和频率限制，缺少密钥或模型不可用时可继续使用非AI功能。

## 3. 本地启动与检查

日常开发，分别在两个终端运行：

```bash
make api-run
make web-dev
```

打开 `http://127.0.0.1:5173`。Vite将 `/api` 转发到18080；接口文档在 `http://127.0.0.1:18080/docs`。

模拟生产的单服务运行方式：

```bash
make demo
```

打开 `http://127.0.0.1:18080`，不需要另起Vite。停止同端口旧进程后再启动，避免端口占用。`make demo`会设置 `SHUNSHOU_SERVE_WEB=1`，AI因此需要显式配置模型密钥。

```bash
curl --fail http://127.0.0.1:18080/api/health
```

健康接口只检查进程与本地服务配置，不消耗地图业务查询，也不证明账号的所有外部接口都可用。实际搜索、算路、等时圈及模型操作会消耗相应额度，按需少量检查。

## 4. 构建与上传运行包

在本机项目根目录执行：

```bash
make web-build
.venv/bin/python -m tools.deploy.tencent.build_runtime
scp output/deploy/shunlu-grid-runtime.zip shunlu-server:/tmp/shunlu-runtime.zip
scp tools/deploy/tencent/shunshou.service shunlu-server:/tmp/shunshou.service
scp tools/deploy/tencent/nginx-domain-http.conf.example shunlu-server:/tmp/shunlu-nginx-http.conf
scp tools/deploy/tencent/nginx-domain-https.conf.example shunlu-server:/tmp/shunlu-nginx-https.conf
```

先在本机SSH配置中定义自己的 `shunlu-server` 别名，或将命令中的别名替换为实际 `用户名@地址`。不要在脚本、仓库或反馈中粘贴私钥内容。

运行包只包含允许的应用源码、前端构建、运行依赖清单、历史案例摘要和许可文件；不包含本机 `.env`、个人模型登录、原始数据库、证书和SSH密钥。`build_runtime`扫描通过才生成包，不自动部署。

## 5. 服务器首次安装

以下命令在服务器执行。创建专用用户、解压版本并安装运行依赖：

```bash
id shunshou >/dev/null 2>&1 || sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin shunshou
sudo install -d -m 755 /opt/shunshou/releases
sudo install -d -o shunshou -g shunshou -m 700 /var/lib/shunshou
release_tag=$(date +%Y%m%d-%H%M%S)
sudo unzip -q /tmp/shunlu-runtime.zip -d "/opt/shunshou/releases/$release_tag"
sudo python3.12 -m venv /opt/shunshou/venv
sudo /opt/shunshou/venv/bin/pip install -r "/opt/shunshou/releases/$release_tag/shunshou/api/requirements.txt"
sudo ln -sfn "/opt/shunshou/releases/$release_tag/shunshou" /opt/shunshou/current
```

源码和虚拟环境由管理员维护，应用用户仅写 `/var/lib/shunshou`。内部目录和服务名保留旧的 `shunshou`，产品名仍为顺路。

首次创建服务端环境文件；已有文件时不要覆盖：

```bash
sudo test -e /etc/shunshou.env || sudo install -o root -g root -m 600 /dev/null /etc/shunshou.env
sudoedit /etc/shunshou.env
```

填入第2节中的实际AK、浏览器AK与可选模型密钥。systemd环境文件使用简单的 `变量=值`，不写 `export`，不依赖shell变量展开。凭据只在此文件中填写，不通过命令行参数传递。

本项目服务文件已经设置生产模式和三项持久数据库路径：

```dotenv
SHUNSHOU_SERVE_WEB=1
LEDGER_DB=/var/lib/shunshou/ledger.db
CACHE_DB=/var/lib/shunshou/cache.db
DERIVED_DB=/var/lib/shunshou/derived.db
```

不要在环境文件里写不同的同名设置，以免和服务文件混淆。安装并启动服务：

```bash
sudo install -m 644 /tmp/shunshou.service /etc/systemd/system/shunshou.service
sudo systemctl daemon-reload
sudo systemctl enable --now shunshou
curl --fail http://127.0.0.1:18080/api/health
```

默认保持单个应用进程。异步任务、进行中请求和限流包含进程内状态，不要直接增加多个Uvicorn worker作为扩容方案。

## 6. Nginx与HTTPS

云安全组和主机防火墙放行公网TCP 80、443。后端18080只监听本机，不需要向公网开放。先使用HTTP模板检查反向代理：

```bash
sudo install -m 644 /tmp/shunlu-nginx-http.conf /etc/nginx/sites-available/shunlu
sudoedit /etc/nginx/sites-available/shunlu
sudo ln -sfn /etc/nginx/sites-available/shunlu /etc/nginx/sites-enabled/shunlu
sudo nginx -t
sudo systemctl reload nginx
```

将模板中的 `example.com` 改为实际域名，并让域名解析到服务器。同一域名不要重复启用冲突的Nginx配置。若系统使用 `conf.d` 而没有 `sites-enabled`，按其主配置的include目录放置文件。

正式访问配置受信任HTTPS证书：从自己的证书签发渠道取得证书链和私钥，仅保存在服务器。使用HTTPS模板前，将其中域名和下面两条路径改为实际位置：

```nginx
ssl_certificate /etc/ssl/shunlu/fullchain.pem;
ssl_certificate_key /etc/ssl/shunlu/privkey.pem;
```

证书已正确放置后：

```bash
sudo install -m 644 /tmp/shunlu-nginx-https.conf /etc/nginx/sites-available/shunlu
sudoedit /etc/nginx/sites-available/shunlu
sudo nginx -t
sudo systemctl reload nginx
```

HTTPS模板将HTTP请求跳转到HTTPS。域名证书不能直接用于不同IP地址；若坚持IP访问，需要匹配该IP的受信任证书和对应续期方案。手机定位需要HTTPS安全上下文及用户授权，普通公网HTTP无法提供相同体验。

根据实际签发渠道配置证书续期与到期提醒。本目录的旧Certbot任务只适配原服务器环境，不应在新服务器直接启用而不核对可执行路径、证书和续期方式。Nginx改动每次先通过 `nginx -t` 再重载。

## 7. 上线检查、更新与回退

将正式域名加入浏览器AK的Referer白名单，检查首页、`/community`、`/api/health`与HTTPS证书；再分别检查一次实际搜索、算路和按需AI操作。不要为了上线检查批量运行真实压测脚本。

更新时先构建新的运行包，解压到新的版本目录、核对依赖并按需更新虚拟环境，再切换 `current` 链接和重启服务：

```bash
sudo systemctl restart shunshou
sudo systemctl status shunshou --no-pager
curl --fail http://127.0.0.1:18080/api/health
```

保留上一版程序目录及对应依赖版本，失败时恢复上一版 `current`，必要时恢复其虚拟环境，然后重启。共享虚拟环境的依赖变更也会影响回退，不能只保留旧程序就假定随时可退。更新不删除 `/etc/shunshou.env`、`/var/lib/shunshou`或证书；备份数据库时停止服务或使用SQLite一致性备份。

## 8. 常见问题

| 现象 | 优先检查 |
| --- | --- |
| 健康接口提示配置错误 | AK变量是否填写到正确文件、systemd是否加载环境、是否重启 |
| 页面能打开但没有底图 | 浏览器类型AK、访问域名Referer、JS API资源网络情况 |
| 搜索或测圈被限流 | 账号权限及额度、按OD计算的窗口；不要连续点击重试 |
| 手机定位失败 | HTTPS证书是否受信任、浏览器位置授权与设备定位状态 |
| AI不可用但手动功能正常 | Go密钥、账号可访问模型、服务器到模型服务的连接；生产不读取个人登录 |
| `/community`刷新404 | 后端是否设生产模式、前端是否构建、Nginx是否代理整个路径 |
| Nginx返回502 | 应用服务是否启动、18080是否监听、反向代理端口是否一致 |
| 修改端口后前端请求失败 | Vite代理、后端启动参数、Nginx配置是否同步 |

进程排查可用 `sudo journalctl -u shunshou -n 100 --no-pager`。分享日志前先隐藏密钥、签名URL和个人位置等敏感内容。`.gitignore`只能阻止新文件被默认加入，不会清除已存在的Git历史；公开源码前另读 [SECURITY](../SECURITY.md)。

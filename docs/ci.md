# GitHub Actions设置

仓库已有 [.github/workflows/ci.yml](../.github/workflows/ci.yml)，不需要在GitHub重新选择工作流模板。将该文件及项目源码同步到仓库后，push和pull request事件会自动触发。

## GitHub页面配置

1. 打开仓库的 **Settings → Actions → General**。
2. 在 **Actions permissions** 中允许本工作流使用的GitHub官方Actions：`actions/checkout`、`actions/setup-python`、`actions/setup-node`。若使用允许列表，必须允许工作流中的固定提交版本。
3. **Workflow permissions**选择 **Read repository contents and packages permissions**。当前流程只读取代码、安装依赖和检查，不需要仓库写权限。
4. 保存后，在仓库 **Actions → ci** 查看运行。点击某一轮，可以分别查看`backend`、`frontend`的步骤与日志。

仓库页面入口：[Actions](https://github.com/hyh32767-cpu/15min_life_cycle/actions)、[设置](https://github.com/hyh32767-cpu/15min_life_cycle/settings/actions)。需要仓库管理权限；组织策略还可能限制可用Actions。

## 当前检查内容

| 任务 | 内容 |
| --- | --- |
| `backend` | Python 3.12、锁定运行/测试依赖、禁止外网的后端测试、发布候选文件扫描 |
| `frontend` | Node 22、npm锁定依赖、类型/格式/单测、构建、Chromium浏览器测试 |

默认CI不执行真实百度或大模型测试，**不需要添加百度AK、SK、浏览器AK或模型密钥到GitHub Secrets**。测试通过模拟响应检查程序行为；依赖安装需要联网。不要为了让测试通过，把本机 `.env` 上传到仓库。

当前工作流没有自动部署、上传运行包或连接服务器的步骤；Actions通过不会更新线上服务。部署操作见[部署指南](deployment.md)。

浏览器检查在CI中启动自己的前端服务，固定两个工作进程，禁止遗留`test.only`。所有用例均实际执行，不配置失败自动重试；失败时本地测试目录会保留Playwright追踪文件。首次同步后的缓存竞态和新版界面测试调整见[修复记录](85-CI失败修复与浏览器回归.md)。

## 怎样手动运行

当前只有push和pull request触发器，因此不显示手动运行入口。如需添加，在同一个`on`段中增加：

```yaml
on:
  push:
  pull_request:
  workflow_dispatch:
```

该变更同步到默认分支后，可以在 **Actions → ci → Run workflow** 选择分支手动运行。不要在文件中重复添加第二个`on`段。

## 看不到或运行失败

- 看不到`ci`：确认GitHub上的 `.github/workflows/ci.yml`确实存在，路径和扩展名正确，且Actions未被禁用。
- 提示Action被禁用：核对仓库/组织允许列表，允许上述三个官方Action及其提交版本。
- 安装失败：先看对应依赖安装步骤，确认Python/Node版本、锁文件与下载错误。
- 测试失败：打开失败步骤看具体用例，不要添加真实密钥或关闭失败测试来绕过。
- 想合并前必须通过：先让CI运行一次，再在分支规则中将`backend`、`frontend`设为必需状态检查；这不属于当前工作流自动配置内容。

参考：[GitHub官方Actions设置说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)、[手动运行工作流](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)。

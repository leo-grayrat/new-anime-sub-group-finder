# GitHub Pages 部署准备

本次只准备文件和本地验证，未创建 GitHub 仓库、推送代码或发布网页。

Pages 提供只读网页：番剧、近24h更新、按字幕组分组的季度屏蔽记录和未匹配资源。设置、手动采集和 MCP 使用本机服务。封面随网页导出，支持 `用户名.github.io/仓库名/` 项目路径。

## 本地导出与预览

在仓库目录运行：

```powershell
.venv\Scripts\python.exe -m fansub_finder.pages_export --output dist/pages
.venv\Scripts\python.exe scripts/smoke_pages.py dist/pages
```

导出读取 SQLite 的一致快照，默认不扫描，不需要停止常驻服务。缺少缓存的封面会通过已配置的代理获取；可加 `--no-covers` 跳过。输出不会复制 `config.json`、SQLite、日志或代理设置。

普通预览可运行 `.venv\Scripts\python.exe -m http.server 18767 --directory dist`，打开 `http://127.0.0.1:18767/pages/`。不要直接以 `file://` 打开。

## 以后发布

确认仓库公开范围后，再创建远端、推送代码。在 GitHub 仓库的 Settings → Pages 中选择 GitHub Actions，手动运行 **Build and deploy read-only monitor**。

已准备 `.github/workflows/pages.yml`：手动触发、main 分支更新，以及每小时第17、47分钟触发。GitHub 调度可能延迟，不等同于本机10分钟采集。任务在 GitHub Runner 上直连采集，不使用本机7897代理；数据和封面通过 Actions 缓存延续，网页显示来源错误及数据过期状态。

季度及公开筛选名单使用 `config.example.json`。本机 `config.json` 的自定义名单不会自动上传；发布前把希望公开使用的规则更新到配置示例。工作流设置 `FANSUB_PROXY` 为空，避免访问 Runner 自己的127.0.0.1。

首次扫描需要补齐目录、组与放送资料，部分来源失败时可能只有部分数据。缓存被清理后会重新建立清单。网页不会持续采集，近24h窗口会随浏览时间滚动过滤已导出的资源，新增资源等待下一次构建。停更时来源状态会显示过期。

GitHub Free 通常需要公开仓库，Pages 网页内容也将公开。发布前检查源码、示例和历史提交，不要把本机数据目录加入 Git。

参考：[GitHub Pages 概述](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)、[通过工作流部署](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。

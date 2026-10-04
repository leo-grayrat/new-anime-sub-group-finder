# 新番字幕组发现

在本机持续监控蜜柑、AnimeGarden、AniBT，把季度番剧的可用发布组和集数汇总到一个网页，并提供只读 MCP 查询。

## Windows 启动

已安装环境时，双击 `start.cmd`。命令行也可以运行 `powershell -File .\start.ps1`。

首次安装需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。运行 `uv sync --frozen`，之后启动服务。

- 网页：<http://127.0.0.1:18765>
- MCP：<http://127.0.0.1:18765/mcp>
- 保持启动窗口运行即可持续采集；关闭窗口或按 Ctrl+C 停止。
- 已有服务运行时，启动入口显示地址并退出。双击 `stop.cmd` 可停止本项目在默认端口的服务；它会先检查进程身份。
- 默认季度为 `2026-10`，每10分钟采集，每6小时刷新放送目录，每日补查。首次补查可能需要几分钟，页面可先查看已取得的结果。

`config.json` 是本机配置（不提交 Git），可复制 `config.example.json` 创建，也可在网页设置中编辑。默认代理为 `http://127.0.0.1:7897`；留空表示直连。所有远端请求使用这个配置，不依赖 Windows 系统代理。环境变量 `FANSUB_PROXY`、`FANSUB_DATA_DIR` 可覆盖文件中的值。

启动端口可以通过 `start.ps1 -Port 18966` 或 `python -m fansub_finder serve --port 18966` 修改。不要同时运行两个实例指向同一数据目录。

## 网页怎么用

“番剧”默认展示当季与跨季续播中有可用组的作品。取消“只看有可用组”可以看到尚无组的番剧。展开番剧看发布组，再展开组看集数和原站、磁力、种子链接。简繁版本、修正版均保留，磁力相同的跨站资源合并来源。

“新增字幕组”只记录首次出现的“番剧＋组”组合。第一次采集建立现有清单，不把历史组当作刚出现；后续集数、重启、解除屏蔽不会重复提醒。

“已屏蔽”保留原始资源和原因，修改规则会重算历史结果。默认名单包括 ANi、黒ネズミたち、Kirara Fantasia、Nix-Raws（含 Nix-Raw）、ToonsHub、Ansgwrt、沸班亚马（含制作组完整名称及Feibanyama）、Skymoon-Raws、YAYOI、Gecko；平台标签包括 CR、Crunchyroll、Baha、Bahamut、巴哈、巴哈姆特、CATCHPLAY、CATCHPLAY+。`WEB-DL` 不屏蔽。没有命中名单不等于已证明字幕原创。

已标明字幕语言且不含中文的资源默认排除，语言未知保留“未标注”。正文简介里的平台、官字说明也参与筛选；中文字幕证据从字幕轨取，不混用音轨语言。每轮按来源补查最多25条当季上传资源的详情，错误会显示在来源状态中。具体核对与排除依据见 [发布组核对记录](docs/group-review.md)。

“放送待核实”包含缺少可靠跨季证据的作品，可以手动覆盖归属。放送判定使用首播、当前放送日历、单集日期及已知最终集日期，不把上传日期当作正在放送的证据。“未匹配”保留无法可靠对应番剧的资源。

续播作品只在本季度（含开季前14天）有可用发布时列出该组，避免长篇详情页把多年前的打包发布组混入当前列表；已列出的组仍展示全部已采集集数，历史记录不删除。

“待核实发布者”可在设置中编辑，目前包含 NEST 及蜜柑“生肉/不明字幕”分类；资源保留在“已屏蔽”页并注明待核实原因。英文组名用于触发人工核查，不直接作为屏蔽条件。SweetSub 有明确中文字幕制作证据，继续保留；按用户要求，本轮新加的“字幕来源”署名判断对 LoliHouse（含联合署名）豁免，原有平台标签及语言规则仍生效。本轮核查范围与证据见 [AniBT 与英文发布组核查](docs/anibt-review.md)。

来源出错时保留旧数据，顶部和设置页显示错误与最后成功时间。集数表示**已经采集的记录**；AniBT RSS 有数量上限，离线过久可能无法回溯所有历史版本，每日补查会继续补充可取得的记录。

## 连接 MCP

推荐连接 HTTP 地址 `http://127.0.0.1:18765/mcp`。例如 Codex 配置：

```toml
[mcp_servers.fansub_finder]
url = "http://127.0.0.1:18765/mcp"
```

也支持 stdio：

```toml
[mcp_servers.fansub_finder]
command = "E:\\Project\\Git\\Tool\\new-anime-sub-group-finder\\.venv\\Scripts\\python.exe"
args = ["-m", "fansub_finder", "mcp", "--server", "http://127.0.0.1:18765"]
cwd = "E:\\Project\\Git\\Tool\\new-anime-sub-group-finder"
```

stdio 只查询已启动的常驻服务，不另外扫描站点。未启动服务会返回明确错误。不要同时为同一项目配置 HTTP 与 stdio 两个入口。

可询问：“十月新番有哪些可用字幕组？”“最近新增了哪些组？”“某组做到了第几集？”“蜜柑的数据是否过期？”工具为 `list_anime`、`list_groups`、`list_releases`、`list_changes`、`get_status`，均为只读。新增查询返回 `cursor`，下次传入 `after` 增量读取；`has_more=true` 时继续读取下一页，游标只推进到已检查的记录。时间采用 ISO 8601，网页显示本地时间。

## Docker

运行 `docker compose up -d --build`。默认宿主机仅暴露本机端口，配置和数据库均保存在挂载的 `data` 目录。需要预置配置时，创建 `data` 目录并将 `config.example.json` 复制为 `data/config.json`；也可以启动后在网页设置中保存。

容器默认直连，不能使用容器自己的 `127.0.0.1:7897` 访问宿主机 Clash。如需代理，在 Compose 环境设置 `FANSUB_PROXY=http://host.docker.internal:7897`（Docker Desktop），并确保该代理监听可从容器访问的地址；不要修改本机现有设置来迁就程序。Linux 环境应填写容器可访问的实际代理地址。

SQLite 数据在 `data/finder.sqlite`，停服务后备份整个 `data` 目录即可。容器持久化配置位于 `/app/data/config.json`，目录挂载支持设置文件的原子保存。

## 开发与验证

```powershell
uv sync --frozen
.venv\Scripts\python.exe -m pytest --basetemp .cache/pytest
.venv\Scripts\ruff.exe check --config pyproject.toml fansub_finder tests
node --check fansub_finder/static/app.js
```

`scripts/fetch_fixtures.py` 通过本机代理获取公开站点的小批量测试样本。`python -m fansub_finder scan --full` 用于单次完整补查（先停常驻服务）。

常驻服务运行时，`scripts/smoke_mcp.py` 联调 HTTP 和 stdio 的五个工具；`scripts/smoke_web.py` 使用已安装的 Edge 进行无窗口浏览器验证，截图位于 `.cache/web-verification`，不会操作用户的浏览器窗口。

站点适配器参考 [ani-rss](https://github.com/wushuo894/ani-rss) 的接口使用方式，解析代码在本项目独立实现。后台查询使用 [AniBT Open API](https://wiki.anibt.net/en/docs/open-api) 和 [AnimeGarden API](https://github.com/yjl9903/AnimeGarden)。不调用下载器，不发送外部消息。

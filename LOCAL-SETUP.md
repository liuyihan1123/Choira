# 本地部署记录（Windows / 本机实测）

> 说明：这份文件记录的是**某一台 Windows 机器**上的实际部署过程，里面提到的一些路径
> （便携版 Node、`..\run_pip.py`、`.tmp` 等）在这台机器之外并不存在。它不属于项目本体，
> 只是想跑起来看效果的话请看 `README.md`。

本文件记录我在当前机器上把这套装起来的实际步骤、与原 README 的差异、以及验证结果。
原始 Linux/macOS 说明见仓库根目录的 `README.md`。

## 结论：跑起来了

| 项 | 值 |
| --- | --- |
| 访问地址 | <http://127.0.0.1:8000> |
| 后端 | FastAPI + Uvicorn，`backend/app` |
| 前端 | React 19 + Vite 8 + OSMD，已构建到 `frontend/dist`，由后端托管 |
| 数据库 | SQLite：`backend/data/choir.db`（首次启动自动建表 + 灌演示数据） |
| 依赖位置 | `backend/.venv/Lib/site-packages`（项目内，未改动系统 Python / Anaconda） |
| Node 运行时 | `..\tools\node\node-v22.23.5-win-x64`（便携版，未全局安装） |

## 启动

```powershell
cd C:\Users\PC\Desktop\class\choir-score-hub
.\start.ps1                 # 或 .\start.ps1 -Port 8010
```

## 本机部署时踩到的坑（都已绕过，换机器不需要）

这台机器没有 git / Node，且 DSH 的文件沙箱会拦截两件事，所以部署方式和 README 的命令行不同：

1. **没有 git** → 用 Python `urllib` 下载 GitHub 归档 zip，解压到本目录。
   （`curl.exe` 在这台机器上 schannel 报 `SEC_E_NO_CREDENTIALS`，不可用。）
2. **没有 Node** → 下载 Node 22 LTS 便携 zip 解压到 `..\tools\node`，只用它的 `npm.cmd`。
   PowerShell 执行策略禁止 `npm.ps1`，所以脚本里必须调 `npm.cmd`。
3. **`python -m venv` 的 ensurepip 在 Anaconda Python 3.13 上失败**
   （`No module named pip`）→ 用 `python -m venv .venv --without-pip`，
   再用系统 pip 以 `--target=.venv\Lib\site-packages` 把依赖装进虚拟环境。
4. **沙箱下 `tempfile.mkdtemp()` 建出的目录不可写**（Python 会给它加仅属主可访问的私有权限，
   而沙箱进程令牌不是属主，于是 pip / pytest 全部 `Permission denied`）。
   → 在 `backend\.venv\Lib\site-packages\sitecustomize.py` 里把 `mkdtemp` 换成
   `os.makedirs`（继承权限）的实现，只对这个虚拟环境生效。
   **删掉这个文件会让 pip / pytest 在这个沙箱里再次失败**；在普通命令行里跑则可有可无。
   安装依赖时用的 `..\run_pip.py` 是同一个补丁的独立版本，可留作参考。
5. npm 缓存重定向到 `..\.npm-cache`、临时目录重定向到 `..\.tmp`，避免写到工作区外被拒。

> 沙箱里 **无法** 用 Edge/Chrome 无头截图（Chromium 的 mojo 命名管道被拦，`FATAL platform_channel 拒绝访问`），
> 所以界面截图取的是仓库里作者自带的 `backend/data/screenshots/`。

## 验证结果

```
backend: .venv\Scripts\python.exe -m pytest -q      -> 14 passed
frontend: npm run build                            -> dist/index.html + assets（js 1.72MB / css 16KB）
GET /                     -> 200，返回 SPA
GET /api/meta             -> 6 个角色 S/A/T/B/ACCOMP/CONDUCTOR
GET /api/scores           -> 2 首（示例总谱 published，PDF 版 pending_omr）
GET /api/library/S        -> 1 份已发布分谱
GET /api/assets/{id}?role=S -> 200，12.5KB，带水印、带歌词
POST /api/assets/{id}/sign -> 签发 token；GET /api/dl/{token} -> 200 下载 P1-v1.musicxml
GET /api/versions/{id}/pdf -> 200，PDF 原件预览
GET /api/audit            -> upload / publish / view / sign / download 均有记录
```

拆分产物（`backend/data/assets/<version>/<角色>/`）：

```
S/P1.musicxml      12632B   含歌词
A/P2.musicxml       6767B
T/P3.musicxml       6770B
B/P4.musicxml       6767B
ACCOMP/P5.musicxml 20317B   钢琴双谱表
```

抽查 P2（女低音）：只剩一个 `<part id="P2">` 与对应 `<score-part>`，
16 个小节齐全，`<print new-system>` 已被清掉，`identification/miscellaneous`
里写入了水印 `女低音 · Ubi caritas (示例) · v1 · 仅限本声部使用`。

## 重建演示库

删掉 `backend/data/choir.db` 后重启即可（首次启动会自动灌数据）；
或者 `cd backend; .venv\Scripts\python.exe -m app.seed`。

## 排练播放器（声部音频）

已在本机跑通，改动如下：

```powershell
# 新增的 Python 依赖（已装进 .venv）
python ..\run_pip.py install --target=backend\.venv\Lib\site-packages mido lameenc
```

| 文件 | 作用 |
| --- | --- |
| `backend/app/services/audio.py` | MusicXML → Verovio MIDI → numpy 合成 → MP3 |
| `backend/app/services/musicxml.py` | 新增 `collect_tempos()` / `extract_parts(tempos=…)`：把总谱的速度表统一写回每份分谱 |
| `backend/app/store.py` | 新表 `part_audio`（版本 + 声部 → 音频路径/时长/sha256） |
| `backend/app/pipeline.py` | `ensure_audio()` 懒生成、`playlist()`、`audio_file()` |
| `backend/app/api.py` | `GET /api/play/{version_id}`、`GET /api/audio/{version_id}/{part_id}`（带 Range） |
| `frontend/src/components/PartMixer.tsx` | Web Audio 多轨播放器，叠在谱面上（solo / mute / 总音量 / 进度） |

本机实测（`v_559e04680b57`，`Ubi caritas (示例)`）：

```
GET /api/play  -> 200，5 个声部全部 available，时长都是 51.12s（spread 0.000s）
GET /api/audio/{vid}/P2 -> 200 audio/mpeg 818364B  accept-ranges=bytes
Range: bytes=100-599 -> 206  Content-Range: bytes 100-599/818364
首次生成 7.6s（懒生成），第二次 0.15s（命中缓存）
FFT 校验：第一个音主频 350.0Hz，谱面 MIDI 65 = 349.2Hz，偏差 0.04 半音
```

两个与环境/库有关的坑，已在代码里处理（换机器也一样受益）：

1. **速度标记只在女高音分谱里** → 逐声部渲染时 S 是 51s、其余是 32s。修复：`collect_tempos()` 从总谱
   抽速度表，`extract_parts(tempos=…)` 统一写回。回归测试 `test_parts_stay_aligned_*` 守住这条。
2. **Verovio 字体资源绑定主线程** → FastAPI 线程池里 `loadData()` 返回 False（报 font resources
   not available，容易误判成 XML 有问题）。修复：`audio.py` 里每次 `setResourcePath(<verovio>/data)`。


## 需要注意的与文档不一致处

- README 说下载 token「一次性过期」，实测**同一 token 可以重复下载**，只在 10 分钟后按时间过期
  （`pipeline.resolve_token` 只校验过期时间，不删除记录）。
- 演示版确实**没有登录**：角色在前端切换，`/api/assets/{id}` 不校验 `role == asset.role`，
  任何人换 `?role=` 就能取到别的声部。上生产前必须补鉴权。
- `backend/data/samples/` 不存在，所以只灌进 2 条演示数据（README 表格里写的是 3 条）；
  想补第 3 条可跑 `tools/fetch_public_score.py --corpus bwv66.6`（需联网）。
- `start.ps1` 是新加的文件，原仓库只有 `backend/run.sh`（bash 用）。

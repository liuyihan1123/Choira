# 技术路线（已落地版本）

> 这份文档把前期讨论的"三段流水线"收敛成可运行的架构，并写清楚哪些环节是自动的、
> 哪些必须人工介入。代码在 `backend/` 与 `frontend/`，演示数据在 `backend/data/demo/`。

## 1. 结论先行

| 环节 | 做法 | 自动化程度 |
| --- | --- | --- |
| 入库 | 只接受 MusicXML / MXL / PDF；PDF 单独进"待识别"队列 | 高 |
| 声部拆分 | **XML 级裁剪**：删掉非本声部的 `<part>` 与 `<score-part>`，其余节点原样保留 | 高（前提：每个声部是独立 part） |
| 声部识别 | `<part-name>` / `<part-abbreviation>` 关键词归一化 + 置信度，管理员复核 | 中（必须有人工确认入口） |
| 生成/发布 | 每个角色一份独立文件，带水印元数据、sha256、版本号 | 高 |
| 分发 | 按角色返回分谱；短时签名下载链接 + 审计日志 | 高 |
| PDF → MusicXML | 交给 Audiveris / MuseScore 转换，再回填到同一版本 | 低（必须人工校对） |
| 录音 → 分谱 | 不做 | — |

三个关键判断：

1. **内部唯一格式是 MusicXML。** PDF 没有声部语义，不能当中间格式。
2. **拆分不要用 music21 重新写出。** music21 重新 `write()` 会丢排版细节（歌词对齐、连谱号、页面设置）。
   本项目用 lxml 深拷贝 + 删除非目标 `<part>`，只清理分页提示，让单声部重新自动排版。
   music21 只在需要"分析"（音域、调性）时作为可选项。
3. **"一个 part 里叠了 SATB" 必须显式拒绝。** 钢琴缩编谱把四个声部写在两行谱表里时，
   XML 级拆分无法按声部切开。系统会把这些 part 标成 `extractable = false`，
   发布时拦下并提示"先在 MuseScore 里拆成独立 part"，另留"强制发布（整段保留）"的逃生口。

## 2. 数据流

```
上传 (musicxml/mxl/pdf)
   │
   ├─ PDF → versions.status = pending_omr，存原件，等人工转换
   │        └─ attach-musicxml → 解析 part → 回到 draft
   │
   └─ MusicXML → 解析 ──► parts 表（part_id / name / staves / voices / 建议角色 / 置信度）
                          │
                管理员在映射矩阵里确认「角色 × part」
                          │
                       publish
                          │
        assets 表：每个 (角色, part) 一份独立 MusicXML
        ├─ 清理 <print new-page/new-system>
        ├─ 写入水印元数据（角色 · 曲名 · 版本 · 日期）
        └─ 计算 sha256、记录文件大小
                          │
            团员端 GET /api/library/{role} → 只返回自己的 asset
                 GET /api/assets/{id} → OSMD 渲染（含水印叠层、审计）
                 POST /api/assets/{id}/sign → 10 分钟有效的下载 token
```

## 3. 数据模型（SQLite）

```
scores(id, title, composer, created_at)
versions(id, score_id, version_no, status, source_kind, source_path, musicxml_path,
         source_hash, title, composer, notes, created_at, published_at)
parts(version_id, part_id, idx, name, abbreviation, staves, voices, note_count,
      multi_voice, extractable, suggested_role, confidence, warnings)
assignments(version_id, role, part_id)          -- 多对多：一个角色可有多份分谱
assets(version_id, role, part_id, path, sha256, size, created_at)
tokens(token, asset_id, role, expires_at)        -- 短时下载链接
audit(id, ts, action, role, version_id, part_id, ip, detail)
```

- `versions.status`：`draft`（可改映射）→ `published`（只读）／`pending_omr`（PDF 待转换）。
- 版本号按 `(score_id, version_no)` 唯一；总谱改版要新建版本重新发布，避免有人练旧谱。
- `assets` 的 sha256 是"这份分谱确实换过"的证据，前端可以显示指纹前缀。

## 4. 拆分实现细节（`backend/app/services/musicxml.py`）

1. **解包**：`.mxl` 走 `META-INF/container.xml` 找 rootfile；失败则取第一个 `.xml/.musicxml`。
2. **解析**：lxml，禁用外部实体与网络；`score-timewise` 直接报错并提示先另存为 partwise。
3. **part 画像**：谱表数、声部编号集合、音符数、谱号；
   `staves >= 2 且声部数 >= 3` 判为"多声部合写"，标记不可拆。
4. **裁剪**：
   - 重建 `<part-list>`，只保留命中的 `<score-part>`，丢弃 `<part-group>`（避免 start/stop 不配对）；
   - 删除未选中的 `<part>`；
   - 删除 `<print>` 的 `new-system/new-page/blank-page` 与 `system-layout/page-layout/staff-layout`，
     空的 `<print>` 一并删除 —— 这一步就是"重新排版"，否则会出现总谱宽度的系统硬塞进单声部页面；
   - 保留 `<work>`、`<credit>`（标题/作曲）、歌词、力度、表情、移调、连音线。
5. **水印**：写入 `<identification>` 的 `software`、`encoding-date` 和
   `<miscellaneous-field name="watermark">`，不改动任何可见谱面元素。
6. **序列化**：补回对应版本的 DOCTYPE，便于 MuseScore / Finale 打开。

## 5. 前端（`frontend/`）

- **团员端**：左侧分谱列表（按角色过滤）→ 右侧 OSMD 视图；支持多声部 tab、缩放、打印、签名下载；
  谱面覆盖低透明度水印（角色 · 曲名 · 版本），截图也会带上归属信息。
- **管理台**：上传 → 曲目库 → 声部映射矩阵（行 = part，列 = 角色）→ 保存/发布；
  PDF 版本显示原件预览和"上传转好的 MusicXML"入口；审计日志单独一页。
- 渲染用 OSMD 默认的 Endless 版式（屏幕连续滚动），打印走浏览器 `@media print`，
  要印刷级分谱仍建议接 MuseScore CLI（`mscore -o part.pdf part.musicxml`）。

## 6. 与最初技术路线相比的调整

| 原方案 | 本项目 | 原因 |
| --- | --- | --- |
| music21 作为拆分引擎 | 改为 lxml XML 级裁剪，music21 只留作可选分析 | 重写会丢排版；music21 也不是为保真导出设计的 |
| MuseScore CLI 拆分 | 暂不依赖，作为印刷级 PDF 的可选后处理 | 需要本机安装；`-P` 对"单 part 多声部"不可靠 |
| PDF 直接 OMR 集成 | 入库 + 待识别队列 + 人工回填 | Audiveris 是 AGPLv3、需人工校对，先把它放在流程外更稳 |
| 账号/角色体系 | 演示版用"身份切换"，数据层已按角色隔离 | 先验证核心链路；接 SSO 只需替换 `role` 的来源 |
| Tone.js 播放 | 暂未做 | 需要 soundfont 与逐声部 MIDI 生成，放到下一里程碑 |

## 7. 上生产前必须补的四件事

1. **鉴权**：当前 `role` 由前端选择，只能做演示。生产环境要从登录态/邀请码里取角色，
   并给 `/api/assets/{id}` 校验 `asset.role == 当前用户角色`；管理员接口加独立鉴权。
2. **水印与下载策略**：正式版应把水印烧进 PDF（服务端排版时叠加），并限制下载次数/有效期。
3. **版本通知**：发布新版本时给相关角色发通知（邮件/企业微信），旧版本自动标记"已过期"。
4. **许可合规**：Audiveris、Satie 为 AGPLv3，MuseScore 为 GPLv2；以独立进程调用与打包进产品的义务不同，
   商用前逐个核对 LICENSE。本项目自身只依赖 lxml/FastAPI/OSMD（BSD/MIT/Apache 系）。

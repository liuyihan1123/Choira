# Git 工作流：把项目放进 GitHub，然后持续迭代

这份文档配合课件第 10 节使用。命令按本项目（`choir-score-hub/`）的真实路径写，
可以直接复制执行。假设你已经装好 Git（`git --version` 能看到版本号）。

---

## 0. 一次性准备

```bash
git config --global user.name  "你的名字"
git config --global user.email "你的邮箱@example.com"
git config --global init.defaultBranch main
git config --global pull.ff only        # 拉取只允许快进，避免莫名的 merge commit

# 可选：命令行建 PR / Release 更方便
brew install gh
gh auth login
```

> 本机现状提醒：`~/`（家目录）本身是一个 Git 仓库，还挂着一个 Trustie 远程。
> 所以**不要**在家目录里 `git add .`。本项目要作为独立仓库管理，请在
> `choir-score-hub/` 里执行下面的命令，它会是嵌套的独立仓库，与家目录仓库互不影响。

---

## 1. 在 GitHub 建仓库

网页方式：New repository → 名字 `choirparts` → **不要勾** README / .gitignore / License
（勾了会产生一个初始 commit，和本地首推冲突，需要 `--allow-unrelated-histories` 或 rebase）。

命令行方式（已 `gh auth login`）：

```bash
gh repo create choirparts --private --source . --remote origin --push
```

---

## 2. 首次提交与推送

先确认 `.gitignore` 已就位，再提交。**顺序错了，历史里会永远留着不该进库的文件。**

```bash
cd choir-score-hub

# 看一眼会进库的文件，确认没有 node_modules / .venv / 大文件
git status --short

git init -b main
git add .
git commit -m "feat: 合唱团分谱分发 MVP（拆分 / 发布 / 审计）"

# SSH（推荐，需已上传公钥）或 HTTPS
git remote add origin git@github.com:<你的账号>/choirparts.git
# git remote add origin https://github.com/<你的账号>/choirparts.git

git push -u origin main
```

推完检查：GitHub 上应该能看到 `backend/`、`frontend/`、`docs/`，看不到 `.venv`、`node_modules`。

### 什么进仓库，什么不进

| 进仓库 | 原因 |
| --- | --- |
| `backend/app/`、`tests/`、`tools/` | 源码与测试，项目的本体 |
| `frontend/src/`、`vite.config.ts`、`package.json`（含 lock） | 前端源码与可复现的依赖版本 |
| `data/demo/*.musicxml`、`*.pdf` | 演示数据，保证 clone 下来能跑 |
| `data/screenshots/`、`docs/` | README 与课件引用 |
| `README.md`、`requirements.txt` | 别人接手的第一入口 |

| 不进仓库 | 原因 |
| --- | --- |
| `.venv/`、`node_modules/` | 平台相关、体积大，用 lock 文件还原 |
| `frontend/dist/` | 构建产物，由 CI 生成 |
| `data/choir.db` | 本地运行数据，含审计记录 |
| `data/assets/`、`data/uploads/`、`data/work/` | 运行时生成的派生文件 |
| `data/samples/` | 可由 `tools/fetch_public_score.py` 重新生成 |
| `*.pyc`、`.pytest_cache/`、`.DS_Store` | 垃圾文件 |

大文件注意：单个文件 > 50MB 会被拒；> 5MB 建议用 Git LFS。本项目的 PDF 课件约 3.4MB，可以直接进库。

---

## 3. 日常循环：一个分支只做一件事

```
Issue ──► 分支 ──► 提交 ──► PR ──► Review ──► 合并 ──► 删分支
```

```bash
git switch main
git pull --ff-only                     # 先同步，避免基于旧代码开分支

git switch -c feat/sub-role            # 功能：feat/xxx；修 bug：fix/xxx；文档：docs/xxx

# ... 写代码、跑测试 ...
cd backend && .venv/bin/python -m pytest -q

git add -A
git commit -m "feat(role): 支持 S1/S2 子声部映射"
git push -u origin HEAD                # 推送到同名远程分支

gh pr create --fill                    # 没装 gh 就去网页点 Compare & pull request
```

合并之后：

```bash
git switch main
git pull --ff-only
git branch -d feat/sub-role
git push origin --delete feat/sub-role 2>/dev/null || true
```

### 分支命名

| 前缀 | 用途 | 例子 |
| --- | --- | --- |
| `feat/` | 新功能 | `feat/pdf-omr-queue` |
| `fix/` | 修 bug | `fix/bass-role-regex` |
| `docs/` | 文档、课件 | `docs/git-workflow` |
| `test/` | 补测试 | `test/force-publish` |
| `chore/` | 依赖、构建、配置 | `chore/osmd-3` |

### 保持分支新鲜（rebase）

```bash
git fetch origin
git rebase origin/main
# 冲突：编辑文件 → git add <file> → git rebase --continue
# 想放弃：git rebase --abort
git push --force-with-lease            # 只在 rebase 后使用，且只推自己的分支
```

---

## 4. 提交信息：Conventional Commits

```
<type>(<scope>): <中文描述>
```

| type | 用途 | 例子 |
| --- | --- | --- |
| `feat` | 新功能 | `feat(split): 支持按 part 导出分谱` |
| `fix` | 修 bug | `fix(role): 修复 Bass 被识别为女高音` |
| `docs` | 文档 | `docs: 补充 Git 工作流与命令` |
| `test` | 测试 | `test(api): 覆盖强制发布分支` |
| `refactor` | 重构，不改行为 | `refactor(pipeline): 抽出水印函数` |
| `chore` | 依赖、配置 | `chore: 升级 OSMD 到 3.0` |

好提交的三个标准：**能独立回滚**、**说清为什么**、**一个提交只做一件事**。
不要出现 `update`、`fix bug`、`111` 这种提交信息。

---

## 5. Pull Request：让别人（和未来的你）看得懂

PR 描述模板（可放到 `.github/pull_request_template.md`）：

```markdown
## 做了什么
一句话说明这个 PR 的目标。

## 为什么
关联 issue：Closes #12

## 怎么验证
- [ ] `cd backend && pytest -q` 全绿
- [ ] 手动走一遍：上传 → 映射 → 发布 → 团员取谱
- [ ] UI 改动附截图

## 风险
是否改数据表、是否影响已发布版本、是否需要迁移。
```

合并前检查清单：

- [ ] 本地测试全绿，CI 通过
- [ ] 改了行为就补了测试
- [ ] 没有把 `.venv`、`node_modules`、`data/*.db` 带进来
- [ ] 数据模型变更写了迁移说明
- [ ] UI 改动有截图（评审的人不一定跑得起来）

---

## 6. CI：让机器守门

`.github/workflows/ci.yml`：

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r backend/requirements.txt
      - run: cd backend && python -m pytest -q

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - run: cd frontend && npm ci
      - run: cd frontend && npm run build
```

然后在 GitHub 仓库 Settings → Branches 给 `main` 加保护：
**Require status checks to pass** + **Require a pull request before merging**。
这样"测试没过就合不进去"是规则，不是自觉。

---

## 7. 版本与发布

发布是 tag，不是"最新代码"——只有打了 tag 的提交才叫一个版本。

```bash
git switch main && git pull --ff-only

git tag -a v0.2.0 -m "v0.2.0：PDF 回填 + 分谱水印"
git push origin v0.2.0
gh release create v0.2.0 --generate-notes
```

版本号建议 `v0.MINOR.PATCH`：

- `MINOR`：新增能力（子声部、OMR 队列）
- `PATCH`：修 bug、文案、样式
- 破坏性变更（改数据表、改接口）：在 CHANGELOG 里写清楚迁移步骤

回滚：

```bash
git revert <bad-commit>      # 生成一个反向提交，历史可追溯
git tag -d v0.2.0            # 只在还没人使用时删本地 tag
```

---

## 8. 紧急修复（hotfix）

线上出问题，不要在 `main` 上直接改：

```bash
git switch -c fix/publish-500 main
# 改代码 + 补一个能复现的测试
git commit -m "fix(publish): 修复空映射时的 500"
git push -u origin HEAD
# 走 PR，合并，打 patch 版本
git tag -a v0.2.1 -m "fix: 空映射发布 500"
git push origin v0.2.1
```

---

## 9. 团队约定（写进仓库，而不是口头）

- `main` 永远可发布；所有改动走 PR。
- 一个 PR 只做一件事，超过 400 行就该拆。
- 至少一个人 review；作者不能自己点合并。
- Issue 模板：背景 / 期望 / 验收标准（对应课件第 5 页的三条验收标准）。
- 每周清理一次已合并分支：`git branch --merged main | grep -v main | xargs -n1 git branch -d`。

---

## 10. 命令速查

```bash
# 状态与差异
git status -sb
git diff --stat
git log --oneline --graph --decorate -15

# 暂存与撤销
git add -p                     # 按块暂存，提交更干净
git restore <file>             # 丢弃工作区改动
git restore --staged <file>    # 取消暂存

# 分支
git switch -c feat/x
git switch main
git branch -vv
git branch -d feat/x

# 同步
git fetch --prune
git pull --ff-only
git rebase origin/main

# 找回
git reflog                     # 误删分支、误 rebase 的救命命令
git cherry-pick <sha>

# 远程
git remote -v
git push -u origin HEAD
git push origin --delete feat/x
```

---

## 11. 这个项目的第一次提交长什么样

```bash
cd choir-score-hub
git init -b main
git add .
git status --short | head -20        # 确认没有 .venv / node_modules / data/choir.db
git commit -m "feat: 合唱团分谱分发 MVP（拆分 / 发布 / 审计）"
git remote add origin git@github.com:<你的账号>/choirparts.git
git push -u origin main
```

后续每个需求都按"issue → 分支 → 提交 → PR → CI → 合并 → tag"走一遍，
版本号和 `assets` 表的 sha256 一起，构成"谁在什么时候改了哪一版"的完整链条。

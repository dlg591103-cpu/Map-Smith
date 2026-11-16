# PR #27 A 区修复独立复验记录

| 项目 | 内容 |
| --- | --- |
| 验收对象 | `feat/v0.1.1-integration` 上 `37a13bf` 的代码内容；`package.py` blob `48c4ae1`、`loop.py` blob `3a33569`，与 `37a13bf` 逐字节一致 |
| 复验范围 | A1 `package.py` 产物缺前端；A2 超时/否决/审查未通过状态未上图 |
| 验收依据 | [SPEC V0.1](../Spec/V0.1-专题制图智能体.md) 第 7 节第 8、12 条；[facts/07](../facts/07-制图规范与审查.md)、[facts/08](../facts/08-交付形态.md)；[工程规则](../工程规则.md) 第 3–6、9 条 |
| 上一轮结论 | [PR #27 独立验收](PR-27-v0.1.1集成.md)（对象 `b26e56d`）判定不通过，阻塞项为 A1、A2 |
| 修复自检 | [PR-27 A 区修复自检](../自检/PR-27-A区修复.md)（仅作线索，不作为验收结论） |
| 执行者 | CodeArts（独立验收会话）。未修改 A1/A2 源码；临时脚本不入库 |
| 环境 | Windows 11 + PowerShell 5.1；Python 3.12.10（`E:\Map Smith\.venv`）；离线 `demo_data` |
| 日期 | 2026-11-16 |

## 1. 验收对象与工作区说明

- 复验开始时 `git rev-parse HEAD` = `37a13bf`。验收期间工作区 HEAD 由另一会话推进到 `6da0536`；
  `git diff --name-only 37a13bf..6da0536` 仅含 `docs/自检/T18.5-buffer-overlay.md`、
  `docs/验收/PR-27-v0.1.1集成.md`、`docs/验收/T24-端到端.md` 三个文档文件。
- 实测 `git hash-object package.py src/mapsmith/loop.py` 与 `37a13bf:package.py`、
  `37a13bf:src/mapsmith/loop.py` 完全相同；`git diff 37a13bf..6da0536 -- package.py src` 为空。
- 因此本记录以 `37a13bf` 的代码为固定对象；HEAD 的文档推进会单独说明，不改变被验收代码。
- 工作区无源码改动；未跟踪项只有 `mapsmith-v0.1.0.zip`。

## 2. 验收方法

1. 不调用开发方临时脚本；另写 `a1_check.py`、`a2_check.py`，分别实跑打包与编排。
2. A1：实跑 `package.py`，统计 zip 条目、必需条目与排除项；解压后调用 `mapsmith.server.index()`，
   并用 `TestClient` 请求首页引用的 JS/CSS；另在最小临时仓库构造缺前端与后置校验失败两种路径。
3. A2：准备徐州 point 数据，用真实渲染函数跑五个编排分支；逐次记录 `render_fn` 调用、`spec.notes`
   与 PNG；再用视觉模型核对底部注记。
4. 定向跑 `test_package.py`、`test_loop.py`，最后跑全量 pytest。
5. 未验证项逐条列出，不推定通过。

## 3. A1 打包修复

### 3.1 正常产物

| 检查 | 结果 |
| --- | --- |
| `package.py --out out/accept-37a13bf/dist/mapsmith_a1.zip` | 返回 0；产物 11,833.6 KB |
| zip 条目 | **86**（修复前 82） |
| `web/dist/` 条目 | **3**：`index.html`、`assets/index-CZ2WOPNj.js`、`assets/index-Cn9ZQ2U6.css` |
| 必需条目 | `run.ps1`、`run.sh`、`Dockerfile`、`docker-compose.yml`、`src/mapsmith/__init__.py`、`web/dist/index.html` 全部存在 |
| 排除项 | 未命中 `.venv/`、`out/`、`.git/`、`__pycache__`、`.pytest_cache` |
| `src/tests/`、`demo_data/` | 均随包进入 |
| 解压目录 `index()` | **HTTP 200**，407 字节，`<!doctype html>`；`project_root` 正确指向解压根；无「前端未构建」 |
| 首页静态资源 | JS **200**（87,125 B）、CSS **200**（7,414 B） |

结论：修复前「解压后首页 503」的阻塞已关闭。

### 3.2 失败路径

| 场景 | 结果 |
| --- | --- |
| 缺 `web/dist/index.html` | 返回 1，`stderr` 为「打包失败：仓库缺少必需文件 web/dist/index.html」，**zip 未产出** |
| `index.html` 存在但不会进入 zip（构造为目录） | 返回 1，`stderr` 为「打包失败：zip 缺少必需条目 web/dist/index.html」；**zip 文件保留**（2,339 B） |

后置校验能阻止错误产物被当作成功交付，但校验失败时未删除已写入的 zip，与自检「不产出半成品」的表述不完全一致。该场景需同时满足「路径存在但不是文件」，属边缘路径；记为**非阻塞观察**，不影响 A1 判定。

> 2026-11-16 已修复：`package.py` 在后置校验或写入失败时删除半成品 zip；回归 `test_package.py::test_partial_zip_removed_when_required_entry_missing`。

### 3.3 一键启动边界

- 已用 `index()` 与 `TestClient` 验证解压产物的首页、JS、CSS，均为 200。
- 用 `http_probe.py` 在解压目录以本机 `.venv` 启动真实 uvicorn 并请求首页：**200**，407 B，`<!doctype html>`。
- 执行 `run.ps1 -Port 8766`：成功定位解释器并创建 `.venv`；pip 按 `requirements.lock` 安装时被沙箱网络拦截
  （PyPI `151.101.x:443`，`WinError 10051`），首次依赖安装未完成。T23 首轮已在真实网络下实测同一脚本首次安装 + 首页 200（`67151da`），本次未改 `run.ps1`。
- 结论：**「解压产物 + 依赖已就绪」路径已实测可启动**；「首次自动安装依赖」需在用户真实网络终端补跑，本次未推定通过。

## 4. A2 状态上图

### 4.1 编排分支

| 场景 | `status` | `round_no` | `render_fn` 次数 | `spec.notes` 中的状态 | 最终 PNG |
| --- | --- | --- | --- | --- | --- |
| 首轮前超时 | rendered | 0 | 1 | 审查未完成（超时）：已用尽总时长。 | 299,281 B |
| 审查中超时 | rendered | 1 | **2** | 审查未完成（超时）：超过 0.5 秒上限 | 299,114 B |
| 返工后 allow_render | rendered | 2 | **3** | 审查未通过（R05）：按协议出图并附审查意见。 | 293,870 B |
| 否决轮次用尽（`deny_limit=1`） | rendered | 1 | **2** | 已用完 1 轮否决，按协议出图并附审查意见。 | 301,819 B |
| 无补丁可返工 | rendered | 1 | **2** | 审查未通过且没有可应用的修复补丁，停止返工。 | 302,563 B |
| 审查通过 | rendered | 1 | 1 | 无状态注记 | 294,240 B |

- 审查中超时：第 1 次渲染的 `spec.notes` 不含状态（PNG SHA `b9d92205ed36035a`），第 2 次含状态
  （SHA `f75e7a794a0a9d25`），确认状态写入后确实重渲染。
- 返工后 allow_render：第 1、2 次渲染均不含状态，第 3 次含状态；`round_no=2` 与「第 1 轮返工」note 一致。
- `_append_status_note` 能把字符串 `notes` 转为列表，重复调用同一状态不叠加。
- 审查通过分支不写状态、不额外重渲染，未出现误标。

### 4.2 图面核对

视觉模型逐张读取 `render_1.png`（首轮前超时）、`render_2.png`（审查中超时）、
`render_3.png`（allow_render 最终图）：

- 三张图底部均出现对应状态文字；文字完整、无乱码、无重叠、未被裁切。
- 状态文字被并入以「**缺失值说明：**」开头的那一行，与站数、覆盖度、降级结论用分号连接。
  例如「缺失值说明：站数：……；覆盖度：……；结论：……；**审查未完成（超时）：超过 0.5 秒上限**」。
- 状态确实上图，SPEC 第 7 节第 8 条「标注审查状态」已满足；但把审查状态归为「缺失值说明」在语义上
  不准确，长行也偏拥挤。记为**非阻塞观察**，建议后续把审查状态作为独立注记行绘制。

> 2026-11-16 已修复：`layout.draw_notes` 识别 loop 写入的状态前缀并单独成行；视觉复核确认「缺失值说明」行只含站数/覆盖度/结论，状态独立一行。回归 `test_layout.py::test_review_status_note_is_drawn_outside_missing_value_line`。

## 5. 测试结果

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| A1/A2 定向 | `.venv\Scripts\python.exe -m pytest src\tests\test_package.py src\tests\test_loop.py -q` | **17 passed**，1.32s |
| 全量 | `.venv\Scripts\python.exe -m pytest src\tests -q` | **374 passed**，12 warnings，42.13s；无 skip/xfail |

- 全量为 369（`b26e56d`）+ 新增 5 项（`test_package.py` 2、`test_loop.py` 3）。
- 本轮 `test_server.py` 12 项全部通过，未复现自检中记录的 `WinError 10051` 沙箱网络错误；
  本轮全量在本机 `.venv` 解释器下完成。
- 12 条 warning 为字体回退、Numba 缺失、`mapclassify` 降级与 TestClient 弃用提示，不影响结论。
- 后续 T04 输出 CRS 白名单修复新增 2 项用例，当前全量 **376 passed**（2026-11-16，本机 `.venv`）。
- 关闭两项观察项并更新版本号后，全量 **378 passed**（2026-11-16，本机 `.venv`）。

## 6. 未验证范围

1. `run.ps1` / `run.sh` 首次自动安装依赖（本次被沙箱网络拦截）与浏览器访问；真实 uvicorn 监听已在解压产物上实测 200（见 3.3）。
2. `docker build` / `docker compose up`；本轮未在 `37a13bf` 上复跑。
3. 真实 Ollama / `.env` 外部 LLM 链路；A2 使用可控替身审查与真实本地渲染，未调用 LLM。
4. 真实浏览器 UI、Playwright E2E、SSE 阶段推送、缺 CRS 弹窗。
5. `npm run build` 与 `web/dist` 和 `web/src` 的一致性；只验证了仓库已提交的 `web/dist`。
6. 本次只复验 A 区两项修复，未重跑五图种、一句话、buffer/overlay、上传等其他 PR #27 范围。

## 7. 结论

**A1、A2 均通过，上一轮两项阻塞关闭。**

- A1：zip 已含 `web/dist`，解压后首页与静态资源 200；解压产物真实 uvicorn 启动首页 200；缺前端时打包失败且不产出 zip。
- A2：超时、否决、allow_render、无补丁四类兜底路径都把状态写入 `spec.notes` 并重渲染上图；
  审查通过路径不误标。

两项非阻塞观察已于 2026-11-16 修复：后置校验失败删除半成品 zip；审查状态从「缺失值说明」行分离、独立绘制。
本次验收对象为 `37a13bf` 的代码；验收期间 HEAD 推进到 `6da0536`，仅文档变化，不影响代码结论。

## 8. 证据与清理

- 验收脚本：`out/accept-37a13bf/a1_check.py`、`out/accept-37a13bf/a2_check.py`（临时文件，不入库）。
- 结构化结果：`out/accept-37a13bf/result_a1.json`、`out/accept-37a13bf/result_a2.json`。
- 打包证据：`out/accept-37a13bf/dist/mapsmith_a1.zip`、解压目录 `out/accept-37a13bf/dist/extract_a1/`。
- 出图证据：`out/accept-37a13bf/a2/*/render_*.png`。
- 启动探测：`out/accept-37a13bf/http_probe.py`、`out/accept-37a13bf/dist/extract_a1/run_ps1.*.log`、`pip_install.log`（首次安装被沙箱拦截的失败证据）。
- 以上均在 `.gitignore` 的 `out/` 下，不进入仓库；未修改源码；验收进程已停止，未启动常驻服务。
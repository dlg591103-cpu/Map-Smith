# T22 第二段：Vue 对话式前端与 loop 接入

> 状态：**已确认（2026-11-10）**。本文件定义 T22 第二段的架构、接口、交互与验收口径；实现以本文件为准，实现中发现的偏差回写本文件。
>
> **变更说明（2026-11-10）**：经用户确认，放弃 Streamlit 界面，改为 **Vue 3 + Vite 前端 + FastAPI 后端**；第一段 `app.py` 与 `test_app_smoke.py` 删除。本文件取代同日早先的 Streamlit 版草案。
>
> 上游依据：[V0.1-专题制图智能体.md](V0.1-专题制图智能体.md) 第 6 节 T22、第 7 节第 1 条；[T20-T21-编排契约.md](T20-T21-编排契约.md) 第 4、9 节；[facts/03](../facts/03-架构与决策原则.md)、[facts/04](../facts/04-三Agent与协作协议.md)、[facts/08](../facts/08-交付形态.md)。
>
> 第一段交付与验收（Streamlit 版，已被本段替换）：[T22 界面骨架（第一段）](../自检/T22-界面-第一段.md)、[T22 独立验收（第一段）](../验收/T22.md)。

## 1. 目标

把第一段「表单直接调渲染」改成「一句话与表单都经 `loop.run`」，并用 Vue 前端提供类 DeepSeek 的对话式界面：

```
浏览器（Vue 3）
  一句话 + 附件
      │ POST /api/chat（SSE）
      ▼
FastAPI（src/mapsmith/server.py）
      │ flow.run_one_sentence
      ▼
loop.run（load → map → render → review）
      ▼
PNG / PDF + 制图说明 + 审查意见
```

必须满足：

1. 一句话含区域 + 时间 + 指标时可出图，无需人工干预。
2. 缺项时反问，一次最多 2 问，不猜默认值。
3. 一句话与表单两条路径都调用 `loop.run`，前端不直接触碰渲染层。
4. 未配置模型时，对话入口给出中文提示并可回退表单，不抛裸 traceback。
5. 对话式布局与 SSE 阶段反馈可用，视觉在 Vue 内完全自定义。

## 2. 交付物与依赖变更

### 2.1 新增

| 路径 | 作用 |
| --- | --- |
| `web/` | Vue 3 + TypeScript + Vite 前端源码（`src/App.vue`、组件、`api.ts`、`styles.css`） |
| `web/dist/` | 构建产物，**提交入库**；交付时解压即可运行，不需要 Node |
| `web/package.json`、`web/vite.config.ts`、`web/index.html` | 前端工程配置 |
| `web/README.md` | 构建与开发说明（`npm install`、`npm run dev`、`npm run build`） |
| `src/mapsmith/server.py` | FastAPI 应用、SSE、上传、静态托管、下载路由 |
| `src/mapsmith/agents/llm.py` | OpenAI 兼容 Chat Completions 客户端 |
| `src/mapsmith/flow.py` | 一句话解析与 `load_fn/map_fn/render_fn/review_fn` 装配 |
| `src/tests/test_llm.py` | 客户端请求构造、超时、未配置、非法 JSON |
| `src/tests/test_flow.py` | 解析、缺项、字段映射、spec 组装、点/面渲染分派 |
| `src/tests/test_server.py` | FastAPI `TestClient`：健康检查、SSE、上传、CRS、静态首页 |
| `docs/自检/T22-界面-第二段.md` | 自检记录 |

### 2.2 修改

| 路径 | 改动 |
| --- | --- |
| `src/mapsmith/config.py` | 增 `llm_*` 配置；`as_dict()` 不输出密钥 |
| `src/mapsmith/ui.py` | 补表单与一句话共用的适配函数；已有函数签名不变 |
| `src/requirements.txt` | 增 `fastapi`、`uvicorn`、`python-multipart`、`httpx`（测试）；删 `streamlit` |
| `src/requirements.lock` | 按新 `requirements.txt` 重新生成 |
| `src/mapsmith/__main__.py` | `python -m mapsmith` 默认启动 Web 服务（`--config` 仍保留） |

### 2.3 删除

| 路径 | 原因 |
| --- | --- |
| `src/mapsmith/app.py` | Streamlit 界面，被 Vue 前端替代 |
| `src/tests/test_app_smoke.py` | 仅测 Streamlit 页面，随 `app.py` 删除 |

### 2.4 不新增

- 不引入前端 UI 组件库（Element Plus / Ant Design 等）；样式手写，避免打包体积与主题不可控。
- 不引入 Pinia / Vue Router；单页两视图用本地状态切换。
- 不引入 Node 运行时依赖到生产环境：`web/dist/` 已入库，运行时只需 Python。

## 3. 架构与目录

```
浏览器
  ├─ 对话视图（默认）
  └─ 表单视图（侧边栏切换）
        │ fetch / EventSource
        ▼
FastAPI server.py
  ├─ /api/chat        SSE：解析 → 加载 → 制图 → 渲染 → 审查
  ├─ /api/form        SSE：表单直接构造请求
  ├─ /api/upload      附件上传与 CRS 状态
  ├─ /api/upload/{id}/crs  确认坐标系
  ├─ /api/output/...   PNG/PDF 下载
  └─ /                web/dist 静态文件
        ▼
flow.py
  ├─ parse_request    data_steward prompt
  ├─ make_load_fn     resolve_inputs / parse_upload + profile_points
  ├─ make_map_fn      cartographer prompt + 本地补齐
  ├─ make_render_fn   ui.run_render
  └─ review_fn        agents.reviewer.review（确定性规则）
        ▼
loop.run
```

运行目录：

```
out/
├─ uploads/<upload_id>/      上传文件与 meta.json（重启后失效，可接受）
└─ web/<request_id>/         web_map.png / web_map.pdf
```

`out/` 已被 `.gitignore` 忽略，不随仓库提交。

## 4. LLM 配置与客户端

### 4.1 配置项（环境变量，`MAPSMITH_` 前缀）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MAPSMITH_LLM_BASE_URL` | 空 | 例如 `https://api.deepseek.com/v1`；末尾斜杠自动去除 |
| `MAPSMITH_LLM_API_KEY` | 空 | 只在服务端请求头使用，不写日志、不回显、不入库 |
| `MAPSMITH_LLM_MODEL` | 空 | 例如 `deepseek-chat` |
| `MAPSMITH_LLM_TIMEOUT_S` | `30` | 单次模型调用超时；与 `global_timeout_s` 分别计时 |

三项必填任一为空即视为**未配置**。`/api/chat` 返回明确中文提示，前端显示提示并引导切到表单视图；不发起模型请求。

`.env` 已被 `.gitignore` 排除；本段只读进程环境变量，不读取 `.env` 文件。

### 4.2 客户端契约

```python
# src/mapsmith/agents/llm.py
class LLMNotConfigured(RuntimeError): ...
class LLMError(RuntimeError): ...

def chat_json(
    system_prompt: str,
    payload: Mapping[str, Any],
    *,
    timeout: float,
    settings: Settings | None = None,
) -> dict[str, Any]: ...

def configured(settings: Settings | None = None) -> bool: ...
```

规则：

1. `POST {base_url}/chat/completions`，请求头 `Authorization: Bearer <key>`。
2. 请求体：`model`、`messages=[system, user]`、`temperature=0`；不强制 `response_format`。
3. 用户消息为 `json.dumps(payload, ensure_ascii=False)`；结果允许 ```json 围栏，解析失败抛 `LLMError`（附原文前 200 字）。
4. `requests.Timeout` → `LLMError("模型调用超时：<秒数> 秒")`。
5. 非 2xx → `LLMError("模型返回 HTTP <状态码>：<响应前 200 字>")`。
6. 不重试、不并发、不缓存；一次请求最多调用 2 次（解析一次、制图一次）。

### 4.3 审查

`review_fn` 只接 `reviewer.review` 的确定性规则，**不传** `llm_callable`。理由：硬判定已由 `qa_check` 覆盖；保证一次请求最多 2 次模型调用，控制 60 秒总时长。

## 5. 一句话链路

### 5.1 解析（DataSteward）

`flow.parse_request(text, llm_callable) -> RequestParse`：

```python
@dataclass(frozen=True)
class RequestParse:
    request: dict[str, str]      # place / time / metric，缺项为空串
    questions: list[str]         # 0–2 条
    raw: dict | None             # 模型原始输出，排错用，不返回前端
```

- system prompt：`agents/prompts/data_steward.md`。
- payload：`{"user_text": text, "known_fields": {"place": "", "time": "", "metric": ""}}`。
- 模型只返回 JSON：`{"place": ..., "time": ..., "metric": ..., "questions": [...]}`。
- 本地只做格式归一，**不补默认值**：
  - `time` 接受 `YYYY-MM-DD`、`YYYYMMDD`、`YYYY/MM/DD`，统一成 `YYYY-MM-DD`；无法识别则置空并生成反问。
  - 空串 / `null` / `"未知"` 视为缺失。
  - 指标名映射到字段白名单：`PM2.5`→`PM2_5_24h`、`PM10`→`PM10_24h`、`O3`→`O3_8h_24h`、`SO2`→`SO2_24h`、`NO2`→`NO2_24h`、`CO`→`CO_24h`、`AQI`→`AQI`；无法映射保留原文，由加载阶段报 `FieldMissing`。
- `questions` 最多 2 条；缺失字段的默认问题取自 `loop.FIELD_QUESTIONS`，模型问题优先但截断到 2。
- 模型失败（`LLMError`）由 API 以 SSE `error` 返回，前端展示并允许切表单。

### 5.2 加载（load_fn）

```python
flow.make_load_fn(
    parse: RequestParse,
    *,
    upload: UploadRecord | None = None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]
```

返回：

```python
{
  "summary": profile.summary,
  "decision": profile.decision,
  "reason_lines": list(profile.reason_lines),
  "profile": profile,           # DataProfile 或面数据统计
  "admin": DataLayer,
  "points": DataLayer | None,
  "layer": DataLayer,           # 实际制图图层（点或面）
}
```

- 未上传：`ui.resolve_inputs(place, date, metric)` + `inspect.profile_points(points, field_name=metric, study_area=admin)`。
- 上传点数据：`parse_upload` 后作为 `points`；行政边界取 `load_admin(place)`；用上传文件的指标字段体检。
- 上传面数据：`parse_upload` 后作为 `layer`；体检改为**面图层统计**（有效面数、完整度、极值、字段缺失），不调用 `profile_points`；`decision` 记为 `"choropleth"`。
- 缺 CRS：`parse_upload` 返回 `crs_status == "missing"` 时不进入 `loop`，API 返回 `crs_required` 事件；前端选择坐标系后带确认值重发，不静默按 4326 处理。
- 多文件只取第一个，其余在回复中提示。

### 5.3 制图（map_fn）

`flow.make_map_fn(request, *, llm_callable, output_dir) -> Callable`：

1. 从 `loaded["profile"]` 取摘要、`decision`、`reason_lines`、极值与覆盖度。
2. system prompt：`agents/prompts/cartographer.md`；payload 只含 `user_request`、`data_profile`、`decision`、`layer_kind`。
3. 模型返回 MapSpec 草案。
4. 本地强制补齐（**LLM 只决策，不计算**）：
   - `map_type`：`decision=idw → idw`；`degrade → point`；上传面数据 → `choropleth`；忽略模型给的其他图种。
   - `extent.bbox`：点数据取 `admin.bbox_wgs84()`；面数据取面图层外接框（转 4326），不采用模型坐标。
   - `extent.adcode`：能取到则填，否则留空。
   - `classification.method` / `n`：采用模型输出；`breaks` **一律本地计算**（`ui.compute_breaks`），忽略模型断点。
   - `palette.scheme`：采用模型输出；`jet` / `rainbow` 改回 `YlOrRd`，并在 notes 追加说明。
   - `data_source_note`：本地按图层来源与请求日期生成，必须含日期。
   - `notes`：`reason_lines` 三行原样放在最前。
   - `crs`：固定 `EPSG:4490`。
5. 交给 `ui.build_spec` 校验；失败抛 `DataError`，由 `loop` 转 `failed`。

### 5.4 渲染（render_fn）

`flow.make_render_fn(loaded, *, output_dir, request_id) -> Callable[[spec], Path]`：

- `choropleth`：面图层有指标字段直接渲染；否则 `ui.aggregate_points_to_admin(admin, points, field)`。
- `point` / `idw`：用 `points.gdf`。
- 调 `ui.run_render(spec, gdf, output_dir, name="web_map")`，返回 `png`；PDF 由同一目录读取。
- 同一 `request_id` 目录内返工覆盖同名文件，避免产物堆积。

### 5.5 审查（review_fn）

```python
def review_fn(spec, *, png, data_summary, round_no, timeout):
    return review(spec, png=png, data_summary=data_summary,
                  round_no=round_no, timeout=timeout)
```

只消费 `passed` / `allow_render` / `issues` / `summary`；返工补丁由 `loop` 取 `issues[0]["fix_spec_patch"]`。

## 6. API 契约

### 6.1 通用

- 前缀 `/api`；请求与响应 `application/json`（上传为 `multipart/form-data`）。
- 错误统一结构：`{"error": "<code>", "message": "<中文说明>"}`。
- 不返回 API Key、完整环境变量或原始模型响应（`raw` 只在服务端日志的调试级别出现，默认关闭）。
- 同源部署：FastAPI 同时托管 `web/dist`，不配置 CORS。

### 6.2 `POST /api/chat`（SSE）

请求：

```json
{"message": "徐州 2026-11-01 的 PM2.5 分布图", "upload_id": null}
```

响应 `text/event-stream`，事件类型：

| event | data | 说明 |
| --- | --- | --- |
| `stage` | `{"stage":"parsing","label":"解析需求"}` | 阶段开始；前端显示进度 |
| `delta` | `{"text":"..."}` | 可追加的文本片段（阶段说明） |
| `crs_required` | `{"upload_id":"...","suggested":"EPSG:4326","options":[...]}` | 附件缺 CRS；流结束，等用户确认 |
| `result` | `{"status":"rendered","round_no":1,"summary":"...","notes":[],"review":{},"png":"/api/output/...","pdf":"...","spec":{},"decision":"degrade"}` | 最终结果 |
| `needs_input` | `{"questions":["...","..."]}` | 信息不足或 `reject` |
| `error` | `{"message":"..."}` | 失败；不返回空白图 |
| `done` | `{}` | 流结束标记 |

阶段顺序固定：`parsing → loading → mapping → rendering → reviewing`。每个阶段最多发一次 `stage`；`delta` 用于该阶段的说明文字。

### 6.3 `POST /api/form`（SSE）

请求：`{"place","time","metric","map_type","method","n","palette_scheme","palette_reverse","upload_id"}`。

- 与 `/api/chat` 共用 `flow` 装配与事件格式；跳过 `parsing` 阶段，直接从 `loading` 开始。
- 表单参数非法时返回 SSE `error`，中文说明。

### 6.4 `POST /api/upload`

`multipart/form-data`，字段 `file`，限制 20 MB，允许 `.csv`、`.geojson`、`.json`、`.zip`。

响应：

```json
{
  "upload_id": "u_20261110_ab12cd",
  "name": "sites.csv",
  "kind": "point | admin | table",
  "crs_status": "declared | missing",
  "suggested_crs": "EPSG:4326",
  "summary": "sites.csv：12 个点，字段 PM2_5_24h"
}
```

- 文件保存到 `out/uploads/<upload_id>/`，元数据写入 `meta.json`。
- 上传失败、格式不支持、超过大小 → `400` + 中文错误。

### 6.5 `POST /api/upload/{upload_id}/crs`

请求 `{"crs":"EPSG:4326"}`；响应对应上传记录的更新后状态。确认后才能进入 `/api/chat`。

### 6.6 `GET /api/output/{request_id}/{filename}`

- 只允许 `web_map.png` / `web_map.pdf`，`request_id` 必须是 `r_[A-Za-z0-9_]+`。
- 路径校验：解析后的绝对路径必须位于 `settings.output_dir / "web"` 下，防止目录穿越。

### 6.7 `GET /api/health`

`{"status":"ok","llm_configured":true|false,"version":"V0.1"}`；不返回密钥。

### 6.8 `GET /` 与静态资源

- `/` 返回 `web/dist/index.html`。
- `/assets/*` 返回构建产物；未构建时返回 503 + 中文提示「前端未构建，请先 npm run build」。
- 不使用 SPA 路由，所有视图在单页内切换，无需 history fallback。

## 7. 前端结构与交互

```
web/
├─ package.json
├─ vite.config.ts          # build.outDir = dist；dev 代理 /api → http://127.0.0.1:8501
├─ index.html
├─ README.md
├─ src/
│  ├─ main.ts
│  ├─ App.vue               # 侧边栏 + 视图切换
│  ├─ api.ts                # fetch、SSE 解析、上传
│  ├─ types.ts
│  ├─ styles.css
│  └─ components/
│     ├─ ChatView.vue
│     ├─ FormView.vue
│     ├─ MessageBubble.vue
│     ├─ Composer.vue
│     ├─ ResultCard.vue
│     └─ CrsDialog.vue
└─ dist/                    # 构建产物，入库
```

### 7.1 布局（类 DeepSeek）

```
┌──────────────┬──────────────────────────────────────────┐
│ MapSmith     │                                          │
│ [＋ 新建对话] │           今天想做什么图？                │
│              │  用一句话告诉我区域、时间和指标…          │
│ ○ 对话       │                                          │
│ ○ 表单       │  🧑 徐州 2026-11-01 的 PM2.5             │
│              │  🗺️ 已出图                                │
│ 最近         │     [地图图片]                            │
│ · 徐州 PM2.5 │     [下载 PNG] [下载 PDF]                 │
│              │     审查状态：第 1 轮通过                  │
│              │  ┌────────────────────────────────────┐  │
│              │  │ 给 MapSmith 发消息…          📎  ➤ │  │
│              │  └────────────────────────────────────┘  │
└──────────────┴──────────────────────────────────────────┘
```

- 侧边栏 260px，`#f9f9fb`，右侧 1px `#ececf1`；移动端宽度 <768px 时折叠为顶部抽屉。
- 主区白色；消息列最大 760px 居中；空状态大标题 + 说明。
- 用户消息右对齐，`#eef2ff` 圆角气泡；助手消息左对齐，头像 + 正文，无边框。
- 底部输入条：圆角 24px、白底、阴影、附件按钮、发送按钮（主色 `#4d6bfe`）。
- 不使用组件库；样式集中在 `styles.css`，CSS 变量定义颜色与间距。

### 7.2 交互

- 发送后禁用输入与发送按钮；助手消息内显示当前阶段（解析 / 加载 / 制图 / 渲染 / 审查）。
- `delta` 文本追加显示；`result` 到达后替换为结果卡片：图片、下载、审查状态、notes 折叠、spec JSON 折叠。
- `needs_input`：助手消息逐条显示问题（≤2），输入框重新可用。
- `error`：红色提示 + 「重试」按钮；错误不覆盖已有历史。
- 附件：选择后立即 `POST /api/upload`，显示文件名 chip；`crs_status=missing` 时弹 `CrsDialog`，确认后调 `/api/upload/{id}/crs`，再发消息。
- 对话历史存 `sessionStorage`，保留最近 20 条；新建对话清空。历史不参与模型上下文。
- 刷新页面保留当前会话（sessionStorage），关闭标签页后清空。

### 7.3 表单视图

- 控件与第一段一致：区域、日期、指标、图种、分级方法、级数、配色、上传。
- `buffer` / `overlay` 不出现；文案「buffer / overlay 尚未实现，待 SPEC 决策」保留。
- 提交调 `/api/form`，SSE 事件与结果卡片同对话视图。
- 上传复用 `/api/upload` 与 CRS 确认。

## 8. 安全与错误处理

| 项 | 处理 |
| --- | --- |
| 密钥 | 只读 `MAPSMITH_LLM_API_KEY`；日志、响应、前端代码均不出现 |
| 上传大小 | 20 MB 上限，超出 `413` + 中文说明 |
| 上传类型 | 只接受 `.csv` / `.geojson` / `.json` / `.zip`；其他 `400` |
| 路径穿越 | 下载与静态路由都做绝对路径前缀校验 |
| 模型错误 | `LLMError` → SSE `error`，中文说明；不返回空白图 |
| 数据错误 | `DataError` / `FieldMissing` / `CrsNotDeclared` → SSE `error` 或 `crs_required` |
| 渲染异常 | `loop` 已捕获并转 `failed`；API 返回 `error` + 原因 |
| 超时 | 60 秒总时长由 `loop` 控制；超时仍出图并标注「审查未完成（超时）」 |
| 认证 | 本段不做登录与鉴权；面向本机/内网演示，公网部署不在验收前提内（facts/08） |

SSE 错误不抛裸 traceback；服务端日志只记录 `request_id`、阶段、耗时与异常类型，不记录用户原文与密钥。

## 9. 与既有契约的关系

| 契约 | 本段做法 |
| --- | --- |
| `loop.run` 注入点 | 不改签名；由 `flow.py` 提供四个函数 |
| `DataProfile` 回灌 | `load_fn` 返回的 `summary` / `decision` 被 `loop` 原样读取；Agent 只见摘要 |
| `reason_lines` | 三行原样进 `MapSpec.notes` |
| `breaks` 由确定性代码计算 | `map_fn` 忽略模型断点，统一 `ui.compute_breaks` |
| 60 秒总时长 | `loop` 计时；LLM 单次 30 秒 |
| 不返回空白图 | 沿用 `loop` 兜底渲染；模型失败只影响解析/制图 |
| 五图种 | 本段仍只开放 choropleth / point / idw；buffer / overlay 缺口不变 |

## 10. 验收条件

1. `npm run build` 成功，`web/dist/` 已提交；`python -m mapsmith.server` 启动后 `/` 可打开对话页。
2. 一句话含区域 + 时间 + 指标，用替身 `llm_callable` 跑通「解析 → 加载 → 制图 → 渲染 → 审查」，SSE 依次收到 5 个 `stage` 与 `result`，PNG 存在。
3. 缺时间 / 指标时，`needs_input` 返回 ≤2 条问题，不触发加载与渲染，不补默认值。
4. 表单 `/api/form` 走 `loop.run`；前端代码中不出现直接渲染调用。
5. 未配置模型时 `/api/chat` 返回 `error`，文案指向表单；`/api/form` 仍可出图。
6. 模型非 JSON / 超时 / 未配置分别得到可读中文错误，无裸 traceback。
7. 审查 FAIL 按 `loop` 返工，2 轮后出图并附意见；超时兜底不空白。
8. 附件点数据参与一句话出图；面数据走 choropleth；缺 CRS 时 `crs_required`，确认后才继续。
9. `MAPSMITH_LLM_API_KEY` 不出现在页面、日志、测试输出与提交里。
10. 前端视觉可用：用户/助手消息分角色、底部输入条、下载按钮、阶段进度均正常；移动端不溢出。
11. 全量 `pytest` 通过；删除 3 个 `test_app_smoke` 后基数下降，新增用例覆盖第 2–8 条，总数不少于 252。
12. 手动端到端：真实 `python -m mapsmith.server` + 浏览器完成一次一句话出图（无 Key 时用表单路径）。

## 11. 明确未做

- 不做多轮上下文：历史只展示，不进入模型输入。
- 不做模型软判（`reviewer.llm_callable`）。
- 不做流式模型输出：SSE 流式的是阶段与本地文本，模型调用仍为一次性返回。
- 不做用户系统、登录、鉴权、多会话持久化。
- 不实现 `buffer` / `overlay` 图种。
- 不新增前端组件库、Pinia、Vue Router。
- 不做前端自动化 E2E（Playwright 等）；以 `npm run build` + API 测试 + 手工验收为准。
- 不验证真实模型遵循度（本机无 Key）；真实模型联调列为未验证项。

## 12. 待确认

1. ~~前端技术~~ → 已确认（2026-11-10）：Vue 3 + Vite + TypeScript。
2. ~~Streamlit 去留~~ → 已确认（2026-11-10）：删除 `app.py` 与 `test_app_smoke.py`。
3. ~~dist 入库~~ → 已确认（2026-11-10）：`web/dist/` 提交入库。
4. ~~流式~~ → 已确认（2026-11-10）：SSE 阶段流。
5. ~~是否接受本段把 `streamlit` 从依赖中移除~~ → 已确认（2026-11-10）：移除，`docs/自检/T01` 版本清单同步注明。
6. ~~是否接受 `python -m mapsmith` 默认启动 Web 服务~~ → 已确认（2026-11-10）：默认启动 Web，`--config` 行为不变。

## 13. 合并前补做项（2026-11-10 追加）

用户要求以下四项完成后才能合并；本节优先于第 11 节「明确未做」中的对应条目。

| 项 | 要改什么 | 验收 |
| --- | --- | --- |
| 真实模型 | 配置 `MAPSMITH_LLM_*`，用真实模型跑一次一句话链路 | 解析、制图、出图、审查均成功；记录模型名与耗时，不记录 Key |
| 点图缺口 | `render/point.py` 叠加城市面底色；指北针移到图框外，避开数据点 | 出图可见行政区轮廓；指北针不与气泡/图例重叠 |
| AQI 配色 | `render/layout.py` 支持 `AQI6` 国标六级色阶；`flow` 对 AQI 强制六级固定断点与配色 | AQI 出图无 R02/R06/R08 fail |
| 前端 E2E | 新增 `web/e2e/` 与 Playwright 配置；覆盖页面、表单出图、下载、附件 CRS、未配置提示 | `npx playwright test` 通过；浏览器二进制不入库 |

### 13.1 接口调整

- `MapSpec.Classification` 增加可选 `unit` 字段（默认 `None`），用于审查 R02 读取图例单位；不改变已有字段语义。
- `ui.build_spec` 接受 `unit` 并写入 `Classification.unit`。
- `ui.run_render` 增加可选 `background_gdf`，仅 point 图种使用；其他图种忽略。
- `render_point` 增加可选 `background_gdf`；`PointReport` 增加 `background: bool`。
- `apply_layout` 增加可选 `north_arrow_anchor`；点图传图框外坐标，其他图种保持默认。
- `flow` 对 `field == "AQI"` 强制 `method="custom"`、`n=6`、断点 `[50,100,150,200,300,None]`、`palette="AQI6"`、`unit="无量纲"`。

### 13.2 明确不做

- 不引入前端组件库或状态管理库。
- 不把 Playwright 浏览器二进制提交入库。
- 不记录真实 API Key；验证只在当前进程环境变量中生效。
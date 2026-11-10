# MapSmith Web 前端

Vue 3 + TypeScript + Vite 构建的对话式界面。构建产物 `dist/` 已提交入库，运行时不需要 Node。

## 开发

```powershell
cd web
npm install
npm run dev
```

开发服务器默认 `http://127.0.0.1:5173`，`/api` 代理到 `http://127.0.0.1:8501`。
先在仓库根启动后端：

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m mapsmith --port 8501
```

## 构建

```powershell
cd web
npm run build
```

产物写入 `web/dist/`。改完前端后需要重新构建并提交 `dist/`，否则后端仍托管旧页面。

## 目录

| 路径 | 作用 |
| --- | --- |
| `src/App.vue` | 侧边栏、视图切换、健康检查 |
| `src/components/ChatView.vue` | 对话视图、SSE、附件、CRS 弹窗 |
| `src/components/FormView.vue` | 高级表单 |
| `src/components/ResultCard.vue` | 图片、下载、审查意见、MapSpec |
| `src/api.ts` | fetch + SSE 解析、上传、CRS 确认 |

契约见 [`../docs/Spec/T22-一句话入口与loop接入.md`](../docs/Spec/T22-一句话入口与loop接入.md)。
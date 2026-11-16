# PR #27 A 区修复自检记录

| 项目 | 内容 |
| --- | --- |
| 任务 | 修复 PR #27 独立验收的两项阻塞：A1 `package.py` 产物缺前端、A2 超时状态未上图 |
| 依据 | [SPEC V0.1](../Spec/V0.1-专题制图智能体.md) 第 7 节第 8、12 条；[facts/08](../facts/08-交付形态.md)；[T24 验收记录](../验收/T24-端到端.md) 阻塞项；[工程规则](../工程规则.md) 第 2–4、8 条 |
| 分支 | `feat/v0.1.1-integration`（PR #27 分支），基线 `origin/main` @ `1db3a02`，`HEAD..origin/main = 0` |
| 修复前对象 | `b26e56d`（独立验收记录：[PR-27-v0.1.1集成](../验收/PR-27-v0.1.1集成.md)） |
| 执行者 | CodeArts（开发会话）。与本次独立验收不同会话；修复后需重新独立验收 |
| 环境 | Windows 11 + PowerShell 5.1；Python 3.12.10（`E:\Map Smith\.venv`） |
| 日期 | 2026-11-16 |

## 1. 改动内容

| 文件 | 改动 | 对应问题 |
| --- | --- | --- |
| `package.py` | `PACK_DIRS` 增加 `web/dist`；新增 `REQUIRED_ENTRIES`，打包前检查源文件、打包后检查 zip 条目，缺 `web/dist/index.html` 等直接失败 | A1 |
| `src/mapsmith/loop.py` | 超时（首轮前/审查中）、用完否决、allow_render 未通过、无补丁可返工时，把状态写入 `spec.notes`；状态在渲染之后写入时重渲染一次，保留原图作为重渲染失败兜底；`summary` 对审查超时统一为「审查未完成（超时），已按当前 spec 出图」 | A2 |
| `src/tests/test_package.py` | 新增 2 个用例：zip 必含 `web/dist/index.html` 与 assets、缺前端时打包失败 | A1 回归 |
| `src/tests/test_loop.py` | 新增 3 个用例：超时写 `spec.notes` 后再兜底渲染、审查超时后重渲染、allow_render 未通过后标注并重渲染 | A2 回归 |

未改动 `docs/facts/`、`kb/`、`qa_check.py`、`reviewer.py`。

## 2. 验证结果

### 2.1 A1 打包

| 检查 | 修复前 `b26e56d` | 修复后工作区 |
| --- | --- | --- |
| `python package.py` 产物条目 | 82，`web/` 为 0 | **86**，`web/dist/` 为 3（`index.html` + 2 个 assets） |
| 解压后 `mapsmith.server.index()` | **HTTP 503**「前端未构建」 | **HTTP 200**，返回 `<!doctype html>` |
| 产物自检 | 无 | 缺 `web/dist/index.html` 等必需条目时 `SystemExit`，不产出半成品 |

### 2.2 A2 超时图面标注

用 `out/accept-pr27/verify_pr27.py`（临时脚本，不入库）复跑同一超时场景：

```text
status                 rendered
round_no               0
notes_has_timeout      true
spec_notes_has_timeout true      # 修复前 false
png_bytes              299281    # 修复前 294240
```

视觉核对 `out/accept-pr27/web/timeout/web_map.png`：底部注记出现「审查未完成（超时）：已用尽总时长。」；修复前同图无此文字。

审查超时（`ReviewTimeoutError`）路径已重渲染：`render_fn` 调用 2 次，最后一次的 spec.notes 含超时状态。allow_render 未通过路径会追加「审查未通过（R01）：按协议出图并附审查意见。」并重渲染，避免第 2 轮失败图无状态。

### 2.3 回归

| 范围 | 结果 |
| --- | --- |
| `test_loop.py` + `test_package.py` | **17 passed** |
| 除 `test_server.py` 外全量 | **362 passed**，11 warnings |
| `test_server.py` | 12 项失败，均为 `OSError: [WinError 10051]`，stderr 含 `Sandbox Network Error: hit restricted [127.0.0.1:...]`；单条用例在限制生效前曾通过 1 项。与 [T23](../验收/T23.md) 第 8 节、[T25](../验收/T25-五图种与默认LLM.md) 第 10.6 节记录的沙箱 loopback 拦截同源，不计为代码失败 |

说明：修复前同一沙箱内曾跑出 369 passed；本次 server 测试 12 项受沙箱网络限制无法完成，未推定通过，需在用户本机终端复跑全量。

## 3. 已知限制

- 重渲染失败时保留已出的原图，状态只回到接口 notes；这是兜底策略，不把出图改成失败。
- 状态注记文本会进入 `LoopResult.notes` 与 `spec.notes`，同时出现在接口与图面；`spec.notes` 去重，重复超时不会叠加多行相同文字。
- `package.py` 仍不打包 `docs/`、`web/src/`、`.dockerignore`；本次只保证「解压后可启动 Web」所需的最小集合。

## 4. 证据与清理

- 打包证据：`out/accept-pr27/dist/mapsmith_fixed.zip`、解压目录 `out/accept-pr27/dist/extract_fixed/`。
- 出图证据：`out/accept-pr27/web/timeout/web_map.png`、`out/accept-pr27/result.json`、`out/accept-pr27/run_fixed.log`。
- 临时文件均在 `.gitignore` 的 `out/` 下，不入库。
- 未启动常驻服务；未清理 `out/accept-pr27/`，供复核与重新验收使用。
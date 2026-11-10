# 参与贡献

感谢参与 Map Smith。本仓库是公开仓库，任何人都可以通过 Fork + Pull Request 提交代码或文档。

本文只写**操作步骤**。分支、自检、验收、合并的强制要求以 [docs/工程规则.md](docs/工程规则.md) 为准，本文不重复规则正文。

## 1. 先读什么

| 顺序 | 文件 | 作用 |
| --- | --- | --- |
| 1 | [README.md](README.md) | 项目概览、目录用途、当前状态 |
| 2 | [docs/facts/](docs/facts/) | 已确认的产品事实，不得改写 |
| 3 | [docs/Spec/](docs/Spec/) | 当前任务对应的 SPEC |
| 4 | [docs/工程规则.md](docs/工程规则.md) | 分支、交付、验收、合并的强制规则 |
| 5 | [AGENTS.md](AGENTS.md) | AI 会话的阅读入口与行为边界 |

发现文档之间冲突时先提出，不要自行选定一方。

## 2. 环境准备

技术选型为 Python 3.12 + geopandas / matplotlib / mapclassify / Streamlit；源码尚未落地前，以 `src/` 下实际依赖声明为准。

```powershell
git clone https://github.com/<你的 GitHub 用户名>/Map-Smith.git
cd Map-Smith
git remote add upstream https://github.com/dlg591103-cpu/Map-Smith.git
git fetch upstream
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

虚拟环境使用仓库已忽略的 `.venv/`，不要提交。依赖文件出现后按 `src/` 下的声明安装，不使用未验证的安装命令。

## 3. 开发流程

1. 从上游 `main` 建立任务分支，不要在 `main` 上直接开发：

   ```powershell
   git switch -c feat/<主题> upstream/main
   ```

2. 只改自己负责的范围；需要动无关功能时，在 PR 中单独说明原因与范围。
3. 本地自检，记录实际执行的命令与结果。
4. 推送到自己的 Fork，向上游 `main` 发起 PR：

   ```powershell
   git push -u origin feat/<主题>
   ```

5. 在 GitHub 新建 Pull Request，填写模板中的全部必填项。

分支名沿用现有约定：`feat/<主题>`、`fix/<主题>`、`docs/<主题>`、`chore/<主题>`。

## 4. 提交信息

沿用仓库现有风格，使用中文简述，类型用英文：

```text
feat: 新增某功能
fix: 修复某缺陷
docs: 更新某文档
chore: 调整构建或工具配置
```

一个提交只做一件事；不把无关改动混入同一提交。

## 5. PR 要求

- 关联对应的 SPEC 或 Issue。
- 写明自检命令与结果；未验证的范围明确标注"未验证"。
- 记录独立验收人及结论（如尚未验收，写明"待验收"）。
- 涉及产品事实、接口或数据规则时，同步更新责任文档。
- PR 至少获得 1 位维护者批准，且所有对话已解决，才能合并。
- `main` 禁止直接推送；维护者使用 Squash 合并，保持历史线性。

## 6. 不得提交的内容

- 密钥、令牌、证书、`.env` 文件。
- 真实用户数据、真实业务原始数据；测试请使用脱敏后的固定样本。
- 大体积原始数据与构建产物。
- 他人的 Git 身份信息；提交身份必须是你自己的 GitHub 账号。

## 7. 行为约定

- 不声称未实际完成的操作，不把"本地跑通"当作验收通过。
- 不自行合并自己的 PR，不绕过分支保护。
- 评审意见以文档与 SPEC 为依据，不以个人偏好替代已确认事实。
- 安全问题不要公开开 Issue，按仓库拥有者公开的联系方式私下报告。
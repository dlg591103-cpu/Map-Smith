# GitHub 仓库设置清单

> 适用对象：仓库拥有者 `dlg591103-cpu`。本清单是 GitHub 网页点击步骤，**不是规则正文**；协作规则见 [工程规则.md](工程规则.md) 第 10 节。
>
> 当前状态：2026-11-05 已完成第 1—3 节，并完成第 6 节的主要实测；第 4、5 节与 PR 模板自动填充尚未逐项验证。`[x]` 仅表示已验证项，未验证项保持未勾选。

## 1. 仓库转为公开

路径：`Settings` → `General` → 页面底部 `Danger Zone` → `Change repository visibility` → `Change to public`。

- GitHub 会要求输入完整仓库名 `dlg591103-cpu/webgis-twin-lab` 确认。
- 提示：公开后所有人都能查看代码、Fork 和提交 PR；已有的星标、关注者会保留，公开后不能再改回私有而不丢失这些数据。

完成标志：仓库页顶部显示 `Public`，未登录浏览器可直接打开仓库。

## 2. 邀请协作者

路径：`Settings` → `Collaborators and teams` → `Add people`。

- 输入 `PINGNINGYI`，角色选 **Write**。
- Write 权限：可推送分支、创建 PR、评审；不能修改仓库设置或管理成员。
- 协作者必须接受邀请后才能推送。公开仓库不邀请也能 Fork，但 CODEOWNERS 自动请求评审、以及直接推送分支需要 Write 权限。
- 如果协作者只是偶尔提交，可以不邀请，走纯 Fork + PR 流程；此时 CODEOWNERS 中对 `@PINGNINGYI` 的自动评审请求不会生效。

完成标志：协作者列表显示 `PINGNINGYI` 已接受邀请。

## 3. 保护 `main` 分支（Rulesets，2026-11-07 起）

**历史（2026-11-05，经典分支保护）**：曾使用 `Settings` → `Branches` 的经典保护。实测 `PINGNINGYI` 直推 `main` 返回 protected branch / GH006；PR #2 显示 `Merging is blocked`、`1 pending review`。该规则已被下面的 Rulesets 取代，历史记录保留。

### 3.1 目标配置

路径：`Settings` → `Rules` → `Rulesets` → `New branch ruleset`。

- 名称：`main-protection`
- `Enforcement status`：`Active`
- `Target branches`：`Include default branch`
- 勾选：
  - `Require a pull request before merging`
    - `Required approvals`：**1**
    - `Require review from Code Owners`
    - `Require conversation resolution`
  - `Block force pushes`
  - `Restrict deletions`
- `Bypass list`：仅添加 `dlg591103-cpu`，bypass mode 选 `Always`

### 3.2 执行与验收

- [ ] 新建 Rulesets 并保存为 `Active`
- [ ] 删除或停用旧的经典分支保护规则，避免双重规则
- [ ] 验证：`dlg591103-cpu` 的 PR 不经批准即可合并（bypass 生效）
- [ ] 验证：`PINGNINGYI` 的 PR 仍显示 `1 pending review`
- [ ] 验证：直推 `main` 仍被拒绝（protected branch / GH006）

完成标志：拥有者可自行合并自己的 PR，其他账号仍被要求批准，直推 `main` 仍被拒绝。

**当前状态（2026-11-07）**：迁移已决定，网页配置由用户执行，尚未实测；实测后在本节下方补记结果。

## 4. 合并方式

路径：`Settings` → `General` → `Pull Requests`。

- [x] `Allow squash merging`，默认提交信息选 `Pull request title`（PR #1 已用 Squash 合并成功）。
- [ ] 关闭 `Allow merge commits` 与 `Allow rebase merging`（可选，保持 `main` 历史线性）。
- [ ] `Automatically delete head branches`（可选，减少残留分支；未确认）。

说明：规则第 10 节约定使用 Squash 合并；关闭其他合并方式可强制该约定。

## 5. 贡献入口检查

路径：仓库首页 → `Issues` / `Pull requests`。

- [ ] 新建 Issue 时能看到「缺陷报告」「功能建议」两个模板，且不能创建空白 Issue。
- [ ] 新建 PR 时能看到 `.github/PULL_REQUEST_TEMPLATE.md` 的模板内容（PR #2 描述为空，尚无法确认模板是否自动填充；下次建 PR 时核对）。
- [ ] 仓库首页 `Community Standards` 检查项能看到 `CONTRIBUTING.md` 被识别。

## 6. 验收实测

由协作者 `PINGNINGYI` 执行，维护者观察结果：

1. `git clone https://github.com/<PINGNINGYI>/webgis-twin-lab.git`（Fork 后）或直接克隆上游。
2. 基于上游 `main` 建分支：`git switch -c docs/test-collab upstream/main`。
3. 做一处无风险文档改动，推送并向上游 `main` 发 PR。
4. 确认 PR 自动带上模板、自动请求维护者评审、CI 未配置时显示无检查。
5. 维护者批准后 Squash 合并；确认 `main` 历史只增加一个提交。
6. 尝试直接 `git push origin main`，确认被拒绝。

记录（2026-11-05）：

- 权限：`PINGNINGYI` 直接向本仓库推送 `docs/test-collab` 成功，确认为 Write。
- PR #2：`https://github.com/dlg591103-cpu/webgis-twin-lab/pull/2`，显示 `Merging is blocked`、`1 pending review`，自动请求 `dlg591103-cpu` 作为 code owner；该 PR 为验证用途，已关闭、不合并。
- 直推 `main`：返回 protected branch / GH006，拒绝成功。
- 未验证：PR 模板自动填充；协作者 PR 获批后 Squash 合并（PR #1 由维护者本人发起）。

## 7. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 协作者推送 403 | 邀请未接受、权限不是 Write、或分支保护拦截 `main` | 检查协作者状态；确认推的是任务分支 |
| CODEOWNERS 没自动请求评审 | 未勾选 `Require review from Code Owners`，或 CODEOWNERS 中的账号无 Write 权限 | 开启该选项；邀请对应账号 |
| Fork 的 PR 看不到 Secrets | GitHub 不向来自 Fork 的 PR 传递仓库 Secrets | 不要在 PR 流程中依赖 Secrets；需要时改用环境审批 |
| 仓库转公开后搜索到敏感内容 | 历史提交中已存在密钥或真实数据 | 先按工程规则清理历史，再转公开；已泄露的密钥立即吊销 |
| 分支保护导致维护者也无法合并 | 开启了 `Do not allow bypassing` 但审批人数不足 | 由另一位维护者批准，或临时调整规则并记录原因 |
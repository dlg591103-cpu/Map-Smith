# GitHub 仓库设置清单

> 适用对象：仓库拥有者 `dlg591103-cpu`。本清单是 GitHub 网页点击步骤，**不是规则正文**；协作规则见 [工程规则.md](工程规则.md) 第 10 节。
>
> 当前状态：以下步骤尚未执行，仓库可见性尚未修改。执行完一项勾选一项，未执行前不得声称已生效。

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

## 3. 保护 `main` 分支

路径：`Settings` → `Branches` → `Add branch protection rule`（新版界面可能叫 `Rules` → `Rulesets`，按实际界面操作）。

分支名模式：`main`。勾选：

- [ ] `Require a pull request before merging`
  - [ ] `Require approvals` 设为 **1**
  - [ ] `Dismiss stale pull request approvals when new commits are pushed`
  - [ ] `Require review from Code Owners`（使 `.github/CODEOWNERS` 生效）
  - [ ] `Require approval of the most recent reviewable push`（可选，建议开启）
- [ ] `Require conversation resolution before merging`
- [ ] `Do not allow bypassing the above settings`（包含管理员，避免维护者绕过）
- [ ] `Block force pushes`
- [ ] 不勾选 `Allow deletions`

说明：GitHub 免费账户的公开仓库支持经典分支保护；若界面已迁移到 Rulesets，对应选项为 `Require a pull request`、`Required approvals`、`Require review from Code Owners`、`Require conversation resolution`、`Block force pushes`。

完成标志：本地执行 `git push origin main` 被拒绝（提示 protected branch），而推送任务分支正常。

## 4. 合并方式

路径：`Settings` → `General` → `Pull Requests`。

- [x] `Allow squash merging`，默认提交信息选 `Pull request title`。
- [ ] 关闭 `Allow merge commits` 与 `Allow rebase merging`（可选，保持 `main` 历史线性）。
- [x] `Automatically delete head branches`（可选，减少残留分支）。

说明：规则第 10 节约定使用 Squash 合并；关闭其他合并方式可强制该约定。

## 5. 贡献入口检查

路径：仓库首页 → `Issues` / `Pull requests`。

- [ ] 新建 Issue 时能看到「缺陷报告」「功能建议」两个模板，且不能创建空白 Issue。
- [ ] 新建 PR 时能看到 `.github/PULL_REQUEST_TEMPLATE.md` 的模板内容。
- [ ] 仓库首页 `Community Standards` 检查项能看到 `CONTRIBUTING.md` 被识别。

## 6. 验收实测

由协作者 `PINGNINGYI` 执行，维护者观察结果：

1. `git clone https://github.com/<PINGNINGYI>/webgis-twin-lab.git`（Fork 后）或直接克隆上游。
2. 基于上游 `main` 建分支：`git switch -c docs/test-collab upstream/main`。
3. 做一处无风险文档改动，推送并向上游 `main` 发 PR。
4. 确认 PR 自动带上模板、自动请求维护者评审、CI 未配置时显示无检查。
5. 维护者批准后 Squash 合并；确认 `main` 历史只增加一个提交。
6. 尝试直接 `git push origin main`，确认被拒绝。

记录：PR 链接、批准人、合并提交 SHA、被拒绝的推送输出。失败情况如实记录，不勾选完成。

## 7. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 协作者推送 403 | 邀请未接受、权限不是 Write、或分支保护拦截 `main` | 检查协作者状态；确认推的是任务分支 |
| CODEOWNERS 没自动请求评审 | 未勾选 `Require review from Code Owners`，或 CODEOWNERS 中的账号无 Write 权限 | 开启该选项；邀请对应账号 |
| Fork 的 PR 看不到 Secrets | GitHub 不向来自 Fork 的 PR 传递仓库 Secrets | 不要在 PR 流程中依赖 Secrets；需要时改用环境审批 |
| 仓库转公开后搜索到敏感内容 | 历史提交中已存在密钥或真实数据 | 先按工程规则清理历史，再转公开；已泄露的密钥立即吊销 |
| 分支保护导致维护者也无法合并 | 开启了 `Do not allow bypassing` 但审批人数不足 | 由另一位维护者批准，或临时调整规则并记录原因 |
# Map Smith

本目录是 Map Smith 的项目根目录，同时是项目的 Git 仓库，用于集中管理产品事实、任务规格、工程规则与应用源码。

> 产品用途、用户角色、使用流程等产品信息尚未确认。确认后的内容只记录在 [`docs/facts/`](docs/facts/)，本文档不重复保存产品内容。

## 目录用途

| 路径 | 用途 |
| --- | --- |
| [`docs/facts/`](docs/facts/) | 产品唯一事实文档。按主题拆分，每份文档负责一个明确主题；同一项事实只在一个位置维护，其他文档链接引用。目前尚未建立文档 |
| [`docs/Spec/`](docs/Spec/) | 每个版本或开发任务的 SPEC（需求规格说明书）。记录目标、修改范围、预期行为、必要依赖与验收条件。目前尚无开发任务 |
| [`docs/工程规则.md`](docs/%E5%B7%A5%E7%A8%8B%E8%A7%84%E5%88%99.md) | 工程规则的唯一正文，涵盖分支与基线、SPEC 先行、自检与独立验收、合并与上线、文档同步、证据与清理、仓库与远端 |
| [`src/`](src/) | 应用源码目录。源码、依赖声明、锁文件、测试及构建运行所需文件都放在这里；技术方案确定后再建立内部结构 |
| [`.gitignore`](.gitignore) | 项目级忽略规则，排除密钥、真实用户数据、依赖缓存、构建结果与临时文件，对 `src/` 子树同样生效 |
| [`.gitattributes`](.gitattributes) | 换行符与二进制文件规则，统一以 LF 存取 |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | 贡献入口：Fork + PR 的操作步骤；分支、自检与合并规则引用 [`docs/工程规则.md`](docs/%E5%B7%A5%E7%A8%8B%E8%A7%84%E5%88%99.md) |
| [`docs/协作邀请说明.md`](docs/%E5%8D%8F%E4%BD%9C%E9%82%80%E8%AF%B7%E8%AF%B4%E6%98%8E.md) | 新协作者上手说明：阅读顺序、认领任务、环境与交付 |
| [`.github/`](.github/) | PR 模板、Issue 模板与 CODEOWNERS |
| [`docs/GitHub仓库设置清单.md`](docs/GitHub%E4%BB%93%E5%BA%93%E8%AE%BE%E7%BD%AE%E6%B8%85%E5%8D%95.md) | 维护者执行 GitHub 网页设置的逐步清单 |
| [`AGENTS.md`](AGENTS.md) | AI 开始工作时的阅读入口和资料索引 |

## 文档入口

-   产品事实：从 [`docs/facts/`](docs/facts/) 开始，按主题查阅；尚未建立时以用户新的确认为准，不自行补写。
-   任务规格：从 [`docs/Spec/`](docs/Spec/) 找到当前任务的 SPEC；没有确认的 SPEC 不进入实现。
-   工程要求：以 [`docs/工程规则.md`](docs/%E5%B7%A5%E7%A8%8B%E8%A7%84%E5%88%99.md) 为准，其他文件只引用，不重复维护。
-   AI 协作：阅读 [`AGENTS.md`](AGENTS.md) 获取必读资料与阅读顺序。

## 当前状态

-   项目骨架已建立并纳入版本控制：`README.md`、`AGENTS.md`、`docs/`、`src/`。
-   产品事实文档：已建立 8 份（产品定义、范围与边界、架构原则、三 Agent 协议、MapSpec 与工具契约、数据源、制图规范、交付形态），位于 [`docs/facts/`](docs/facts/)。
-   SPEC：[`docs/Spec/V0.1-专题制图智能体.md`](docs/Spec/V0.1-专题制图智能体.md)，状态为草稿，待确认后开工。
-   `src/`：目录已就绪，技术选型已定（Python 3.12 + geopandas / matplotlib / mapclassify / Streamlit），源码尚未开始。
-   远端仓库：`https://github.com/dlg591103-cpu/webgis-twin-lab`（公开），`main` 跟踪 `origin/main`；外部贡献者通过 Fork + PR 参与，入口见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。
-   多人协作：协作模式与协作者（`PINGNINGYI`）已确认，工程规则第 10 节与贡献模板已就绪；仓库可见性、协作者邀请与 `main` 分支保护需在 GitHub 网页执行，执行前不视为已生效。
-   协作者推送验证：`docs/test-collab` 分支用于验证协作者（`PINGNINGYI`）对远端的推送权限；验证通过后由维护者删除该分支，不并入 `main`。

## 版本管理约定

-   项目根目录是唯一仓库，`main` 为稳定分支；`src/`、`docs/` 与根目录文件同库管理、同远端同步。
-   分支、提交、自检、验收与合并流程见 [`docs/工程规则.md`](docs/%E5%B7%A5%E7%A8%8B%E8%A7%84%E5%88%99.md)。
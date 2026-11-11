# Enterprise AI Work · 项目复刻工作台（持续开发）

本地可操作的项目复刻功能版，核心主线：**台账 → 冻结快照/规则汇总 → 人工修订/审核发布 → 独立确认整改 → 负责人处理 → 退回/重提/验收**。

当前用途（2026-11-11 确认）：复刻此前公司项目，供本地演示与讲解。模拟业务数据即可，真实企业数据、外部系统与生产上线能力不作为这轮交付条件。最终目标是完成全部需求的复刻产品，功能优先、严格测试后置。当前分析模式为 DEMO_RULES，知识问答采用本地检索与原文摘录；真实模型可选增强。演示前阅读 [演示路线与范围](docs/Demo_Guide.md)。

Python 3.11+，SQLite 与原生 Web 界面，无需 npm install。首次运行 start.sh 会建立 .venv 并安装 pypdf（解析）和 reportlab（PDF 导出）；当前工作区已安装。PDF 导出自动使用本机 Arial Unicode 中文字体，其他机器可用 EAW_PDF_FONT 指定可嵌入的中文 TrueType 字体。

## 启动

从公开仓库获取源码后启动（已有本地目录时直接执行 `./start.sh --port 8765`）：

```sh
git clone https://github.com/alchemy9/enterprise-ai-work.git
cd enterprise-ai-work
./start.sh --port 8765
```

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。默认只监听本机，不支持公网访问。

仓库包含源码、PRD、演示说明与模拟操作截图。本地数据库、登录会话、备份、虚拟环境和环境变量文件不上传；首次启动会创建新的模拟项目与账号。文档中列出的历史报告/任务 ID 属于开发时的本地记录，新的运行实例会生成自己的 ID。

| 账号 | 角色 | 演示密码 |
| --- | --- | --- |
| `manager` | 项目经理；可审核自己发起的报告 | `EawDemo!2026` |
| `owner` | 项目成员/整改负责人 | `EawDemo!2026` |
| `reviewer` | 可被指定为报告审核人 | `EawDemo!2026` |
| `outsider` | 另一租户，仅有隔离项目权限 | `EawDemo!2026` |

这是本地演示认证，不能直接用于生产。密码经 scrypt 散列，会话 HttpOnly / SameSite=Strict、12 小时有效。每次接口检查有效账号、租户、项目与角色；成员/项目管理界面已实现；企业 SSO、HTTPS、登录防爆破和生产部署不属于当前演示交付。

## 操作闭环

1. `manager` 登录，在项目空间查看首次初始化的 **10 项、完成 4 项、完成率 40%、未完成逾期 2 项**台账。
2. 新建进度汇总，选择截至今天的周期、指定审核人，检查并确认数据缺口。历史周期没有期末快照会被拒绝。
3. 运行由服务端队列继续执行，等待审核后打开报告。可看台账行证据；要编辑时先撤回，生成新版本，再提交新审核单。
4. 指定审核人“核对通过并发布”。正文版本/hash 不一致、旧审核单、非指定审核人均会被拒绝。查看历史版本时审核按钮禁用。
5. 发布后点击“确认整改事项”，选择风险，填写负责人、截止日、验收标准；核对最终清单并明确确认，才会创建整改。报告批准本身不创建整改。
6. 退出并以 `owner` 登录，进入整改协同，开始处理、填写处理说明与证据、提交验收。
7. 切换回 `manager`，可退回（原因必填）；负责人补证重提后，由项目经理验收。负责人不能自行验收，已验收是终态。

五类页面均有实际接口与持久数据：项目空间、业务台账、任务运行/详情、报告列表/审核、整改列表/详情。CSV 支持预检、行级错误、下载错误清单、原子提交与按任务编号更新；台账页面也可编辑单条任务。

## 存储、重启与备份

- 默认数据库 `var/eaw.sqlite3`。关闭/重启不会重置账号、台账、运行、报告、审核或整改。不要删除该文件来“恢复”业务。
- 指定独立数据库：`python3 -m app.server --port 8766 --db /absolute/path/eaw.sqlite3`。不同数据库之间数据不共享。
- 初始种子以首次初始化的上海日期生成。跨日后动态逾期数可能变化；验证 40%/2 的固定规则集见自动测试。
- 使用 Python SQLite 在线备份：

```sh
python3 scripts/backup.py --output var/backups/eaw-backup.sqlite3
```

- 恢复时先停止服务，使用 `--db` 指向备份副本验证，再决定切换；恢复不会自动删除原数据库。
- 单服务实例由一个调度 Worker 推进业务；只读编排一批最多并行三个节点。重启从原快照和持久检查点继续；不重新计算已成功节点、不清空累计尝试。人工等待不占 Worker。
- 撤回作废旧审核单；取消禁止新步骤，取消后不能恢复；已完成发布的运行不允许取消，已创建整改独立存在。

## 开发检查

按用户要求，新增功能只检查语法、启动和关键操作，不扩写严格测试集或执行多轮回归。日常语法检查可使用：

```sh
python3 -m py_compile app/*.py
node --check static/app.js
node --check static/advanced.js
```

历史自动测试及实际结果保留在 `tests/` 和 `docs/Validation_Report.md`，对应此前的核心闭环版本，不能视为所有新增模块的完整验收。最新关键操作记录见 `docs/Development_Log.md`，截图在 `docs/evidence/current/`。

## API 要点

登录：`POST /api/auth/login`，JSON `{username,password}`。之后携带服务端会话 Cookie。所有 POST 需 `Content-Type: application/json` 与 `X-EAW-Request: 1`，浏览器跨站来源被拒绝。

| 操作 | 接口 |
| --- | --- |
| 当前账号/项目 | `GET /api/me`、`GET /api/projects/{id}` |
| CSV 预检/提交 | `POST /api/projects/{id}/imports`（`csv` 字符串）、`POST .../imports/{batch}/commit` |
| 发起/查询运行 | `POST /api/runs`（返回 202）、`GET /api/runs/{id}` |
| 取消/恢复 | `POST /api/runs/{id}/cancel`、`.../resume`（`expected_version`） |
| 报告与版本 | `GET /api/reports/{id}`、`POST .../withdraw`、`.../edit`、`.../submit` |
| 审核并发布 | `POST /api/approvals/{id}/decision`（`expected_version, report_version, content_hash, decision, comment, event_key`） |
| 整改参数冻结 | `POST /api/reports/{id}/confirmations`（`expected_version, items`） |
| 明确确认写入 | `POST /api/confirmations/{id}/execute`（`confirmed: true, params_hash`） |
| 整改详情/流转 | `GET /api/rectifications/{id}`、`POST .../transition`（`action, expected_version, event_key, comment, evidence`） |
| 导出与下载 | `POST /api/exports`、`GET /api/exports/{id}`、`POST .../link`、`GET /api/downloads/{token}`（当前授权，账号绑定，十分钟有效） |
| 历史/里程碑 | `GET /api/projects/{id}/planning`、`POST .../snapshots`、`POST .../milestones` |
| 编排与成果确认 | `GET /api/flows`、`POST /api/flows/{id}/run`、`GET /api/flow-runs/{id}`、`POST .../review` |
| 版本样本比较 | `GET/POST /api/evaluations`、`POST /api/evaluations/run`、`GET /api/evaluations/{id}` |

创建确认 30 分钟有效，绑定操作者、项目、报告版本与完整参数摘要。相同风险/报告版本的稳定 action_id 有唯一约束；同参数返回原任务 ID，异参数逐项返回冲突。重复流转的同 event_key 原样重放，不能改参数。一次审批的相反并发决策只能一个成功。所有错误返回业务错误码与 trace_id。

## 当前功能与真实边界

- **汇总整改主线**：台账/CSV、不可变快照、确定性统计、持久运行、报告原稿/修订、审核发布、独立确认整改、处理证据、退回重提与验收。
- **知识与问答**：知识库、TXT/Markdown/DOCX/PDF 上传、文本解析与索引、版本切换、来源定位、成员授权、下架与失败重试；本地关键词检索和摘录式问答、历史、引用与反馈；汇总报告冻结文档版本，来源撤权影响历史输出访问。
- **协作与管理**：项目切换、项目资料、成员/角色/移交、审核转交、成员账号与停用、项目创建/归档、站内待办通知、授权审计记录、成果收藏与 Markdown/Word 导出。演示经理明确兼任企业管理员、运营、工具管理员与审计角色。
- **演示数据与分析**：内置项目台账和三份虚构资料。分析模式 DEMO_RULES，问答为 LOCAL_EXTRACTIVE；未调用真实 LLM，没有把关键词检索标成语义向量检索。
- **扩展演示**：只读模拟源映射/同步/水位与来源快照汇总；每日/每周定时草稿、独立项目执行身份与人工审核；开放风险分析的澄清/计划确认/有限只读执行与证据结果；跨项目概览和第二个虚构示例项目；同项目追问、父段上下文、知识反馈处理。
- **模板与运行治理**：应用模板中心；Workflow/Agent/模型/工具的草稿、校验、沙箱预览、发布、复制、默认版本回滚与停用；汇总运行绑定版本，风险建议和报告开场配置生效；节点工具白名单、调用预算、上下文裁剪、运行评估与队列容量。预览采用本地规则，不是模型质量评测。
- **报告与 R2 编排**：历史快照/里程碑/上期比较、八章报告、正式版派生与替代、人工接管/指标声明；可拖动画布、并行/汇合、两层版本化子流程和人工成果确认，两个规则核对视角分别保留结果。
- **交付与后续协作**：整改拆分/关联跟进/处理记录/沟通摘要、失效待改派、催办/订阅/失败通知重投；后台 Markdown/Word/PDF 与十分钟下载、知识库负责人/默认有效期/库级授权/下架保留；八类变量和 Gold 样本比较/人工评审工作台。已支持安全段落/表格行的权限收窄和检索配置版本；真实模型/向量检索、企业连接和生产能力不宣称已接通。
- **检查方式**：用户要求先做成品，新增功能只做语法、启动与关键操作检查，不扩写严谨测试集、不做多轮回归。历史 27 项测试记录只对应此前版本，不代表新增功能全部经过严格验收。

完整功能覆盖进度见 `docs/requirements/Coverage.md`，开发批次见 `docs/Development_Log.md`。68 条编号需求均记录实现与边界，片段级混合权限与检索参数不可变版本现已接通；74 条原始验收用例保留为未逐项严格核验，不宣称生产或模型质量达标。

PDF 文本提取参考 [pypdf 官方文档](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)。本地解析不包含 OCR。

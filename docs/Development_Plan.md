# R1 MVP 开发计划与决策

日期：2026-11-10。范围：首先交付进度汇总 → 人工审核/发布 → 独立确认整改 → 处理/验收的本地纵向切片，不代表两份 PRD 全部 P0 已交付。

## 2026-11-11 最新执行要求

最终成品覆盖两份 PRD 的全部需求，模拟企业数据继续可用。用户明确先做成品，不扩写严格测试集、不做多轮严谨回归；开发阶段仅做语法、启动与关键操作的基本检查。完整需求台账位于 `requirements/coverage.json`，不能把当前已实现部分重新定义为全部完成。

## 2026-11-11 演示数据口径

用户明确：当前是此前公司项目的复刻，交付目标为可演示，不要求真实企业数据。后续工作按演示价值排序：现有闭环演示素材与路线 → 使用模拟文档的知识中心/引用问答 → 必要的模板、运行与治理展示。未实现的页面仍应标为待补齐，不以静态占位冒充可用功能。

真实模型接入是可选增强，不把“缺客户数据”当作阻断；若使用规则或预置分析，继续明确演示模式。外部连接、SSO、生产扩容、完整运维治理和生产性能指标不列为当前演示门槛。两份原始 PRD 不改写为已完成状态。具体演示验收与讲解步骤见 `Demo_Guide.md`。

## 技术与模块

- Python 3.11+ 标准库 HTTP 服务、SQLite WAL、原生 HTML/CSS/JavaScript；主服务依赖标准库，PDF 文本提取使用 pypdf，便于本地复现。
- `app/db.py`：版本化建表、演示种子、事务；`app/domain.py`：统计与字段校验；`app/service.py`：授权、状态机、业务事务；`app/server.py`：HTTP/会话/持久队列 Worker；`static/`：可操作工作台。
- 单机单服务实例，Worker 顺序处理持久队列。人工等待不占 Worker。SQLite `BEGIN IMMEDIATE` 与唯一约束串行化竞争写入；生产多实例/SSO/数据库加密另行设计。
- 账号使用 scrypt 密码散列、HttpOnly/SameSite 会话；每次请求重验有效账号、租户、项目成员与业务角色。服务仅监听 loopback。
- 当前模式为 `DEMO_RULES`：规则构建风险建议、引用冻结台账行；真实 LLM、文档语义检索、向量库尚未接通，不编造 token/成本/检索质量。

## 对象与状态

- Project/Membership/Ledger/ImportBatch；SourceSnapshot 保存 JSON、hash、采集时间，数据库触发器禁止更新删除。
- WorkflowRun：QUEUED → RUNNING → WAITING_REVIEW → RUNNING/PUBLISHING → COMPLETED；退回 REVIEW_REJECTED；撤回 phase=WAITING_REVISION；故障 FAILED；取消 CANCELLED。
- NodeAttempt 逐次保存，重启将中断尝试标记失败，从原快照恢复；预算/累计尝试不清零。
- Report + 不可变 ReportVersion；正文仅可编辑叙述，统计为独立只读规则区。编辑必须先撤回，生成新版本并记录人工补充/原因。
- Approval 绑定 report_version/content_hash/reviewer，单次决策；批准与发布两条事件。发布为独立持久队列阶段，可恢复。
- ActionConfirmation 冻结完整参数、hash、操作者、有效期（30 分钟）；Rectification 的 action_id 由报告版本/风险稳定生成，唯一约束防重。
- Rectification：TODO → IN_PROGRESS → PENDING_ACCEPTANCE → ACCEPTED；退回 REWORK → 重提；经理可取消未验收项。状态变动具有 expected_version 与 event_key。

## 需求映射与实施

1. ORG-02/03、SEC-01/02：最小账号与项目授权，演示经理/审核人/负责人及隔离账号。
2. DATA-01、RPT-01/02、WA-T11/12：内置台账、原子 CSV 预检/提交、历史快照缺失拦截、40%/2 固定集。
3. WF-01、RUN-01/02/03、AG-R04：固定节点、冻结证据、明确缺口、持久队列/尝试/恢复/取消。
4. APR-01/02/03、HITL-01/02/03：原稿、修订、审核版本/hash、乐观锁、发布与重放。
5. FIX-01/02/03、TOOL-S03/04：独立动作确认、参数 hash、批量逐项结果、幂等创建、处理证据与验收活动。
6. OUT-01、OPS-03：报告历史、Markdown 导出、对象级活动审计。完整文档知识库、问答、DOCX 导出、配置管理及运营平台不在这个首个切片中，后续单列。
7. unittest 真实 HTTP 验证规则、权限、旧审核、并发决策、确认过期/变参、幂等、状态转换、取消、Worker 重启及发布故障恢复；浏览器操作本地闭环并截图。

## 决策日志

- 主 PRD 与专项对于批准后发布阶段的状态表差异：按专项使用 RUNNING + PUBLISHING；COMPLETED 仅在正式版发布成功后。
- 演示台账以首次初始化的上海日期生成，非历史业绩；刷新不重置，后续日期统计可能变化。完整固定统计由冻结日期测试独立验证。
- 当前历史周期没有期末快照时直接拒绝；允许用户选择截至今天的当前状态汇总，不倒推历史。
- 所有演示数据和业务记录写入 `var/eaw.sqlite3`（忽略提交），首次启动初始化，之后只执行非破坏迁移。
- schema v2 依据已有审核单/事件补齐早期人工等待节点的生命周期跟踪，保留原报告/hash/审核决策/业务状态；无法确定的历史结束时间保持未知，不编造耗时。

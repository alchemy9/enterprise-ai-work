'use strict';
const ADV={analysisKey:null};
Object.assign(statusNames,{AWAITING_PLAN:'等待计划确认',NEEDS_CLARIFICATION:'待补充信息',PARTIAL:'部分完成',STOPPED:'已停止',PAUSED:'已暂停',CREATED:'已创建',SKIPPED:'已跳过',DISABLED:'已停用',SUCCEEDED:'成功'});
Object.assign(colors,{AWAITING_PLAN:'orange',NEEDS_CLARIFICATION:'orange',PARTIAL:'orange',STOPPED:'gray',PAUSED:'orange',CREATED:'green',SKIPPED:'gray',DISABLED:'gray'});
const advField=(name,label,value,type='text',extra='')=>`<div class="field"><label for="adv-${name}">${label}</label><input id="adv-${name}" name="${name}" type="${type}" value="${esc(value??'')}" ${extra}></div>`;
const advArea=(name,label,value,rows=4)=>`<div class="field full"><label for="adv-${name}">${label}</label><textarea id="adv-${name}" name="${name}" rows="${rows}" required>${esc(value)}</textarea></div>`;
function advDialog(title,content,submit,kind){kbDialog(title,content,submit,'advanced-'+kind);const form=$('#dialog form');delete form.dataset.kbForm;if(kind.startsWith('rp-'))form.dataset.reportForm=kind;else form.dataset.advForm=kind;}

function connectionsPage(data){
  return `${pagehead('数据连接','以只读模拟数据源演示字段映射、同步水位与快照。','<button class="primary" data-adv-action="new-connection">'+icon('plus')+'新建模拟连接</button>')}
  <div class="notice">${icon('info')}<span>本页数据源来自本地模拟记录。同步不会改动内置台账；发起汇总时可以选用同步后的来源快照。</span></div>
  <section class="panel"><div class="tablewrap"><table><thead><tr><th>连接名称 / 方式</th><th>状态</th><th>最近同步成功</th><th>水位</th><th></th></tr></thead><tbody>${data.items.map(x=>`<tr><td class="title">${esc(x.name)}<div class="sub">只读模拟源 · ${esc(x.config.address)}</div></td><td>${tag(x.state,x.state==='ACTIVE'?'启用中':'已停用')}<div class="sub">${{VALID:'模拟凭据有效',EXPIRED:'模拟凭据已到期',REVOKED:'模拟凭据已撤销'}[x.config.credential_state]}</div></td><td>${fmt(x.last_success_at)}</td><td>${x.watermark}</td><td><a href="#/connections/${x.id}">查看与同步 →</a></td></tr>`).join('')}</tbody></table></div>${data.items.length?'':empty('尚未配置数据连接','可以用当前项目台账作为模拟源创建连接，再修改模拟源记录演示增量同步。')}</section>`;
}

function connectionDetail(x){
  const last=x.jobs[0],pending=x.jobs.some(j=>j.state==='QUEUED');
  return `<a class="back" href="#/connections">${icon('back')}全部数据连接</a>${pagehead(x.name,'当前项目 · 本地只读模拟源',`<button data-adv-action="edit-connection">编辑配置</button><button data-adv-action="test-connection">检查连接</button><button class="primary" data-adv-action="sync-connection" ${pending?'disabled':''}>${pending?'正在同步…':'同步模拟源'}</button>`)}
  <div class="twocol"><section class="panel"><div class="panelhead"><h2>连接与同步</h2>${tag(x.state,x.state==='ACTIVE'?'已启用':'已停用')}</div><div class="panelbody"><dl class="keyvalues"><dt>数据模式</dt><dd>DEMO_READ_ONLY · 未连接企业系统</dd><dt>源地址</dt><dd class="mono">${esc(x.config.address)}</dd><dt>凭据引用</dt><dd>${esc(x.config.credential_ref)}<div class="sub">${{VALID:'模拟有效',EXPIRED:'模拟到期',REVOKED:'模拟撤销'}[x.config.credential_state]}，无真实密钥</div></dd><dt>同步频率</dt><dd>${x.config.sync_minutes?'每 '+x.config.sync_minutes+' 分钟':'手动同步'}</dd><dt>最近成功</dt><dd>${fmt(x.last_success_at)}</dd><dt>有效水位</dt><dd>${x.watermark}</dd><dt>最近有效快照</dt><dd class="mono">${esc(x.last_snapshot_id||'尚无')}</dd></dl><div class="actions"><button data-adv-action="connection-status">${x.state==='ACTIVE'?'停用连接':'启用连接'}</button>${x.snapshot?'<a class="button primary" href="#/new" data-adv-source="'+x.id+'">用此快照生成汇总</a>':''}</div></div></section><section class="panel"><div class="panelhead"><h2>最近同步结果</h2>${last?tag(last.state):''}</div><div class="panelbody">${last?last.state==='FAILED'?`<div class="error">${esc(last.data.error.message)}<div class="mono">${esc(last.data.error.code)} · ${esc(last.id)}</div></div><p class="sub">原有效快照保留：${esc(last.data.retained_snapshot_id||'尚无')}</p>`:last.state==='QUEUED'?'<p>任务已受理，服务端正在处理。</p>':`<p>读取 ${last.data.row_count} 条，变化 ${last.data.changed_count} 条。</p><p class="sub">水位 ${last.data.watermark} · ${fmt(last.updated_at)}</p>`:'<p class="sub">先检查连接，再同步模拟源。</p>'}<details><summary>查看字段映射</summary><pre class="pre">${esc(JSON.stringify(x.config.field_mapping,null,2))}</pre></details></div></section></div>
  <section class="panel"><div class="panelhead"><h2>最近有效快照</h2><span class="sub">${x.snapshot?.rows.length||0} 条 · 不因后续源修改而改变</span></div>${x.snapshot?`<div class="tablewrap"><table><thead><tr><th>任务</th><th>状态</th><th>负责人</th><th>截止日期</th></tr></thead><tbody>${x.snapshot.rows.slice(0,20).map(r=>`<tr><td class="title">${esc(r.task_id)} · ${esc(r.title)}</td><td>${tag(r.status)}</td><td>${esc(person(r.owner_id))}</td><td>${esc(r.due_date||'未提供')}</td></tr>`).join('')}</tbody></table></div>`:empty('尚无有效快照','首次同步成功后显示。')}</section>
  <section class="panel"><div class="panelhead"><h2>同步与配置记录</h2></div>${x.events.map(e=>`<div class="listrow"><div class="grow"><strong>${esc(e.action)}</strong><p>${esc(e.data.error?.message||e.data.snapshot_id||e.data.mode||'连接配置已记录')}</p></div>${tag(e.state)}<span class="sub">${fmt(e.created_at)}</span></div>`).join('')}</section>`;
}

function connectionEditor(x){
  ADV.editConnection=x;
  const config=x?.config||{source_rows:S.detail.sample_rows,field_mapping:S.detail.field_mapping,sync_minutes:0,credential_state:'VALID',failure_mode:'NONE'};
  advDialog(x?'编辑模拟数据源':'新建只读模拟连接',`${advField('name','连接名称',x?.name||'项目任务 · 只读模拟连接','text','maxlength="100" required')}<div class="formgrid">${advField('sync_minutes','同步间隔（分钟，0 为手动）',config.sync_minutes,'number','min="0" max="1440" required')}<div class="field"><label for="adv-credential_state">凭据演示状态</label><select id="adv-credential_state" name="credential_state">${[['VALID','有效 / 重新授权'],['EXPIRED','到期'],['REVOKED','撤销']].map(([v,n])=>`<option value="${v}" ${config.credential_state===v?'selected':''}>${n}</option>`).join('')}</select></div><div class="field full"><label for="adv-failure_mode">同步故障演示</label><select id="adv-failure_mode" name="failure_mode">${[['NONE','正常'],['NETWORK','模拟网络故障，保留旧快照'],['SCHEMA','模拟字段变更，停止切换快照']].map(([v,n])=>`<option value="${v}" ${config.failure_mode===v?'selected':''}>${n}</option>`).join('')}</select></div></div>${advArea('field_mapping','字段映射（标准字段 → 模拟源列名）',JSON.stringify(config.field_mapping,null,2),5)}${advArea('source_rows','模拟源记录（JSON 数组，可编辑后同步）',JSON.stringify(config.source_rows,null,2),9)}<p class="sub">只在本地读取这组记录，不访问外部地址，也不写入企业系统。</p>`,'保存连接','connection');
}

function schedulesPage(data){
  return `${pagehead('定时汇总','按上海时区生成待审草稿，自动执行到人工审核为止。','<button class="primary" data-adv-action="new-schedule">'+icon('plus')+'新建计划</button>')}
  <section class="panel"><div class="tablewrap"><table><thead><tr><th>计划 / 周期</th><th>状态</th><th>下一次执行</th><th>执行身份</th><th></th></tr></thead><tbody>${data.items.map(s=>`<tr><td class="title">${esc(s.data.name)}<div class="sub">${scheduleDescription(s.data)} · 最近 ${s.data.period_days} 天</div></td><td>${tag(s.state,s.state==='ACTIVE'?'启用中':'已暂停')}</td><td>${fmt(s.next_at)}</td><td>${esc(s.execution_name)}<div class="sub">仅当前项目执行权限</div></td><td><a href="#/schedules/${s.id}">管理计划 →</a></td></tr>`).join('')}</tbody></table></div>${data.items.length?'':empty('尚无定时汇总计划','可新建每日或每周计划，并用“立即触发一次”展示执行效果。')}</section>
  <div class="notice">${icon('info')}<span>计划使用独立执行身份。创建者、执行身份或审核人失效时暂停；上次仍在运行或待审时跳过。服务关闭期间不执行，恢复后只补最近一次。</span></div>`;
}
function scheduleDescription(d){return `${d.frequency==='DAILY'?'每天':'每周'+['一','二','三','四','五','六','日'][d.weekday]} ${d.time} · ${d.timezone}`;}
function scheduleDetail(s){
  return `<a class="back" href="#/schedules">${icon('back')}全部计划</a>${pagehead(s.data.name,scheduleDescription(s.data),`<button data-adv-action="edit-schedule">编辑计划</button><button data-adv-action="schedule-status">${s.state==='ACTIVE'?'暂停计划':'启用计划'}</button><button class="primary" data-adv-action="trigger-schedule" ${s.state!=='ACTIVE'?'disabled':''}>立即触发一次</button>`)}
  <section class="panel"><div class="panelhead"><h2>计划设置</h2>${tag(s.state,s.state==='ACTIVE'?'启用中':'已暂停')}</div><div class="panelbody"><dl class="keyvalues"><dt>下一次执行</dt><dd>${fmt(s.next_at)}</dd><dt>统计周期</dt><dd>截至触发当天的最近 ${s.data.period_days} 天</dd><dt>审核人</dt><dd>${esc(person(s.data.reviewer_id))}</dd><dt>模板版本</dt><dd>${esc(s.data.workflow_id)} · ${s.data.version_strategy==='LATEST'?'触发时使用最新发布版':'固定 v'+s.data.workflow_version}</dd><dt>执行身份</dt><dd class="mono">${esc(s.execution_user_id)}</dd><dt>资料范围</dt><dd>${s.data.include_documents?'执行身份有权读取的当前项目资料':'仅任务台账'}</dd><dt>截止日期</dt><dd>${esc(s.data.expires_on||'未设置')}</dd><dt>授权边界</dt><dd>只生成草稿并提交人工审核；发布与整改需人操作</dd></dl></div></section>
  <section class="panel"><div class="panelhead"><h2>触发记录</h2></div><div class="tablewrap"><table><thead><tr><th>触发时间</th><th>方式</th><th>结果</th><th>说明</th><th></th></tr></thead><tbody>${s.fires.map(f=>`<tr><td>${fmt(f.created_at)}</td><td>${f.trigger_type==='TIMER'?'定时':'手动触发演示'}</td><td>${tag(f.state)}</td><td>${esc(f.data.error?.message||f.data.reason||(f.data.delayed?'离线后补最近一次':'已创建待审草稿运行'))}</td><td>${f.run_id?`<a href="#/runs/${f.run_id}">查看运行 →</a>`:f.data.previous_run_id?`<a href="#/runs/${f.data.previous_run_id}">前次运行 →</a>`:''}</td></tr>`).join('')}</tbody></table></div>${s.fires.length?'':empty('还没有触发记录','等待计划执行，或手动触发一次查看草稿链路。')}</section>`;
}
async function scheduleEditor(s){
  ADV.editSchedule=s;const d=s?.data||{name:'每周项目进度汇总',frequency:'WEEKLY',time:'09:00',weekday:0,period_days:7,reviewer_id:S.me.user.id,workflow_id:'wf_progress',version_strategy:'LATEST',expires_on:'',include_documents:true};
  const options=await api('/projects/'+S.pid+'/schedules');
  advDialog(s?'编辑定时计划':'新建定时汇总计划',`${advField('name','计划名称',d.name,'text','maxlength="100" required')}<div class="formgrid"><div class="field"><label for="adv-frequency">触发频率</label><select id="adv-frequency" name="frequency"><option value="DAILY" ${d.frequency==='DAILY'?'selected':''}>每天</option><option value="WEEKLY" ${d.frequency==='WEEKLY'?'selected':''}>每周</option></select></div>${advField('time','上海时区执行时间',d.time,'time','required')}<div class="field"><label for="adv-weekday">每周执行日</label><select id="adv-weekday" name="weekday">${['一','二','三','四','五','六','日'].map((v,i)=>`<option value="${i}" ${d.weekday===i?'selected':''}>星期${v}</option>`).join('')}</select></div>${advField('period_days','统计最近多少天',d.period_days,'number','min="1" max="90" required')}<div class="field"><label for="adv-workflow_id">汇总模板</label><select id="adv-workflow_id" name="workflow_id">${options.templates.filter(t=>t.scene==='PROGRESS').map(t=>`<option value="${t.id}" ${d.workflow_id===t.id?'selected':''}>${esc(t.name)} · v${t.version}</option>`).join('')}</select></div><div class="field"><label for="adv-version_strategy">版本策略</label><select id="adv-version_strategy" name="version_strategy"><option value="LATEST" ${d.version_strategy==='LATEST'?'selected':''}>触发时使用最新发布版</option><option value="PINNED" ${d.version_strategy==='PINNED'?'selected':''}>固定为本次保存时的发布版</option></select></div><div class="field"><label for="adv-reviewer_id">指定审核人</label><select id="adv-reviewer_id" name="reviewer_id">${options.members.map(m=>`<option value="${m.id}" ${m.id===d.reviewer_id?'selected':''}>${esc(m.name)}</option>`).join('')}</select></div>${advField('expires_on','计划截止日期（选填）',d.expires_on,'date')}</div><label class="check"><input name="include_documents" type="checkbox" ${d.include_documents?'checked':''}>纳入执行身份授权的项目资料</label><p class="sub">保存后将按此范围自动发起草稿。独立执行身份没有配置管理权限，不能自动审核、发布或创建整改。</p>`,'保存计划','schedule');
}

function analysesPage(data){
  return `${pagehead('开放风险分析','先确认读取计划，再核对事实与原因线索。','<button class="primary" data-adv-action="new-analysis">'+icon('plus')+'新建分析</button>')}
  <div class="notice">${icon('info')}<span>当前为计划确认与证据分析的本地演示，采用规则和关键词检索。分析只读，不会直接分配、关闭或创建任务。</span></div>
  <section class="panel"><div class="tablewrap"><table><thead><tr><th>分析目标</th><th>状态</th><th>选择周期</th><th>创建时间</th><th></th></tr></thead><tbody>${data.items.map(a=>`<tr><td class="title">${esc(a.goal)}</td><td>${tag(a.state,a.state==='COMPLETED'?'分析完成':null)}</td><td>${esc(a.period_start||'待补充')} ～ ${esc(a.period_end||'待补充')}</td><td>${fmt(a.created_at)}</td><td><a href="#/analyses/${a.id}">查看 →</a></td></tr>`).join('')}</tbody></table></div>${data.items.length?'':empty('尚无开放分析','填写目标，选择关注任务与资料范围，系统会先展示读取计划。')}</section>`;
}

function analysisEditor(a){
  ADV.editAnalysis=a;const d=a?.data||{goal:'分析验收联调延期的可能原因，并列出仍需核实的信息',period_start:dayAdd(S.me.today,-6),period_end:S.me.today,include_documents:true,task_ids:[]};
  const tasks=S.project.ledger;
  advDialog(a?a.state==='NEEDS_CLARIFICATION'?'补充分析参数':'调整目标与读取范围':'新建风险原因分析',`${advArea('goal','分析目标',d.goal,3)}<div class="formgrid">${advField('period_start','开始日期（可先留空，演示澄清）',d.period_start,'date',`max="${S.me.today}"`)}${advField('period_end','结束日期',d.period_end,'date',`max="${S.me.today}"`)}</div><div class="field"><label>关注任务（空选表示当前项目全部任务）</label><div class="adv-task-options">${tasks.map(t=>`<label class="check"><input name="task_ids" type="checkbox" value="${esc(t.task_id)}" ${d.task_ids.includes(t.task_id)?'checked':''}>${esc(t.task_id)} · ${esc(t.title)}</label>`).join('')}</div></div><label class="check"><input name="include_documents" type="checkbox" ${d.include_documents?'checked':''}>读取当前授权项目资料查找线索</label><p class="sub">下一步先确认计划。改变范围会生成新的计划版本，旧确认不可复用。</p>`,'生成待确认计划','analysis');
}

function analysisDetail(a){
  const d=a.data,p=a.plans[0],running=['QUEUED','RUNNING'].includes(a.state);
  return `<a class="back" href="#/analyses">${icon('back')}全部分析</a>${pagehead('风险原因分析',d.goal,`<button data-action="refresh">${icon('refresh')}刷新</button>${['AWAITING_PLAN','NEEDS_CLARIFICATION'].includes(a.state)?'<button data-adv-action="revise-analysis">调整目标与范围</button>':''}${!['COMPLETED','CANCELLED','STOPPED'].includes(a.state)?'<button data-adv-action="cancel-analysis">取消分析</button>':''}`)}
  <div class="twocol"><div>${a.state==='NEEDS_CLARIFICATION'?`<section class="panel"><div class="panelhead"><h2>补充时间范围</h2>${tag(a.state,a.state==='COMPLETED'?'分析完成':null)}</div><div class="panelbody"><p>分析目标已保存，还需明确开始和结束日期。</p><p class="sub">当前澄清 ${d.clarification_rounds} / 2 轮。补齐后生成计划，确认前不读取业务资料。</p><button class="primary" data-adv-action="revise-analysis">补充参数</button></div></section>`:''}
  ${p?`<section class="panel"><div class="panelhead"><h2>读取计划 v${p.version}</h2>${tag(a.state,a.state==='COMPLETED'?'分析完成':null)}</div><div class="panelbody"><p>${esc(p.data.expected_result)}</p><ol class="cfg-nodes">${p.data.steps.map(s=>`<li><strong>${esc(s.title)}</strong><div class="sub">${esc(s.tool)} · ${esc(s.scope.join('、'))}</div></li>`).join('')}</ol><p class="sub">${esc(p.data.risk)} · 工具上限 ${p.data.budget.tool_calls} 次，分析上限 ${p.data.budget.iterations} 轮。</p>${a.state==='AWAITING_PLAN'?'<button class="primary" data-adv-action="confirm-plan">核对计划并开始分析</button>':`<p class="sub">${d.confirmed_at?'确认时间：'+fmt(d.confirmed_at):'计划尚未执行'}</p>`}</div></section>`:''}
  ${d.summary?`<section class="panel"><div class="panelhead"><h2>分析结果</h2><span class="tag blue">本地规则 · 待核实假设</span></div><div class="panelbody"><p>${esc(d.summary)}</p>${d.metrics?`<div class="adv-result-metrics"><span>完成率 <strong>${d.metrics.completion_rate??'—'}${d.metrics.completion_rate===null?'':'%'}</strong></span><span>未完成逾期 <strong>${d.metrics.overdue_count} 项</strong></span></div>`:''}<h3>规则事实</h3>${d.facts.map(f=>`<p class="adv-fact">${esc(f.text)} ${f.evidence_ids.map(id=>`<button class="text" data-adv-evidence="${esc(id)}">依据 ↗</button>`).join('')}</p>`).join('')}<h3>原因假设与替代解释</h3>${d.hypotheses.map(h=>`<article class="adv-hypothesis"><h3>${esc(h.title)}</h3><p>${esc(h.hypothesis)}</p><div class="actions">${h.supporting_evidence_ids.map(id=>`<button class="text" data-adv-evidence="${esc(id)}">支持线索 ↗</button>`).join('')||'<span class="sub">尚无直接支持该原因的证据</span>'}</div><ul class="gaps">${h.missing_information.map(m=>`<li>${esc(m)}</li>`).join('')}</ul><p><strong>建议验证：</strong>${esc(h.validation_action)}</p></article>`).join('')||'<p class="sub">所选任务当前未发现未完成逾期，仍需结合资料核实其他风险。</p>'}<h3>信息缺口与停止原因</h3><ul class="gaps">${d.missing_information.map(m=>`<li>${esc(m)}</li>`).join('')}</ul><p class="sub">${esc(d.stop_reason)}</p><a class="button" href="#/new">需要正式汇总时进入审核流程 →</a></div></section>`:running?'<section class="panel"><div class="panelbody loading">正在按已确认计划读取与核对证据…</div></section>':''}
  ${d.error?`<div class="error">${esc(d.error.message)}<div class="mono">${esc(d.error.code)} · ${esc(d.error.trace_id)}</div></div>`:''}</div><aside><section class="panel"><div class="panelhead"><h2>范围与用量</h2></div><div class="panelbody"><dl class="keyvalues"><dt>选择周期</dt><dd>${esc(d.period_start||'待补充')} ～ ${esc(d.period_end||'待补充')}</dd><dt>台账截点</dt><dd>${fmt(d.cutoff_time)}</dd><dt>关注任务</dt><dd>${d.task_ids.length?d.task_ids.map(esc).join('、'):'当前项目全部任务'}</dd><dt>工具调用</dt><dd>${d.tool_calls} / 8 次</dd><dt>分析步骤</dt><dd>${d.iterations} / 3 轮</dd><dt>活跃耗时</dt><dd>${d.active_seconds} 秒，不含等待确认</dd><dt>模型用量</dt><dd>0 调用 · 0 tokens</dd></dl></div></section><section class="panel"><div class="panelhead"><h2>执行轨迹</h2></div><div class="panelbody">${a.steps.map(s=>`<div class="activity"><strong>${s.ordinal}. ${esc(s.tool_id)}</strong><p>${esc(JSON.stringify(s.result))}</p><span class="sub">${fmt(s.started_at)}</span></div>`).join('')||'<p class="sub">确认计划后开始记录。</p>'}</div></section>${d.evidence?.filter(e=>e.kind==='DOCUMENT').length?`<section class="panel"><div class="panelhead"><h2>文档证据</h2></div><div class="panelbody">${d.evidence.filter(e=>e.kind==='DOCUMENT').map(e=>`<button class="citation-card" data-adv-evidence="${e.evidence_id}"><strong>${esc(e.title)}</strong><span>${esc(e.version)} · ${esc(e.locator)}</span></button>`).join('')}</div></section>`:''}</aside></div>`;
}

function portfolioPage(data){
  return `${pagehead('跨项目概览','统一查看授权项目当前进度、风险与整改。',(hasRole('enterprise_admin')?'<button data-adv-action="demo-project">添加另一示例项目</button>':'')+'<button data-action="refresh">'+icon('refresh')+'刷新</button>')}
  <div class="cfg-stats">${[['授权项目',data.totals.projects],['任务总数',data.totals.tasks],['已完成',data.totals.completed],['未完成逾期',data.totals.overdue],['未结束整改',data.totals.open_fixes]].map(([n,v])=>`<div class="panel"><span class="sub">${n}</span><strong>${v}</strong></div>`).join('')}</div>
  <section class="panel"><div class="panelhead"><h2>当前状态对比</h2><span class="sub">统一截点：${data.cutoff} · 上海时区</span></div><div class="tablewrap"><table><thead><tr><th>项目</th><th>完成率</th><th>本期完成</th><th>未完成逾期</th><th>整改待办</th><th></th></tr></thead><tbody>${data.items.map(x=>`<tr><td class="title">${esc(x.project.name)}<div class="sub">${esc(x.project.code)} · ${statusNames[x.project.status]||x.project.status}</div></td><td><div class="adv-mini-progress"><i style="width:${x.metrics.completion_rate||0}%"></i></div>${x.metrics.completion_rate??'—'}${x.metrics.completion_rate===null?'':'%'}</td><td>${x.metrics.period_completed}</td><td>${x.metrics.overdue_count}</td><td>${x.open_fixes}</td><td><button class="text" data-adv-action="project" data-id="${x.project.id}">进入项目 →</button></td></tr>`).join('')}</tbody></table></div></section>
  <section class="panel"><div class="panelhead"><h2>已发布报告趋势</h2><span class="sub">保留各自的数据截点</span></div>${data.items.map(x=>`<div class="panelbody"><h3>${esc(x.project.name)}</h3>${x.trend.length?`<div class="adv-trends">${x.trend.map(t=>`<a href="#/reports/${t.report_id}" data-adv-project="${x.project.id}" class="adv-trend"><span class="sub">${fmt(t.cutoff_time)}</span><strong>${t.completion_rate??'—'}${t.completion_rate===null?'':'%'}</strong><span>未完成逾期 ${t.overdue_count} 项</span></a>`).join('')}</div>`:'<p class="sub">尚无有权查看的已发布报告，不生成趋势曲线。</p>'}</div>`).join('')}</section><div class="notice">${icon('info')}<span>${esc(data.trend_note)} 当前比较来自模拟项目中的实际台账与业务状态。</span></div>`;
}

pageModules.connections={title:'数据连接',visible:manager,load:id=>api(id?'/connections/'+id:'/projects/'+S.pid+'/connections'),render:(d,id)=>id?connectionDetail(d):connectionsPage(d),isActive:d=>d.jobs?.some(j=>j.state==='QUEUED')};
pageModules.schedules={title:'定时汇总',visible:manager,load:id=>api(id?'/schedules/'+id:'/projects/'+S.pid+'/schedules'),render:(d,id)=>id?scheduleDetail(d):schedulesPage(d)};
pageModules.analyses={title:'开放风险分析',visible:manager,load:id=>api(id?'/analyses/'+id:'/projects/'+S.pid+'/analyses'),render:(d,id)=>id?analysisDetail(d):analysesPage(d),isActive:d=>['QUEUED','RUNNING'].includes(d.state)};
pageModules.portfolio={title:'跨项目概览',global:true,load:()=>api('/portfolio'),render:portfolioPage};
const feedbackKindName=k=>({HELPFUL:'有帮助',WRONG_ANSWER:'答案有误',WRONG_CITATION:'引用不对',OUTDATED:'信息过期',OTHER:'其他'}[k]||k);
const feedbackStateName=k=>({OPEN:'待处理',PROCESSING:'处理中',RESOLVED:'已解决',DISMISSED:'不采纳'}[k]||k);
function feedbackPage(data){
  return `${pagehead('知识反馈','查看用户主动提交的问答问题，跟踪资料修正与处理结论。')}<section class="panel"><div class="tablewrap"><table><thead><tr><th>问题与反馈</th><th>反馈人</th><th>类型</th><th>状态</th><th></th></tr></thead><tbody>${data.items.map(f=>`<tr><td class="title">${esc(f.question)}<div class="sub">${esc(f.comment||'未补充说明')}</div><details><summary class="sub">查看授权样本与引用</summary><p>${esc(f.answer)}</p>${f.facts.map(x=>`<p class="sub">${esc(x.text)}</p>`).join('')}<div class="actions">${f.evidence.map(e=>`<button class="text" data-kb-action="citation" data-id="${e.evidence_id}">${esc(e.title)} ↗</button>`).join('')}</div></details></td><td>${esc(f.actor_name)}<div class="sub">${fmt(f.created_at)}</div></td><td>${feedbackKindName(f.kind)}</td><td>${feedbackStateName(f.state)}<div class="sub">${esc(f.resolution_note)}</div></td><td><button class="text" data-adv-action="handle-feedback" data-id="${f.id}">记录处理 →</button></td></tr>`).join('')}</tbody></table></div>${data.items.length?'':empty('暂无授权范围内反馈','用户提交有帮助、答案或引用问题后，会显示在这里。')}</section>`;
}
pageModules.feedback={title:'知识反馈',visible:()=>['manager','knowledge_admin'].includes(currentProjectRole()),load:()=>api('/projects/'+S.pid+'/feedback'),render:feedbackPage};

document.addEventListener('click',async event=>{
  const source=event.target.closest('[data-adv-source]');if(source){ADV.source=source.dataset.advSource;return;}
  const project=event.target.closest('[data-adv-project]');if(project){S.pid=project.dataset.advProject;localStorage.setItem('eaw-project',S.pid);S.project=null;}
  const ev=event.target.closest('[data-adv-evidence]');
  if(ev){const evidence=S.detail.data.evidence.find(e=>e.evidence_id===ev.dataset.advEvidence);if(evidence.kind==='DOCUMENT')await showKnowledgeEvidence(evidence.evidence_id);else modal('冻结台账证据',`<h3>${esc(evidence.title)}</h3><p class="sub">${esc(evidence.snapshot_id)} · ${esc(evidence.locator)}</p><pre class="pre">${esc(JSON.stringify(evidence.row,null,2))}</pre>`,'<button data-action="close">关闭</button>');return;}
  const button=event.target.closest('[data-adv-action]');if(!button)return;
  const action=button.dataset.advAction;
  try{
    button.disabled=true;
    if(action==='new-connection')connectionEditor(null);
    else if(action==='handle-feedback'){
      ADV.feedback=S.detail.items.find(f=>f.id===button.dataset.id);
      advDialog('记录反馈处理',`<p>${esc(ADV.feedback.question)}</p><div class="field"><label for="adv-state">处理状态</label><select id="adv-state" name="state">${['OPEN','PROCESSING','RESOLVED','DISMISSED'].map(x=>`<option value="${x}" ${x===ADV.feedback.state?'selected':''}>${feedbackStateName(x)}</option>`).join('')}</select></div>${advArea('note','处理说明',ADV.feedback.resolution_note,3)}`,'保存处理','feedback');
    }
    else if(action==='demo-project'){await api('/portfolio/demo-project',{});toast('示例项目已准备，不覆盖已有数据');await refresh();}
    else if(action==='edit-connection')connectionEditor(S.detail);
    else if(action==='test-connection'){const x=S.detail;const r=await api('/connections/'+x.id+'/test',{expected_version:x.version});toast(r.message);await refresh();}
    else if(action==='sync-connection'){await api('/connections/'+S.detail.id+'/sync',{event_key:key()});toast('同步任务已受理');await refresh();}
    else if(action==='connection-status'){const x=S.detail;await api('/connections/'+x.id+'/status',{state:x.state==='ACTIVE'?'DISABLED':'ACTIVE',expected_version:x.version});await refresh();}
    else if(action==='new-schedule')await scheduleEditor(null);
    else if(action==='edit-schedule')await scheduleEditor(S.detail);
    else if(action==='schedule-status'){const x=S.detail;await api('/schedules/'+x.id+'/status',{state:x.state==='ACTIVE'?'PAUSED':'ACTIVE',expected_version:x.version});await refresh();}
    else if(action==='trigger-schedule')advDialog('触发一次汇总草稿',`<p>${esc(S.detail.data.name)}</p><p>会使用计划的执行身份、模板策略和审核人生成草稿。前一次仍在运行或待审时跳过。</p><label class="check"><input name="confirmed" type="checkbox" required>我已核对，确认触发一次</label>`,'确认触发','trigger');
    else if(action==='new-analysis')analysisEditor(null);
    else if(action==='revise-analysis')analysisEditor(S.detail);
    else if(action==='confirm-plan')advDialog('确认读取计划',`<p>${esc(S.detail.data.goal)}</p><p>计划 v${S.detail.data.plan_version} · 仅当前项目的已列明读取与计算工具。</p><label class="check"><input name="confirmed" type="checkbox" required>我已核对目标、范围与预算，同意开始只读分析</label>`,'确认计划并执行','confirm-plan');
    else if(action==='cancel-analysis')advDialog('取消分析',advArea('reason','取消原因','',3),'确认取消','cancel-analysis');
    else if(action==='project'){S.pid=button.dataset.id;localStorage.setItem('eaw-project',S.pid);S.project=null;location.hash='#/overview';}
  }catch(error){failure(error,$('#dialog').open?$('#dialog'):document);}finally{if(button.isConnected)button.disabled=false;}
});

document.addEventListener('submit',async event=>{
  const form=event.target,kind=form.dataset.advForm;if(!kind)return;event.preventDefault();const b=Object.fromEntries(new FormData(form));const button=form.querySelector('button[type=submit]');button.disabled=true;
  try{
    let target=null;
    if(kind==='feedback'){
      await api('/projects/'+S.pid+'/feedback/'+ADV.feedback.id,{state:b.state,note:b.note,expected_version:ADV.feedback.resolution_version});toast('反馈处理已保存');
    }else if(kind==='connection'){
      const payload={name:b.name,sync_minutes:Number(b.sync_minutes),credential_state:b.credential_state,failure_mode:b.failure_mode,source_rows:JSON.parse(b.source_rows),field_mapping:JSON.parse(b.field_mapping)};
      const x=ADV.editConnection;if(x)payload.expected_version=x.version;
      const r=await api(x?'/connections/'+x.id+'/save':'/projects/'+S.pid+'/connections',payload);target='#/connections/'+r.id;toast('模拟连接已保存');
    }else if(kind==='schedule'){
      const payload={...b,weekday:Number(b.weekday),period_days:Number(b.period_days),include_documents:b.include_documents==='on'};const x=ADV.editSchedule;if(x)payload.expected_version=x.version;
      const r=await api(x?'/schedules/'+x.id+'/save':'/projects/'+S.pid+'/schedules',payload);target='#/schedules/'+r.id;toast('定时计划已保存');
    }else if(kind==='trigger'){
      const x=S.detail;const r=await api('/schedules/'+x.id+'/trigger',{expected_version:x.version,event_key:key()});toast(r.state==='CREATED'?'草稿运行已创建':r.data.reason||'本次触发已记录');
    }else if(kind==='analysis'){
      const payload={goal:b.goal,period_start:b.period_start||null,period_end:b.period_end||null,include_documents:b.include_documents==='on',task_ids:[...form.querySelectorAll('[name=task_ids]:checked')].map(x=>x.value)};
      const x=ADV.editAnalysis;
      if(x){payload.expected_version=x.version;payload.event_key=key();}else{ADV.analysisKey??=key();payload.submission_key=ADV.analysisKey;}
      const r=await api(x?'/analyses/'+x.id+'/'+(x.state==='NEEDS_CLARIFICATION'?'clarify':'revise'):'/projects/'+S.pid+'/analyses',payload);ADV.analysisKey=null;target='#/analyses/'+r.id;toast('目标已保存，请核对读取计划');
    }else if(kind==='confirm-plan'){
      const x=S.detail;await api('/analyses/'+x.id+'/confirm',{expected_version:x.version,event_key:key(),confirmed:b.confirmed==='on',plan_version:x.data.plan_version,plan_hash:x.data.plan_hash});toast('计划已确认，开始只读分析');
    }else if(kind==='cancel-analysis'){const x=S.detail;await api('/analyses/'+x.id+'/cancel',{expected_version:x.version,event_key:key(),reason:b.reason});toast('分析已取消');}
    closeModal();S.dirty=false;if(target&&target!==location.hash)location.hash=target;else await refresh();
  }catch(error){failure(error,form);}finally{if(button.isConnected)button.disabled=false;}
});

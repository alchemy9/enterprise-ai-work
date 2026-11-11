'use strict';
const RP={next:null};
Object.assign(statusNames,{SUPERSEDED:'已被新版替代',ON_TRACK:'按计划推进',OVERDUE:'已逾期',NO_TASKS:'缺关联任务',MILESTONE_OVERDUE:'里程碑逾期'});
Object.assign(colors,{SUPERSEDED:'gray',ON_TRACK:'blue',OVERDUE:'orange',NO_TASKS:'orange'});
const snapshotName=s=>({CURRENT:'当前采集',IMPORTED:'用户提供期末数据',DEMO:'模拟期末数据'}[s.kind]||s.kind);

function planningPage(data,id){
  if(id)return snapshotDetail(data);
  return `${pagehead('快照与里程碑','管理明确的数据截点、历史比较与里程碑计划。','<button data-report-action="new-milestone">'+icon('plus')+'新建里程碑</button><button class="primary" data-report-action="new-snapshot">'+icon('plus')+'采集或导入快照</button>')}
  <section class="panel"><div class="panelhead"><h2>里程碑计划</h2><span class="sub">新运行冻结计划版本，旧报告不随修改变化</span></div><div class="tablewrap"><table><thead><tr><th>里程碑</th><th>计划日</th><th>关联任务</th><th>上游依赖</th><th></th></tr></thead><tbody>${data.milestones.map(m=>`<tr><td class="title">${esc(m.name)} ${m.critical?'<span class="tag red">关键</span>':''}<div class="sub">v${m.version}</div></td><td>${esc(m.due_date)}</td><td>${m.data.task_ids.map(esc).join('、')}</td><td>${m.data.depends_on.map(k=>esc(data.milestones.find(x=>x.id===k)?.name||k)).join('、')||'未设置'}</td><td><button class="text" data-report-action="edit-milestone" data-id="${m.id}">编辑</button> <button class="text" data-report-action="remove-milestone" data-id="${m.id}">删除</button></td></tr>`).join('')}</tbody></table></div>${data.milestones.length?'':empty('尚无里程碑计划','可以关联任务和上游里程碑。依据不足时，系统不会自行升级风险等级。')}</section>
  <section class="panel"><div class="panelhead"><h2>历史与当前快照</h2><span class="sub">保存后不可覆盖</span></div><div class="tablewrap"><table><thead><tr><th>日期 / 类型</th><th>数据截点</th><th>条目</th><th>来源说明</th><th></th></tr></thead><tbody>${data.snapshots.map(s=>`<tr><td class="title">${esc(s.period_end)}<div class="sub">${snapshotName(s)}</div></td><td>${fmt(s.captured_at)}</td><td>${s.row_count}</td><td>${esc(s.note)}</td><td><a href="#/planning/${s.id}">查看快照 →</a></td></tr>`).join('')}</tbody></table></div>${data.snapshots.length?'':empty('暂无历史期末快照','采集当前台账，或导入明确日期的历史 CSV；演示时也可创建标明模拟来源的上期数据。')}</section>`;
}
function snapshotDetail(s){
  return `<a class="back" href="#/planning">${icon('back')}快照与里程碑</a>${pagehead('快照 · '+s.period_end,snapshotName(s),'<a class="button primary" href="#/new" data-report-snapshot="'+s.id+'">使用此快照汇总</a>')}
  <div class="notice">${icon('info')}<span>${esc(s.data.declared_source)}。${esc(s.note)} 截点：${fmt(s.captured_at)}；${s.data.full_day?'此输入声明为当天期末状态。':'这是中途采集，不能当作历史全天期末。'}</span></div>
  <section class="panel"><div class="panelbody"><dl class="keyvalues"><dt>快照标识</dt><dd class="mono">${esc(s.id)}</dd><dt>内容校验</dt><dd class="mono">${esc(s.content_hash)}</dd><dt>任务数量</dt><dd>${s.rows.length}</dd><dt>完成率</dt><dd>${s.metrics.completion_rate??'不适用'}${s.metrics.completion_rate===null?'':'%'}</dd><dt>未完成逾期</dt><dd>${s.metrics.overdue_count}</dd></dl></div><div class="tablewrap"><table><thead><tr><th>任务</th><th>状态</th><th>截止日期</th><th>完成时间</th></tr></thead><tbody>${s.rows.slice(0,100).map(r=>`<tr><td>${esc(r.task_id)} · ${esc(r.title)}</td><td>${tag(r.status)}</td><td>${esc(r.due_date||'未提供')}</td><td>${esc(r.completed_at||'未提供')}</td></tr>`).join('')}</tbody></table></div>${s.rows.length>100?'<p class="panelbody sub">页面预览前 100 行，运行使用全部冻结记录。</p>':''}</section>`;
}
function milestoneEditor(m){
  RP.milestone=m;const data=S.detail;
  advDialog(m?'编辑里程碑':'新建里程碑',`${advField('name','里程碑名称',m?.name||'验收联调完成','text','maxlength="100" required')}${advField('due_date','计划完成日',m?.due_date||dayAdd(S.me.today,-1),'date','required')}<label class="check"><input name="critical" type="checkbox" ${m?.critical?'checked':''}>这是关键交付里程碑</label><div class="field"><label>关联任务（至少选择一项）</label><div class="adv-task-options">${data.tasks.map(t=>`<label class="check"><input name="task_ids" type="checkbox" value="${esc(t.task_id)}" ${m?.data.task_ids.includes(t.task_id)?'checked':''}>${esc(t.task_id)} · ${esc(t.title)}</label>`).join('')}</div></div><div class="field"><label>依赖的上游里程碑</label>${data.milestones.filter(x=>x.id!==m?.id).map(x=>`<label class="check"><input name="depends_on" type="checkbox" value="${x.id}" ${m?.data.depends_on.includes(x.id)?'checked':''}>${esc(x.name)}</label>`).join('')||'<p class="sub">暂未设置其他里程碑。</p>'}</div>`,'保存计划','rp-milestone');
}
function newReportRun(){
  const preset=RP.next||{};RP.next=null;const p=S.project;
  return `<a class="back" href="#/overview">${icon('back')}项目空间</a>${pagehead(preset.parent_run_id?'复制参数并重新生成':'新建进度汇总','冻结台账、计划与资料版本，生成后进入人工审核。')}
  <div class="twocol"><section class="panel"><div class="panelhead"><h2>汇总范围</h2><span class="tag blue">固定工作流</span></div><form class="panelbody" data-report-form="run">${preset.parent_run_id?`<input type="hidden" name="parent_run_id" value="${preset.parent_run_id}"><p class="versionnote">新运行会重新检查权限与输入，不复用旧审批。来源运行 ${esc(preset.parent_run_id)}</p>`:''}
  <div class="field"><label for="rp-template">报告模板</label><select id="rp-template" name="workflow_id">${S.me.templates.filter(t=>t.scene==='PROGRESS'&&(!t.allowed_projects?.length||t.allowed_projects.includes(S.pid))).map(t=>`<option value="${t.id}" ${t.id===(preset.workflow_id||G.selectedTemplate)?'selected':''}>${esc(t.name)} · v${t.version}</option>`).join('')}</select></div>
  <div class="formgrid">${advField('period_start','统计开始',preset.period_start||dayAdd(S.me.today,-6),'date',`max="${S.me.today}" required`)}${advField('period_end','统计结束',preset.period_end||S.me.today,'date',`max="${S.me.today}" required`)}</div>
  <div class="field"><label for="rp-snapshot">输入快照</label><select id="rp-snapshot" name="snapshot_id"><option value="">本次采集当前数据</option>${p.period_snapshots.map(s=>`<option value="${s.id}" data-date="${s.period_end}" ${preset.snapshot_id===s.id?'selected':''}>${esc(s.period_end)} · ${snapshotName(s)} · ${s.row_count} 条</option>`).join('')}</select><small class="sub">历史日期必须选择对应的明确期末快照。模拟期末数据会保留模拟标记。</small></div>
  <div class="field"><label for="rp-connection">当前数据源</label><select id="rp-connection" name="connection_id"><option value="">内置项目台账</option>${p.connections.map(c=>`<option value="${c.id}" ${!preset.snapshot_id&&(preset.connection_id||ADV.source)===c.id?'selected':''}>${esc(c.name)} · ${fmt(c.last_success_at)}</option>`).join('')}</select><small class="sub">选择历史快照后不再读取连接；连接来源以最近同步截点为准。</small></div>
  <label class="check"><input name="compare_previous" type="checkbox" ${preset.compare_previous?'checked':''}>与本周期开始前一天的期末快照比较</label><div class="field"><label for="rp-baseline">比较快照</label><select id="rp-baseline" name="previous_snapshot_id"><option value="">自动匹配日期；缺少时明确提示缺口</option>${p.period_snapshots.filter(s=>s.kind!=='CURRENT').map(s=>`<option value="${s.id}">${esc(s.period_end)} · ${snapshotName(s)}</option>`).join('')}</select></div>
  <div class="field"><label for="rp-reviewer">审核人</label><select id="rp-reviewer" name="reviewer_id">${reviewers(S.me.user.id)}</select></div><label class="check"><input name="include_documents" type="checkbox" checked>纳入授权文档与纪要</label><div class="field"><label for="rp-library">知识范围</label><select id="rp-library" name="library_id"><option value="">全部授权项目资料</option>${p.libraries.map(l=>`<option value="${l.id}">${esc(l.name)}</option>`).join('')}</select></div>${advField('focus','重点关注（选填）',preset.focus||'','text','maxlength="1000"')}<label class="check"><input name="acknowledge_gaps" type="checkbox" required>已核对数据范围、截点和缺口，同意生成待审报告</label><details><summary class="sub">演示恢复与人工接管</summary><label class="check"><input name="demo_interrupt" type="checkbox">演示一次分析中断，保留输入后选择恢复或人工接管</label><p class="sub">这是明确标记的演示情景，不代表真实外部服务故障。</p></details><div class="inline-error"></div><button class="primary" type="submit">发起进度汇总</button></form></section>
  <aside><section class="panel"><div class="panelhead"><h2>当前输入参考</h2></div><div class="panelbody"><p>${esc(p.project.name)}</p><dl class="keyvalues"><dt>当前台账</dt><dd>${p.ledger.length} 项 · ${fmt(p.updated_at)}</dd><dt>可用资料</dt><dd>${p.document_count} 份</dd><dt>里程碑计划</dt><dd>${p.milestones.length} 项，启动后冻结版本</dd><dt>明确日期快照</dt><dd>${p.period_snapshots.length} 份</dd><dt>分析方式</dt><dd>本地规则与资料摘录</dd></dl><a href="#/planning">管理快照与里程碑 →</a></div></section><div class="notice warning">${icon('info')}<span>右侧是当前台账参考，历史报告使用所选快照。缺少比较快照时不倒推旧数据；历史文档按声明的生效日期选择版本。</span></div></aside></div>`;
}

function reportArticle(d,version,reason){
  const m=d.metrics,rows=d.evidence.filter(x=>x.row).map(x=>x.row);
  const completed=d.completed_tasks||rows.filter(x=>x.status==='DONE'&&x.completed_at&&x.completed_at.slice(0,10)>=d.period_start&&x.completed_at.slice(0,10)<=d.period_end);
  const pending=d.in_progress_tasks||rows.filter(x=>!['DONE','CANCELLED'].includes(x.status));
  return `<div class="sub">正文 v${version} · ${esc(reason)}</div><div class="versionnote">${d.human_supplement?'人工修订，需按当前正文重新审核。':'本地规则原稿，原因分析仍需人工核实。'} 数字与引用保留冻结版本。</div>
  <h3>一、报告概况与数据截点</h3><p>${esc(d.period_start)} — ${esc(d.period_end)} · 截点 ${fmt(d.cutoff_time)}</p>${d.data_source?`<p class="sub">${esc(d.data_source.name)} · ${esc(d.data_source.mode)}${d.data_source.note?' · '+esc(d.data_source.note):''}</p>`:''}
  <h3>二、关键统计与口径</h3><div class="metrics reportmetrics"><div class="metric"><div class="label">任务完成率</div><strong>${m.completion_rate??'不适用'}${m.completion_rate===null?'':'<span class="unit">%</span>'}</strong></div><div class="metric"><div class="label">完成 / 非取消任务</div><strong>${m.completed}<span class="unit"> / ${m.total}</span></strong></div><div class="metric alert"><div class="label">未完成逾期</div><strong>${m.overdue_count}<span class="unit"> 项</span></strong></div><div class="metric"><div class="label">本期完成</div><strong>${m.period_completed}<span class="unit"> 项</span></strong></div></div><p class="sub">完成时逾期 ${m.completed_late} 项，与当前未完成逾期分别统计。</p>
  ${m.comparison?`<div class="notice">${icon('info')}<span>对比 ${esc(m.comparison.period_end)} 期末${m.comparison.kind==='DEMO'?'模拟数据':''}：完成率变化 ${m.comparison.completion_rate_change??'不适用'} 个百分点；未完成逾期变化 ${m.comparison.overdue_change} 项。<a href="#/planning/${m.comparison.snapshot_id}">查看比较来源 →</a></span></div>`:''}
  <details><summary class="sub">查看计算口径</summary><p>完成率 = 截点前已完成任务 / 非取消任务。截止日早于截点本地日期且未完成为逾期；当天到期不算逾期。完成时间缺失不计入本期完成数。空任务集合显示不适用。业务数字不由模型生成。</p></details>
  ${d.human_adjustments?.length?`<div class="notice warning"><div><strong>人工指标调整 · 需随正文审核</strong>${d.human_adjustments.map(a=>`<p>${esc(({total:"有效任务数",completed:"完成任务数",completion_rate:"完成率",period_completed:"本期完成数",overdue_count:"未完成逾期数",completed_late:"完成时逾期数"})[a.metric]||a.metric)}：规则 ${a.source_value??"不适用"} → 人工 ${a.value}；原因：${esc(a.reason)}<br><span class="sub">${esc(person(a.actor_id))} · ${fmt(a.at)}；冻结台账与规则数字未改写</span></p>`).join("")}</div></div>`:""}<h3>三、本期完成与主要进展</h3>${completed.length?`<ul class="gaps">${completed.map(t=>`<li>${esc(t.task_id)} · ${esc(t.title)} · ${esc(t.completed_at?.slice(0,10))}</li>`).join('')}</ul>`:'<p class="sub">该周期未保存符合完成时间口径的任务明细。</p>'}
  <h3>四、进行中、逾期与里程碑</h3><p>当前未完成 ${pending.length} 项。${pending.slice(0,20).map(t=>esc(t.task_id)+' '+esc(t.title)).join('；')}</p>${m.milestones?.length?`<div class="tablewrap"><table><thead><tr><th>里程碑</th><th>计划日</th><th>任务完成</th><th>规则状态</th></tr></thead><tbody>${m.milestones.map(x=>`<tr><td>${esc(x.name)}${x.critical?' · 关键':''}</td><td>${esc(x.due_date)}</td><td>${x.completed} / ${x.total}</td><td>${tag(x.status,x.status==='DONE'?'已完成':null)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="sub">缺少里程碑计划，未生成关键路径判断。</p>'}
  <h3>五、风险与问题</h3>${d.risks.length?d.risks.map(r=>`<section class="riskblock"><div class="actions"><h3 style="margin:0;flex:1">${esc(r.title)}</h3><span class="tag ${r.level==='HIGH'?'red':r.level==='MEDIUM'?'orange':''}">${{HIGH:'高',MEDIUM:'中',LOW:'低'}[r.level]||'待确认'} · 规则初值</span></div><p><strong>事实：</strong>${esc(r.fact)}</p><p><strong>规则依据：</strong>${esc(r.rule_trigger||'台账逾期；缺少关键路径时不升级')}</p><p><strong>可能原因：</strong>${esc(r.hypothesis)}</p><p><strong>影响：</strong>${esc(r.impact||'影响范围需人工补充')}</p><div class="actions">${r.evidence_ids.map(id=>`<button class="text" data-action="evidence" data-id="${esc(id)}">${esc(id)} ↗</button>`).join('')}</div></section>`).join(''):d.mode==='HUMAN_TAKEOVER'?'<p>自动分析未完整完成，尚未形成结构化风险清单；请在人工正文补充事实与建议，不能据此判断无风险。</p>':'<p>规则未识别未完成逾期项，仍需核对其他风险与资料缺口。</p>'}
  <h3>六、建议整改清单</h3>${d.risks.length?`<ol class="gaps">${d.risks.map(r=>`<li>${esc(r.recommendation)}<br><span class="sub">${(r.pending_fields||['负责人','截止日期','验收标准']).map(esc).join('；')}，需另行确认。</span></li>`).join('')}</ol>`:'<p class="sub">当前无根据规则生成的整改建议。</p>'}
  <h3>七、下周期关注与人工补充</h3><div class="narrative">${esc(d.narrative)}</div>${d.focus?`<p><strong>发起人关注：</strong>${esc(d.focus)}</p>`:''}
  <h3>八、数据缺口与引用清单</h3><ul class="gaps">${d.missing.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><p class="sub">本次绑定 ${d.evidence.length} 条证据；可在右侧核对版本与原文。快照 ${esc(d.snapshot_id)}</p>`;
}

pageModules.planning={title:'快照与里程碑',visible:manager,load:id=>api('/projects/'+S.pid+(id?'/snapshots/'+id:'/planning')),render:planningPage};
pageModules.new={title:'新建进度汇总',visible:manager,load:async()=>null,render:newReportRun};
const noticeKindName=k=>({report:'报告与审核',fix:'整改处理与验收',document:'资料解析',run:'汇总运行',analysis:'风险分析',connection:'数据同步',schedule:'定时计划',flow:'编排成果'}[k]||k);
function remindersPage(d){
  return `${pagehead('提醒与订阅','设置站内提醒，并查看需要转交的审核事项。',d.can_manage?'<button data-report-action="check-reminders">立即检查提醒与转交</button>':'')}
  <div class="twocol"><section class="panel"><div class="panelhead"><h2>我的站内订阅</h2></div><form class="panelbody" data-report-form="subscriptions">${d.kinds.map(k=>`<label class="check"><input name="kinds" type="checkbox" value="${k}" ${d.preferences.kinds.includes(k)?'checked':''}>${noticeKindName(k)}</label>`).join('')}<p class="sub">只影响后续站内通知。审核、处理和验收待办仍会保留，不会因取消订阅而自动完成。</p><div class="inline-error"></div><button class="primary" type="submit">保存订阅</button></form></section>
  ${d.can_manage?`<section class="panel"><div class="panelhead"><h2>当前项目催办规则</h2></div><form class="panelbody" data-report-form="reminder-settings">${advField('review_hours','报告等待审核多久后提醒（小时）',d.settings.review_hours,'number','min="1" max="168" required')}${advField('acceptance_hours','整改等待验收多久后提醒（小时）',d.settings.acceptance_hours,'number','min="1" max="168" required')}<p class="sub">逾期整改每天最多提醒一次；报告等待七天会额外提示项目经理。提醒不自动批准、发布、验收或关闭任务。</p><div class="inline-error"></div><button class="primary" type="submit">保存催办规则</button></form></section>`:''}</div>
  ${d.can_manage?`<section class="panel"><div class="panelhead"><h2>审核待转交队列</h2><span class="sub">${d.handoffs.length} 项</span></div>${d.handoffs.map(h=>`<div class="listrow"><div class="grow"><strong>待转交审核</strong><p>${esc(h.reason)} · ${fmt(h.detected_at)}</p></div><a href="#/reports/${h.report_id}">核对并转交 →</a></div>`).join('')||empty('暂无待转交事项','审核人停用、退出或失去来源权限时会进入这里。')}</section>
  <section class="panel"><div class="panelhead"><h2>通知处理记录</h2><span class="sub">通知重投不重复执行业务动作</span></div><div class="tablewrap"><table><thead><tr><th>时间 / 事件</th><th>状态</th><th>处理次数</th><th>说明</th><th></th></tr></thead><tbody>${d.outbox.map(x=>`<tr><td>${fmt(x.created_at)}<div class="sub mono">${esc(x.action)}</div></td><td>${{QUEUED:'待处理',DELIVERED:'已处理',FAILED:'等待人工重投'}[x.state]||x.state}</td><td>${x.attempts}</td><td>${esc(x.error||'按当前对象状态与订阅范围处理')}</td><td>${x.state==='FAILED'?`<button class="text" data-report-action="retry-notice" data-id="${x.event_id}">重投通知</button>`:''}</td></tr>`).join('')}</tbody></table></div>${d.outbox.length?'':'<p class="panelbody sub">后续业务事件会在这里记录处理状态。</p>'}</section>`:''}`;
}
pageModules.reminders={title:'提醒与订阅',load:()=>api('/projects/'+S.pid+'/reminders'),render:remindersPage,isActive:d=>d.outbox?.some(x=>x.state==='QUEUED')};

document.addEventListener('change',event=>{
  if(event.target.id==='rp-snapshot'){
    const option=event.target.selectedOptions[0];if(option.dataset.date){$('#adv-period_end').value=option.dataset.date;$('#adv-period_start').value=dayAdd(option.dataset.date,-6);$('#rp-connection').value='';}
  }
  if(event.target.name==='snapshot_kind'){
    const form=event.target.form;form.querySelector('[name=period_end]').value=event.target.value==='CURRENT'?S.me.today:dayAdd(S.me.today,-7);form.querySelector('[name=csv]').required=event.target.value==='IMPORTED';
  }
});
document.addEventListener('click',async event=>{
  const snapshot=event.target.closest('[data-report-snapshot]');if(snapshot){RP.next={snapshot_id:S.detail.id,period_end:S.detail.period_end,period_start:dayAdd(S.detail.period_end,-6)};return;}
  const button=event.target.closest('[data-report-action]');if(!button)return;
  try{
    button.disabled=true;const action=button.dataset.reportAction;
    if(action==='check-reminders'){await api('/projects/'+S.pid+'/reminders/check',{});toast('当前提醒条件已检查，通知异步处理');await refresh();}
    else if(action==='retry-notice'){await api('/projects/'+S.pid+'/reminders/retry/'+button.dataset.id,{});toast('通知已重新排队');await refresh();}
    else if(action==='takeover')advDialog('人工接管分析草稿',`<p>原始输入、失败节点与统计来源保留。人工补充内容仍需重新提交审核；此操作不会发布报告或创建整改。</p>${advArea('reason','接管原因','',3)}${advArea('narrative','人工接管正文','根据冻结台账核对当前进度。自动分析尚未完成，风险原因及建议由人工补充并审核。',5)}`,'保存人工接管稿','rp-takeover');
    else if(action==='new-milestone')milestoneEditor(null);
    else if(action==='edit-milestone')milestoneEditor(S.detail.milestones.find(m=>m.id===button.dataset.id));
    else if(action==='remove-milestone'){RP.milestone=S.detail.milestones.find(m=>m.id===button.dataset.id);advDialog('删除里程碑',`<p>${esc(RP.milestone.name)}</p><p class="sub">旧报告中的计划版本保留。有下游依赖时需先解除依赖。</p>`,'确认删除','rp-remove-milestone');}
    else if(action==='new-snapshot')advDialog('采集或导入快照',`<div class="field"><label for="rp-kind">快照类型</label><select id="rp-kind" name="snapshot_kind"><option value="CURRENT">采集当前台账</option><option value="IMPORTED">导入声明日期的历史 CSV</option><option value="DEMO">创建模拟期末数据（明确标记）</option></select></div>${advField('period_end','对应日期',S.me.today,'date',`max="${S.me.today}" required`)}${advArea('note','来源与截点说明','用于本地演示的数据快照，来源与日期按所选类型标注。',3)}<div class="field"><label for="rp-csv">历史 CSV（仅导入时填写）</label><textarea id="rp-csv" name="csv" rows="6" placeholder="task_id,title,owner_id,status,planned_start,due_date,completed_at,milestone_id,updated_at"></textarea></div><p class="sub">模拟快照用于讲解上期比较，不是原公司历史数据。导入内容不能包含晚于截点的完成或更新时间。</p>`,'保存不可变快照','rp-snapshot');
    else if(action==='derive-report'){advDialog('从正式版派生修订',`<p>来源报告 v${S.detail.current_version}。保留原正式版和已创建整改，新草稿重新审核发布后才替代来源。</p>${advArea('reason','修订原因','',3)}`,'创建修订草稿','rp-derive');}
    else if(action==='regenerate'){
      const r=S.detail,d=r.current.data;RP.next={parent_run_id:r.run_id,workflow_id:r.run.data.configuration?.workflow?.id,focus:d.focus||''};
      if(d.period_end===S.me.today){RP.next.period_start=d.period_start;RP.next.period_end=d.period_end;}
      if(d.data_source?.kind){RP.next.snapshot_id=d.data_source.snapshot_id;RP.next.period_start=d.period_start;RP.next.period_end=d.period_end;}
      location.hash='#/new';
    }else if(action==='compare-report'){
      const r=S.detail;let previous=r.versions.at(-2);const relation=r.relations.find(x=>x.child_report_id===r.id);
      if(!previous&&relation){const parent=await api('/reports/'+relation.parent_report_id);previous=parent.versions.find(v=>v.version===relation.parent_version);}
      modal('正文版本对比',`<div class="cfg-compare"><section><h3>来源 / 上一版本 ${previous?'v'+previous.version:''}</h3><div class="pre">${esc(previous?.data.narrative||'无上一版本')}</div></section><section><h3>当前 v${r.current_version}</h3><div class="pre">${esc(r.current.data.narrative)}</div></section></div><p class="sub">数字与引用请分别核对各版本的数据截点。正文变化后需重新审核。</p>`,'<button data-action="close">关闭</button>');
    }
  }catch(error){failure(error,$('#dialog').open?$('#dialog'):document);}finally{if(button.isConnected)button.disabled=false;}
});
document.addEventListener('submit',async event=>{
  const form=event.target;let kind=form.dataset.reportForm;
  if(!kind&&form.dataset.advForm?.startsWith('rp-')){kind=form.dataset.advForm;delete form.dataset.advForm;}
  if(!kind)return;event.preventDefault();const b=Object.fromEntries(new FormData(form));const button=form.querySelector('button[type=submit]');button.disabled=true;const operationKey=form.dataset.operationKey||(form.dataset.operationKey=key());
  try{
    let target=null;
    if(kind==='subscriptions'){
      await api('/projects/'+S.pid+'/reminders',{expected_version:S.detail.preferences.version,kinds:[...form.querySelectorAll('[name=kinds]:checked')].map(x=>x.value)});toast('站内订阅已保存');
    }else if(kind==='reminder-settings'){
      await api('/projects/'+S.pid+'/reminders/settings',{expected_version:S.detail.settings.version,review_hours:Number(b.review_hours),acceptance_hours:Number(b.acceptance_hours)});toast('催办规则已保存');
    }else if(kind==='rp-takeover'){const r=await api('/runs/'+S.detail.id+'/takeover',{expected_version:S.detail.version,event_key:operationKey,reason:b.reason,narrative:b.narrative});target='#/reports/'+r.id;toast('人工接管稿已保存，请继续修订并提交审核');
    }else if(kind==='run'){
      const payload={project_id:S.pid,submission_key:form.dataset.submissionKey||(form.dataset.submissionKey=key()),workflow_id:b.workflow_id,period_start:b.period_start,period_end:b.period_end,reviewer_id:b.reviewer_id,acknowledge_gaps:b.acknowledge_gaps==='on',include_documents:b.include_documents==='on',compare_previous:b.compare_previous==='on',focus:b.focus||'',demo_interrupt:b.demo_interrupt==='on'};
      if(b.snapshot_id)payload.snapshot_id=b.snapshot_id;else if(b.connection_id)payload.connection_id=b.connection_id;
      if(b.previous_snapshot_id&&payload.compare_previous)payload.previous_snapshot_id=b.previous_snapshot_id;
      if(b.library_id&&payload.include_documents)payload.library_ids=[b.library_id];if(b.parent_run_id)payload.parent_run_id=b.parent_run_id;
      const r=await api('/runs',payload);target='#/runs/'+r.id;toast('汇总已受理，输入版本已冻结');
    }else if(kind==='rp-milestone'){
      const payload={name:b.name,due_date:b.due_date,critical:b.critical==='on',task_ids:[...form.querySelectorAll('[name=task_ids]:checked')].map(x=>x.value),depends_on:[...form.querySelectorAll('[name=depends_on]:checked')].map(x=>x.value)};if(RP.milestone)payload.expected_version=RP.milestone.version;
      await api('/projects/'+S.pid+'/milestones'+(RP.milestone?'/'+RP.milestone.id:''),payload);toast('里程碑计划已保存');
    }else if(kind==='rp-remove-milestone'){await api('/projects/'+S.pid+'/milestones/'+RP.milestone.id+'/remove',{expected_version:RP.milestone.version});toast('里程碑已删除，历史版本保留');}
    else if(kind==='rp-snapshot'){const r=await api('/projects/'+S.pid+'/snapshots',{kind:b.snapshot_kind,period_end:b.period_end,note:b.note,csv:b.csv,event_key:operationKey});target='#/planning/'+r.id;toast('快照已保存');}
    else if(kind==='rp-derive'){const r=await api('/reports/'+S.detail.id+'/derive',{expected_version:S.detail.current_version,reason:b.reason,event_key:operationKey});target='#/reports/'+r.id;toast('修订草稿已创建，请编辑后重新提交审核');}
    if($('#dialog').open)closeModal();S.dirty=false;if(target&&target!==location.hash)location.hash=target;else await refresh();
  }catch(error){if(kind.startsWith('rp-'))form.dataset.reportForm=kind;failure(error,form);}finally{if(button.isConnected)button.disabled=false;}
});

document.addEventListener('input',event=>{if(event.target.closest('[data-report-form]'))S.dirty=true;});

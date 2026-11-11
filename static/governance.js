'use strict';
const G={kind:'WORKFLOW',version:null,filters:{}};
const kindNames={WORKFLOW:'Workflow 模板',AGENT:'Agent',MODEL:'模型配置',TOOL:'工具'};
const cfgState=s=>({DRAFT:'草稿',TESTING:'预览中',PUBLISHED:'已发布',DISABLED:'已停用'}[s]||s);
const field=(name,label,value,type='text',extra='')=>`<div class="field"><label for="cfg-${name}">${label}</label><input id="cfg-${name}" name="${name}" type="${type}" value="${esc(value??'')}" ${extra}></div>`;
const area=(name,label,value)=>`<div class="field full"><label for="cfg-${name}">${label}</label><textarea id="cfg-${name}" name="${name}" rows="4" required>${esc(value)}</textarea></div>`;

function configList(data){
  const tools=G.kind==='TOOL';
  return `${pagehead(tools?'工具连接':'模板与 Agent',tools?'管理内置读取、计算与业务写能力。停用立即阻断后续调用。':'保存草稿、预览、发布与回滚；已启动运行继续绑定原配置。')}
  ${tools?'':`<div class="pilltabs">${['WORKFLOW','AGENT','MODEL'].map(k=>`<button data-gov-action="kind" data-kind="${k}" class="${G.kind===k?'active':''}">${kindNames[k]}</button>`).join('')}</div>`}
  <section class="panel"><div class="tablewrap"><table><thead><tr><th>名称与用途</th><th>默认发布版</th><th>配置状态</th><th>更新时间</th><th></th></tr></thead><tbody>${data.items.map(d=>`<tr><td class="title">${esc(d.name)}<p class="sub">${esc(d.description)}</p></td><td>${d.active_version?'v'+d.active_version:'尚未发布'}${d.draft_version?`<div class="sub">草稿 v${d.draft_version}</div>`:''}</td><td>${tag(d.enabled?'ACTIVE':'CANCELLED',d.enabled?'启用中':'已停用')}</td><td>${fmt(d.updated_at)}</td><td><a href="#/${tools?'tools':'configs'}/${d.id}">管理配置 →</a></td></tr>`).join('')}</tbody></table></div></section>
  <div class="notice">${icon('info')}<span>${tools?'内置工具在当前本地服务中运行；真实企业连接可在演示扩展中模拟。不配置真实凭据或外部写入。':'当前为规则与资料摘录演示。配置预览只展示拟执行结果，不创建业务对象；预览结果仅说明本地配置与规则可运行。'}</span></div>`;
}

function configFields(d,v,refs){
  const c=v.data,locked=v.state!=='DRAFT';
  let html='';
  if(d.kind==='WORKFLOW'){
    html=`<div class="formgrid">${field('scene','业务场景',c.scene,'text','readonly')}${field('agent_version','绑定 Agent 版本',c.agent_version,'number','min="1" required')}<div class="field full"><label for="cfg-agent_id">分析 Agent</label><select id="cfg-agent_id" name="agent_id">${refs.agents.items.map(a=>`<option value="${a.id}" ${a.id===c.agent_id?'selected':''}>${esc(a.name)} · 默认 v${a.active_version||'—'}</option>`).join('')}</select></div>${area('narrative_prefix','报告开场文字',c.narrative_prefix)}${field('followup_days','逾期重点关注阈值（天）',c.rules.followup_days,'number','min="1" max="365" required')}<div class="field"><label>人工审核</label><input value="${c.review_required?'必须审核后发布':'问答无业务写入'}" readonly></div></div><div class="field"><label for="cfg-mappings">变量映射（合法来源 → 分析输入）</label><textarea class="mono" id="cfg-mappings" name="mappings" rows="5">${esc(JSON.stringify(c.mappings,null,2))}</textarea><small class="sub">任务与证据映射保持节点契约。下方变量目录可配置八种类型，运行时再次校验。</small></div><div class="field"><label for="cfg-variables">类型变量目录</label><textarea class="mono" id="cfg-variables" name="variables" rows="12">${esc(JSON.stringify(c.variables||[],null,2))}</textarea><small class="sub">支持 string、number、boolean、date、enum、object、array、reference。合法来源：focus、metrics.completion_rate、context.has_evidence、period_end、context.mode、context.metrics_summary、evidence、context.snapshot_ref；问答为 question、context.has_evidence、context.mode、evidence。重命名只影响 allowed_nodes 所列分析节点；系统身份与权限不能覆盖。</small></div><div class="field"><label>适用项目（空选表示不额外限制，仍需项目授权）</label>${S.me.projects.map(p=>`<label class="check"><input name="allowed_projects" type="checkbox" value="${p.id}" ${c.allowed_projects.includes(p.id)?'checked':''}>${esc(p.name)}</label>`).join('')}</div>`;
  }else if(d.kind==='AGENT'){
    html=`<div class="notice">${icon('info')}<span>平台规则固定：当前项目授权、数字由规则计算、引用可追溯、业务写入需人工确认。职责提示不能覆盖这些规则。</span></div>${area('responsibility','职责与边界',c.responsibility)}${area('prompt','职责提示',c.prompt)}${area('recommendation','演示风险建议文字',c.recommendation)}<div class="formgrid"><div class="field"><label for="cfg-model_id">模型配置</label><select id="cfg-model_id" name="model_id">${refs.models.items.map(m=>`<option value="${m.id}" ${m.id===c.model_id?'selected':''}>${esc(m.name)}</option>`).join('')}</select></div>${field('model_version','绑定模型配置版本',c.model_version,'number','min="1" required')}${field('tool_calls','工具次数上限',c.budget.tool_calls,'number','min="3" max="30" required')}${field('iterations','分析轮数上限',c.budget.iterations,'number','min="1" max="3" required')}${field('active_seconds','活跃时间上限（秒）',c.budget.active_seconds,'number','min="10" max="300" required')}${field('context_chars','上下文字符上限',c.budget.context_chars,'number','min="1000" max="40000" required')}</div><div class="field"><label>只读工具白名单</label>${refs.tools.items.filter(t=>!['tool_publish','tool_rectify'].includes(t.id)).map(t=>`<label class="check"><input name="tools" type="checkbox" value="${t.id}" ${c.tools.includes(t.id)?'checked':''}>${esc(t.name)}</label>`).join('')}</div>`;
  }else if(d.kind==='TOOL'){
    html=`<div class="formgrid">${field('handler','平台能力',c.handler,'text','readonly')}${field('type','读写分类',c.type,'text','readonly')}${field('timeout_seconds','超时（秒）',c.timeout_seconds,'number','min="1" max="120" required')}${field('max_retries','最多重试',c.max_retries,'number',`min="0" max="${c.type==='WRITE'?0:2}" required`)}<div class="field full"><label>确认与凭据</label><input value="${c.requires_confirmation?'必须绑定人工确认或批准版本':'每次检查当前执行身份与资料授权'}；平台内置，无外部凭据" readonly></div></div>`;
  }else{
    html=`<div class="notice">${icon('info')}<span>本配置使用本地演示规则，模型调用与 tokens 均为 0。无需模型密钥即可完成演示。</span></div><div class="formgrid">${field('model','模型标识',c.model,'text','readonly')}${field('mode','运行模式',c.mode,'text','readonly')}${field('context_limit','上下文上限',c.context_limit,'number','min="1000" max="40000" required')}${field('max_output_tokens','输出上限',c.max_output_tokens,'number','min="128" max="8000" required')}${field('timeout_seconds','单次超时（秒）',c.timeout_seconds,'number','min="1" max="120" required')}</div>`;
  }
  return `<fieldset class="cfg-fields" ${locked?'disabled':''}>${html}</fieldset>`;
}

function configDetail(data){
  const d=data.definition, v=d.versions.find(x=>x.version===G.version)||d.versions[0];G.version=v.version;
  const editable=v.state==='DRAFT';
  const debug=d.debugs.find(x=>x.definition_version===v.version&&x.revision===v.revision&&x.content_hash===v.content_hash);
  return `<a class="back" href="#/${d.kind==='TOOL'?'tools':'configs'}">${icon('back')}${kindNames[d.kind]}列表</a>${pagehead(d.name,d.description,`<button data-gov-action="derive">派生草稿</button>${d.kind!=='TOOL'?'<button data-gov-action="copy">复制配置</button>':''}<button class="${d.enabled?'':'primary'}" data-gov-action="status">${d.enabled?'停用':'启用'}</button>`)}
  <div class="cfg-versionbar"><label for="config-version">查看版本</label><select id="config-version">${d.versions.map(x=>`<option value="${x.version}" ${x.version===v.version?'selected':''}>v${x.version} · ${cfgState(x.state)}${x.version===d.active_version?' · 当前默认':''}</option>`).join('')}</select><span class="sub">草稿修订 ${v.revision} · ${esc(v.content_hash.slice(0,12))}</span>${v.state==='PUBLISHED'&&d.active_version!==v.version?'<button data-gov-action="rollback">设为默认版本</button>':''}</div>
  <div class="twocol"><section class="panel"><div class="panelhead"><h2>${kindNames[d.kind]}配置</h2>${tag(v.state,cfgState(v.state))}</div><form class="panelbody" data-gov-form="config">${configFields(d,v,data.refs)}<div class="inline-error"></div><div class="actions">${editable?'<button class="primary" type="submit">保存草稿</button><button type="button" data-gov-action="validate">校验配置</button><button type="button" data-gov-action="debug">沙箱预览</button><button type="button" data-gov-action="publish">发布版本</button>':'<span class="sub">已发布配置只读。修改请派生新草稿。</span>'}</div></form></section><div><section class="panel"><div class="panelhead"><h2>${d.kind==='WORKFLOW'?'固定流程':'依赖与约束'}</h2></div><div class="panelbody">${d.kind==='WORKFLOW'?`<ol class="cfg-nodes">${v.data.nodes.map(n=>`<li>${esc({ValidateInput:'校验参数与权限',ReadSnapshot:'读取冻结快照',RuleCompute:'规则统计',RetrieveEvidence:'检索授权证据',AnalyzeAgent:'分析风险与建议',ValidateOutput:'校验输出与引用',SaveDraft:'保存草稿',HumanReview:'等待人工审核',PublishReport:'发布已审核报告',GenerateAnswer:'生成引用回答',SaveAnswer:'保存问答成果'}[n]||n)}</li>`).join('')}</ol><p class="sub">无证据：保留规则数字并显示缺口；故障：停止并保留输入；默认：继续下一节点。</p>`:`<p>被 ${d.dependencies.length} 个已发布版本引用</p>${d.dependencies.map(x=>`<p class="sub">${esc(x.name)} · v${x.version}</p>`).join('')}<p class="sub">旧运行保留配置快照。工具撤销与资料权限变化即时生效。</p>`}<details><summary>查看完整配置</summary><pre class="pre">${esc(JSON.stringify(v.data,null,2))}</pre></details></div></section>
  ${debug?`<section class="panel"><div class="panelhead"><h2>该版本预览结果</h2>${tag('SUCCEEDED','已完成')}</div><div class="panelbody"><p>${esc(debug.data.project_name)} · ${debug.data.input.ledger_rows} 行台账 · ${debug.data.input.document_versions} 份资料</p><p>${esc(debug.data.output.summary)}</p><p>规则逾期：${debug.data.output.overdue_count} 项；拟建议：${debug.data.output.proposal_count} 项</p><p class="sub">${esc(debug.data.output.write_actions)}</p><details><summary>查看依据与校验</summary><pre class="pre">${esc(JSON.stringify(debug.data,null,2))}</pre></details></div></section>`:''}</div></div>
  <section class="panel"><div class="panelhead"><h2>版本比较与发布记录</h2></div><div class="panelbody"><details><summary>当前版本与上一版本的配置对比</summary><div class="cfg-compare"><pre class="pre">${esc(JSON.stringify(d.versions.find(x=>x.version<v.version)?.data||{},null,2))}</pre><pre class="pre">${esc(JSON.stringify(v.data,null,2))}</pre></div></details></div>${d.releases.map(r=>`<div class="listrow"><div class="grow"><strong>v${r.version} · ${esc({PUBLISH:'发布',ROLLBACK:'默认版本切换',STATUS:'启停调整',BOOTSTRAP:'内置版本'}[r.action]||r.action)}</strong><p>${esc(r.note)}</p></div><span class="sub">${fmt(r.created_at)}</span></div>`).join('')}</section>`;
}

function templateCatalog(data){
  return `${pagehead('应用模板','选择标准业务流程，使用模拟台账与项目资料演示协同。',hasRole('operations')?'<a class="button" href="#/configs">管理模板与 Agent</a>':'')}
  <div class="cfg-cards">${data.items.map(t=>`<section class="panel"><div class="panelhead"><h2>${esc(t.name)}</h2><span class="tag blue">v${t.version}</span></div><div class="panelbody"><p>${esc(t.description)}</p><p class="sub">${t.nodes.length} 个固定步骤 · ${t.scene==='PROGRESS'?'需要人工审核；整改另行确认':'授权检索与引用；不执行业务写入'}</p><div class="actions">${t.scene==='PROGRESS'&&manager()?`<a class="button primary" href="#/new" data-gov-template="${t.id}">使用模板 →</a>`:t.scene==='QUESTION'?'<a class="button primary" href="#/questions">开始问答 →</a>':'<span class="sub">项目经理可发起汇总</span>'}</div></div></section>`).join('')}</div>`;
}

function operationsPage(data){
  return `${pagehead('运行评估','按真实本地运行记录展示状态、预算与工具调用。',hasRole('enterprise_admin')?'<button data-gov-action="limits">调整演示配额</button>':'')}
  <form class="filters" data-gov-form="filters"><select name="channel" aria-label="运行类型"><option value="">全部运行类型</option>${[["PROGRESS","进度汇总"],["QUESTION","我的引用问答"],["ANALYSIS","开放风险分析"],["FLOW","流程编排"]].map(([k,n])=>`<option value="${k}" ${G.filters.channel===k?"selected":""}>${n}</option>`).join("")}</select><select name="project_id" aria-label="运行项目"><option value="">全部授权项目</option>${S.me.projects.map(p=>`<option value="${p.id}" ${G.filters.project_id===p.id?'selected':''}>${esc(p.name)}</option>`).join('')}</select><select name="template_id" aria-label="运行模板"><option value="">全部模板</option>${data.templates.map(t=>`<option value="${t.id}" ${G.filters.template_id===t.id?'selected':''}>${esc(t.name)}</option>`).join('')}</select><input type="date" name="date_from" value="${esc(G.filters.date_from||'')}" aria-label="开始日期"><input type="date" name="date_to" value="${esc(G.filters.date_to||'')}" aria-label="结束日期"><button type="submit">筛选</button></form>
  <div class="cfg-stats">${[['运行总数',data.total],['运行完成',data.counts.COMPLETED],['等待审核',data.counts.WAITING_REVIEW],['系统失败',data.counts.FAILED],['人工退回',data.counts.REVIEW_REJECTED],['用户取消',data.counts.CANCELLED]].map(([label,value])=>`<div class="panel"><span class="sub">${label}</span><strong>${value}</strong></div>`).join('')}</div>
  <section class="panel"><div class="panelhead"><h2>用量与资源</h2></div><div class="panelbody cfg-usage"><div><strong>${data.model_calls}</strong><span>实际模型调用</span></div><div><strong>${data.tokens}</strong><span>实际 tokens</span></div><div><strong>${data.tool_errors}</strong><span>工具失败</span></div><div><strong>${data.budget_hits}</strong><span>预算命中</span></div><div><strong>未配置</strong><span>账单单价 · 无外部调用</span></div></div><div class="panelbody sub">${esc(data.worker_mode)} · 最多 ${data.limits.max_active_runs} 个排队/执行实例；模型日配额 ${data.limits.daily_model_calls}。${esc(data.measurement_note)}</div></section>
  <section class="panel"><div class="panelhead"><h2>运行明细</h2></div><div class="tablewrap"><table><thead><tr><th>项目 / 模板版本</th><th>状态</th><th>生成耗时</th><th>人工等待 / 总经过</th><th>工具 / 节点尝试</th><th></th></tr></thead><tbody>${data.items.map(r=>`<tr><td class="title">${esc(r.project_name)}<div class="sub">${esc(r.template)} · v${r.template_version}</div></td><td>${tag(r.state,r.state==='COMPLETED'?(r.kind==='PROGRESS'?'已发布':r.kind==='FLOW'?'已确认完成':'已完成'):null)}</td><td>${r.generation_seconds===null?"历史未采集":r.generation_seconds+" 秒"}</td><td>${r.review_wait_seconds} 秒 / ${r.elapsed_seconds} 秒</td><td>${r.tool_calls??'历史未采集'} / ${r.node_calls??'历史未采集'}</td><td><a href="${esc(r.url)}">运行详情 →</a></td></tr>`).join('')}</tbody></table></div>${data.items.length?'':empty('暂无运行记录','发起进度汇总后会在这里显示。')}</section>
  <section class="panel"><div class="panelhead"><h2>最近工具调用</h2><span class="sub">仅元数据，不展示密钥或内部提示</span></div><div class="tablewrap"><table><thead><tr><th>时间</th><th>工具 / 版本</th><th>节点</th><th>结果</th><th>业务摘要</th></tr></thead><tbody>${data.calls.map(c=>`<tr><td>${fmt(c.created_at)}</td><td class="mono">${esc(c.tool_id)} @v${c.tool_version}</td><td class="mono">${esc(c.node)}</td><td>${tag(c.state)}</td><td>${esc(c.summary)}</td></tr>`).join('')}</tbody></table></div>${data.calls.length?'':empty('暂无已采集调用','新运行会采集；历史记录不补造调用数据。')}</section>`;
}

async function loadConfigs(id){
  if(G.kind==='TOOL')G.kind='WORKFLOW';
  if(!id){G.version=null;return api('/definitions?kind='+G.kind);}
  const [definition,agents,models,tools]=await Promise.all([api('/definitions/'+id),api('/definitions?kind=AGENT'),api('/definitions?kind=MODEL'),api('/definitions?kind=TOOL')]);
  if(G.current!==id){G.current=id;G.version=null;}
  return {definition,refs:{agents,models,tools}};
}
pageModules.templates={title:'应用模板',load:()=>api('/templates?project_id='+S.pid),render:templateCatalog};
pageModules.configs={title:'模板与 Agent',global:true,visible:()=>hasRole('operations'),load:loadConfigs,render:(d,id)=>id?configDetail(d):configList(d)};
pageModules.tools={title:'工具连接',global:true,visible:()=>hasRole('tool_admin'),async load(id){G.kind='TOOL';if(!id){G.version=null;return api('/definitions?kind=TOOL');}const definition=await api('/definitions/'+id);if(G.current!==id){G.current=id;G.version=null;}return {definition,refs:{}};},render:(d,id)=>id?configDetail(d):configList(d)};
pageModules.operations={title:'运行评估',global:true,visible:()=>hasRole('operations'),load:()=>api('/operations/overview?'+new URLSearchParams(G.filters)),render:operationsPage};

function govDialog(title,body,button,kind){kbDialog(title,body,button,'gov-'+kind);const form=$('#dialog form');delete form.dataset.kbForm;form.dataset.govForm=kind;}
function currentConfig(){const d=S.detail.definition;return {d,v:d.versions.find(x=>x.version===G.version)||d.versions[0]};}
document.addEventListener('change',event=>{if(event.target.id==='config-version'){G.version=Number(event.target.value);shell(configDetail(S.detail));}else if(event.target.closest('[data-gov-form="config"]'))S.dirty=true;});
document.addEventListener('click',async event=>{
  const template=event.target.closest('[data-gov-template]');if(template){G.selectedTemplate=template.dataset.govTemplate;return;}
  const button=event.target.closest('[data-gov-action]');if(!button)return;
  try{
    button.disabled=true;const action=button.dataset.govAction;
    if(action==='kind'){G.kind=button.dataset.kind;G.version=null;await refresh();return;}
    if(action==='limits'){const l=S.detail.limits;govDialog('调整演示配额',`${field('max_active_runs','最多排队/执行实例',l.max_active_runs,'number','min="1" max="20" required')}${field('daily_model_calls','模型每日调用上限',l.daily_model_calls,'number','min="0" max="10000" required')}<p class="sub">本地队列顺序执行。当前演示不调用外部模型。</p>`,'保存配额','limits');return;}
    const {d,v}=currentConfig();const payload={version:v.version,expected_revision:v.revision};
    if(action==='derive'){const result=await api('/definitions/'+d.id+'/derive',{version:v.version});G.version=result.version;await refresh();toast('配置草稿已准备');}
    else if(action==='copy')govDialog('复制配置',field('name','新配置名称',d.name+' · 副本','text','maxlength="100" required')+'<p class="sub">产生新 ID，不复制业务授权、运行记录或审批。</p>','创建副本','copy');
    else if(action==='validate'){const result=await api('/definitions/'+d.id+'/validate',payload);toast(result.checks.join('；'));}
    else if(action==='debug')govDialog('沙箱预览',`<div class="field"><label for="debug-project">授权样本项目</label><select id="debug-project" name="project_id">${S.me.projects.map(p=>`<option value="${p.id}" ${p.id===S.pid?'selected':''}>${esc(p.name)}</option>`).join('')}</select></div><p class="sub">使用模拟资料与台账执行本地规则预览，不创建报告、整改或外部调用。先保存页面上的修改。</p>`,'运行预览','debug');
    else if(['publish','rollback','status'].includes(action))govDialog({publish:'发布配置版本',rollback:'切换默认版本',status:d.enabled?'停用配置':'启用配置'}[action],`<p>${esc(d.name)} · v${v.version}</p>${area('note','操作说明','')}<p class="sub">${action==='publish'?'发布当前已保存并预览的草稿。新任务使用新版本，旧运行保持原配置。':action==='status'?'模板停用后禁止新任务；工具停用后即时阻断后续调用。':'仅切换新任务的默认版本；已有报告和整改保留。'}</p>`,'确认操作',action);
  }catch(error){failure(error,$('#dialog').open?$('#dialog'):document);}finally{if(button.isConnected)button.disabled=false;}
});
document.addEventListener('submit',async event=>{
  const form=event.target,kind=form.dataset.govForm;if(!kind)return;event.preventDefault();const values=Object.fromEntries(new FormData(form));const button=form.querySelector('button[type=submit]');if(button)button.disabled=true;
  try{
    if(kind==='filters'){G.filters=values;await refresh();return;}
    if(kind==='limits'){await api('/operations/limits',{max_active_runs:Number(values.max_active_runs),daily_model_calls:Number(values.daily_model_calls),expected_version:S.detail.limits.version});closeModal();await refresh();toast('配额已保存');return;}
    const {d,v}=currentConfig(),url='/definitions/'+d.id+'/';
    const payload={version:v.version,expected_revision:v.revision};
    if(kind==='config'){
      const data=structuredClone(v.data);
      if(d.kind==='WORKFLOW'){data.agent_id=values.agent_id;data.agent_version=Number(values.agent_version);data.narrative_prefix=values.narrative_prefix;data.rules.followup_days=Number(values.followup_days);data.mappings=JSON.parse(values.mappings);data.variables=JSON.parse(values.variables);data.allowed_projects=[...form.querySelectorAll('[name=allowed_projects]:checked')].map(x=>x.value);}
      else if(d.kind==='AGENT'){for(const k of ['responsibility','prompt','recommendation','model_id'])data[k]=values[k];data.model_version=Number(values.model_version);for(const k of ['tool_calls','iterations','active_seconds','context_chars'])data.budget[k]=Number(values[k]);data.tools=[...form.querySelectorAll('[name=tools]:checked')].map(x=>x.value);}
      else if(d.kind==='TOOL'){data.timeout_seconds=Number(values.timeout_seconds);data.max_retries=Number(values.max_retries);}
      else for(const k of ['context_limit','max_output_tokens','timeout_seconds'])data[k]=Number(values[k]);
      await api(url+'save',{...payload,data});toast('配置草稿已保存');
    }else if(kind==='copy'){const result=await api(url+'copy',{version:v.version,name:values.name});closeModal();G.version=1;G.current=result.id;location.hash='#/configs/'+result.id;return;}
    else if(kind==='debug'){await api(url+'debug',{...payload,project_id:values.project_id});toast('沙箱预览已完成');}
    else if(kind==='publish'){await api(url+'publish',{...payload,note:values.note});toast('新版本已发布');}
    else if(kind==='rollback'){await api(url+'rollback',{version:v.version,expected_version:d.version,note:values.note});toast('默认版本已切换');}
    else if(kind==='status'){await api(url+'status',{enabled:!d.enabled,expected_version:d.version,note:values.note});toast('启停状态已保存');}
    if($('#dialog').open)closeModal();S.dirty=false;await refresh();
  }catch(error){failure(error,form);}finally{if(button?.isConnected)button.disabled=false;}
});

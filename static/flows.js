'use strict';
const FB={version:null,key:null,selected:null,graph:null,drag:null};
const flowTypeName=k=>({START:'开始',LEDGER:'冻结台账',RULES:'规则统计',KNOWLEDGE:'证据检索',RISK:'进度风险视角',ACCEPTANCE:'验收证据视角',SUBFLOW:'版本化子流程',JOIN:'结果汇合',REVIEW:'人工确认',END:'结束'}[k]||k);
const flowStateName=s=>({PENDING:'未执行',RUNNING:'执行中',SUCCEEDED:'已完成',FAILED:'失败',SKIPPED:'未执行此分支',WAITING:'等待确认',CANCELLED:'已取消'}[s]||s);
const flowNumber=v=>Number.isFinite(Number(v))?Math.max(0,Math.min(4000,Number(v))):0;

function flowCanvas(graph,statuses={},editable=false){
  const nodes=graph.nodes,width=Math.max(950,...nodes.map(n=>flowNumber(n.x)+205)),height=Math.max(350,...nodes.map(n=>flowNumber(n.y)+110));
  return `<div class="flow-canvas-wrap"><svg class="flow-canvas" viewBox="0 0 ${width} ${height}" style="min-width:${Math.min(width,1200)}px" data-flow-editable="${editable?'1':'0'}" role="img" aria-label="流程节点与连接，选择节点查看或编辑"><defs><marker id="flow-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="#99a9c1"/></marker></defs>${nodes.flatMap(n=>n.deps.map(up=>{const source=nodes.find(x=>x.id===up);return source?`<path class="flow-edge" data-from="${esc(up)}" data-to="${esc(n.id)}" d="${flowPath(source,n)}" marker-end="url(#flow-arrow)"/>`:''})).join('')}${nodes.map(n=>`<g data-flow-node="${esc(n.id)}" transform="translate(${flowNumber(n.x)},${flowNumber(n.y)})" class="flow-node ${FB.selected===n.id?'selected':''} ${statuses[n.id]||''}" role="button" tabindex="0" aria-label="${esc(n.title)}，${flowTypeName(n.type)}"><rect width="180" height="72" rx="10"/><text x="13" y="22" class="flow-node-kind">${esc(flowTypeName(n.type))}${n.type==='JOIN'?' · '+(n.config.policy==='ALLOW_PARTIAL'?'允许部分':'全部成功'):''}</text><text x="13" y="44">${esc(n.title.slice(0,14))}</text><text x="13" y="61" class="flow-node-id">${esc(statuses[n.id]?flowStateName(statuses[n.id]):n.id)}</text></g>`).join('')}</svg></div>`;
}
function flowPath(a,b){const x=flowNumber(a.x)+180,y=flowNumber(a.y)+36,endX=flowNumber(b.x),endY=flowNumber(b.y)+36;return `M ${x} ${y} C ${x+55} ${y},${endX-55} ${endY},${endX} ${endY}`;}
function flowsHome(d){
  return `${pagehead('流程编排','编辑只读节点与连接，观察并行读取、版本化子流程和人工确认。')}
  <div class="notice">${icon('info')}<span>本地编排演示使用实际的模拟台账和授权资料。两个分析视角分别核对进度风险与验收证据，模型调用为 0；报告发布和整改创建使用既有业务入口。</span></div>
  <div class="cfg-cards">${d.items.map(f=>`<section class="panel"><div class="panelhead"><h2>${esc(f.name)}</h2><span class="tag">${f.purpose==='SUBFLOW'?'子流程':'主流程'}</span></div><div class="panelbody"><p>当前默认 ${f.active_version?'v'+f.active_version:'未发布'} · ${f.enabled?'启用中':'已停用'}</p><p class="sub">${f.purpose==='SUBFLOW'?'继承父流程的身份、项目、证据与预算。':'支持并行分支、明确汇合策略，最后等待人工确认。'}</p><a class="button primary" href="#/flows/${f.id}">查看流程 →</a></div></section>`).join('')}</div>`;
}
function flowDefinition(d){
  const v=d.versions.find(x=>x.version===FB.version)||d.versions[0];if(!v)return empty('暂无可用版本','请由运营人员发布配置。');FB.version=v.version;
  const key=d.id+':'+v.version+':'+v.revision;if(FB.key!==key){FB.key=key;FB.graph=structuredClone(v.data);FB.selected=FB.graph.nodes[0]?.id;}
  const editing=d.can_edit&&v.state==='DRAFT',n=FB.graph.nodes.find(x=>x.id===FB.selected);
  return `<a class="back" href="#/flows">${icon('back')}全部流程</a>${pagehead(d.name,d.purpose==='SUBFLOW'?'子流程通过父流程继承范围；每次绑定不可变版本。':'同批准备就绪的只读节点最多并行执行三个，结果分开保存。',`${d.can_edit?'<button data-flow-action="derive">派生草稿</button><button data-flow-action="copy">复制为新流程</button><button data-flow-action="status">'+(d.enabled?'停用':'启用')+'</button>':''}${d.purpose==='TOP_LEVEL'&&d.enabled&&d.active_version&&manager()?'<button class="primary" data-flow-action="start">发起编排演示</button>':''}`)}
  <div class="cfg-versionbar"><label for="flow-version">配置版本</label><select id="flow-version">${d.versions.map(x=>`<option value="${x.version}" ${x.version===v.version?'selected':''}>v${x.version} · ${x.state==='DRAFT'?'草稿':'已发布'}${d.active_version===x.version?' · 当前默认':''}</option>`).join('')}</select><span class="sub">修订 ${v.revision} · ${esc(v.content_hash.slice(0,12))}</span>${d.can_edit&&v.state==='PUBLISHED'&&v.version!==d.active_version?'<button data-flow-action="rollback">设为默认版本</button>':''}</div>
  <section class="panel"><div class="panelhead"><h2>节点画布</h2><span class="sub">${editing?'拖动节点调整位置，选中后编辑上游与配置':'发布版只读，修改请派生草稿'}</span></div>${flowCanvas(FB.graph,{},editing)}<div class="panelbody actions">${editing?'<button class="primary" data-flow-action="save">保存草稿</button><button data-flow-action="validate">校验连接与契约</button><button data-flow-action="publish">发布配置</button><button data-flow-action="add-node">新增节点</button>':'<span class="sub">节点结果独立保存；工具当前权限与启停每次调用重验。</span>'}</div><div class="inline-error"></div></section>
  <div class="twocol"><section class="panel"><div class="panelhead"><h2>节点配置</h2><span class="sub">${esc(n?.id||'未选择')}</span></div>${n?`<form class="panelbody" data-flow-form="node"><fieldset class="cfg-fields" ${editing?'':'disabled'}>${advField('title','节点名称',n.title,'text','maxlength="60" required')}<div class="field"><label for="flow-type">节点类型</label><select id="flow-type" name="type">${d.types.map(t=>`<option value="${t}" ${n.type===t?'selected':''}>${flowTypeName(t)}</option>`).join('')}</select></div>${advField('deps','上游节点 ID（逗号分隔）',n.deps.join(','))}<div class="formgrid">${advField('x','横坐标',n.x,'number','min="0" max="4000"')}${advField('y','纵坐标',n.y,'number','min="0" max="2000"')}</div>${advArea('config','节点参数 JSON',JSON.stringify(n.config,null,2),4)}<p class="sub">JOIN：{"policy":"ALL_SUCCESS"} 或 ALLOW_PARTIAL；KNOWLEDGE：可选 query；SUBFLOW：flow_id 与 version。其他节点参数为 {}。</p>${editing?'<button type="submit">应用节点修改</button> <button type="button" data-flow-action="remove-node">移除此节点</button>':''}</fieldset><div class="inline-error"></div></form>`:'<p class="panelbody sub">选择一个节点。</p>'}</section>
  <section class="panel"><div class="panelhead"><h2>可引用子流程与发布说明</h2></div><div class="panelbody">${d.subflows.map(f=>`<p><a href="#/flows/${f.id}">${esc(f.name)}</a><br><span class="sub mono">${f.id} · 当前 v${f.active_version}</span></p>`).join('')}<p>${esc(v.note||'草稿尚未填写发布说明')}</p><p class="sub">只允许继承当前项目；子流程最多嵌套两层，禁止无终止条件的环。保存草稿与发布分开。</p><details><summary>查看或编辑完整定义</summary><textarea id="flow-json" class="mono" rows="12" ${editing?'':'readonly'}>${esc(JSON.stringify(FB.graph,null,2))}</textarea>${editing?'<button data-flow-action="apply-json">应用到画布</button>':''}</details></div></section></div>
  <section class="panel"><div class="panelhead"><h2>当前授权范围内的运行</h2></div>${d.runs.map(r=>`<div class="listrow"><div class="grow"><strong>v${r.flow_version}</strong><p>${fmt(r.created_at)} · ${esc(r.project_id)}</p></div>${tag(r.state,r.state==='COMPLETED'?'已确认完成':null)}<a href="#/flow-runs/${r.id}">查看执行 →</a></div>`).join('')||'<p class="panelbody sub">还没有可查看的编排运行。</p>'}</section>`;
}
function flowResult(value,depth=0){
  if(depth>3||!value)return '';
  let html='';
  if(value.risk_items)html+=`<h3>${esc(value.view)}</h3>${value.risk_items.map(r=>`<article class="adv-hypothesis"><strong>${esc(r.title)} · 逾期 ${r.overdue_days} 天</strong><p>${esc(r.hypothesis)}</p><div class="actions">${r.evidence_ids.map(id=>`<button class="text" data-kb-action="citation" data-id="${esc(id)}">原因线索 ↗</button>`).join('')}</div><p class="sub">${esc(r.proposal)}</p></article>`).join('')||'<p class="sub">当前未识别未完成逾期，仍需核对其他风险。</p>'}${value.truncated?'<p class="sub">仅展示前 20 项，完整数量见规则统计。</p>':''}`;
  if(value.facts)html+=`<h3>${esc(value.view)}</h3>${value.facts.map(f=>`<blockquote class="fact-quote">${esc(f.text)}<div class="actions">${f.evidence_ids.map(id=>`<button class="text" data-kb-action="citation" data-id="${esc(id)}">引用 ↗</button>`).join('')}</div></blockquote>`).join('')}`;
  if(value.missing_information?.length)html+=`<ul class="gaps">${value.missing_information.map(s=>`<li>${esc(s)}</li>`).join('')}</ul>`;
  if(value.partial)html+='<div class="notice warning">汇合保留了部分结果，存在失败或缺失分支，需人工核对。</div>';
  if(value.outputs)html+=Object.values(value.outputs).map(v=>flowResult(v,depth+1)).join('');
  return html;
}
function flowRunPage(r){
  const d=r.data;FB.selected=null;const metric=Object.values(d.outputs).find(v=>v.metrics)?.metrics;const joined=Object.values(d.outputs).find(v=>v.policy);const partial=Object.values(d.statuses).some(x=>x==='FAILED'||x==='SKIPPED');
  return `<a class="back" href="#/flows/${r.flow_id}">${icon('back')}流程定义</a>${pagehead('编排运行 · v'+r.flow_version,d.goal,`<button data-action="refresh">${icon('refresh')}刷新</button>${r.state==='WAITING_REVIEW'&&manager()?'<button data-flow-action="transfer-run">转交确认</button>':''}${r.state==='FAILED'&&manager()?'<button data-flow-action="resume-run">从原输入恢复</button>':''}${!['COMPLETED','CANCELLED','REVIEW_REJECTED'].includes(r.state)&&manager()?'<button data-flow-action="cancel-run">取消运行</button>':''}`)}
  <section class="panel"><div class="panelhead"><h2>实际执行状态</h2>${tag(r.state,r.state==='COMPLETED'?(partial?'部分结果已确认':'已确认完成'):null)}</div>${flowCanvas(d.graph,d.statuses)}<div class="panelbody actions"><span>工具 ${d.tool_calls} / 8 次</span><span>活跃 ${d.active_seconds} / 300 秒</span><span>模型 0 调用 · 0 tokens</span><span class="sub">等待人工确认不计活跃时间</span></div></section>
  ${d.error?`<div class="notice warning">${icon('info')}<span>${esc(d.error.message)} · ${esc(d.error.code)}。失败记录保留，允许部分结果时会明确标记。</span></div>`:''}
  ${r.state==='WAITING_REVIEW'?`<section class="panel"><div class="panelhead"><h2>核对当前成果</h2><span class="sub">绑定 hash ${esc(d.review_hash.slice(0,12))}</span></div><div class="panelbody">${d.needs_transfer?'<p class="error">指定确认人曾失效，请项目经理明确转交后继续。</p>':''}<p>请核对规则数字、证据与缺口。确认只归档本次分析成果；发布报告、创建整改需要另行操作。</p>${!d.needs_transfer&&r.reviewer_id===S.me.user.id?'<button class="primary" data-flow-action="approve-run">核对并确认成果</button> <button data-flow-action="reject-run">退回此成果</button>':`<p class="sub">等待指定审核人 ${esc(person(r.reviewer_id))}。</p>`}</div></section>`:''}
  <div class="twocol"><section class="panel"><div class="panelhead"><h2>规则与独立核对结果</h2></div><div class="panelbody">${metric?`<div class="adv-result-metrics"><span>任务 ${metric.total}</span><span>完成率 <strong>${metric.completion_rate??'不适用'}${metric.completion_rate===null?'':'%'}</strong></span><span>未完成逾期 <strong>${metric.overdue_count}</strong></span></div>`:''}${joined?flowResult(joined):Object.values(d.outputs).filter(v=>v.risk_items||v.facts||v.subflow_id).map(v=>flowResult(v)).join('')||'<p class="sub">节点执行完成后显示有依据的结果。</p>'}${r.state==='COMPLETED'?'<div class="actions"><a class="button" href="#/new">转入正式汇总审核流程 →</a></div>':''}</div></section>
  <section class="panel"><div class="panelhead"><h2>节点尝试与调用</h2></div><div class="panelbody">${r.attempts.map(a=>`<div class="activity"><strong>${esc(d.graph.nodes.find(n=>n.id===a.node_id)?.title||a.node_id)} · ${flowStateName(a.state)} · 第 ${a.attempt} 次</strong><p>${fmt(a.started_at)}${a.ended_at?' → '+fmt(a.ended_at):' · 等待人工事件'}</p><details><summary class="sub">查看当前授权摘要</summary><pre class="pre">${esc(JSON.stringify(a.data,null,2))}</pre></details></div>`).join('')||'<p class="sub">已排队，等待执行。</p>'}<p class="sub">实际只读工具调用 ${r.calls.length} 条；子流程共用父流程的调用预算。</p></div></section></div>`;
}

pageModules.flows={title:'流程编排',global:true,visible:()=>hasRole('operations')||manager(),async load(id){if(!id){FB.key=null;FB.version=null;return api('/flows');}const d=await api('/flows/'+id);if(FB.id!==id){FB.id=id;FB.key=null;FB.version=null;}return d;},render:(d,id)=>id?flowDefinition(d):flowsHome(d)};
pageModules['flow-runs']={title:'编排运行',global:true,async load(id){const r=await api('/flow-runs/'+id);if(S.pid!==r.project_id||!S.project){S.pid=r.project_id;localStorage.setItem('eaw-project',S.pid);S.project=await api('/projects/'+S.pid);}return r;},render:flowRunPage,isActive:r=>['QUEUED','RUNNING'].includes(r.state)};
function flowVersion(){return S.detail.versions.find(v=>v.version===FB.version)||S.detail.versions[0];}
function flowDialog(title,content,submit,kind){advDialog(title,content,submit,'flow-'+kind);const form=$('#dialog form');delete form.dataset.advForm;form.dataset.flowForm=kind;}
document.addEventListener('change',event=>{if(event.target.id==='flow-version'){FB.version=Number(event.target.value);FB.key=null;shell(flowDefinition(S.detail));}});
document.addEventListener('click',async event=>{
  const selected=event.target.closest('[data-flow-node]');if(selected&&S.route==='flows'){if(FB.drag?.moved)return;FB.selected=selected.dataset.flowNode;shell(flowDefinition(S.detail));return;}
  const button=event.target.closest('[data-flow-action]');if(!button)return;
  try{
    button.disabled=true;const action=button.dataset.flowAction;
    if(action==='start'){
      const project=await api('/projects/'+S.pid);FB.startProject=project;
      flowDialog('发起只读编排演示',`${advArea('goal','核对目标','核对 T-005、T-006 的进度风险和验收证据。',3)}<div class="field"><label for="flow-reviewer">指定确认人</label><select id="flow-reviewer" name="reviewer_id">${project.members.filter(m=>['manager','reviewer'].includes(m.role)).map(m=>`<option value="${m.id}" ${m.id===S.me.user.id?'selected':''}>${esc(m.name)}</option>`).join('')}</select></div><p class="sub">使用当前项目台账与授权资料，绑定所选发布版本；人工确认之前保留为待审分析成果。</p>`,'开始执行','start');return;
    }
    if(action==='transfer-run'){flowDialog('转交成果确认',`<div class="field"><label for="flow-transfer">新确认人</label><select id="flow-transfer" name="reviewer_id">${S.project.members.filter(m=>['manager','reviewer'].includes(m.role)).map(m=>`<option value="${m.id}">${esc(m.name)}</option>`).join('')}</select></div>${advArea('reason','转交原因','',3)}`,'确认转交','transfer');return;}
    if(['approve-run','reject-run','cancel-run','resume-run'].includes(action)){
      if(action==='resume-run'){await api('/flow-runs/'+S.detail.id+'/resume',{expected_version:S.detail.version,event_key:key()});await refresh();return;}
      FB.runAction=action;flowDialog(action==='cancel-run'?'取消编排运行':action==='reject-run'?'退回当前成果':'确认当前分析成果',`${advArea('comment',action==='cancel-run'?'取消原因':'确认或退回说明',action==='approve-run'?'已核对当前规则数字、证据与信息缺口。':'',3)}<p class="sub">确认绑定当前结果 hash；已有业务报告和整改不受此操作影响。</p>`,'确认操作','run-action');return;
    }
    const d=S.detail,v=flowVersion(),url='/flows/'+d.id+'/';
    if(action==='derive'){const r=await api(url+'derive',{version:v.version});FB.version=r.version;FB.key=null;await refresh();}
    else if(action==='copy')flowDialog('复制为新流程',advField('name','新流程名称',d.name+' · 副本','text','maxlength="100" required'),'创建副本','copy');
    else if(action==='status'||action==='rollback'||action==='publish'){FB.configAction=action;flowDialog({status:d.enabled?'停用流程':'启用流程',rollback:'切换默认发布版',publish:'发布当前草稿'}[action],`${advArea('note','操作说明','',3)}<p class="sub">已启动的运行保持原配置；工具当前启停与权限变化始终生效。发布前请保存画布修改。</p>`,'确认操作','release');}
    else if(action==='validate'){const result=await api(url+'validate',{version:v.version,expected_revision:v.revision});toast(result.checks.join('；'));}
    else if(action==='save'){await api(url+'save',{version:v.version,expected_revision:v.revision,data:FB.graph});S.dirty=false;FB.key=null;await refresh();toast('流程草稿已保存');}
    else if(action==='add-node'){const id='node_'+Math.random().toString(16).slice(2,8);FB.graph.nodes.push({id,type:'KNOWLEDGE',title:'补充资料检索',deps:['start'],x:230,y:500,config:{query:''}});FB.selected=id;S.dirty=true;shell(flowDefinition(d));}
    else if(action==='remove-node'){FB.graph.nodes=FB.graph.nodes.filter(n=>n.id!==FB.selected);FB.selected=FB.graph.nodes[0]?.id;S.dirty=true;shell(flowDefinition(d));}
    else if(action==='apply-json'){
      const graph=JSON.parse($('#flow-json').value);if(!Array.isArray(graph.nodes)||graph.nodes.length>16||!graph.nodes.every(n=>typeof n.id==='string'&&typeof n.title==='string'&&typeof n.type==='string'&&Array.isArray(n.deps)&&n.deps.every(x=>typeof x==='string')&&n.config&&typeof n.config==='object'))throw new Error('请提供最多 16 个含完整字段的节点');
      FB.graph=graph;FB.selected=graph.nodes[0]?.id;S.dirty=true;shell(flowDefinition(d));
    }
  }catch(error){failure(error,$('#dialog').open?$('#dialog'):document);}finally{if(button.isConnected)button.disabled=false;}
});
document.addEventListener('submit',async event=>{
  const form=event.target,kind=form.dataset.flowForm;if(!kind)return;event.preventDefault();const b=Object.fromEntries(new FormData(form));const button=form.querySelector('button[type=submit]');button.disabled=true;const operation=form.dataset.operationKey||(form.dataset.operationKey=key());
  try{
    if(kind==='node'){const n=FB.graph.nodes.find(n=>n.id===FB.selected);Object.assign(n,{title:b.title,type:b.type,deps:b.deps.split(',').map(x=>x.trim()).filter(Boolean),x:Number(b.x),y:Number(b.y),config:JSON.parse(b.config)});S.dirty=true;shell(flowDefinition(S.detail));return;}
    let target=null;
    if(kind==='start'){const d=S.detail,v=flowVersion();if(v.state!=='PUBLISHED')throw new Error('请先选择已发布版本');const r=await api('/flows/'+d.id+'/run',{project_id:S.pid,version:v.version,goal:b.goal,reviewer_id:b.reviewer_id,event_key:operation});target='#/flow-runs/'+r.id;}
    else if(kind==='copy'){const r=await api('/flows/'+S.detail.id+'/copy',{name:b.name,version:flowVersion().version});FB.key=null;FB.version=1;target='#/flows/'+r.id;}
    else if(kind==='release'){
      const d=S.detail,v=flowVersion(),payload={note:b.note,version:v.version};if(FB.configAction==='publish')payload.expected_revision=v.revision;else payload.expected_version=d.version;if(FB.configAction==='status')payload.enabled=!d.enabled;
      await api('/flows/'+d.id+'/'+FB.configAction,payload);FB.key=null;toast('流程配置已更新');
    }else if(kind==='transfer'){await api('/flow-runs/'+S.detail.id+'/transfer',{...b,expected_version:S.detail.version,event_key:operation});toast('确认人已转交');}
    else if(kind==='run-action'){
      const r=S.detail,payload={expected_version:r.version,event_key:operation};if(FB.runAction==='cancel-run')payload.reason=b.comment;else Object.assign(payload,{decision:FB.runAction==='approve-run'?'APPROVE':'REJECT',content_hash:r.data.review_hash,comment:b.comment});
      await api('/flow-runs/'+r.id+'/'+(FB.runAction==='cancel-run'?'cancel':'review'),payload);toast('编排运行状态已保存');
    }
    closeModal();S.dirty=false;if(target&&target!==location.hash)location.hash=target;else await refresh();
  }catch(error){failure(error,form);}finally{if(button.isConnected)button.disabled=false;}
});
document.addEventListener('pointerdown',event=>{
  const group=event.target.closest('[data-flow-node]'),svg=group?.closest('svg');if(!group||svg.dataset.flowEditable!=='1')return;
  const p=new DOMPoint(event.clientX,event.clientY).matrixTransform(svg.getScreenCTM().inverse()),n=FB.graph.nodes.find(n=>n.id===group.dataset.flowNode);FB.drag={id:n.id,x:p.x,y:p.y,ox:n.x,oy:n.y,svg,group,moved:false};group.setPointerCapture(event.pointerId);
});
document.addEventListener('pointermove',event=>{
  const drag=FB.drag;if(!drag||event.buttons===0)return;const p=new DOMPoint(event.clientX,event.clientY).matrixTransform(drag.svg.getScreenCTM().inverse());if(Math.abs(p.x-drag.x)+Math.abs(p.y-drag.y)<3)return;
  const n=FB.graph.nodes.find(n=>n.id===drag.id);n.x=Math.round(Math.max(0,Math.min(4000,drag.ox+p.x-drag.x)));n.y=Math.round(Math.max(0,Math.min(2000,drag.oy+p.y-drag.y)));drag.group.setAttribute('transform',`translate(${n.x},${n.y})`);drag.moved=true;S.dirty=true;
  drag.svg.querySelectorAll('.flow-edge').forEach(edge=>{const a=FB.graph.nodes.find(n=>n.id===edge.dataset.from),b=FB.graph.nodes.find(n=>n.id===edge.dataset.to);if(a&&b)edge.setAttribute('d',flowPath(a,b));});
});
document.addEventListener('pointerup',()=>{if(FB.drag){const moved=FB.drag.moved;FB.drag=null;if(moved)setTimeout(()=>shell(flowDefinition(S.detail)),0);}});
document.addEventListener('keydown',event=>{const node=event.target.closest('[data-flow-node]');if(node&&event.key==='Enter'&&S.route==='flows'){FB.selected=node.dataset.flowNode;shell(flowDefinition(S.detail));}});

document.addEventListener('input',event=>{if(event.target.closest('[data-flow-form]'))S.dirty=true;});

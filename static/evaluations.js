'use strict';
const EV={set:null};
function demoEvaluationCases(){
  const date=S.me.today;
  return [{id:'demo-progress',name:'完成、逾期与取消任务',kind:'RULES',input:{rows:[{task_id:'S-1',title:'演示已完成任务',status:'DONE',due_date:date,completed_at:date},{task_id:'S-2',title:'演示待处理任务',status:'TODO',due_date:dayAdd(date,-2)},{task_id:'S-3',title:'演示已取消任务',status:'CANCELLED'}],cutoff:date,period_start:dayAdd(date,-6),period_end:date},gold:{total:2,completed:1,completion_rate:50,period_completed:1,overdue_count:1,completed_late:0},allowed_actions:['READ_ONLY']},{id:'demo-empty',name:'空台账显示不适用',kind:'RULES',input:{rows:[],cutoff:date,period_start:dayAdd(date,-6),period_end:date},gold:{total:0,completed:0,completion_rate:null,overdue_count:0},allowed_actions:['READ_ONLY']}];
}
function evaluationPage(d,id){
  if(id)return evaluationResult(d);
  return `${pagehead('版本评测','用明确的演示样本、预期结果与人工评审，记录配置变化。','<button data-eval-action="new">新建演示样本集</button>')}
  <div class="notice">${icon('info')}<span>本页提供产品内的样本比较。当前执行本地规则或原文检索，模型调用为零；这里的通过数只对应所选样本，不代表真实模型准确率。</span></div>
  <section class="panel"><div class="panelhead"><h2>版本化样本集</h2></div>${d.sets.map(s=>`<div class="listrow"><div class="grow"><strong>${esc(s.name)} · v${s.version}</strong><p>${s.data.length} 条 · 数据 hash ${esc(s.content_hash.slice(0,12))} · ${fmt(s.created_at)}</p></div><button data-eval-action="revise" data-id="${s.id}" data-version="${s.version}">派生样本版本</button><button class="primary" data-eval-action="run" data-id="${s.id}" data-version="${s.version}">比较配置版本</button></div>`).join('')||empty('还没有样本集','可使用内置的两条模拟样本开始讲解，再补充预期结果。')}</section>
  <section class="panel"><div class="panelhead"><h2>比较与人工评审记录</h2></div>${d.runs.map(r=>`<div class="listrow"><div class="grow"><strong>${esc(r.definition_id)} · 候选 v${r.definition_version}</strong><p>样本集 v${r.set_version} · ${fmt(r.created_at)}</p></div>${tag(r.state,r.state==='COMPLETED'?'比较完成':null)}<a href="#/evaluations/${r.id}">查看结果 →</a></div>`).join('')||'<p class="panelbody sub">尚未运行样本比较。</p>'}</section>`;
}
function evaluationResult(r){
  const d=r.data,candidate=d.candidate_result,baseline=d.baseline_result;
  const result=(label,result)=>`<section class="panel"><div class="panelhead"><h2>${label}</h2><span>${result.passed}/${result.total} 条符合预期</span></div><div class="panelbody"><p class="sub">字段匹配 ${result.check_matched}/${result.check_total}，以下为实际本地比较结果。</p>${result.results.map(x=>`<details open><summary><strong>${esc(x.name)}</strong> · ${x.passed?'符合预期':'存在差异'}</summary><table><thead><tr><th>判分项</th><th>预期</th><th>实际</th><th>结果</th></tr></thead><tbody>${x.checks.map(c=>`<tr><td>${esc(c.field)}</td><td>${esc(JSON.stringify(c.expected))}</td><td>${esc(JSON.stringify(c.actual))}</td><td>${c.matched?'一致':'差异'}</td></tr>`).join('')}</tbody></table><details><summary>查看输出、关注项与只读动作</summary><pre class="pre">${esc(JSON.stringify(x.actual,null,2))}</pre><p class="sub">允许动作 READ_ONLY；业务写入 ${x.business_writes}。</p></details></details>`).join('')}</div></section>`;
  return `<a class="back" href="#/evaluations">${icon('back')}全部版本评测</a>${pagehead('配置样本比较',`候选 v${r.definition_version}${r.baseline_version?' / 基准 v'+r.baseline_version:''} · 样本数据 v${r.set_version}`,r.state==='COMPLETED'?'<button data-eval-action="review">记录人工评审</button>':'')}
  <div class="notice">${icon('info')}<span>模式：本地演示比较 · 模型 0 调用 · 0 tokens · 业务写入 0。${d.limitations.map(esc).join('；')}。</span></div>
  <section class="panel"><div class="panelbody"><p>候选配置 hash ${esc(d.candidate.hash.slice(0,16))} · 草稿修订 ${d.candidate.revision}<br>数据 hash ${esc(d.dataset_hash.slice(0,16))}</p><p class="sub">${tag(r.state,r.state==='COMPLETED'?'比较完成':null)} · ${d.duration_ms??'—'} 毫秒</p>${d.error?`<p class="error">${esc(d.error)}</p>`:''}</div></section>
  ${candidate?`<div class="${baseline?'twocol':''}">${baseline?result('基准 v'+r.baseline_version,baseline):''}${result('候选 v'+r.definition_version,candidate)}</div>`:'<p class="sub">比较结果生成中，页面自动更新。</p>'}
  <section class="panel"><div class="panelhead"><h2>人工评审</h2></div>${r.reviews.map(v=>`<div class="panelbody"><strong>${v.decision==='ACCEPT_DEMO'?'演示样本可接受':'需要继续修改'}</strong><p>${esc(v.comment)}</p><span class="sub">${esc(person(v.actor_id))} · ${fmt(v.created_at)}</span></div>`).join('')||'<p class="panelbody sub">尚无人工结论，系统不会将字段匹配数自动当成发布批准。</p>'}</section>`;
}
pageModules.evaluations={title:'版本评测',visible:()=>hasRole('operations')&&manager(),async load(id){const r=await api('/evaluations'+(id?'/'+id:'?project_id='+S.pid));if(id&&S.pid!==r.project_id){S.pid=r.project_id;S.project=await api('/projects/'+S.pid);}return r;},render:evaluationPage,isActive:d=>d.state==='QUEUED'};
function evaluationDialog(title,body,label,kind){advDialog(title,body,label,'eval-'+kind);const f=$('#dialog form');delete f.dataset.advForm;f.dataset.evalForm=kind;}
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-eval-action]');if(!button)return;button.disabled=true;
  try{
    const action=button.dataset.evalAction;
    if(action==='new'||action==='revise'){
      EV.set=action==='revise'?S.detail.sets.find(s=>s.id===button.dataset.id&&s.version===Number(button.dataset.version)):null;
      evaluationDialog('保存演示样本集版本',`${advField('name','样本集名称',EV.set?.name||'进度规则 · 演示样本','text','maxlength="100" required')}<div class="field"><label for="eval-cases">输入与 Gold 预期结果</label><textarea class="mono" id="eval-cases" name="cases" rows="18" required>${esc(JSON.stringify(EV.set?.data||demoEvaluationCases(),null,2))}</textarea></div><p class="sub">RULES 样本检查冻结输入的数字。QUESTION 样本输入为 question，gold 包含 answer_status、contains 原文关键词数组、min_evidence。所有样本 allowed_actions 固定为 ["READ_ONLY"]。保存产生不可变的新数据版本。</p>`,'保存样本版本','set');return;
    }
    if(action==='run'){
      EV.set=S.detail.sets.find(s=>s.id===button.dataset.id&&s.version===Number(button.dataset.version));const options=S.detail.definitions;
      evaluationDialog('比较配置版本',`<p>使用 ${esc(EV.set.name)} · v${EV.set.version}，不创建业务报告或整改。</p><div class="field"><label for="eval-candidate">候选配置</label><select id="eval-candidate" name="candidate">${options.map(o=>`<option value="${o.id}@${o.version}">${esc(o.name)} · v${o.version} · ${o.state==='DRAFT'?'草稿':'已发布'}</option>`).join('')}</select></div><div class="field"><label for="eval-baseline">基准配置（选填）</label><select id="eval-baseline" name="baseline"><option value="">不比较基准</option>${options.map(o=>`<option value="${o.id}@${o.version}">${esc(o.name)} · v${o.version}</option>`).join('')}</select></div>`,'运行样本比较','run');return;
    }
    if(action==='review')evaluationDialog('记录人工评审',`<div class="field"><label for="eval-decision">结论</label><select id="eval-decision" name="decision"><option value="ACCEPT_DEMO">演示样本可接受</option><option value="NEEDS_CHANGE">需要继续修改</option></select></div>${advArea('comment','判分依据、限制与后续建议','',4)}`,'保存人工结论','review');
  }catch(error){failure(error,$('#dialog').open?$('#dialog'):document);}finally{if(button.isConnected)button.disabled=false;}
});
document.addEventListener('submit',async event=>{
  const form=event.target,kind=form.dataset.evalForm;if(!kind)return;event.preventDefault();const b=Object.fromEntries(new FormData(form)),button=form.querySelector('button[type=submit]');button.disabled=true;
  try{
    const event_key=form.dataset.operationKey||(form.dataset.operationKey=key());let target;
    if(kind==='set'){await api('/evaluations',{project_id:S.pid,name:b.name,cases:JSON.parse(b.cases),...(EV.set?{set_id:EV.set.id}:{})});toast('样本版本已保存');}
    if(kind==='run'){
      const [ident,version]=b.candidate.split('@');const [baselineId,baselineVersion]=(b.baseline||'').split('@');if(baselineId&&baselineId!==ident)throw new Error('请在同一模板中选择基准和候选版本');
      const r=await api('/evaluations/run',{set_id:EV.set.id,set_version:EV.set.version,definition_id:ident,definition_version:Number(version),baseline_version:baselineVersion?Number(baselineVersion):null,event_key});target='#/evaluations/'+r.id;
    }
    if(kind==='review'){await api('/evaluations/'+S.detail.id+'/review',{...b,expected_version:S.detail.version,event_key});toast('人工评审已记录');}
    closeModal();S.dirty=false;if(target)location.hash=target;else await refresh();
  }catch(error){failure(error,form);}finally{if(button.isConnected)button.disabled=false;}
});

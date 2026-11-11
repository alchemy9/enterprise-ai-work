'use strict';
const DL={relation:null};
const exportState=s=>({QUEUED:'排队中',RUNNING:'生成中',SUCCEEDED:'可下载',FAILED:'生成失败'}[s]||s);
function exportCenter(d,id){
  const items=id?[d]:d.items;
  return `${pagehead('导出与下载','选择的报告版本固定保留；生成和下载时均检查当前访问权限。')}
  <div class="notice">${icon('info')}<span>下载链接有效期为 10 分钟，并绑定当前账号。已下载到设备的文件无法远程撤回。</span></div>
  ${items.map(j=>`<section class="panel"><div class="panelhead"><h2>${esc(j.data.title)} · v${j.report_version}</h2><span class="tag">${exportState(j.state)}</span></div><div class="panelbody"><p>${j.format.toUpperCase()} · ${fmt(j.created_at)} · 请求时状态 ${esc(j.data.status_at_request)}</p>${j.error?`<p class="error">${esc(j.error)}</p>`:''}<div class="actions"><a href="#/reports/${j.report_id}">来源报告 →</a>${j.state==='SUCCEEDED'?`<button class="primary" data-delivery-action="link" data-id="${j.id}">生成 10 分钟下载地址</button>`:j.state==='FAILED'?`<button data-delivery-action="retry" data-id="${j.id}" data-version="${j.version}">重新生成</button>`:'<span class="sub">生成中，页面将更新</span>'}<span id="download-${j.id}"></span></div></div></section>`).join('')||empty('暂无导出任务','在报告或成果中心选择文件格式后开始生成。')}`;
}
pageModules.downloads={title:'导出与下载',global:true,load:id=>api('/exports'+(id?'/'+id:'')),render:exportCenter,isActive:d=>Array.isArray(d.items)?d.items.some(j=>['QUEUED','RUNNING'].includes(j.state)):['QUEUED','RUNNING'].includes(d.state)};
function fixDetail(f){
  const own=f.owner_id===S.me.user.id;
  return (f.data.needs_assignment?`<div class="notice warning">${icon("info")}<span>整改待分配：${esc(f.data.assignment_reason)}，请项目经理明确改派负责人。</span></div>`:"")+fixDetailBase(f)+`<section class="panel"><div class="panelhead"><h2>关联事项与沟通记录</h2></div><div class="panelbody">${f.data.parent_fix_id?`<p>来源：<a href="#/fixes/${esc(f.data.parent_fix_id)}">${f.data.relation==='FOLLOWUP'?'已验收事项的后续跟进':'拆分来源'} →</a><br><span class="sub">${esc(f.data.relation_reason)}</span></p>`:''}<div class="actions">${manager()&&f.state!=='CANCELLED'?`<button data-delivery-action="related">${f.state==='ACCEPTED'?'新建关联跟进':'拆分为另一整改'}</button>`:''}${manager()||own?'<button data-delivery-action="communication">补录沟通摘要</button>':''}<button data-delivery-action="show-related">查看关联整改</button></div><p class="sub">拆分和跟进均需重新核对字段并明确确认创建。沟通摘要只记录交流，不改变处理或验收状态。</p><div id="related-fixes"></div></div></section>`;
}
function retentionPage(d){return `${pagehead('资料保留','下架立即阻断访问；默认保留 30 天后清理内容，保留审计与来源标识。')}<section class="panel"><div class="tablewrap"><table><thead><tr><th>资料</th><th>访问状态</th><th>内容保留</th><th>说明</th><th></th></tr></thead><tbody>${d.items.map(x=>`<tr><td>${esc(x.title)}</td><td>${x.state==='ACTIVE'?'可按授权读取':'已下架，不能读取'}</td><td>${x.retention_state==='PURGED'?'内容已清理':x.purge_after?fmt(x.purge_after):'尚未安排'}</td><td>${esc(x.reason||'文件保持可用，未进入清理')}</td><td>${x.state==='REMOVED'&&x.retention_state!=='PURGED'?`<button data-delivery-action="retention" data-id="${x.id}">设置保留期</button>`:''}</td></tr>`).join('')}</tbody></table></div></section><p class="sub">本页只管理应用内原文件与索引。现有本地备份由演示者保管，不宣称已同步擦除备份。</p>`;}
pageModules.retention={title:'资料保留',visible:()=>manager()||S.project?.project.role==='knowledge_admin',load:()=>api('/retention?project_id='+S.pid),render:retentionPage};
pageModules.libraries={title:'知识库设置',visible:canManageKnowledge,load:()=>api('/projects/'+S.pid+'/libraries'),render:d=>`${pagehead('知识库设置','负责人、默认有效期与库级授权叠加到每份资料和历史成果。','<a class="button" href="#/knowledge">返回知识中心</a>')}<section class="panel">${d.libraries.map(l=>`<div class="listrow"><div class="grow"><strong>${esc(l.name)}</strong><p>负责人 ${esc(person(l.policy.owner_id))} · 默认有效期 ${l.policy.default_valid_days?l.policy.default_valid_days+' 天':'不默认到期'} · ${l.policy.acl_mode==='PROJECT'?'项目成员':'指定角色与成员'} · 授权资料 ${l.document_count} 份</p></div><button data-delivery-action="library-policy" data-id="${l.id}">编辑设置</button></div>`).join('')||empty('暂无可访问知识库','请在知识中心创建知识库。')}</section>`};
function deliveryDialog(title,body,label,kind){advDialog(title,body,label,'dl-'+kind);const f=$('#dialog form');delete f.dataset.advForm;f.dataset.deliveryForm=kind;}
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-delivery-action]');if(!button)return;
  button.disabled=true;
  try{
    const action=button.dataset.deliveryAction;
    if(action==='export'){
      const r=await api('/exports',{report_id:button.dataset.id||S.detail.id,format:button.dataset.format,event_key:key()});location.hash='#/downloads/'+r.id;return;
    }
    if(action==='library-policy'){
      const l=S.detail.libraries.find(x=>x.id===button.dataset.id),p=l.policy;DL.library=l;
      deliveryDialog('知识库负责人、有效期与权限',`<p>${esc(l.name)}</p><div class="field"><label for="dl-lib-owner">负责人</label><select id="dl-lib-owner" name="owner_id">${S.project.members.filter(m=>['manager','knowledge_admin'].includes(m.role)).map(m=>`<option value="${m.id}" ${m.id===p.owner_id?'selected':''}>${esc(m.name)}</option>`).join('')}</select></div>${advField('default_valid_days','新上传资料的默认有效天数（0 表示不默认到期）',p.default_valid_days,'number','min="0" max="3650" required')}<div class="field"><label for="dl-lib-scope">授权方式</label><select id="dl-lib-scope" name="acl_mode"><option value="PROJECT" ${p.acl_mode==='PROJECT'?'selected':''}>有效项目成员</option><option value="CUSTOM" ${p.acl_mode==='CUSTOM'?'selected':''}>指定角色或成员</option></select></div><div class="field"><label>允许的项目角色</label>${['manager','reviewer','member','knowledge_admin','service_runner'].map(r=>`<label class="check"><input type="checkbox" name="roles" value="${r}" ${p.roles.includes(r)?'checked':''}>${esc(roleName(r))}</label>`).join('')}</div><div class="field"><label>额外允许的成员</label>${S.project.members.map(m=>`<label class="check"><input type="checkbox" name="members" value="${m.id}" ${p.members.includes(m.id)?'checked':''}>${esc(m.name)}</label>`).join('')}</div><p class="sub">库级授权和资料授权取交集；缩小范围会影响检索、引用与历史报告。负责人字段不自动授予内容阅读权。默认有效期只用于后续上传，不改写旧版本。</p>`,'保存知识库设置','library-policy');return;
    }
    if(action==='link'){
      const result=await api('/exports/'+button.dataset.id+'/link',{});$('#download-'+button.dataset.id).innerHTML=`<a class="button primary" href="${esc(result.url)}" download>下载文件</a><span class="sub">有效至 ${fmt(result.expires_at)}</span>`;return;
    }
    if(action==='retry'){await api('/exports/'+button.dataset.id+'/retry',{expected_version:Number(button.dataset.version)});await refresh();return;}
    if(action==='show-related'){
      const r=await api('/rectifications/'+S.detail.id+'/related');$('#related-fixes').innerHTML=r.items.map(x=>`<p><a href="#/fixes/${x.id}">${esc(JSON.parse(x.data).title)}</a> · ${tag(x.state)}</p>`).join('')||'<p class="sub">当前没有下游关联整改。</p>';return;
    }
    if(action==='related'){
      const f=S.detail;DL.relation=f.state==='ACCEPTED'?'FOLLOWUP':'SPLIT';
      deliveryDialog(DL.relation==='FOLLOWUP'?'新建关联跟进':'拆分整改事项',`${advField('title','新事项标题',f.data.title+' · '+(DL.relation==='FOLLOWUP'?'后续跟进':'拆分事项'),'text','maxlength="100" required')}${advArea('description','问题描述',f.data.description,3)}<div class="formgrid"><div class="field"><label for="dl-owner">负责人</label><select id="dl-owner" name="owner_id">${S.project.members.filter(m=>m.role!=='service_runner').map(m=>`<option value="${m.id}" ${m.id===f.owner_id?'selected':''}>${esc(m.name)}</option>`).join('')}</select></div>${advField('due_date','截止日期',dayAdd(S.me.today,3),'date',`min="${S.me.today}" required`)}<div class="field"><label for="dl-priority">优先级</label><select id="dl-priority" name="priority"><option value="MEDIUM">中</option><option value="HIGH">高</option><option value="LOW">低</option></select></div></div>${advArea('acceptance','验收标准',f.data.acceptance,3)}${advArea('reason','拆分或继续跟进的原因','',3)}`,'核对将创建的事项','related');return;
    }
    if(action==='communication')deliveryDialog('补录沟通摘要',`${advField('channel','沟通方式','线下沟通','text','maxlength="80" required')}${advArea('summary','沟通摘要','',4)}<p class="sub">该记录不会把任务自动标记为处理完成或验收通过。</p>`,'保存沟通记录','communication');
    if(action==='retention'){DL.documentId=button.dataset.id;deliveryDialog('设置下架资料保留期',`${advField('days','从今天起保留多少天',30,'number','min="1" max="365" required')}${advArea('reason','保留与清理说明','演示资料下架后按保留期自动清理应用内原文件与索引。',3)}<p class="sub">当前操作安排未来清理，不立即销毁内容。</p>`,'保存保留计划','retention');}
  }catch(error){failure(error,$('#dialog').open?$('#dialog'):document);}finally{if(button.isConnected)button.disabled=false;}
});
document.addEventListener('submit',async event=>{
  const form=event.target,kind=form.dataset.deliveryForm;if(!kind)return;event.preventDefault();const b=Object.fromEntries(new FormData(form)),button=form.querySelector('button[type=submit]');button.disabled=true;
  try{
    const event_key=form.dataset.operationKey||(form.dataset.operationKey=key());
    if(kind==='related'){const cf=await api('/rectifications/'+S.detail.id+'/related',{...b,expected_version:S.detail.version,event_key,relation:DL.relation});finalConfirmation(cf);return;}
    if(kind==='communication')await api('/rectifications/'+S.detail.id+'/communication',{...b,expected_version:S.detail.version,event_key});
    if(kind==='library-policy')await api('/projects/'+S.pid+'/libraries/'+DL.library.id+'/policy',{owner_id:b.owner_id,default_valid_days:Number(b.default_valid_days),acl_mode:b.acl_mode,roles:[...form.querySelectorAll('[name=roles]:checked')].map(e=>e.value),members:[...form.querySelectorAll('[name=members]:checked')].map(e=>e.value),expected_version:DL.library.policy.version});
    if(kind==='retention')await api('/retention',{project_id:S.pid,document_id:DL.documentId,days:Number(b.days),reason:b.reason});
    closeModal();S.dirty=false;toast('记录已保存');await refresh();
  }catch(error){failure(error,form);}finally{if(button.isConnected)button.disabled=false;}
});

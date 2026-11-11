'use strict';
const PUI={tab:'users',auditFilters:{}};
PUI.artifactFilters={page:1};
const hasRole=role=>(S.me?.system_roles||[]).includes(role);
const systemRoleName=role=>({enterprise_admin:'企业管理员',operations:'AI 运营',tool_admin:'工具管理员',audit:'审计查询'}[role]||role);

function roleOptions(selected='member'){
  return ['member','reviewer','manager','knowledge_admin'].map(role=>`<option value="${role}" ${role===selected?'selected':''}>${roleName(role)}</option>`).join('');
}

function userOptions(users,selected=''){
  return users.filter(u=>u.active!==0).map(u=>`<option value="${u.id}" ${u.id===selected?'selected':''}>${esc(u.name)} · ${esc(u.username)}</option>`).join('');
}

function adminPage(data){
  return `${pagehead('管理控制台','维护演示企业的账号与项目。系统权限与项目内容权限分别判断。','<button class="primary" data-platform-action="'+(PUI.tab==='users'?'new-user':'new-project')+'">'+icon('plus')+(PUI.tab==='users'?'新增账号':'新建项目')+'</button>')}
  <section class="panel"><div class="pilltabs"><button data-platform-action="admin-tab" data-tab="users" class="${PUI.tab==='users'?'active':''}">成员账号 · ${data.users.length}</button><button data-platform-action="admin-tab" data-tab="projects" class="${PUI.tab==='projects'?'active':''}">项目空间 · ${data.projects.length}</button></div>
  ${PUI.tab==='users'?`<div class="tablewrap"><table><thead><tr><th>成员 / 账号</th><th>系统角色</th><th>状态</th><th></th></tr></thead><tbody>${data.users.map(u=>`<tr><td class="title">${esc(u.name)}<div class="sub mono">${esc(u.username)}</div></td><td>${u.roles.length?u.roles.map(r=>`<span class="tag">${systemRoleName(r)}</span>`).join(' '):'<span class="sub">无系统管理角色</span>'}</td><td>${u.active?tag('ACTIVE','已启用'):tag('CANCELLED','已停用')}</td><td><button class="text" data-platform-action="edit-user" data-id="${u.id}">编辑账号</button></td></tr>`).join('')}</tbody></table></div>`:`<div class="tablewrap"><table><thead><tr><th>项目名称</th><th>项目经理</th><th>成员</th><th>状态</th><th></th></tr></thead><tbody>${data.projects.map(p=>{const membership=S.me.projects.find(m=>m.id===p.id);return `<tr><td class="title">${esc(p.name)}<div class="sub mono">${esc(p.code)}</div></td><td>${esc(p.manager_name||'待指定')}</td><td>${p.member_count} 人</td><td>${tag(p.status)}</td><td>${membership?`<button class="text" data-platform-action="enter-project" data-id="${p.id}">进入项目 →</button>`:'<span class="sub">尚无项目内容授权</span>'} <button class="text" data-platform-action="authorize-project" data-id="${p.id}">授权成员</button>${membership?.role==='manager'?` <button class="text" data-platform-action="project-status" data-id="${p.id}">${p.status==='ACTIVE'?'归档':'重新开启'}</button>`:''}</td></tr>`;}).join('')}</tbody></table></div>`}</section>
  <div class="notice">${icon('info')}<span>新增账号后，仍需在项目中分配成员角色。停用会阻断旧会话；历史审核与活动记录保留。</span></div>`;
}

function membersPage(data){
  const p=data.settings.project,settings=data.settings.settings;
  return `${pagehead('项目与成员','维护项目资料、成员范围和业务角色。','<button class="primary" data-platform-action="add-member">'+icon('plus')+'添加或调整成员</button>')}
  <section class="panel"><div class="panelhead"><h2>项目成员</h2><span class="sub">${data.members.length} 人</span></div><div class="tablewrap"><table><thead><tr><th>成员</th><th>项目角色</th><th>账号状态</th><th></th></tr></thead><tbody>${data.members.map(m=>`<tr><td class="title">${esc(m.name)}<div class="sub mono">${esc(m.username)}</div></td><td>${roleName(m.role)}</td><td>${m.active?tag('ACTIVE','启用中'):tag('CANCELLED','已停用')}</td><td><button class="text" data-platform-action="edit-member" data-id="${m.id}">调整角色</button> <button class="text" data-platform-action="remove-member" data-id="${m.id}">移出项目</button></td></tr>`).join('')}</tbody></table></div></section>
  <section class="panel"><div class="panelhead"><h2>项目信息</h2>${tag(p.status)}</div><form class="panelbody" data-platform-form="project-settings"><div class="formgrid"><div class="field"><label for="project-name">项目名称</label><input id="project-name" name="name" value="${esc(p.name)}" maxlength="100" required></div><div class="field"><label for="project-code">项目编号</label><input id="project-code" name="code" value="${esc(p.code)}" maxlength="40" required></div><div class="field"><label for="planned-start">计划开始日期</label><input id="planned-start" name="planned_start" type="date" value="${esc(settings.planned_start)}"></div><div class="field"><label for="planned-end">计划结束日期</label><input id="planned-end" name="planned_end" type="date" value="${esc(settings.planned_end)}"></div><div class="field full"><label for="project-description">项目说明</label><textarea id="project-description" name="description" maxlength="2000">${esc(p.description)}</textarea></div></div><div class="inline-error"></div><div class="actions"><button class="primary" type="submit">保存项目信息</button><span class="sub">日期按上海时区展示</span></div></form></section>`;
}

function inboxPage(data){
  return `${pagehead('待办与通知','聚焦需要你审核、处理和验收的事项。','<button data-action="refresh">'+icon('refresh')+'刷新</button>')}
  <section class="panel"><div class="panelhead"><h2>当前待办</h2><span class="tag orange">${data.todos.length} 项</span></div>${data.todos.length?data.todos.map(t=>`<div class="listrow"><div class="riskicon">${icon(t.kind==='REVIEW'?'report':'fix')}</div><div class="grow"><strong>${esc(t.title)}</strong><p>${esc(t.project_name)}${t.due_date?' · 截止 '+esc(t.due_date):''}</p></div>${tag(t.state)}<a href="${esc(t.url)}">处理 →</a></div>`).join(''):empty('当前没有待办','有报告待审或整改待处理时会显示在这里。')}</section>
  <section class="panel"><div class="panelhead"><h2>站内通知</h2><span class="sub">${data.unread} 条未读</span></div>${data.notices.length?data.notices.map(n=>`<div class="listrow ${n.read_at?'notice-read':''}"><span class="notice-status ${n.read_at?'read':''}"></span><div class="grow"><strong>${esc(n.title)}</strong><p>${fmt(n.created_at)}</p></div>${!n.read_at?`<button class="small" data-platform-action="read-notice" data-id="${n.id}">标为已读</button>`:''}${n.accessible?`<a href="#/${{report:'reports',fix:'fixes',run:'runs',document:'knowledge',analysis:'analyses',connection:'connections',schedule:'schedules',flow:'flow-runs'}[n.object_type]||'overview'}/${n.object_id}" data-platform-action="open-notice" data-id="${n.id}">查看 →</a>`:'<span class="sub">当前无访问权限</span>'}</div>`).join(''):empty('还没有站内通知','后续审核、发布与整改事件会自动生成通知。')}</section>`;
}

function auditPage(data){
  PUI.auditItems=data.items;
  return `${pagehead('审计记录','按权限查看操作轨迹，业务内容仍受项目与来源授权限制。','<button data-platform-action="export-audit">'+icon('download')+'导出当前记录</button>')}
  <form class="filters" data-platform-form="audit-filter"><input name="action" placeholder="筛选操作类型，如 REPORT" value="${esc(PUI.auditFilters.action||'')}" aria-label="操作类型"><input name="actor_id" placeholder="操作者 ID（选填）" value="${esc(PUI.auditFilters.actor_id||'')}" aria-label="操作者 ID"><select name="project_id" aria-label="筛选项目"><option value="">全部授权范围</option>${S.me.projects.map(p=>`<option value="${p.id}" ${PUI.auditFilters.project_id===p.id?'selected':''}>${esc(p.name)}</option>`).join('')}</select><input name="object_id" placeholder="对象 ID（选填）" value="${esc(PUI.auditFilters.object_id||'')}" aria-label="审计对象"><input name="date_from" type="date" value="${esc(PUI.auditFilters.date_from||'')}" aria-label="审计开始日期"><input name="date_to" type="date" value="${esc(PUI.auditFilters.date_to||'')}" aria-label="审计结束日期"><button type="submit">筛选</button></form>
  <section class="panel"><div class="tablewrap"><table><thead><tr><th>时间</th><th>操作者</th><th>操作</th><th>对象与变更</th></tr></thead><tbody>${data.items.map(item=>`<tr><td>${fmt(item.created_at)}</td><td>${esc(item.actor_name)}</td><td class="mono">${esc(item.action)}</td><td><div class="mono">${esc(item.object_id)}</div><details><summary class="sub">${item.data.restricted?'内容受限':'查看变更摘要'}</summary><pre class="pre">${esc(JSON.stringify(item.data,null,2))}</pre></details></td></tr>`).join('')}</tbody></table></div>${data.items.length?'':empty('暂无匹配记录','调整筛选条件，后续操作会自动记录。')}</section>`;
}

function artifactsPage(data){
  PUI.artifactItems=data.items;
  const filters=PUI.artifactFilters;
  return `${pagehead('成果中心','查看和收藏当前授权范围内的报告与问答。','')}
  <form class="filters" data-artifact-form="filter"><input name="search" placeholder="搜索成果名称" value="${esc(filters.search||'')}" aria-label="搜索成果"><select name="project_id" aria-label="成果项目"><option value="">全部授权项目</option>${S.me.projects.map(p=>`<option value="${p.id}" ${filters.project_id===p.id?'selected':''}>${esc(p.name)}</option>`).join('')}</select><select name="type" aria-label="成果类型"><option value="">全部类型</option><option value="REPORT" ${filters.type==='REPORT'?'selected':''}>报告</option><option value="QUESTION" ${filters.type==='QUESTION'?'selected':''}>问答</option></select><select name="state" aria-label="成果状态"><option value="">全部状态</option>${["PUBLISHED","SUPERSEDED","IN_REVIEW","DRAFT","CHANGES_REQUESTED","APPROVED","SUPPORTED","INSUFFICIENT","CONFLICT"].map(v=>`<option value="${v}" ${filters.state===v?"selected":""}>${esc(statusNames[v]||v)}</option>`).join("")}</select><input name="author" aria-label="成果作者" placeholder="作者姓名" value="${esc(filters.author||'')}"><input type="date" name="date_from" aria-label="成果开始日期" value="${esc(filters.date_from||'')}"><input type="date" name="date_to" aria-label="成果结束日期" value="${esc(filters.date_to||'')}"><label class="check" style="margin:0;white-space:nowrap"><input name="bookmarked" type="checkbox" value="1" ${filters.bookmarked==='1'?'checked':''}>仅收藏</label><button type="submit">筛选</button></form>
  <section class="panel">${data.items.length?`<div class="tablewrap"><table><thead><tr><th>成果名称</th><th>项目</th><th>状态 / 版本</th><th>作者 / 创建时间</th><th></th></tr></thead><tbody>${data.items.map(item=>`<tr><td class="title"><a href="${item.url}" data-artifact-action="open" data-id="${item.id}">${esc(item.title)}</a><div class="sub">${item.type==='REPORT'?'进度报告':'引用问答'}</div></td><td>${esc(item.project_name)}</td><td>${tag(item.state)} <span class="sub">v${item.version}</span></td><td>${esc(item.author_name)}<div class="sub">${fmt(item.created_at)}</div></td><td><button class="text" data-artifact-action="bookmark" data-id="${item.id}">${item.bookmarked?'已收藏 · 取消':'收藏'}</button>${item.type==='REPORT'?` <button class="text" data-delivery-action="export" data-id="${item.id}" data-format="docx">Word</button> · <button class="text" data-delivery-action="export" data-id="${item.id}" data-format="md">Markdown</button> · <button class="text" data-delivery-action="export" data-id="${item.id}" data-format="pdf">PDF</button>`:''}</td></tr>`).join('')}</tbody></table></div>`:empty('暂无匹配成果','生成报告或完成问答后，会在这里保留成果入口。')}<div class="pagination"><span>共 ${data.total} 项 · 第 ${data.page} 页</span><button class="small" data-artifact-action="previous" ${data.page<=1?'disabled':''}>上一页</button><button class="small" data-artifact-action="next" ${data.page*data.page_size>=data.total?'disabled':''}>下一页</button></div></section>`;
}

pageModules.admin={title:'管理控制台',global:true,visible:()=>hasRole('enterprise_admin'),load:()=>api('/admin/overview'),render:adminPage};
pageModules.members={title:'项目与成员',visible:manager,async load(){const [members,settings]=await Promise.all([api('/projects/'+S.pid+'/members'),api('/projects/'+S.pid+'/settings')]);return {...members,settings};},render:membersPage};
pageModules.notifications={title:'待办与通知',global:true,async load(){const [todos,notices]=await Promise.all([api('/todos'),api('/notifications')]);return {todos:todos.items,notices:notices.items,unread:notices.unread};},render:inboxPage};
pageModules.audit={title:'审计记录',global:true,visible:()=>hasRole('audit'),load:()=>api('/admin/audit?'+new URLSearchParams(PUI.auditFilters)),render:auditPage};
pageModules.artifacts={title:'成果中心',global:true,load:()=>api('/artifacts?'+new URLSearchParams(PUI.artifactFilters)),render:artifactsPage};

function userEditor(user=null){
  PUI.editUser=user;
  kbDialog(user?'编辑成员账号':'新增成员账号',`<div class="formgrid"><div class="field"><label for="user-name">显示名</label><input id="user-name" name="name" value="${esc(user?.name||'')}" maxlength="100" required></div><div class="field"><label for="user-username">账号</label><input id="user-username" name="username" value="${esc(user?.username||'')}" ${user?'readonly':''} maxlength="40" required></div>${user?`<div class="field full"><label for="user-active">账号状态</label><select id="user-active" name="active"><option value="1" ${user.active?'selected':''}>启用</option><option value="0" ${!user.active?'selected':''}>停用（旧会话失效）</option></select></div>`:'<div class="field full"><label for="user-password">初始密码</label><input id="user-password" name="password" type="password" autocomplete="new-password" minlength="8" required></div>'}</div><div class="field"><label>系统角色（不自动授予项目内容权限）</label>${['enterprise_admin','operations','tool_admin','audit'].map(role=>`<label class="check"><input name="roles" type="checkbox" value="${role}" ${user?.roles.includes(role)?'checked':''}><span>${systemRoleName(role)}</span></label>`).join('')}</div>`,user?'保存账号':'创建账号','platform-user');
  const form=$('#dialog form');form.dataset.platformForm='user';delete form.dataset.kbForm;
}

function memberEditor(user=null,access=null){
  PUI.memberEndpoint=access?'/admin/projects/'+access.project_id+'/members':'/projects/'+S.pid+'/members';
  PUI.editMember=user;
  kbDialog('添加或调整项目成员',`<div class="field"><label for="member-user">成员</label><select id="member-user" name="user_id">${userOptions(access?.available_users||S.detail.available_users,user?.id)}</select></div><div class="field"><label for="member-role">项目角色</label><select id="member-role" name="role">${roleOptions(user?.role)}</select></div>`,'保存成员','platform-member');
  const form=$('#dialog form');form.dataset.platformForm='member';delete form.dataset.kbForm;
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-platform-action]');if(!button)return;
  const action=button.dataset.platformAction;
  try{
    button.disabled=true;
    if(action==='admin-tab'){PUI.tab=button.dataset.tab;shell(adminPage(S.detail));}
    else if(action==='new-user')userEditor();
    else if(action==='edit-user')userEditor(S.detail.users.find(u=>u.id===button.dataset.id));
    else if(action==='authorize-project'){const access=await api('/admin/projects/'+button.dataset.id+'/members');memberEditor(null,{...access,project_id:button.dataset.id});}
    else if(action==='add-member'||action==='edit-member')memberEditor(action==='edit-member'?S.detail.members.find(m=>m.id===button.dataset.id):null);
    else if(action==='new-project'){
      kbDialog('新建项目空间',`<div class="field"><label for="new-project-name">项目名称</label><input id="new-project-name" name="name" maxlength="100" required></div><div class="field"><label for="new-project-code">项目编号</label><input id="new-project-code" name="code" maxlength="40" required></div><div class="field"><label for="new-project-manager">项目经理</label><select id="new-project-manager" name="manager_id">${userOptions(S.detail.users,S.me.user.id)}</select></div><div class="field"><label for="new-project-description">说明</label><textarea id="new-project-description" name="description" maxlength="2000"></textarea></div>`,'创建项目','platform-project');
      const form=$('#dialog form');form.dataset.platformForm='new-project';delete form.dataset.kbForm;
    }else if(action==='enter-project'){
      S.pid=button.dataset.id;localStorage.setItem('eaw-project',S.pid);S.project=null;location.hash='#/overview';
    }else if(action==='project-status'){
      PUI.targetProject=await api('/projects/'+button.dataset.id);
      const p=PUI.targetProject.project;
      kbDialog(p.status==='ACTIVE'?'归档项目':'重新开启项目',`<p>${esc(p.name)}</p>${p.status==='ACTIVE'?'<label class="check"><input name="confirm_continue" type="checkbox" required><span>我已确认：归档后不能新增汇总或整改，已有未完成整改继续处理。</span></label>':'<p class="sub">重新开启后可继续维护台账和发起任务。</p>'}`,'确认操作','platform-project-status');
      const form=$('#dialog form');form.dataset.platformForm='project-status';delete form.dataset.kbForm;
    }else if(action==='remove-member'){
      PUI.removeMember=S.detail.members.find(m=>m.id===button.dataset.id);
      kbDialog('移出项目成员',`<p>${esc(PUI.removeMember.name)} 将失去此项目的访问权限。历史记录保留。</p><div class="field"><label for="member-successor">未完成事项移交人（有待办时必选）</label><select id="member-successor" name="transfer_to"><option value="">无未完成事项时可不选</option>${userOptions(S.detail.available_users.filter(u=>u.id!==PUI.removeMember.id))}</select></div>`,'确认移出','platform-remove-member');
      const form=$('#dialog form');form.dataset.platformForm='remove-member';delete form.dataset.kbForm;
    }else if(action==='transfer-review'){
      kbDialog('转交报告审核',`<div class="field"><label for="transfer-reviewer">新审核人</label><select id="transfer-reviewer" name="reviewer_id">${reviewers()}</select></div><div class="field"><label for="transfer-reason">转交原因</label><textarea id="transfer-reason" name="reason" required></textarea></div>`,'确认转交','platform-transfer');
      const form=$('#dialog form');form.dataset.platformForm='transfer-review';delete form.dataset.kbForm;
    }else if(action==='read-notice'){await api('/notifications/'+button.dataset.id+'/read',{});await refresh();}
    else if(action==='open-notice'){await api('/notifications/'+button.dataset.id+'/read',{});}
    else if(action==='export-audit'){
      const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([JSON.stringify(PUI.auditItems,null,2)],{type:'application/json'}));link.download='authorized-audit-records.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);
    }
  }catch(error){failure(error,$('#dialog').open?$('#dialog'):document);}
  finally{if(button.isConnected)button.disabled=false;}
});

document.addEventListener('submit',async event=>{
  const form=event.target,kind=form.dataset.platformForm;if(!kind)return;
  event.preventDefault();const b=Object.fromEntries(new FormData(form));const submit=form.querySelector('button[type=submit]');submit.disabled=true;
  try{
    if(kind==='user'){
      const payload={...b,roles:[...form.querySelectorAll('input[name=roles]:checked')].map(x=>x.value)};
      if(PUI.editUser){payload.expected_version=PUI.editUser.version;payload.active=b.active==='1';await api('/admin/users/'+PUI.editUser.id,payload);}
      else await api('/admin/users',payload);
      toast('成员账号已保存');
    }else if(kind==='member'){await api(PUI.memberEndpoint,b);toast('项目成员已保存');}
    else if(kind==='new-project'){await api('/projects',b);toast('项目空间已创建');}
    else if(kind==='project-status'){
      const p=PUI.targetProject.project;
      await api('/projects/'+p.id+'/status',{expected_version:p.version,status:p.status==='ACTIVE'?'ARCHIVED':'ACTIVE',confirm_continue:b.confirm_continue==='on'});toast('项目状态已更新');
    }else if(kind==='remove-member'){await api('/projects/'+S.pid+'/members/'+PUI.removeMember.id+'/remove',b);toast('成员已移出，事项按确认结果移交');}
    else if(kind==='transfer-review'){await api('/approvals/'+S.detail.approval.id+'/transfer',{...b,expected_version:S.detail.approval.version});toast('审核已转交，旧页面不能继续决策');}
    else if(kind==='project-settings'){await api('/projects/'+S.pid+'/settings',{...b,expected_version:S.detail.settings.project.version});S.dirty=false;toast('项目信息已保存');await refresh();return;}
    else if(kind==='audit-filter'){PUI.auditFilters=b;await refresh();return;}
    closeModal();S.dirty=false;await refresh();
  }catch(error){failure(error,form);}
  finally{if(submit.isConnected)submit.disabled=false;}
});
document.addEventListener('change',event=>{
  if(event.target.id==='project-switch'){
    if(S.dirty&&!window.confirm('有尚未提交的内容，确认切换项目？')){event.target.value=S.pid;return;}
    S.pid=event.target.value;S.project=null;S.dirty=false;localStorage.setItem('eaw-project',S.pid);KB.library='';location.hash='#/overview';refresh();
  }
});
document.addEventListener('input',event=>{if(event.target.closest('[data-platform-form]'))S.dirty=true;});
document.addEventListener('click',async event=>{
  const target=event.target.closest('[data-artifact-action]');if(!target)return;
  const action=target.dataset.artifactAction;
  try{
    if(action==='open'){
      const item=PUI.artifactItems.find(x=>x.id===target.dataset.id);
      S.pid=item.project_id;localStorage.setItem('eaw-project',S.pid);return;
    }
    target.disabled=true;
    if(action==='bookmark'){
      const item=PUI.artifactItems.find(x=>x.id===target.dataset.id);
      await api('/bookmarks',{object_id:item.id,object_type:item.type,bookmarked:!item.bookmarked});
    }else PUI.artifactFilters.page=Number(PUI.artifactFilters.page||1)+(action==='next'?1:-1);
    await refresh();
  }catch(error){toast(error.message);}
  finally{if(target.isConnected)target.disabled=false;}
});
document.addEventListener('submit',async event=>{
  const form=event.target;if(!form.dataset.artifactForm)return;
  event.preventDefault();PUI.artifactFilters={...Object.fromEntries(new FormData(form)),page:1};await refresh();
});

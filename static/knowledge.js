'use strict';
Object.assign(statusNames,{UPLOADED:'等待解析',PARSING:'正在解析',INDEXING:'建立索引',AVAILABLE:'可检索',SUPPORTED:'依据充分',INSUFFICIENT:'依据不足',CONFLICT:'资料存在冲突'});
Object.assign(colors,{UPLOADED:'orange',PARSING:'blue',INDEXING:'blue',AVAILABLE:'green',SUPPORTED:'green',INSUFFICIENT:'orange',CONFLICT:'red'});
const canManageKnowledge=()=>['manager','knowledge_admin'].includes(S.project?.project?.role);
const KB={library:'',data:null,documentId:null,uploadKeys:{}};

function kbDialog(title,body,label,kind){
  modal(title,`<form data-kb-form="${kind}">${body}<div class="inline-error"></div><div class="footer">${cancelButton}<button class="primary" type="submit">${esc(label)}</button></div></form>`);
}

async function showKnowledgeEvidence(id){
  const ev=await api('/evidence/'+encodeURIComponent(id));
  modal('引用来源',`<div class="actions"><span class="tag blue">文档证据</span><span class="sub">${esc(ev.version)}</span></div><h3 style="margin-top:18px">${esc(ev.title)}</h3><p class="sub">${esc(ev.filename)} · ${esc(ev.locator)}</p><div class="pre source-excerpt">${esc(ev.text)}</div>${ev.parent_text?`<details><summary>查看父段上下文${ev.parent_truncated?'（已截取，完整内容见来源）':''}</summary><div class="pre source-excerpt">${esc(ev.parent_text)}</div></details>`:''}<p class="sub">引用绑定该文档版本，访问时重新检查当前权限。</p><a href="#/knowledge/${ev.document_id}/${ev.document_version}" data-kb-action="open-source">打开来源 v${ev.document_version} →</a>`,'<button type="button" data-action="close">关闭</button>');
}

function knowledgeHome(data){
  KB.data=data;
  const documents=data.documents.filter(d=>!KB.library||d.library_id===KB.library);
  return `${pagehead('知识中心','管理项目依据，让问答与报告可以追溯到原文。',canManageKnowledge()?'<a class="button" href="#/libraries">知识库设置</a><a class="button" href="#/retrieval">检索参数</a><button data-kb-action="new-library">'+icon('plus')+'新建知识库</button><button class="primary" data-kb-action="upload">'+icon('plus')+'上传资料</button>':'')}
  <div class="knowledge-summary"><div><strong>${data.libraries.length}</strong><span>知识库</span></div><div><strong>${data.documents.length}</strong><span>授权资料</span></div><div><strong>${data.documents.filter(d=>d.available).length}</strong><span>可检索资料</span></div><div><strong>本地</strong><span>关键词检索与原文摘录</span></div></div>
  <div class="library-grid">${data.libraries.map(lib=>`<button class="library-card ${KB.library===lib.id?'selected':''}" data-kb-action="filter-library" data-id="${lib.id}"><span class="library-mark">${icon('ledger')}</span><strong>${esc(lib.name)}</strong><span class="sub">${esc(lib.description||'项目资料')}</span><span class="sub">${lib.document_count} 份授权资料</span></button>`).join('')}</div>
  <section class="panel"><div class="panelhead"><div class="actions"><h2>${KB.library?'当前知识库资料':'全部项目资料'}</h2>${KB.library?'<button class="text" data-kb-action="filter-library" data-id="">查看全部</button>':''}</div><a href="#/questions">使用资料提问 →</a></div>
  ${documents.length?`<div class="tablewrap"><table><thead><tr><th>资料名称</th><th>可用版本</th><th>最新处理状态</th><th>访问范围</th><th>更新时间</th><th></th></tr></thead><tbody>${documents.map(doc=>`<tr><td class="title"><a href="#/knowledge/${doc.id}">${esc(doc.title)}</a><div class="sub">${esc(doc.topic)} · ${esc(doc.filename)}</div></td><td>${doc.active_version?'v'+doc.active_version:'尚不可用'}</td><td>${tag(doc.latest_status)}${doc.latest_version!==doc.active_version&&doc.active_version?`<div class="sub">保留可用 v${doc.active_version}</div>`:''}</td><td>${doc.acl_mode==='PROJECT'?'项目成员':'指定成员'}</td><td>${fmt(doc.updated_at)}</td><td><a href="#/knowledge/${doc.id}">查看 →</a></td></tr>`).join('')}</tbody></table></div>`:empty('暂无可见资料','上传项目说明、会议纪要或验收标准，再开始引用问答。')}</section>
  <div class="notice">${icon('info')}<span>内置资料为虚构演示内容。文件经过解析、索引后才可检索；扫描 PDF 需先 OCR。当前为本地关键词检索与原文摘录，未调用 LLM。</span></div>`;
}

function knowledgeDocument(doc){
  const current=doc.current,latest=doc.versions[0];
  return `<a class="back" href="#/knowledge">${icon('back')}知识中心</a>${pagehead(doc.title,doc.topic,`<button data-action="refresh">${icon('refresh')}刷新</button>${canManageKnowledge()?'<a class="button" href="#/fragments/'+doc.id+'/'+doc.current.version+'">片段权限</a><button data-kb-action="acl">访问权限</button><button class="primary" data-kb-action="upload-version">上传新版本</button>':''}`)}
  <div class="reportlayout"><section class="panel"><div class="panelhead"><div class="actions"><h2>资料正文</h2>${tag(current.status)}</div><select class="compact-select" data-kb-version="${doc.id}" aria-label="选择资料版本">${doc.versions.map(v=>`<option value="${v.version}" ${v.version===current.version?'selected':''}>v${v.version} · ${statusNames[v.status]||v.status}${v.version===doc.active_version?' · 当前可用':''}</option>`).join('')}</select></div><div class="panelbody">
  ${current.status==='AVAILABLE'?`<div class="versionnote">${current.partial_access?'当前仅展示本人授权片段，其余正文不提供。 ' :''}正在查看 v${current.version}${current.version!==doc.active_version?'，这是历史版本。':'，这是当前可用版本。'} 引用保持原版本，访问使用当前授权。</div>${current.pages.map(p=>`<section class="document-page"><h3>${esc(p.anchor)}</h3><div class="document-text">${esc(p.text)}</div></section>`).join('')}`:`<div class="empty">${icon('ledger')}<h3>${statusNames[current.status]||current.status}</h3><p>${esc(doc.versions.find(v=>v.version===current.version)?.error_message||'文件已保存，服务端正在处理。')}</p>${canManageKnowledge()&&current.status==='FAILED'?'<button data-kb-action="retry-document">重试此版本</button>':''}</div>`}</div></section>
  <aside><section class="panel"><div class="panelhead"><h2>版本与授权</h2></div><div class="panelbody"><dl class="keyvalues"><dt>资料 ID</dt><dd class="mono">${esc(doc.id)}</dd><dt>当前可用</dt><dd>${doc.active_version?'v'+doc.active_version:'无'}</dd><dt>最新上传</dt><dd>v${latest.version} · ${tag(latest.status)}</dd><dt>生效日期</dt><dd>${esc(latest.effective_from)}</dd><dt>失效日期</dt><dd>${esc(latest.effective_to||'未设置')}</dd><dt>访问范围</dt><dd>${doc.acl_mode==='PROJECT'?'当前项目成员':doc.acl.map(person).map(esc).join('、')}</dd><dt>内容哈希</dt><dd class="mono">${esc(latest.content_hash)}</dd></dl></div></section>
  <section class="panel"><div class="panelhead"><h2>处理记录</h2></div><div class="panelbody">${doc.attempts.length?[...doc.attempts].reverse().map(a=>`<div class="activity"><strong>${a.stage==='PARSE'?'文本解析':'建立索引'} · 第 ${a.attempt} 次</strong><p>${esc(a.summary)}</p><span class="sub">${fmt(a.started_at)}</span></div>`).join(''):'<p class="sub">已进入处理队列</p>'}</div></section>${canManageKnowledge()?'<button class="danger" data-kb-action="remove-document">下架资料</button>':''}</aside></div>`;
}

function questionResult(q){
  if(!q)return `<div class="qa-welcome">${icon('info')}<h2>先找到依据，再判断行动</h2><p class="muted">试着询问验收要求、项目阻塞项或审核流程。</p><div class="question-prompts">${['这个项目的验收标准是什么？','验收环境联调为什么滞后？','报告审核通过后会自动创建整改吗？'].map(question=>`<button data-kb-action="prompt-question" data-question="${esc(question)}">${esc(question)} ${icon('arrow')}</button>`).join('')}</div></div>`;
  const d=q.data;
  let answer;
  if(['QUEUED','RUNNING'].includes(q.state))answer='<div class="loading">正在检索当前授权资料…</div><button data-kb-action="stop-question">停止生成</button>';
  else if(q.state==='CANCELLED')answer='<div class="notice">此次问答已停止，未生成完整答案。</div>';
  else if(q.state==='FAILED')answer=`<div class="error">${esc(d.error?.message||'检索失败，请稍后重试')}<div class="mono">${esc(d.error?.trace_id||q.id)}</div></div>`;
  else answer=`<div class="statusline">${tag(q.answer_status)}<span class="sub">${esc(d.interpretation)}</span></div><p class="qa-summary">${esc(d.answer)}</p>${q.answer_status==='CONFLICT'?'<div class="notice warning">不同有效资料对相同事项有不同表述，需确认适用版本。系统未自行选择其中一份作为定论。</div>':''}
    ${d.facts?.length?`<h3>资料事实</h3>${d.facts.map(f=>`<blockquote class="fact-quote"><div>${esc(f.text)}</div><div class="actions">${f.evidence_ids.map(ev=>`<button class="text" data-kb-action="citation" data-id="${ev}">${esc(ev)} ↗</button>`).join('')}</div></blockquote>`).join('')}`:''}
    <h3>归纳解释</h3><p class="sub">当前回答依据授权资料原文，具体适用性请结合项目范围、生效日期与引用版本核对。</p>${d.suggestions?.length?`<h3>建议动作</h3><ul class="gaps">${d.suggestions.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}${d.missing_information?.length?`<h3>信息缺口</h3><ul class="gaps">${d.missing_information.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}
    ${d.evidence?.length?`<h3>引用来源</h3><div class="citation-grid">${d.evidence.map(ev=>`<button class="citation-card" data-kb-action="citation" data-id="${ev.evidence_id}"><strong>${esc(ev.title)}</strong><span>${esc(ev.version)} · ${esc(ev.locator)}</span></button>`).join('')}</div>`:''}
    <div class="feedback-row"><span class="sub">这次回答是否有帮助？</span>${[['HELPFUL','有帮助'],['WRONG_ANSWER','答案有误'],['WRONG_CITATION','引用不对'],['OUTDATED','信息过期'],['OTHER','其他']].map(([kind,label])=>`<button class="small" data-kb-action="feedback" data-kind="${kind}">${label}</button>`).join('')}</div>`;
  return `<div class="asked-question"><span class="sub">你的问题 · 当前会话第 ${d.turn||1} 轮</span><h3>${esc(q.question)}</h3>${d.parent_question_id?`<p class="sub">追问上轮：${esc(d.previous_question)} <a href="#/questions/${d.parent_question_id}">查看上轮 →</a></p>`:''}</div>${answer}`;
}

function questionPage(data,id){
  const active=['QUEUED','RUNNING'].includes(data.current?.state);
  return `${pagehead('引用问答','在当前授权的项目资料中查找依据。','<a href="#/knowledge">管理项目资料 →</a>')}
  <div class="qa-layout"><aside class="panel qa-history"><div class="panelhead"><h2>问答历史</h2><a href="#/questions">新问题</a></div><div class="qa-history-items">${data.history.map(item=>`<a class="question-history-item ${item.id===id?'active':''}" href="#/questions/${item.id}"><strong>${esc(item.question)}</strong><span class="sub">${fmt(item.created_at)} · ${esc(statusNames[item.answer_status]||statusNames[item.state]||item.state)}</span></a>`).join('')||'<div class="panelbody sub">提问后会保留问题、回答与引用。</div>'}</div></aside>
  <section class="panel qa-main"><div class="panelhead"><h2>项目资料助手</h2><span class="tag blue">本地检索 · 原文摘录</span></div><div class="panelbody qa-answer">${questionResult(data.current)}</div>
  <form class="qa-composer" data-kb-form="ask"><label for="qa-question">输入问题</label><textarea id="qa-question" name="question" maxlength="4000" required placeholder="例如：项目验收需要哪些证据？"></textarea>${data.current?.state==='COMPLETED'?'<label class="check"><input name="followup" type="checkbox" checked>作为追问，结合本项目上轮问题重新检索资料</label>':''}<div class="qa-composer-footer"><select name="library_id" aria-label="提问知识范围"><option value="">全部授权项目资料</option>${data.libraries.map(lib=>`<option value="${lib.id}">${esc(lib.name)}</option>`).join('')}</select><span class="sub">事实附出处 · 权限由服务端检查</span><button class="primary" type="submit" ${active?'disabled':''}>查找依据 ${icon('arrow')}</button></div><div class="inline-error"></div></form></section></div>`;
}

pageModules.knowledge={
  async load(id,version){return id?api('/documents/'+id+(version?'?version='+version:'')):api('/projects/'+S.pid+'/knowledge');},
  render(data,id){return id?knowledgeDocument(data):knowledgeHome(data);},
  isActive(data){return data.documents?data.documents.some(d=>['UPLOADED','PARSING','INDEXING'].includes(d.latest_status)):data.versions.some(v=>['UPLOADED','PARSING','INDEXING'].includes(v.status));}
};
pageModules.questions={
  async load(id){
    const [history,knowledge,current]=await Promise.all([api('/projects/'+S.pid+'/questions'),api('/projects/'+S.pid+'/knowledge'),id?api('/questions/'+id):Promise.resolve(null)]);
    return {history:history.items,libraries:knowledge.libraries,current};
  },
  render:questionPage,
  isActive(data){return ['QUEUED','RUNNING'].includes(data.current?.state);}
};

async function openUpload(version=false){
  KB.documentId=version?S.detail.id:null;
  KB.uploadKeys={};
  const data=await api('/projects/'+S.pid+'/knowledge');
  if(!data.libraries.length)throw new Error('请先新建知识库');
  kbDialog(version?'上传资料新版本':'上传项目资料',`${version?`<div class="notice">当前可用 v${S.detail.active_version||'—'} 在新版本索引成功前继续使用。</div>`:`<div class="field"><label for="upload-library">所属知识库</label><select id="upload-library" name="library_id">${data.libraries.map(lib=>`<option value="${lib.id}">${esc(lib.name)}</option>`).join('')}</select></div><div class="field"><label for="upload-topic">资料主题</label><input id="upload-topic" name="topic" value="项目资料" maxlength="100" required></div>`}
  <div class="field"><label for="knowledge-files">选择文件</label><input id="knowledge-files" type="file" accept=".txt,.md,.docx,.pdf" ${version?'':'multiple'} required><small>支持 TXT / Markdown / DOCX / PDF；每文件最多 50 MB，每批最多 20 个。新文件默认仅上传者可读，配置资料/片段权限后再共享。</small></div><div class="formgrid"><div class="field"><label for="effective-from">生效日期</label><input id="effective-from" name="effective_from" type="date" value="${S.me.today}" required></div><div class="field"><label for="effective-to">失效日期（选填）</label><input id="effective-to" name="effective_to" type="date"></div></div><div id="upload-progress" class="sub"></div>`,'上传并处理','upload');
}

async function encodeFile(file){
  const bytes=new Uint8Array(await file.arrayBuffer()),parts=[];
  for(let i=0;i<bytes.length;i+=32768)parts.push(String.fromCharCode(...bytes.subarray(i,i+32768)));
  return btoa(parts.join(''));
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-kb-action]');
  if(!button)return;
  const action=button.dataset.kbAction;
  try{
    if(action==='open-source'){closeModal();return;}
    button.disabled=true;
    if(action==='new-library')kbDialog('新建知识库','<div class="field"><label for="library-name">名称</label><input id="library-name" name="name" maxlength="100" required></div><div class="field"><label for="library-description">说明</label><textarea id="library-description" name="description" maxlength="2000"></textarea></div>','创建知识库','library');
    else if(action==='upload'||action==='upload-version')await openUpload(action==='upload-version');
    else if(action==='filter-library'){KB.library=button.dataset.id;shell(knowledgeHome(KB.data));}
    else if(action==='citation')await showKnowledgeEvidence(button.dataset.id);
    else if(action==='prompt-question'){$('#qa-question').value=button.dataset.question;$('#qa-question').focus();}
    else if(action==='stop-question'){const q=S.detail.current;await api('/questions/'+q.id+'/cancel',{expected_version:q.version});await refresh();}
    else if(action==='feedback'){
      KB.feedbackKind=button.dataset.kind;
      if(KB.feedbackKind==='HELPFUL'){await api('/questions/'+S.detail.current.id+'/feedback',{kind:'HELPFUL',comment:'',event_key:key()});toast('感谢反馈，已保存');}
      else kbDialog('反馈资料问题','<div class="field"><label for="feedback-comment">补充说明（选填）</label><textarea id="feedback-comment" name="comment" maxlength="2000" placeholder="指出具体问题或对应资料，便于维护者修正"></textarea></div>','提交反馈','feedback');
    }else if(action==='retry-document'){
      await api('/documents/'+S.detail.id+'/retry',{expected_version:S.detail.version,document_version:S.detail.current.version});toast('已重新加入处理队列');await refresh();
    }else if(action==='remove-document')kbDialog('下架资料',`<p>下架后停止检索与原文访问，依赖该资料的历史问答和报告也会受限制。</p><div class="notice warning">${esc(S.detail.title)} · 所有版本</div>`,'确认下架','remove');
    else if(action==='acl'){
      const doc=S.detail;
      kbDialog('资料访问权限',`<div class="field"><label for="acl-mode">授权方式</label><select id="acl-mode" name="acl_mode"><option value="PROJECT" ${doc.acl_mode==='PROJECT'?'selected':''}>当前项目成员</option><option value="MEMBERS" ${doc.acl_mode==='MEMBERS'?'selected':''}>仅指定成员</option></select></div><div class="field"><label>指定成员</label>${S.project.members.map(m=>`<label class="check"><input type="checkbox" name="members" value="${m.id}" ${doc.acl_mode==='PROJECT'||doc.acl.includes(m.id)?'checked':''}><span>${esc(m.name)} · ${roleName(m.role)}</span></label>`).join('')}</div><div class="notice warning">取消自己的授权后，将无法查看正文及依赖它的报告。</div>`,'保存权限','acl');
    }
  }catch(error){failure(error,$('#dialog').open?$('#dialog'):document);}
  finally{if(button.isConnected)button.disabled=false;}
});

document.addEventListener('submit',async event=>{
  const form=event.target,kind=form.dataset.kbForm;
  if(!kind)return;
  event.preventDefault();
  const fields=Object.fromEntries(new FormData(form));
  const submit=form.querySelector('button[type=submit]');
  submit.disabled=true;
  try{
    if(kind==='library'){await api('/projects/'+S.pid+'/libraries',fields);toast('知识库已创建');}
    else if(kind==='upload'){
      const files=[...$('#knowledge-files').files];
      if(!files.length||files.length>20)throw new Error('请选择 1～20 个文件');
      if(KB.documentId&&files.length!==1)throw new Error('每次只能上传一个新版本');
      const results=[];
      for(let i=0;i<files.length;i++){
        const file=files[i];
        $('#upload-progress').textContent=`正在保存第 ${i+1}/${files.length} 个文件：${file.name}`;
        try{
          if(file.size>50*1024*1024)throw new Error('文件超过 50 MB');
          const fileKey=file.name+':'+file.lastModified+':'+file.size;
          KB.uploadKeys[fileKey]??=key();
          const payload={...fields,filename:file.name,content_base64:await encodeFile(file),event_key:KB.uploadKeys[fileKey]};
          if(KB.documentId){payload.expected_version=S.detail.version;await api('/documents/'+KB.documentId+'/versions',payload);}
          else await api('/projects/'+S.pid+'/documents',payload);
          results.push(file.name+'：已保存，等待处理');
        }catch(error){results.push(file.name+'：'+error.message);}
      }
      S.dirty=false;
      modal('文件提交结果',`<div class="pre">${esc(results.join('\n'))}</div><p class="sub">解析和索引在服务端继续执行，可在资料列表查看结果。</p>`,'<button type="button" data-action="close">关闭</button>');
      await refresh();return;
    }else if(kind==='ask'){
      const payload={project_id:S.pid,question:fields.question,submission_key:key()};
      if(fields.library_id)payload.library_ids=[fields.library_id];
      if(fields.followup==='on'&&S.detail.current)payload.parent_question_id=S.detail.current.id;
      const result=await api('/questions',payload);S.dirty=false;location.hash='#/questions/'+result.id;return;
    }else if(kind==='feedback'){
      await api('/questions/'+S.detail.current.id+'/feedback',{kind:KB.feedbackKind,comment:fields.comment,event_key:key()});toast('反馈已保存');
    }else if(kind==='acl'){
      const members=[...form.querySelectorAll('input[name=members]:checked')].map(x=>x.value);
      await api('/documents/'+S.detail.id+'/acl',{expected_version:S.detail.version,acl_mode:fields.acl_mode,members});toast('授权已更新');
    }else if(kind==='remove'){
      await api('/documents/'+S.detail.id+'/remove',{expected_version:S.detail.version});closeModal();S.dirty=false;location.hash='#/knowledge';toast('资料已下架');return;
    }
    closeModal();S.dirty=false;await refresh();
  }catch(error){failure(error,form);}
  finally{if(submit.isConnected)submit.disabled=false;}
});
document.addEventListener('change',event=>{if(event.target.matches('[data-kb-version]'))location.hash='#/knowledge/'+event.target.dataset.kbVersion+'/'+event.target.value;});
document.addEventListener('input',event=>{if(event.target.closest('[data-kb-form]'))S.dirty=true;});

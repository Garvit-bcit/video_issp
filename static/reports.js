const $=id=>document.getElementById(id),csrf=document.querySelector('meta[name=csrf-token]')?.content||'';
const params=new URLSearchParams(location.search);let selected=params.get('video'),videos=[],docs=[],editingReport=null,editingContent=null;
async function api(url,method='GET'){const r=await fetch(url,{method,headers:{'X-CSRF-Token':csrf}});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.error||`Request failed (${r.status})`);return d}

// Reuse a saved transcript; otherwise transcribe and wait before generating output.
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function ensureTranscript(videoId, notify){
  const path=`/api/videos/${encodeURIComponent(videoId)}`;
  let video=await api(path);
  if((video.steps||[]).some(s=>s.kind==='transcript'))return;
  if(video.status!=='transcribing'){
    notify('Preparing transcript automatically. This may take several minutes…');
    await api(`${path}/transcribe`,'POST');
  }
  const deadline=Date.now()+30*60*1000;
  while(Date.now()<deadline){
    notify('Transcribing video automatically…');
    await sleep(3000);
    video=await api(path);
    if(video.status==='failed')throw Error(video.error||'Automatic transcription failed.');
    if((video.steps||[]).some(s=>s.kind==='transcript') && video.status!=='transcribing')return;
    if(video.status!=='transcribing')throw Error('Transcription completed without usable text. Check the video audio.');
  }
  throw Error('Transcription is taking longer than 30 minutes. Check the video status and retry.');
}
function status(s,err=false){$('generationStatus').textContent=s;$('generationStatus').className='inline-message'+(err?' error':'')}
function busy(on){$('generationProgress').hidden=!on;$('progressNote').hidden=!on;$('generateSop').disabled=on||!selected}
function library(){const q=$('videoSearch').value.trim().toLowerCase();$('videoNavigation').replaceChildren();for(const v of videos.filter(x=>x.title.toLowerCase().includes(q))){const a=document.createElement('a');a.href=`/reports?video=${encodeURIComponent(v.id)}`;a.className='result-video-link'+(v.id===selected?' active':'');a.textContent=v.title;$('videoNavigation').append(a)}if(!$('videoNavigation').children.length)$('videoNavigation').textContent='No matching videos.'}
function render(){const el=$('documentsList'),q=$('documentSearch').value.trim().toLowerCase();el.replaceChildren();const matching=docs.filter(d=>(!selected||d.video_id===selected)&&(d.title+' '+(videos.find(v=>v.id===d.video_id)?.title||'')).toLowerCase().includes(q));if(!matching.length){el.textContent='No SOP documents found.';return}for(const d of matching){const card=document.createElement('article');card.className='document-card';const info=document.createElement('div');const h=document.createElement('h3');h.textContent=d.title;const meta=document.createElement('p');meta.className='muted';meta.textContent=(videos.find(v=>v.id===d.video_id)?.title||'Video')+' · Updated '+new Date(d.updated_at).toLocaleString();info.append(h,meta);const controls=document.createElement('div');controls.className='button-row';const view=document.createElement('button');view.className='secondary';view.textContent='Preview';view.onclick=()=>preview(d);const pdf=document.createElement('a');pdf.className='button-link primary';pdf.href=`/api/reports/${d.id}/pdf`;pdf.textContent='Download PDF';const del=document.createElement('button');del.className='secondary';del.textContent='Delete';del.onclick=async()=>{if(!confirm('Delete this SOP?'))return;try{await api(`/api/reports/${d.id}`,'DELETE');await reload();$('documentDetail').hidden=true;$('sopEditor').hidden=true}catch(e){status(e.message,true)}};const edit=document.createElement('button');edit.className='secondary';edit.textContent='Edit SOP';edit.onclick=()=>openEditor(d);controls.append(view,edit,pdf,del);card.append(info,controls);el.append(card)}}
async function reload(){docs=await api('/api/reports');render()}
async function preview(d){try{const r=await api(`/api/reports/${d.id}`);const c=r.content;$('detailTitle').textContent=d.title;const holder=$('documentPreview');holder.replaceChildren();for(const [heading,value] of [['Overview',c.overview],['Purpose',c.purpose],['Prerequisites',(c.prerequisites||[]).join('\n')],['Warnings',(c.warnings||[]).join('\n')],['Expected outcome',c.outcome],['Summary',c.summary]]){if(!value)continue;const section=document.createElement('section');const h=document.createElement('h3');h.textContent=heading;const p=document.createElement('p');p.textContent=value;section.append(h,p);holder.append(section)}for(const [i,s] of (c.steps||[]).entries()){const section=document.createElement('section');const h=document.createElement('h3');h.textContent=`${i+1}. ${s.title||'Step'}`;const p=document.createElement('p');p.textContent=s.description||'';section.append(h,p);holder.append(section)}$('downloadPdf').href=`/api/reports/${d.id}/pdf`;$('sopEditor').hidden=true;$('documentDetail').hidden=false;$('documentDetail').scrollIntoView({behavior:'smooth',block:'start'})}catch(e){status(e.message,true)}}
async function generate(){if(!selected)return;if(docs.some(d=>d.video_id===selected)){status('SOP already exists. Preview it below.');return;}busy(true);status('Generating SOP from the selected video transcript…');try{await ensureTranscript(selected,t=>status(t));status('Generating SOP from the transcript…');await api(`/api/videos/${encodeURIComponent(selected)}/report/generate`,'POST');await reload();await updateSopButton();status('SOP generated successfully. Select Preview or Download PDF.');}catch(e){status(e.message,true)}finally{busy(false)}}
async function updateSopButton(){const exists=docs.some(d=>d.video_id===selected);$('generateSop').textContent=exists?'View existing SOP':'Generate SOP';$('generateSop').onclick=exists?()=>{$('documentsList').scrollIntoView({behavior:'smooth'})}:generate}

// Edit a copy of the full document so unmodified AI fields are preserved.
function editorField(label, value, onChange, multiline=false){
  const wrap=document.createElement('label');wrap.className='sop-edit-field';
  const name=document.createElement('span');name.textContent=label;
  const input=document.createElement(multiline?'textarea':'input');
  if(multiline)input.rows=3;else input.type='text';
  input.value=value==null?'':String(value);
  input.addEventListener('input',()=>onChange(input.value));
  wrap.append(name,input);return wrap;
}
function editStep(index){
  const step=editingContent.steps[index],box=document.createElement('section');
  box.className='sop-edit-step';
  const heading=document.createElement('div');heading.className='section-heading';
  const title=document.createElement('h3');title.textContent=`Step ${index+1}`;
  const remove=document.createElement('button');remove.type='button';remove.className='secondary';remove.textContent='Delete step';
  remove.onclick=()=>{editingContent.steps.splice(index,1);renderEditorSteps()};
  heading.append(title,remove);box.append(heading);
  for(const [label,key,multi] of [['Title','title',false],['Timestamp (MM:SS)','timestamp',false],['Instructions','description',true],['Notes','notes',true],['Expected result','expected_result',true]]){
    box.append(editorField(label,step[key],value=>{
      step[key]=value;
      if(key==='description')step.detail=value;
      if(key==='expected_result')step.value=value;
    },multi));
  }
  const review=document.createElement('label');review.className='sop-review-toggle';
  const check=document.createElement('input');check.type='checkbox';check.checked=!!step.requires_review;
  check.onchange=()=>{step.requires_review=check.checked};
  review.append(check,document.createTextNode('Requires human review'));box.append(review);
  return box;
}
function renderEditorSteps(){
  const holder=$('sopEditorSteps');holder.replaceChildren();
  editingContent.steps.forEach((_,i)=>holder.append(editStep(i)));
}
async function openEditor(doc){
  try{
    const report=await api(`/api/reports/${doc.id}`);
    editingReport=doc.id;editingContent=structuredClone(report.content);
    if(!Array.isArray(editingContent.steps))editingContent.steps=[];
    $('sopEditorTitle').textContent=`Edit: ${doc.title}`;
    $('sopEditorFields').replaceChildren();
    for(const [label,key,multi] of [['Document title','document_title',false],['Overview','overview',true],['Purpose','purpose',true],['Expected outcome','outcome',true],['Summary','summary',true]]){
      $('sopEditorFields').append(editorField(label,editingContent[key],value=>editingContent[key]=value,multi));
    }
    for(const [label,key] of [['Prerequisites (one per line)','prerequisites'],['Warnings (one per line)','warnings']]){
      $('sopEditorFields').append(editorField(label,(editingContent[key]||[]).join('\n'),value=>editingContent[key]=value.split('\n').map(x=>x.trim()).filter(Boolean),true));
    }
    renderEditorSteps();$('documentDetail').hidden=true;$('sopEditor').hidden=false;
    $('sopEditor').scrollIntoView({behavior:'smooth',block:'start'});
  }catch(e){status(e.message,true)}
}
$('addSopStep').onclick=()=>{
  editingContent.steps.push({title:'New step',timestamp:'00:00',description:'',detail:'',notes:'',expected_result:'',value:'',verify:'',requires_review:false});
  renderEditorSteps();
};
$('cancelSopEdit').onclick=()=>{$('sopEditor').hidden=true;editingReport=null;editingContent=null};
$('saveSopEdit').onclick=async()=>{
  if(!editingReport||!editingContent)return;
  if(!editingContent.steps.length){status('Add at least one SOP step before saving.',true);return}
  if(editingContent.steps.some(s=>!String(s.title||'').trim())){status('Every SOP step needs a title.',true);return}
  const btn=$('saveSopEdit');btn.disabled=true;
  try{
    const r=await fetch(`/api/reports/${editingReport}`,{
      method:'PUT',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
      body:JSON.stringify({content:editingContent})
    });
    const result=await r.json().catch(()=>({}));
    if(!r.ok)throw Error(result.error||`Save failed (${r.status})`);
    const savedId=editingReport;$('sopEditor').hidden=true;editingReport=null;editingContent=null;
    await reload();status('SOP changes saved. The PDF will include your edits.');
    const doc=docs.find(d=>d.id===savedId);if(doc)await preview(doc);
  }catch(e){status(e.message,true)}finally{btn.disabled=false}
};

$('generateSop').onclick=generate;$('videoSearch').addEventListener('input',library);$('documentSearch').addEventListener('input',render);$('closeDetail').onclick=()=>$('documentDetail').hidden=true;
(async()=>{try{videos=await api('/api/videos');if(!videos.some(v=>v.id===selected))selected=null;library();$('selectedVideoTitle').textContent=videos.find(v=>v.id===selected)?.title||'Select a video';busy(false);await reload();if(selected){await updateSopButton();status('Ready to generate or review SOP documents.');if(params.get('generate')==='1'){history.replaceState(null,'',`/reports?video=${encodeURIComponent(selected)}`);await generate()}}}catch(e){status(e.message,true)}})();

let selected=null, currentSteps=[], editing=null, timer=null;
const $=id=>document.getElementById(id);
const format=s=>{let n=Math.floor(Number(s)||0);return `${String(Math.floor(n/60)).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`};
async function api(url,opts={}){const r=await fetch(url,opts);let data=await r.json().catch(()=>({}));if(!r.ok)throw Error(data.error||`Request failed: ${r.status}`);return data}
async function list(){
 const videos=await api('/api/videos');
 $('videoList').replaceChildren();
 for(const v of videos){
  const row=document.createElement('div');
  row.className='videoRow';
  const open=document.createElement('button');
  open.className='videoChoice'+(v.id===selected?' selected':'');
  open.textContent=v.title+' · '+format(v.duration);
  open.onclick=()=>openVideo(v.id);
  const remove=document.createElement('button');
  remove.className='secondary deleteVideo';
  remove.textContent='Delete';
  remove.title='Delete this video and its saved instructions';
  remove.onclick=async()=>{
   if(!confirm(`Delete "${v.title}" and all its saved instructions? This cannot be undone.`))return;
   remove.disabled=true;
   try{
    await api('/api/videos/'+v.id,{method:'DELETE'});
    if(selected===v.id){
     selected=null;currentSteps=[];clearTimeout(timer);
     $('videoTitle').textContent='Select or upload a video';
     $('status').textContent='Create a project by uploading a recording.';
     $('player').pause();$('player').removeAttribute('src');$('player').load();
     for(const id of ['transcribe','pdf','newStep'])$(id).disabled=true;
     $('steps').textContent='No video selected.';
    }
    await list();
   }catch(err){alert(err.message);remove.disabled=false}
  };
  row.append(open,remove);
  $('videoList').append(row);
 }
}
async function openVideo(id){selected=id;let v=await api('/api/videos/'+id);currentSteps=v.steps;$('videoTitle').textContent=v.title;$('status').textContent=`Status: ${v.status}${v.error?' — '+v.error:''}`;$('player').src='/api/videos/'+id+'/file';for(const b of ['transcribe','pdf','newStep'])$(b).disabled=false;renderSteps();await list();if(v.status==='transcribing'){clearTimeout(timer);timer=setTimeout(()=>openVideo(id),3000)}}
function renderSteps(){let holder=$('steps');holder.replaceChildren();if(!currentSteps.length){holder.textContent='No steps yet. Add one manually or transcribe the video.';return}for(const s of currentSteps){let card=document.createElement('div');card.className='item';card.dataset.start=s.start_sec;let heading=document.createElement('div');heading.className='row';let title=document.createElement('strong');title.textContent=`${format(s.start_sec)}  ${s.title}`;heading.append(title);let edit=document.createElement('button');edit.className='secondary';edit.textContent='Edit';edit.onclick=e=>{e.stopPropagation();showEditor(s)};heading.append(edit);card.append(heading);let p=document.createElement('p');p.textContent=s.body;card.append(p);card.onclick=()=>{$('player').currentTime=s.start_sec;$('player').play().catch(()=>{});highlight()};holder.append(card)}}
function highlight(){let time=$('player').currentTime;let current=null;for(const s of currentSteps){if(s.start_sec<=time)current=s.id}for(let i=0;i<currentSteps.length;i++){const el=$('steps').children[i];if(el?.classList)el.classList.toggle('active',currentSteps[i].id===current)}}
$('player').addEventListener('timeupdate',highlight);
$('upload').onsubmit=async e=>{e.preventDefault();let f=$('file').files[0];if(!f)return;let fd=new FormData();fd.append('file',f);fd.append('title',$('title').value);$('uploadMsg').textContent='Uploading...';try{let v=await api('/api/videos',{method:'POST',body:fd});$('uploadMsg').textContent='Upload complete.';$('upload').reset();await openVideo(v.id)}catch(err){$('uploadMsg').textContent=err.message}};
$('transcribe').onclick=async()=>{if(!confirm('Run local Whisper? First run may download a model. Existing automatically generated transcript sections will be replaced.'))return;try{await api(`/api/videos/${selected}/transcribe`,{method:'POST'});await openVideo(selected)}catch(e){alert(e.message)}};
$('pdf').onclick=()=>{if(selected)location.href=`/api/videos/${selected}/pdf`};
function showEditor(s=null){editing=s?.id||null;$('dialogTitle').textContent=s?'Edit instruction':'New instruction';$('stepTitle').value=s?.title||'';$('start').value=s?.start_sec??Math.floor($('player').currentTime);$('end').value=s?.end_sec??Math.floor($('player').currentTime);$('body').value=s?.body||'';$('editor').showModal()}
$('newStep').onclick=()=>showEditor();$('cancel').onclick=()=>$('editor').close();
$('stepForm').onsubmit=async e=>{e.preventDefault();let payload={title:$('stepTitle').value,start_sec:Number($('start').value),end_sec:Number($('end').value),body:$('body').value};try{await api(editing?`/api/steps/${editing}`:`/api/videos/${selected}/steps`,{method:editing?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});$('editor').close();await openVideo(selected)}catch(e){alert(e.message)}};
list().catch(e=>alert(e.message));

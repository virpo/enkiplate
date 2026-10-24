const $=id=>document.getElementById(id);
let designs=[],selected='cutout',state='back',detailIndex=0,selectionAt=0;
const preview=(id,side=state)=>`/api/designs/${encodeURIComponent(id)}/${side}.png`;
async function api(path,options={}){
 const r=await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers}});
 if(!r.ok)throw Error(r.status===401?'Open the study page and connect with your device key first.':'Could not connect. Try again.');
 return r.json();
}
function message(text,error=false){$('message').textContent=text;$('message').classList.toggle('error',error)}
function updateSelection(){
 const chosen=designs.find(d=>d.id===selected);
 $('restore').disabled=selected==='cutout';
 $('selection').textContent='Current: '+(chosen?chosen.name.replace(/^\d+ · /,''):'Cutout');
 for(const card of document.querySelectorAll('.design')){
  const active=card.dataset.id===selected;card.classList.toggle('selected',active);
  const button=card.querySelector('.use');button.textContent=active?'Selected':'Use on Inkplate';button.disabled=active;
 }
 const active=designs[detailIndex]?.id===selected;$('use-detail').textContent=active?'Selected':'Use on Inkplate';$('use-detail').disabled=active;
}
function setState(next){state=next;for(const b of document.querySelectorAll('[data-state]'))b.setAttribute('aria-pressed',String(b.dataset.state===state));for(const img of document.querySelectorAll('.thumb img'))img.src=preview(img.dataset.id);if($('detail').open)updateDetail()}
function updateDetail(){
 for(const b of document.querySelectorAll('[data-state]'))b.setAttribute('aria-pressed',String(b.dataset.state===state));
 const d=designs[detailIndex];$('detail-title').textContent=d.name;$('detail-note').textContent=d.note;
 $('detail-image').src=preview(d.id);$('detail-image').alt=`${d.name}, ${state}`;$('full-size').href=preview(d.id);
 $('preview-targets').replaceChildren();
 for(const hit of state==='idle'?[]:d.hits[state]){
  const b=document.createElement('button');b.setAttribute('aria-label',hit.action==='reveal'?'Reveal preview':hit.action==='little'?'Preview knew a little':`Preview ${hit.action}`);
  Object.assign(b.style,{left:hit.x/6+'%',top:hit.y/6+'%',width:hit.w/6+'%',height:hit.h/6+'%'});b.onclick=()=>setState(state==='front'?'back':'front');$('preview-targets').append(b);
 }
 updateSelection();
}
function openDetail(index){detailIndex=(index+designs.length)%designs.length;updateDetail();if(!$('detail').open)$('detail').showModal()}
async function choose(id){
 try{
  message('Saving your screen…');await api('/api/settings',{method:'PATCH',body:JSON.stringify({display_style:id})});selected=id;selectionAt=Date.now();updateSelection();message('Selected. The Inkplate will update over Wi-Fi shortly.');
 }catch(e){message(e.message,true)}
}
function render(){
 $('grid').replaceChildren();
 designs.forEach((d,index)=>{
  const card=document.createElement('article');card.className='design';card.dataset.id=d.id;
  const thumb=document.createElement('button');thumb.className='thumb';thumb.setAttribute('aria-label',`Inspect ${d.name}`);
  const img=document.createElement('img');img.src=preview(d.id);img.dataset.id=d.id;img.width=600;img.height=600;img.alt=d.name;img.loading='eager';thumb.append(img);thumb.onclick=()=>openDetail(index);
  const h=document.createElement('h2');h.textContent=d.name;const p=document.createElement('p');p.textContent=d.note;
  const foot=document.createElement('div');foot.className='card-foot';const inspect=document.createElement('button');inspect.className='inspect';inspect.textContent='Inspect';inspect.onclick=()=>openDetail(index);
  const use=document.createElement('button');use.className='use';use.textContent='Use on Inkplate';use.onclick=()=>choose(d.id);foot.append(inspect,use);card.append(thumb,h,p,foot);$('grid').append(card);
 });updateSelection();
}
async function health(){
 try{
  const r=await api('/api/status');const d=r.device;const live=d.wifi_seen_at&&Date.now()/1000-d.wifi_seen_at<50;
  $('live').textContent=live?'Inkplate on Wi-Fi'+(Number.isInteger(d.wifi_remaining)?` · ${d.wifi_remaining} cards ready`:''):d.connected?'Inkplate on USB':'Waiting for Inkplate';
  if(selectionAt&&live&&d.wifi_style===selected&&d.wifi_seen_at*1000>=selectionAt){message('On your Inkplate.');selectionAt=0}
 }catch{$('live').textContent='Local service unavailable'}
}
for(const b of document.querySelectorAll('[data-state]'))b.onclick=()=>setState(b.dataset.state);
$('restore').onclick=()=>choose('cutout');
$('close').onclick=()=>$('detail').close();$('previous').onclick=()=>openDetail(detailIndex-1);$('next').onclick=()=>openDetail(detailIndex+1);$('use-detail').onclick=()=>choose(designs[detailIndex].id);
$('detail').addEventListener('click',e=>{if(e.target===$('detail')){const r=$('detail').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('detail').close()}});
document.addEventListener('keydown',e=>{if(!$('detail').open)return;if(e.key==='ArrowRight')openDetail(detailIndex+1);if(e.key==='ArrowLeft')openDetail(detailIndex-1)});
try{const r=await api('/api/designs');designs=r.designs;selected=r.selected;render();const focus=designs.findIndex(d=>d.id===location.hash.slice(1));if(focus>=0)openDetail(focus);await health()}catch(e){message(e.message,true);$('grid').replaceChildren()}
setInterval(health,4000);

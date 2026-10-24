const $=id=>document.getElementById(id);
let concepts=[],state='back',index=0;
function setState(next){
 state=next;
 for(const button of document.querySelectorAll('[data-state]'))button.setAttribute('aria-pressed',String(button.dataset.state===state));
 for(const image of document.querySelectorAll('.thumb img'))image.src=concepts[Number(image.dataset.index)][state];
 if($('detail').open)detail();
}
function detail(){
 const c=concepts[index];$('detail-title').textContent=c.name;$('detail-note').textContent=c.note;
 $('detail-image').src=c[state];$('detail-image').alt=`${c.name}, ${state==='back'?'revealed':'front'}`;
 $('preview-targets').replaceChildren();
 const targets=state==='front'?[{x:24,y:474,w:552,h:112,label:'Reveal sample'}]:['missed','knew a little','knew'].map((label,i)=>({x:20+i*188,y:474,w:184,h:112,label:`Preview ${label}`}));
 for(const hit of targets){const b=document.createElement('button');b.setAttribute('aria-label',hit.label);Object.assign(b.style,{left:hit.x/6+'%',top:hit.y/6+'%',width:hit.w/6+'%',height:hit.h/6+'%'});b.onclick=()=>setState(state==='front'?'back':'front');$('preview-targets').append(b)}
}
function open(i){index=(i+concepts.length)%concepts.length;detail();if(!$('detail').open)$('detail').showModal()}
for(const b of document.querySelectorAll('[data-state]'))b.onclick=()=>setState(b.dataset.state);
$('close').onclick=()=>$('detail').close();$('previous').onclick=()=>open(index-1);$('next').onclick=()=>open(index+1);
document.addEventListener('keydown',e=>{if(!$('detail').open)return;if(e.key==='ArrowRight')open(index+1);if(e.key==='ArrowLeft')open(index-1)});
$('detail').addEventListener('click',e=>{if(e.target===$('detail')){const r=$('detail').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('detail').close()}});
try{
 const response=await fetch('/web/'+(document.body.dataset.collection||'paper-concepts.json'));if(!response.ok)throw Error('Could not load the concepts. Reload to try again.');concepts=await response.json();$('grid').replaceChildren();
 concepts.forEach((c,i)=>{const article=document.createElement('article');article.className='design';const thumb=document.createElement('button');thumb.className='thumb';thumb.setAttribute('aria-label',`Inspect ${c.name}`);thumb.onclick=()=>open(i);const image=document.createElement('img');image.src=c[state];image.alt=c.name;image.width=600;image.height=600;image.dataset.index=i;thumb.append(image);const title=document.createElement('h2');title.textContent=c.name;const note=document.createElement('p');note.textContent=c.note;article.append(thumb,title,note);$('grid').append(article)});
}catch(e){$('grid').textContent=e.message}

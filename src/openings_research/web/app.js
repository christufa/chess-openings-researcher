const $ = id => document.getElementById(id);
let library = [], runs = [], tab = 'claims', report = null, page = 0, generation = 0;
const el = (tag, text, cls) => { const node = document.createElement(tag); node.textContent = text; if(cls) node.className = cls; return node; };
async function get(path) { const r = await fetch('/api/v1/' + path); if(!r.ok) throw new Error(r.status === 503 ? 'The research store is unavailable. Try refreshing shortly.' : `Request failed (${r.status}).`); return r.json(); }
function error(e) { $('status').textContent = e.message; }
function options(id, items, key, label) { $(id).replaceChildren(...items.map(item => { const n=el('option', label(item)); n.value=item[key]; return n; })); }
async function load(append=false) {
  try {
    const data=await get(`openings?limit=50&offset=${append?library.length:0}`);
    library=append?[...library,...data.items]:data.items;
    options('opening',library,'opening_id',r=>r.opening);
    $('more').hidden=data.items.length<50;
    if(!library.length){ $('status').textContent='No published research yet. Complete a research run to populate this library.'; return; }
    const requested=new URLSearchParams(location.search).get('opening');
    if(library.some(r=>r.opening_id===requested)) $('opening').value=requested;
    await selectOpening();
  } catch(e){ error(e); }
}
async function selectOpening() {
  const ticket=++generation;
  try {
    $('run').disabled=true; $('status').textContent='Loading runs…'; $('results').replaceChildren();
    const data=await get(`openings/${encodeURIComponent($('opening').value)}/runs?limit=100`);
    if(ticket!==generation)return;
    runs=data.items.filter(r=>r.status==='completed');
    options('run',runs,'run_id',r=>`${r.completed_at?.slice(0,16).replace('T',' ')} UTC · ${r.run_id}`);
    options('before',runs,'run_id',r=>r.run_id);
    const requested=new URLSearchParams(location.search).get('run');
    if(runs.some(r=>r.run_id===requested)) $('run').value=requested;
    $('run').disabled=!runs.length;
    if(runs.length)await selectRun();
  } catch(e){error(e);}
}
async function selectRun() {
  const ticket=++generation, id=$('run').value;
  history.replaceState(null,'',`?opening=${encodeURIComponent($('opening').value)}&run=${encodeURIComponent(id)}`);
  $('diff').textContent=''; $('status').textContent='Loading snapshot…';
  try {
    const data=await get(`runs/${encodeURIComponent(id)}/coverage`);
    if(ticket!==generation)return;
    report=data.report; $('metrics').replaceChildren();
    for(const [label,value] of [['Claims',report?.published_claims],['Lines',report?.published_lines],['Research gaps',report?.gaps?.length]]){
      const card=el('div','', 'metric');card.append(el('strong',value??'—'),el('span',label));$('metrics').append(card);
    }
    $('run-info').textContent='Latest 100 runs shown. Each published run is a replacement snapshot.';
    await render();
  }catch(e){error(e);}
}
async function render(append=false) {
  const ticket=++generation, run=$('run').value, selectedTab=tab;
  if(!append){page=0;$('results').replaceChildren();}
  $('next').hidden=true;
  try {
    const items=tab==='gaps'?(report?.gaps||[]):(await get(`runs/${encodeURIComponent(run)}/${tab}?limit=50&offset=${page*50}`)).items;
    if(ticket!==generation)return;
    $('status').textContent=items.length?'Published snapshot · inspect each finding’s evidence and review status.':(append?'No more records.':'No records in this section.');
    for(const item of items){
      const card=el('article');
      card.append(el('span',selectedTab==='gaps'?`Priority ${item.priority} · ${item.side}`:(item.category||'Opening line')+' · '+(item.side||item.review_status),'tag'));
      card.append(el('h3',item.text||item.name||item.topic.replaceAll('_',' ')));
      if(item.moves_san)card.append(el('p',item.moves_san.join(' ')),el('p','Starting position: '+item.start_fen));
      if(selectedTab==='gaps'){card.append(el('p',item.reason),el('p','Suggested search: '+item.query));}
      else{
        const details=el('details'),summary=el('summary','Inspect source evidence');details.append(summary);
        let loaded=false;
        details.addEventListener('toggle',async()=>{if(!details.open||loaded)return;loaded=true;
          try{const evidence=await get(`runs/${encodeURIComponent(run)}/evidence/${encodeURIComponent(item.candidate_id)}?limit=100`);
            for(const e of evidence.items){details.append(el('p',e.relation));
              try{const u=new URL(e.url);if(['https:','http:'].includes(u.protocol)){const a=el('a',e.title||e.url);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';details.append(a);}}catch{}
              details.append(el('blockquote',e.excerpt));}
            if(!evidence.items.length)details.append(el('p','No evidence available.'));
          }catch(e){loaded=false;details.append(el('p',e.message));}
        });card.append(details);
      } $('results').append(card);
    }
    $('next').hidden=selectedTab==='gaps'||items.length<50;
  }catch(e){error(e);}
}
$('opening').onchange=selectOpening;$('run').onchange=selectRun;$('retry').onclick=()=>load();$('more').onclick=()=>load(true);
$('next').onclick=()=>{page++;render(true);};
document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{tab=button.dataset.tab;document.querySelectorAll('[data-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));render();});
$('compare').onclick=async()=>{try{const d=await get(`compare?before=${encodeURIComponent($('before').value)}&after=${encodeURIComponent($('run').value)}`);$('diff').textContent=['claims','lines'].map(k=>`${k[0].toUpperCase()+k.slice(1)}: ${d[k].added.length} added, ${d[k].removed.length} removed, ${d[k].retained} retained`).join('\n');}catch(e){error(e);}};
load();

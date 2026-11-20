// ChainTrace v28 read-only share viewer. The token lives in the URL fragment; it is posted to /api/share/open, which decrypts and checks it.
(async()=>{
const $=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const short=s=>{s=String(s);return s.length>16?s.slice(0,8)+'…'+s.slice(-4):s};
const dt=t=>new Date(t*1000).toLocaleString('en-GB',{timeZone:'Europe/London'})+' UK ('+new Date(t*1000).toISOString().slice(0,16).replace('T',' ')+' UTC)';
const tok=new URLSearchParams(location.hash.slice(1)).get('t');
if(!tok){$('msg').textContent='No snapshot in this link.';return}
let j;try{const r=await fetch('/api/share/open',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({token:tok})});j=await r.json();if(!r.ok)throw new Error(j.detail||r.status)}
catch(e){$('msg').innerHTML='⚠ '+esc(e.message);$('msg').className='err';return}
window.CT_SHARE=j;const S=j.snapshot;$('msg').style.display='none';
$('ban').innerHTML=`<b>🔒 Shared snapshot – read-only.</b> Case “${esc(S.case.name)}”. Shared ${esc(dt(j.issued))} · expires ${esc(dt(j.expires))}.<br><span class="mono">Audit SHA-256 ${esc(j.audit_sha256)}</span> ${j.hash_ok?'<span class="ok">✓ matches content</span>':'<span class="bad">✗ hash mismatch</span>'}<br><span class="dim">A snapshot from ChainTrace. Labels and inferences in it are leads for investigation, not evidence.</span>`;
$('ban').style.display='block';
const RC={sanctioned:'#ff3b5c',darknet:'#e0245e',hack:'#ff6b6b',scam:'#ff8c42',mixer:'#ffb020',exchange:'#4c8dff',bridge:'#22c3c3',gambling:'#ffd23f',tx:'#8a7dff'};
const L=S.labels||{};
const nm=n=>(L[n.id]&&L[n.id].name)||n.name||short(String(n.id).replace(/^tx:/,'tx '));
const els=[...S.nodes.map(n=>({data:{id:n.id,lbl:nm(n),c:RC[n.kind]||(String(n.id).startsWith('tx:')?RC.tx:'#5d6b85')}})),
 ...S.edges.filter(e=>S.nodes.some(n=>n.id===e.source)&&S.nodes.some(n=>n.id===e.target)).map((e,i)=>({data:{id:'e'+i,source:e.source,target:e.target,lbl:(e.amount!=null?(+e.amount).toLocaleString(undefined,{maximumFractionDigits:4})+' ':'')+(e.unit||'')}}))];
const cy=window.cy=cytoscape({container:$('g'),elements:els,autoungrabify:false,boxSelectionEnabled:false,
 style:[{selector:'node',style:{'background-color':'data(c)',label:'data(lbl)',color:'#cfd8ea','font-size':9,'text-valign':'bottom','text-margin-y':4,width:22,height:22}},
  {selector:'edge',style:{width:1.6,'line-color':'#3d4d6b','target-arrow-color':'#3d4d6b','target-arrow-shape':'triangle','curve-style':'bezier',label:'data(lbl)','font-size':7,color:'#8fa0bf','text-rotation':'autorotate'}}],
 layout:{name:'cose',animate:false,padding:30}});
cy.on('tap','node',ev=>{const n=S.nodes.find(x=>x.id===ev.target.id());$('det').innerHTML=`<b>${esc(nm(n))}</b><div class="mono">${esc(n.id)}</div>${n.chain?'<div>chain '+esc(n.chain)+'</div>':''}${n.kind?'<div>label category: '+esc(n.kind)+'</div>':''}${(n.sources||[]).map(s=>`<div class="dim">source: ${esc(s.source)} ${s.source_url?`<a target="_blank" rel="noopener noreferrer" href="${esc(s.source_url)}">link</a>`:''}</div>`).join('')}${L[n.id]?'<div class="dim">private label: '+esc(L[n.id].name||'')+'</div>':''}`});
$('cnt').textContent=`${S.nodes.length} nodes · ${S.edges.length} transfers`;
$('tbl').innerHTML='<tr><th>From</th><th>To</th><th>Amount</th><th>Time (UTC)</th><th>Tx</th></tr>'+S.edges.slice(0,400).map(e=>`<tr><td class="mono">${esc(short(e.source))}</td><td class="mono">${esc(short(e.target))}</td><td>${e.amount!=null?(+e.amount).toLocaleString(undefined,{maximumFractionDigits:6}):''} ${esc(e.unit||'')}</td><td>${e.time?new Date(e.time*1000).toISOString().slice(0,16).replace('T',' '):''}</td><td class="mono">${esc(e.tx?short(e.tx):'')}</td></tr>`).join('');
if(S.notes){const c=typeof S.notes==='object'?(S.notes.case||''):S.notes;$('notes').innerHTML='<h3>Case notes (shared by the investigator)</h3><div style="white-space:pre-wrap">'+esc(c)+'</div>'}
})();

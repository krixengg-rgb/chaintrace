// ChainTrace v32: multi-case link finder. Compares saved cases (this browser's case store) and exported case files picked from disk,
// finds shared addresses, counterparties, exchange deposit addresses, BTC co-spend clusters and transactions, shows a cross-case table and
// opens a merged graph (a new local case). Runs entirely in this browser: case files are read with FileReader and nothing is uploaded.
(()=>{
const E=s=>typeof esc==='function'?esc(s):String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const css=document.createElement('style');css.textContent=`#xcm{position:fixed;inset:0;z-index:80;display:none;background:rgba(5,8,18,.62);backdrop-filter:blur(3px);overflow:auto;padding:24px 10px}
#xcm.on{display:block}#xcm>.card{max-width:1040px;margin:0 auto;padding:18px}#xcm h4{margin:14px 0 6px;font-size:13px;color:#cfd8ff}
#xcm .ban{font-size:11.5px;border:1px dashed rgba(92,200,255,.5);border-radius:9px;padding:6px 8px;background:rgba(92,200,255,.06);color:#bfe7ff;margin:6px 0}
#xcm .ban.w{border-color:rgba(246,201,69,.6);background:rgba(246,201,69,.07);color:#ffe3a3}
#xcm .cl{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:6px}#xcm .cl label{display:flex;gap:6px;align-items:flex-start;font-size:12px;border:1px solid var(--line);border-radius:8px;padding:6px 8px;min-width:0}
#xcm .cl label span{overflow-wrap:anywhere}#xcm .cl small{display:block;color:var(--mut);font-size:10.5px}
#xcm .tw{overflow-x:auto;max-width:100%}#xcm table{width:100%;border-collapse:collapse;font-size:11.5px}#xcm td,#xcm th{padding:4px 6px;border-top:1px solid var(--line);text-align:left;vertical-align:top}
#xcm th{color:var(--mut);font-weight:600}#xcm .mono{font:10.5px var(--mono,monospace);word-break:break-all}#xcm .s3{color:#ff8fa3;font-weight:700}#xcm .s2{color:#f6c945;font-weight:600}#xcm .s1{color:var(--mut)}
#xcm .acts{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}#xcm input[type=file]{font-size:12px;max-width:100%}
@media (max-width:700px){#xcm{padding:0}#xcm>.card{border-radius:0;min-height:100%;padding:14px 10px}}`;document.head.appendChild(css);
const norm=id=>{id=String(id||'').trim();return /^0x[0-9a-fA-F]{40}$/.test(id)?id.toLowerCase():id};
const SERVICE=new Set(['mixer','bridge','defi','gambling','miner','privacy','swap','nokyc_swap']);
let FILES=[];   // cases read from exported files: in memory only
function roleOf(c,n){const d=n.data||{},i=d.info||{},L=(c.labels||{})[d.id]||null,ln=((L&&L.name)||'').toLowerCase();
 if(ln.includes('victim'))return'victim';if(ln.includes('suspect'))return'suspect';
 if((i.suggested&&i.suggested.category==='exchange-deposit')||d.sugg||/deposit/i.test(i.name||d.lbl||''))return'exchange deposit';
 if(d.kind==='exchange'||i.kind==='exchange')return'exchange (hot wallet / service)';
 if(SERVICE.has(d.kind||i.kind))return'service ('+(d.kind||i.kind)+')';
 if(['scam','phishing','hack','sanctioned','darknet','ransomware'].includes(d.kind||i.kind))return'labelled '+(d.kind||i.kind);
 if(d.focus||norm(d.id)===norm(c.query))return'case subject';return'counterparty'}
const STR={'exchange deposit':3,'suspect':3,'victim':2,'case subject':2,'counterparty':2,'labelled scam':3,'labelled phishing':3,'labelled hack':3,'labelled sanctioned':3};
function strength(roles){if(roles.some(r=>r==='exchange deposit'))return[3,'strong: exchange deposit addresses are usually unique to one customer account'];
 if(roles.every(r=>r.startsWith('exchange')||r.startsWith('service')))return[1,'weak: common exchange / service infrastructure links unrelated cases'];
 if(roles.some(r=>r==='suspect'||r.startsWith('labelled')))return[3,'strong: same suspect / labelled address'];return[2,'medium: same address in these cases']}
window.ctCrossCaseAnalyse=function(cases){
 const A=new Map(),T=new Map(),K=new Map();
 cases.forEach((c,ci)=>{const ns=(c.graph&&c.graph.nodes)||[],es=(c.graph&&c.graph.edges)||[];
  for(const n of ns){const d=n.data||{};const id=String(d.id||'');if(!id)continue;
   if(id.startsWith('tx:')){const h=norm(id.slice(3));if(!T.has(h))T.set(h,new Map());T.get(h).set(ci,'transaction node');continue}
   const k=norm(id);if(!A.has(k))A.set(k,{id:d.id,chain:(d.info&&d.info.chain)||null,label:null,per:new Map()});const a=A.get(k);
   const lb=((c.labels||{})[d.id]||{}).name||(d.info&&d.info.name)||null;if(lb&&!a.label)a.label=lb;a.per.set(ci,roleOf(c,n));
   const cl=d.info&&d.info.cluster;if(cl&&cl.root){const r=norm(cl.root);if(!K.has(r))K.set(r,{root:cl.root,size:cl.size,per:new Map()});const kk=K.get(r);if(!kk.per.has(ci))kk.per.set(ci,new Set());kk.per.get(ci).add(d.id)}}
  for(const e of es){const tx=e.info&&(e.info.tx||e.info.txid);if(tx){const h=norm(tx);if(!T.has(h))T.set(h,new Map());if(!T.get(h).has(ci))T.get(h).set(ci,'transfer')}}});
 // an address in case B that is the root / member of a cluster seen in case A links the cases too
 for(const [r,kk] of K){const a=A.get(r);if(a)for(const ci of a.per.keys())if(!kk.per.has(ci))kk.per.set(ci,new Set([a.id]))}
 const ent=[];
 for(const [k,a] of A){if(a.per.size<2)continue;const roles=[...a.per.values()];const [s,why]=strength(roles);
  ent.push({type:roles.includes('exchange deposit')?'exchange deposit':roles.every(r=>r.startsWith('exchange')||r.startsWith('service'))?'service':'address',key:a.id,chain:a.chain,label:a.label,strength:s,why,cases:[...a.per.entries()].map(([ci,r])=>({ci,name:cases[ci].name,role:r}))})}
 for(const [h,m] of T){if(m.size<2)continue;ent.push({type:'transaction',key:h,strength:3,why:'strong: the same on-chain transaction appears in these cases',cases:[...m.entries()].map(([ci,r])=>({ci,name:cases[ci].name,role:r}))})}
 for(const [r,kk] of K){if(kk.per.size<2)continue;ent.push({type:'cluster',key:kk.root,chain:'btc',label:`co-spend cluster of ${kk.size||'?'} addresses`,strength:2,why:'medium: addresses that likely belong to the same BTC wallet (common-input heuristic, a lead)',cases:[...kk.per.entries()].map(([ci,s])=>({ci,name:cases[ci].name,role:'cluster member: '+[...s].slice(0,3).map(x=>String(x).slice(0,10)+'…').join(', ')}))})}
 ent.sort((a,b)=>b.strength-a.strength||b.cases.length-a.cases.length);
 const pairs=[];for(let i=0;i<cases.length;i++)for(let j=i+1;j<cases.length;j++){const sh=ent.filter(e=>e.cases.some(x=>x.ci===i)&&e.cases.some(x=>x.ci===j));
  if(sh.length)pairs.push({a:i,b:j,an:cases[i].name,bn:cases[j].name,addresses:sh.filter(e=>e.type==='address'||e.type==='service').length,deposits:sh.filter(e=>e.type==='exchange deposit').length,txs:sh.filter(e=>e.type==='transaction').length,clusters:sh.filter(e=>e.type==='cluster').length,strong:sh.filter(e=>e.strength===3).length})}
 return{cases:cases.map((c,i)=>({i,name:c.name,id:c.id,nodes:((c.graph&&c.graph.nodes)||[]).length,src:c._src||'browser'})),entities:ent,pairs,at:new Date().toISOString()}};
window.ctCrossCaseMerge=async function(cases,R){
 const shared=new Map();for(const e of R.entities)if(e.type!=='transaction'&&e.type!=='cluster')shared.set(norm(e.key),e);
 const nodes=new Map(),edges=new Map();
 cases.forEach((c,ci)=>{const ns=(c.graph&&c.graph.nodes)||[];const xs=ns.map(n=>(n.position||{}).x||0),minx=xs.length?Math.min(...xs):0;
  for(const n of ns){const k=norm(n.data.id);const sh=shared.get(k);
   if(nodes.has(k)){const m=nodes.get(k);m.data.xcases=[...new Set([...(m.data.xcases||[]),c.name])];m.data.xc=m.data.xcases.length;continue}
   const d={...n.data,xcases:[c.name],xc:1,xcase:c.name};if(sh){d.xc=sh.cases.length;d.xcases=sh.cases.map(x=>x.name);d.lbl='⛓ '+(d.lbl||'')}
   nodes.set(k,{data:d,position:{x:((n.position||{}).x||0)-minx+ci*900,y:(n.position||{}).y||0}})}
  for(const e of (c.graph&&c.graph.edges)||[]){if(!edges.has(e.id))edges.set(e.id,{...e,xcase:c.name})}});
 const names=cases.map(c=>c.name);
 const mc=blankCase('Merged · '+names.slice(0,2).join(' + ')+(names.length>2?` (+${names.length-2})`:''));
 mc.graph={nodes:[...nodes.values()],edges:[...edges.values()]};mc.mode='lookup';mc.lookup=null;mc.trace=null;mc.query='';
 mc.labels=Object.assign({},...cases.map(c=>c.labels||{}));
 mc.notes.case=`Merged view of ${names.length} cases (${names.join('; ')}), made on ${new Date().toISOString().slice(0,16).replace('T',' ')} UTC. Nodes marked ⛓ appear in more than one case. Shared addresses are leads: common exchange or service wallets can link unrelated cases.`;
 mc.crosscase={sources:names,links:R.entities.length};await Store.put(mc);await openCase(mc.id);try{if(typeof relayout==='function'){relayout();setTimeout(()=>{try{persist()}catch(e){}},900)}}catch(e){}
 if(typeof ctAudit==='function')try{ctAudit('crosscase.merge',{cases:names.length,links:R.entities.length})}catch(e){}
 return mc};
function csv(R){const q=s=>'"'+String(s??'').replace(/"/g,'""')+'"';const rows=[['type','strength','entity','chain','label','cases','roles','why']];
 for(const e of R.entities)rows.push([e.type,e.strength===3?'strong':e.strength===2?'medium':'weak',e.key,e.chain||'',e.label||'',e.cases.map(x=>x.name).join(' | '),e.cases.map(x=>x.role).join(' | '),e.why]);
 return rows.map(r=>r.map(q).join(',')).join('\r\n')}
let LAST=null,LASTC=null;
async function allCases(){const st=(await Store.list()).map(c=>({...c,_src:'browser'}));return st.concat(FILES)}
async function render(){const m=document.getElementById('xcm');const cs=await allCases();
 m.querySelector('.cl').innerHTML=cs.length?cs.map((c,i)=>`<label><input type="checkbox" class="xcc" data-i="${i}" checked><span>${E(c.name)}<small>${c._src==='file'?'📄 file: '+E(c._file):'💾 saved in this browser'} · ${((c.graph||{}).nodes||[]).length} nodes</small></span></label>`).join(''):'<div class="dim">No saved cases yet.</div>'}
window.ctCrossCase=async function(open=true){let m=document.getElementById('xcm');
 if(!m){m=document.createElement('div');m.id='xcm';m.innerHTML=`<div class="card glass"><h3>🔗 Cross-case link finder<span class="sp"></span><button class="btn sm" onclick="ctCrossCase(false)">✕ Close</button></h3>
  <div class="ban">🔒 Local only: cases are read from this browser's case store and from the files you pick below. Nothing is uploaded to the server.</div>
  <h4>1 · Cases to compare</h4><div class="cl"></div>
  <div class="acts"><label class="btn sm" style="cursor:pointer">📄 Add exported case files (.json)<input id="xcfile" type="file" accept=".json,application/json" multiple style="display:none"></label><span id="xcfmsg" class="dim" style="font-size:11.5px"></span></div>
  <div class="acts"><button class="btn primary" id="xcrun">🔗 Find links</button></div>
  <div id="xcout"></div></div>`;document.body.appendChild(m);
  m.querySelector('#xcfile').onchange=async ev=>{let n=0,bad=0;for(const f of ev.target.files){try{const o=JSON.parse(await f.text());const arr=o.case?[o.case]:o.cases||(o.graph?[o]:[]);
    for(const c of arr){if(!c.graph)continue;FILES.push({...c,_src:'file',_file:f.name});n++}}catch(e){bad++}}
   m.querySelector('#xcfmsg').textContent=`${n} case(s) read from file(s) in this browser${bad?`, ${bad} file(s) not readable`:''} (not saved, not uploaded)`;ev.target.value='';render()};
  m.querySelector('#xcrun').onclick=()=>ctCrossCaseRun()}
 m.classList.toggle('on',!!open);if(open)await render()};
window.ctCrossCaseRun=async function(){const m=document.getElementById('xcm');const cs=await allCases();const sel=[...m.querySelectorAll('.xcc:checked')].map(x=>cs[+x.dataset.i]).filter(Boolean);
 const out=m.querySelector('#xcout');if(sel.length<2){out.innerHTML='<div class="warnbox">Pick at least two cases.</div>';return}
 const R=ctCrossCaseAnalyse(sel);LAST=R;LASTC=sel;window.CT_LAST_CROSSCASE=R;
 const cnt=t=>R.entities.filter(e=>e.type===t).length;
 const st=s=>s===3?'<span class="s3">strong</span>':s===2?'<span class="s2">medium</span>':'<span class="s1">weak</span>';
 out.innerHTML=`<h4>2 · Links found</h4><div class="ban w">⚠ Leads, not evidence: a shared address shows the cases touch the same wallet, not that the same person is behind them. Exchange deposit addresses are the strongest link (one customer account); exchange hot wallets and services are weak links.</div>
  <div style="font-size:12.5px">${sel.length} cases · <b>${R.entities.length}</b> shared item(s): ${cnt('exchange deposit')} exchange deposit address(es), ${cnt('address')} address(es), ${cnt('service')} service wallet(s), ${cnt('transaction')} transaction(s), ${cnt('cluster')} cluster(s)</div>
  ${R.pairs.length?`<h4>Case pairs</h4><div class="tw"><table id="xcpairs"><tr><th>Case</th><th>Case</th><th>Exchange deposits</th><th>Addresses</th><th>Transactions</th><th>Clusters</th><th>Strong</th></tr>${R.pairs.map(p=>`<tr><td>${E(p.an)}</td><td>${E(p.bn)}</td><td>${p.deposits}</td><td>${p.addresses}</td><td>${p.txs}</td><td>${p.clusters}</td><td>${p.strong}</td></tr>`).join('')}</table></div>`:''}
  <h4>Cross-case table</h4>${R.entities.length?`<div class="tw"><table id="xctab"><tr><th>Shared</th><th>Type</th><th>Strength</th><th>Cases (role in each)</th></tr>${R.entities.slice(0,300).map(e=>`<tr data-type="${E(e.type)}"><td><span class="mono">${E(e.key)}</span>${e.label?`<br><b>${E(e.label)}</b>`:''}${e.chain?` <span class="dim">${E(e.chain)}</span>`:''}</td><td>${E(e.type)}</td><td>${st(e.strength)}<br><span class="dim" style="font-size:10.5px">${E(e.why)}</span></td><td>${e.cases.map(x=>`${E(x.name)}: <i>${E(x.role)}</i>`).join('<br>')}</td></tr>`).join('')}</table></div>`:'<div class="dim">No shared addresses, transactions or clusters between the selected cases.</div>'}
  <div class="acts"><button class="btn primary" id="xcmerge" ${R.entities.length?'':'disabled'}>🕸 Open merged graph (new local case)</button><button class="btn" id="xccsv">⬇ Cross-case CSV</button></div>`;
 out.querySelector('#xccsv').onclick=()=>{const b=new Blob([csv(R)],{type:'text/csv'});if(typeof dl==='function')dl('chaintrace-crosscase-'+new Date().toISOString().slice(0,10)+'.csv',b)};
 out.querySelector('#xcmerge').onclick=async()=>{await ctCrossCaseMerge(LASTC,LAST);ctCrossCase(false);if(typeof toast==='function')toast('Merged graph opened as a new local case')};
 if(typeof ctAudit==='function')try{ctAudit('crosscase.find',{cases:sel.length,links:R.entities.length})}catch(e){}};
try{cy.style().selector('node[xc>1]').style({'border-width':5,'border-color':'#e85cff','border-style':'double'}).update()}catch(e){}
const anchor=document.getElementById('intakebtn')||document.getElementById('lossbtn');if(anchor){const b=document.createElement('button');b.className='btn';b.id='xcbtn';b.title='Find shared addresses, exchange deposits, clusters and transactions across saved cases (local only)';b.textContent='🔗 Cross-case';b.onclick=()=>ctCrossCase(true);anchor.after(b)}
const nav=(performance.getEntriesByType('navigation')[0]||{}).name||location.href;if(new URL(nav).searchParams.get('crosscase')==='1')setTimeout(()=>ctCrossCase(true),300);
})();

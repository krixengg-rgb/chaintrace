// ChainTrace v9: watchlist + alerts. The list, cursors and alert feed live in this browser (IndexedDB); the server check is stateless.
(()=>{
const css=document.createElement('style');css.textContent=`
#wdrawer{position:fixed;right:12px;top:12px;bottom:12px;width:420px;z-index:45;padding:14px;display:flex;flex-direction:column;gap:10px;transform:translateX(110%);transition:transform .25s ease;background:rgba(14,19,32,.94)}
#wdrawer.open{transform:none}
#wdrawer h2{margin:0;font-size:16px;display:flex;align-items:center;gap:8px}#wdrawer h2 .sp{flex:1}
#wbtn{position:relative}#wbtn .n{position:absolute;top:-6px;right:-6px;min-width:18px;height:18px;padding:0 5px;box-sizing:border-box;border-radius:999px;background:var(--red);color:#fff;font-size:11px;font-weight:700;display:none;align-items:center;justify-content:center;box-shadow:0 0 12px rgba(255,77,109,.6)}
#wbtn .n.on{display:flex}#wbtn .n.med{background:var(--org)}#wbtn .n.low{background:var(--blu)}
.wtabs{display:flex;gap:4px;padding:3px;border-radius:11px;background:rgba(0,0,0,.25);border:1px solid var(--line)}
.wtabs button{flex:1;border:0;background:none;padding:6px 8px;border-radius:8px;cursor:pointer;color:var(--mut);font-weight:600;font-size:12.5px}
.wtabs button.on{background:var(--panel2);color:var(--txt);box-shadow:0 1px 6px rgba(0,0,0,.3)}
.wbar{display:flex;gap:6px;align-items:center;flex-wrap:wrap;font-size:12px;color:var(--mut)}
.wbar select{background:var(--panel2);border:1px solid var(--line);color:inherit;border-radius:8px;padding:4px 6px;font-size:12px}
#wbody{flex:1;overflow:auto;display:flex;flex-direction:column;gap:8px;padding-right:2px;-webkit-overflow-scrolling:touch}
.wit{border:1px solid var(--line);border-radius:12px;padding:9px 10px;background:rgba(255,255,255,.025);position:relative}
.wit .t{display:flex;align-items:center;gap:6px;font-weight:600;font-size:13px;min-width:0}
.wit .t .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0}
.wit .m{font-size:11.5px;color:var(--mut);margin-top:3px;display:flex;flex-wrap:wrap;gap:2px 10px}
.wit .acts{display:flex;gap:5px;flex-wrap:wrap;margin-top:7px}
.wit .ab{min-width:20px;height:20px;padding:0 6px;box-sizing:border-box;border-radius:999px;font-size:11px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;background:var(--red);color:#fff}
.wit .ab.medium{background:var(--org)}.wit .ab.low{background:var(--blu)}
.wst{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--mut)}.wst.ok{background:var(--grn)}.wst.err{background:var(--red)}.wst.run{background:var(--acc2);animation:wp 1s infinite}
@keyframes wp{50%{opacity:.3}}
.wev{border:1px solid var(--line);border-left:3px solid var(--blu);border-radius:12px;padding:9px 10px 8px;background:rgba(255,255,255,.025)}
.wev.high{border-left-color:var(--red);background:rgba(255,77,109,.06)}.wev.medium{border-left-color:var(--org)}.wev.unread{box-shadow:0 0 0 1px rgba(124,92,255,.35) inset}
.wev .h{display:flex;align-items:center;gap:6px;font-size:12.5px;font-weight:600;min-width:0}
.wev .h .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;flex:1}
.wev .sv{font-size:10px;font-weight:800;letter-spacing:.6px;padding:1px 6px;border-radius:6px;background:rgba(76,141,255,.15);color:#9dbcff}
.wev.high .sv{background:rgba(255,77,109,.18);color:#ffb3c1}.wev.medium .sv{background:rgba(255,159,67,.16);color:#ffc999}
.wev .amt{font-size:17px;font-weight:700;margin:4px 0 1px;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}.wev .amt .in{color:var(--grn)}.wev .amt .out{color:var(--red)}
.wev .amt small{font-size:12px;color:var(--mut);font-weight:500}
.wev .cp{font-size:12px;margin-top:3px;display:flex;align-items:center;gap:4px;flex-wrap:wrap}
.wev .rl{font-size:11.5px;color:#cfd6e6;margin-top:4px}.wev .rl span{display:inline-block;margin:2px 4px 0 0;padding:1px 7px;border-radius:999px;border:1px solid var(--line);background:rgba(255,255,255,.04)}
.wev .tm{font-size:11px;color:var(--mut);margin-top:5px}.wev .acts{display:flex;gap:5px;margin-top:7px;flex-wrap:wrap}
#wform{border:1px solid var(--line);border-radius:12px;padding:10px;background:rgba(0,0,0,.18);display:none}#wform.on{display:block}
#wform label{display:block;font-size:11.5px;color:var(--mut);margin:7px 0 3px}
#wform input[type=text],#wform input[type=number]{width:100%;box-sizing:border-box;background:rgba(0,0,0,.25);border:1px solid var(--line);border-radius:9px;padding:7px 9px;color:var(--txt);outline:0;font:13px var(--font)}
#wform input.mono{font-family:var(--mono);font-size:12px}#wform input:focus{border-color:rgba(124,92,255,.6)}
#wform .g2{display:grid;grid-template-columns:1fr 1fr;gap:0 8px}
#wform .chips{display:flex;flex-wrap:wrap;gap:5px}#wform .chips label{margin:0;display:inline-flex;gap:5px;align-items:center;font-size:12px;color:var(--txt);border:1px solid var(--line);border-radius:999px;padding:3px 9px;cursor:pointer;background:rgba(255,255,255,.03)}
#wform .chips input{margin:0}#wform .rr{display:flex;gap:8px;align-items:center;font-size:12.5px;margin-top:7px;flex-wrap:wrap}#wform .rr input[type=number]{width:96px}
.wempty{font-size:12.5px;color:var(--mut);text-align:center;padding:26px 10px;border:1px dashed var(--line);border-radius:12px}
@media (max-width:900px){#wdrawer{right:0;top:0;bottom:0;width:100%;border-radius:0;box-sizing:border-box}#wform .g2{grid-template-columns:1fr}}`;
document.head.appendChild(css);
// ---------- storage (IndexedDB, localStorage fallback) ----------
const DBN='chaintrace_watch',K='state';let W={items:[],events:[],settings:{every:5,notify:false,tab:'alerts'}};
const idb=()=>new Promise((ok,no)=>{try{const r=indexedDB.open(DBN,1);r.onupgradeneeded=()=>r.result.createObjectStore('kv');r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)}catch(e){no(e)}});
async function load(){try{const db=await idb();const v=await new Promise((ok,no)=>{const q=db.transaction('kv').objectStore('kv').get(K);q.onsuccess=()=>ok(q.result);q.onerror=()=>no(q.error)});if(v)W=v}
 catch(e){try{const v=JSON.parse(localStorage.ct_watch||'null');if(v)W=v}catch(_){}}W.settings=Object.assign({every:5,notify:false,tab:'alerts'},W.settings||{});W.items=W.items||[];W.events=W.events||[]}
let sh;function save(){clearTimeout(sh);sh=setTimeout(async()=>{const v=JSON.parse(JSON.stringify(W));try{const db=await idb();await new Promise((ok,no)=>{const t=db.transaction('kv','readwrite');t.objectStore('kv').put(v,K);t.oncomplete=ok;t.onerror=()=>no(t.error)})}catch(e){try{localStorage.ct_watch=JSON.stringify(v)}catch(_){}}},150)}
// ---------- helpers ----------
const CATS=[['sanctioned','Sanctioned'],['mixer','Mixer'],['risky','Hack/scam/darknet'],['exchange','Exchange'],['exchange-deposit','Exchange deposit'],['bridge','Bridge'],['labelled','Any labelled']];
const DEF={any_tx:true,out_usd:null,cats:['sanctioned','mixer','risky','exchange','exchange-deposit','bridge'],bal_pct:null};
const uk=t=>t?new Date(t*1000).toLocaleString('en-GB',{timeZone:'Europe/London',day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',timeZoneName:'short'}).replace(',',''):'unconfirmed (mempool)';
const utc=t=>t?new Date(t*1000).toISOString().slice(11,16)+' UTC':'';
const ago=ms=>{if(!ms)return'never';const s=(Date.now()-ms)/1000;return s<60?'just now':s<3600?Math.round(s/60)+' min ago':s<86400?Math.round(s/3600)+' h ago':Math.round(s/86400)+' d ago'};
const uid=()=>Math.random().toString(36).slice(2,10)+Date.now().toString(36).slice(-4);
const SEVN={high:3,medium:2,low:1};const ctag=k=>k==='exchange-deposit'?tagH('exchange'):k==='risky'?tagH('hack'):tagH(k);
const sevOf=evs=>evs.reduce((m,e)=>SEVN[e.severity]>SEVN[m]?e.severity:m,'low');
// ---------- UI shell ----------
const d=document.createElement('div');d.id='wdrawer';d.className='glass';d.setAttribute('aria-label','Watchlist');
d.innerHTML=`<h2>👁 Watchlist<span class="sp"></span><button class="btn sm pri" id="wchk" onclick="ctWatchCheck()">↻ Check now</button><button class="btn sm ico" onclick="ctWatch(false)" aria-label="Close">✕</button></h2>
<div class="wtabs"><button id="wt-alerts" onclick="ctWTab('alerts')">Alerts <span id="wtn-a"></span></button><button id="wt-items" onclick="ctWTab('items')">Addresses <span id="wtn-i"></span></button></div>
<div class="wbar"><span>Auto-check</span><select id="wevery" onchange="ctWSet('every',+this.value)">${[0,2,5,10,15,30,60].map(n=>`<option value="${n}">${n?'every '+n+' min':'off'}</option>`).join('')}</select>
<button class="btn sm" id="wnotify" onclick="ctWNotify()">🔔 Notify</button><span class="sp" style="flex:1"></span>
<button class="btn sm" onclick="ctWExport()" title="Download the watchlist (with cursors) as JSON, the format watch_check.py reads">⤓ Export</button><button class="btn sm" onclick="$('wimp').click()">⤒ Import</button><input type="file" id="wimp" accept=".json,application/json" style="display:none" onchange="ctWImport(this.files[0]);this.value=''"></div>
<div id="wstat" class="dim" style="font-size:11.5px;min-height:15px"></div>
<div id="wform"></div><div id="wbody"></div>
<div class="dim" style="font-size:10.5px">Stored only in this browser. Checks read public blockchain data via third-party APIs; alerts are leads, verify before acting.</div>`;
document.body.appendChild(d);
const anchor=$('rptbtn')||$('savebtn');const b=document.createElement('button');b.className='btn';b.id='wbtn';b.title='Watchlist & alerts';b.innerHTML='👁 Watch<span class="n" id="wn"></span>';b.onclick=()=>ctWatch();anchor.after(b);
window.ctWatch=on=>{on=on===undefined?!d.classList.contains('open'):on;d.classList.toggle('open',on);if(on){if(typeof toggleCases==='function')toggleCases(false);render()}else markRead()};
window.ctWTab=t=>{if(W.settings.tab==='alerts'&&t!=='alerts')markRead();W.settings.tab=t;save();render()};
window.ctWSet=(k,v)=>{W.settings[k]=v;save();schedule();render()};
function markRead(){let ch=0;for(const e of W.events)if(e.unread){e.unread=false;ch++}if(ch){save();badge()}}
function badge(){const u=W.events.filter(e=>e.unread);const n=$('wn');n.textContent=u.length>99?'99+':u.length;n.className='n'+(u.length?' on':'')+(u.length&&sevOf(u)==='medium'?' med':u.length&&sevOf(u)==='low'?' low':'');
 document.title=(u.length?'('+u.length+') ':'')+document.title.replace(/^\(\d+\+?\) /,'')}
// ---------- add / edit form ----------
window.ctWatchAdd=function(pre={}){const ex=pre.address&&W.items.find(x=>x.address.toLowerCase()===pre.address.toLowerCase());if(ex)pre={...ex,...pre,id:ex.id};
 ctWatch(true);W.settings.tab='items';render();const r={...DEF,...(pre.rules||{})};const f=$('wform');
 f.innerHTML=`<div style="font-weight:600;font-size:13px">${pre.id?'Edit watch':'＋ Watch an address'}</div>
 <label for="wf-a">BTC / ETH / SOL address</label><input type="text" class="mono" id="wf-a" value="${esc(pre.address||'')}" ${pre.id?'readonly':''} placeholder="bc1… / 0x… / Solana address" autocomplete="off" spellcheck="false">
 <div class="g2"><div><label for="wf-n">Name</label><input type="text" id="wf-n" maxlength="80" value="${esc(pre.name||'')}" placeholder="e.g. Suspect wallet 1"></div><div><label for="wf-r">Case ref</label><input type="text" id="wf-r" maxlength="80" value="${esc(pre.ref||'')}" placeholder="optional"></div></div>
 <label for="wf-note">Note</label><input type="text" id="wf-note" maxlength="300" value="${esc(pre.note||'')}" placeholder="why it's watched">
 <label>Alert when</label><div class="rr"><label style="margin:0;display:flex;gap:6px;align-items:center;color:var(--txt);font-size:12.5px"><input type="checkbox" id="wf-any" ${r.any_tx?'checked':''}> any new transaction</label></div>
 <div class="rr">outflow ≥ $<input type="number" id="wf-out" min="0" step="100" value="${r.out_usd??''}" placeholder="off"> · balance change ≥<input type="number" id="wf-bal" min="0" step="1" value="${r.bal_pct??''}" placeholder="off" style="width:70px">%</div>
 <label>…or a transfer to/from</label><div class="chips">${CATS.map(([k,n])=>`<label><input type="checkbox" class="wf-cat" value="${k}" ${r.cats.includes(k)?'checked':''}>${esc(n)}</label>`).join('')}</div>
 ${pre.id?'':`<div class="rr"><span class="dim">Start</span><select id="wf-since" style="background:var(--panel2);border:1px solid var(--line);color:inherit;border-radius:8px;padding:4px 6px"><option value="0">from now (baseline)</option><option value="1">include last hour</option><option value="24">include last 24 h</option></select></div>`}
 <div class="acts" style="display:flex;gap:6px;justify-content:flex-end;margin-top:10px"><button class="btn sm" onclick="$('wform').classList.remove('on')">Cancel</button><button class="btn sm pri" id="wf-save">${pre.id?'Save':'Watch'}</button></div>`;
 f.classList.add('on');$('wf-save').onclick=()=>{const a=$('wf-a').value.trim();const[c,k]=detect(a);if(!c||k!=='address')return toast('Enter a BTC, ETH or SOL address');
  const rules={any_tx:$('wf-any').checked,out_usd:+$('wf-out').value||null,bal_pct:+$('wf-bal').value||null,cats:[...f.querySelectorAll('.wf-cat:checked')].map(x=>x.value)};
  let it=pre.id&&W.items.find(x=>x.id===pre.id);
  if(it)Object.assign(it,{name:$('wf-n').value.trim(),ref:$('wf-r').value.trim(),note:$('wf-note').value.trim(),rules});
  else{if(W.items.length>=200)return toast('Watchlist is full (200)');it={id:uid(),address:a,chain:c,name:$('wf-n').value.trim(),ref:$('wf-r').value.trim(),note:$('wf-note').value.trim(),rules,added:Date.now(),case_id:pre.case_id||(curCase&&curCase.id)||null,cursor:null,last:null};
   const sh=+($('wf-since')?.value||0);if(sh)it.since=Math.floor(Date.now()/1000-sh*3600);W.items.unshift(it)}
  save();f.classList.remove('on');render();toast(pre.id?'Watch updated':'Watching '+short(a));if(!pre.id)checkItems([it])};
 setTimeout(()=>(pre.address?$('wf-n'):$('wf-a')).focus(),60)};
window.ctWRemove=id=>{const it=W.items.find(x=>x.id===id);if(!it||!confirm('Stop watching '+(it.name||it.address)+'? Its alerts stay in the feed.'))return;W.items=W.items.filter(x=>x.id!==id);save();render()};
// ---------- render ----------
function render(){const tab=W.settings.tab||'alerts';$('wt-alerts').classList.toggle('on',tab==='alerts');$('wt-items').classList.toggle('on',tab==='items');
 const un=W.events.filter(e=>e.unread).length;$('wtn-a').textContent=W.events.length?`(${un?un+' new':W.events.length})`:'';$('wtn-i').textContent=W.items.length?`(${W.items.length})`:'';
 $('wevery').value=String(W.settings.every);$('wnotify').textContent=W.settings.notify&&window.Notification&&Notification.permission==='granted'?'🔔 On':'🔕 Notify';
 const last=Math.max(0,...W.items.map(x=>x.last?.checked||0));$('wstat').innerHTML=RUN?`<span class="wst run"></span> checking ${RUN}…`:last?`Last check ${ago(last)}${W.settings.every?' · next in ≤'+W.settings.every+' min':''}`:'';
 $('wchk').disabled=!!RUN||!W.items.length;const body=$('wbody');
 if(tab==='items'){body.innerHTML=`<button class="btn sm" style="align-self:flex-start" onclick="ctWatchAdd()">＋ Add address</button>`+(W.items.length?W.items.map(it=>{const s=it.last?.summary||{};const ev=W.events.filter(e=>e.watch_id===it.id&&e.unread);const st=RUNIDS.has(it.id)?'run':it.last?.status==='error'?'err':it.last?'ok':'';
  const r=it.rules||{};const rl=[r.any_tx?'any tx':'',r.out_usd?'out ≥ '+usd(r.out_usd):'',r.bal_pct?'bal ±'+r.bal_pct+'%':'',(r.cats||[]).length?(r.cats||[]).length+' categories':''].filter(Boolean).join(' · ');
  return`<div class="wit"><div class="t">${chainTag(it.chain)}<span class="nm" title="${esc(it.address)}">${esc(it.name||short(it.address))}</span>${ev.length?`<span class="ab ${sevOf(ev)}" title="unread alerts">${ev.length}</span>`:''}${s.label&&s.label.kind?ctag(s.label.kind):''}</div>
  <div class="m"><span class="mono">${esc(short(it.address))}</span>${it.ref?`<span>📁 ${esc(it.ref)}</span>`:''}${s.balance!=null?`<span>${fmt(s.balance,6)} ${esc(s.unit||'')}${s.balance_usd!=null?' · '+usd(s.balance_usd):''}</span>`:''}</div>
  <div class="m"><span><span class="wst ${st}"></span> ${it.last?'checked '+ago(it.last.checked):'not checked yet'}${it.last?.status==='baseline'?' (baseline set)':''}</span><span>latest activity ${s.last_activity?uk(s.last_activity):'–'}</span></div>
  ${it.last?.error?`<div class="m" style="color:#ffb3c1">⚠ ${esc(it.last.error)}</div>`:''}${it.note?`<div class="m">📝 ${esc(it.note)}</div>`:''}<div class="m">rules: ${esc(rl||'none')}</div>
  <div class="acts"><button class="btn sm" onclick="ctWCheckOne('${it.id}')">↻ Check</button><button class="btn sm" onclick="ctWOpen('${esc(it.address)}')">◎ Open in graph</button><button class="btn sm" onclick="ctWEdit('${it.id}')">Edit</button><button class="btn sm danger" onclick="ctWRemove('${it.id}')">Remove</button></div></div>`}).join(''):'<div class="wempty">No addresses watched yet.<br>Add one here, from a node’s details (👁 Watch), the counterparties panel or a case.</div>')}
 else{const evs=W.events.slice(0,300);body.innerHTML=evs.length?`<div class="wbar"><span>${W.events.length} alert(s)</span><span style="flex:1"></span><button class="btn sm" onclick="ctWClear()">Clear feed</button></div>`+evs.map(evH).join(''):`<div class="wempty">No alerts yet.${W.items.length?' Checks run '+(W.settings.every?'every '+W.settings.every+' min while ChainTrace is open':'when you press Check now')+'.':'<br>Watch an address to start.'}</div>`}}
function evH(e){const cp=e.counterparty;const dir=e.dir==='out'?'out':'in';const a0=(e.amounts||[])[0];
 const amt=e.type==='summary'?'':`<div class="amt"><span class="${dir}">${dir==='out'?'↑ OUT':'↓ IN'}</span> ${e.usd!=null?usd(e.usd):'<span class="dim">no USD</span>'} <small>${(e.amounts||[]).slice(0,3).map(x=>fmt(Math.abs(x.amount),6)+' '+esc(x.unit)).join(' · ')}</small></div>`;
 const cpH=cp?`<div class="cp">${dir==='out'?'to':'from'} ${cp.cat?ctag(cp.kind||cp.cat):''}<b>${esc(cp.name||short(cp.id))}</b> <span class="mono dim">${esc(short(cp.id))}</span>${cp.suggested?'<span class="dim">· inferred, lead only</span>':''}${cp.risk>=45?`<span class="sv" style="background:rgba(255,77,109,.18);color:#ffb3c1">risk ${cp.risk}</span>`:''}${e.counterparties>1?`<span class="dim">+${e.counterparties-1} more</span>`:''}</div>`:'';
 return`<div class="wev ${e.severity} ${e.unread?'unread':''}"><div class="h"><span class="sv">${e.severity.toUpperCase()}</span>${chainTag(e.chain)}<span class="nm">${esc(e.name||short(e.address))}${e.ref?' · '+esc(e.ref):''}</span></div>${amt}${cpH}
 <div class="rl">${(e.rules||[]).map(r=>`<span>${esc(r)}</span>`).join('')}</div><div class="tm">${uk(e.time)}${e.time?' · '+utc(e.time):''}${e.type==='tx'?' · <span class="mono">'+esc(short(e.tx))+'</span>':''}</div>
 <div class="acts">${e.type==='tx'?`<button class="btn sm pri" onclick="ctWOpen('${esc(e.tx)}')">◎ Open in graph</button>`:''}<button class="btn sm" onclick="ctWOpen('${esc(e.address)}')">Address</button>${e.tx_url?`<a class="btn sm" target="_blank" rel="noopener" href="${esc(e.tx_url)}">Explorer ↗</a>`:''}</div></div>`}
window.ctWEdit=id=>{const it=W.items.find(x=>x.id===id);if(it)ctWatchAdd({...it})};
window.ctWClear=()=>{if(!confirm('Clear all alerts from the feed?'))return;W.events=[];save();badge();render()};
window.ctWOpen=q=>{$('q').value=q;setBadge();if(innerWidth<900)ctWatch(false);go()};
// ---------- checks (batched + staggered; server is stateless) ----------
let RUN='',RUNIDS=new Set(),TMR=null;const BATCH=4;
const PEND=new Set();
async function checkItems(list){if(!list.length)return;if(RUN){list.forEach(x=>PEND.add(x.id));return}const todo=[...list];let done=0,newE=[];
 try{for(let i=0;i<todo.length;i+=BATCH){const bt=todo.slice(i,i+BATCH);bt.forEach(x=>RUNIDS.add(x.id));RUN=`${Math.min(i+BATCH,todo.length)}/${todo.length}`;render();
  if(i)await new Promise(r=>setTimeout(r,2500));
  let j;try{const r=await fetch('/api/watch/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items:bt.map(x=>({id:x.id,address:x.address,chain:x.chain,name:x.name,ref:x.ref,rules:x.rules,cursor:x.cursor,since:x.cursor?undefined:x.since}))})});
   if(r.status===429){$('wstat').textContent='Rate limited: will retry next round';break}j=await r.json();if(!r.ok)throw new Error(j.detail||r.status)}
  catch(e){bt.forEach(x=>{x.last={...(x.last||{}),checked:Date.now(),status:'error',error:'check failed: '+e.message};RUNIDS.delete(x.id)});continue}
  for(const res of j.results||[]){const it=W.items.find(x=>x.id===res.id);RUNIDS.delete(res.id);if(!it)continue;
   if(res.status==='ok'||res.status==='baseline'){it.cursor=res.cursor;delete it.since;it.last={checked:Date.now(),status:res.status,summary:res.summary,warnings:res.warnings};
    const have=new Set(W.events.map(e=>e.id));for(const e of res.events||[]){if(have.has(e.id))continue;e.unread=true;e.seen_at=Date.now();newE.push(e)}}
   else if(res.status==='deferred')it.last={...(it.last||{}),status:it.last?.status||'pending'};
   else it.last={...(it.last||{}),checked:Date.now(),status:'error',error:res.error||res.status}}
  done+=bt.length}}
 finally{RUN='';RUNIDS.clear();if(PEND.size){const p=W.items.filter(x=>PEND.has(x.id));PEND.clear();setTimeout(()=>checkItems(p),1500)}}
 if(newE.length){newE.sort((a,b)=>SEVN[b.severity]-SEVN[a.severity]||(b.time||9e12)-(a.time||9e12));W.events=newE.concat(W.events).slice(0,600);notify(newE)}
 W.lastRun=Date.now();save();badge();render();if(newE.length&&!d.classList.contains('open'))toast(`👁 ${newE.length} new watchlist alert(s)`);return newE}
window.ctWatchCheck=()=>checkItems([...W.items].sort((a,b)=>(a.last?.checked||0)-(b.last?.checked||0)));
window.ctWCheckOne=id=>{const it=W.items.find(x=>x.id===id);if(it)checkItems([it])};
function schedule(){clearInterval(TMR);const m=W.settings.every;if(m)TMR=setInterval(()=>{if(!document.hidden||W.settings.notify)ctWatchCheck()},m*60000)}
// ---------- browser notifications ----------
window.ctWNotify=async()=>{if(!window.Notification)return toast('Notifications not supported in this browser');
 if(W.settings.notify&&Notification.permission==='granted'){W.settings.notify=false;save();render();return toast('Notifications off')}
 const p=await Notification.requestPermission();W.settings.notify=p==='granted';save();render();toast(p==='granted'?'Notifications on for new alerts':'Notifications blocked by the browser')};
function notify(evs){if(!W.settings.notify||!window.Notification||Notification.permission!=='granted')return;
 const top=evs.filter(e=>e.severity!=='low').slice(0,3);const show=top.length?top:evs.slice(0,1);
 try{for(const e of show){const n=new Notification(`ChainTrace · ${e.severity.toUpperCase()} · ${e.name||short(e.address)}`,{body:(e.dir==='out'?'OUT ':'IN ')+(e.usd!=null?usd(e.usd):'')+' · '+(e.rules||[]).join('; '),tag:e.id});n.onclick=()=>{window.focus();ctWatch(true);ctWTab('alerts')}}
  if(evs.length>show.length)new Notification('ChainTrace watchlist',{body:`${evs.length} new alert(s)`,tag:'ct-sum'})}catch(e){}}
// ---------- export / import (same format as watch_check.py) ----------
window.ctWExport=()=>{const o={format:'chaintrace-watchlist',version:1,exported:Date.now(),source:'browser',items:W.items.map(({last,...x})=>x)};
 dl('chaintrace-watchlist-'+new Date().toISOString().slice(0,10)+'.json',new Blob([JSON.stringify(o,null,1)],{type:'application/json'}));toast('Exported '+o.items.length+' address(es)')};
window.ctWImport=async f=>{if(!f)return;let o;try{o=JSON.parse(await f.text())}catch(e){return toast('Not a JSON file')}const xs=Array.isArray(o)?o:o.items;
 if(!Array.isArray(xs)||(o.format&&o.format!=='chaintrace-watchlist'))return toast('Not a ChainTrace watchlist file');let add=0,upd=0;
 for(const x of xs){const a=String(x.address||'').trim();const[c,k]=detect(a);if(!c||k!=='address')continue;const ex=W.items.find(y=>y.address.toLowerCase()===a.toLowerCase());
  if(ex){if(x.cursor&&(!ex.cursor||(x.cursor.checked||0)>(ex.cursor.checked||0)))ex.cursor=x.cursor;Object.assign(ex,{name:x.name||ex.name,ref:x.ref||ex.ref,note:x.note||ex.note,rules:x.rules||ex.rules});upd++}
  else if(W.items.length<200){W.items.push({id:x.id||uid(),address:a,chain:c,name:x.name||'',ref:x.ref||'',note:x.note||'',rules:{...DEF,...(x.rules||{})},added:x.added||Date.now(),case_id:x.case_id||null,cursor:x.cursor||null,last:null});add++}}
 save();render();toast(`Imported: ${add} new, ${upd} updated`)};
// ---------- entry points: node details, counterparties, case ----------
cy.on('tap','node',e=>{const n=e.target;if(n.data('grp'))return;const i=n.data('info')||{};const id=n.id();const[c,k]=detect(id);if(!c||k!=='address')return;
 setTimeout(()=>{const r=$('det').querySelector('.card .row');if(!r||r.querySelector('.wbtn'))return;const w=W.items.some(x=>x.address.toLowerCase()===id.toLowerCase());
  r.insertAdjacentHTML('beforeend',`<button class="btn sm wbtn" onclick="ctWatchAdd({address:'${esc(id)}',name:${esc(JSON.stringify(i.name||''))},ref:${esc(JSON.stringify(curCase?curCase.name:''))}})">${w?'👁 Watching':'👁 Watch'}</button>`)},0)});
const asideEl=document.querySelector('aside');if(asideEl)new MutationObserver(()=>{const cpp=$('cpp');if(!cpp)return;const rows=cpp._rows||[];cpp.querySelectorAll('table tr').forEach((tr,i)=>{const x=rows[i];if(!x||tr.querySelector('.wbtn'))return;const td=tr.lastElementChild;if(!td)return;
 const b=document.createElement('button');b.className='btn sm plus wbtn';b.title='Watch this counterparty';b.textContent='👁';b.style.marginLeft='4px';b.onclick=()=>ctWatchAdd({address:x.id,name:x.name||'',ref:curCase?curCase.name:''});td.appendChild(b)})}).observe(asideEl,{childList:true,subtree:true});
const _cc=window.caseCard;window.caseCard=function(){_cc();const h=$('casecard')?.querySelector('h3');if(!curCase||!h)return;const q=(curCase.query||$('q').value||'').trim();const[c,k]=detect(q);if(!c||k!=='address')return;
 const b=document.createElement('button');b.className='btn sm';b.id='wcase';b.style.marginLeft='6px';b.textContent='👁 Watch subject';b.onclick=()=>ctWatchAdd({address:q,name:curCase.name,ref:curCase.report_meta?.ref||curCase.name,case_id:curCase.id});h.appendChild(b)};
// ---------- boot ----------
load().then(()=>{badge();render();schedule();if(W.items.length&&W.settings.every)setTimeout(()=>{const last=Math.max(0,...W.items.map(x=>x.last?.checked||0));if(Date.now()-last>W.settings.every*30000)ctWatchCheck()},2500)});
window.CT_WATCH=()=>W;
})();

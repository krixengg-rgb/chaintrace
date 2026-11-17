// ChainTrace v21: case notes journal + tamper-evident audit log (both stored with the case in this browser).
// Notes: timestamped, attributed entries on the case, an address or a flow; edits keep every revision, deletes are soft.
// Audit log: append-only, SHA-256 hash-chained record of case actions (graph changes, labels, roles, notes, imports, exports,
// reports). "Verify" recomputes the chain; "Anchor" gets a server-signed receipt (HMAC) for the current head so a later
// rewrite of the whole chain is detectable too. Times: UK (Europe/London) + UTC.
(()=>{
const css=document.createElement('style');css.textContent=`
#cnm{position:fixed;inset:0;z-index:84;display:none;align-items:center;justify-content:center;background:rgba(3,5,10,.62);padding:12px}#cnm.on{display:flex}
#cnm .card{width:min(1040px,100%);max-height:calc(100vh - 24px);overflow:auto;padding:14px 16px;background:rgba(16,21,36,.97)}
#cnm h3{margin:0 0 8px;font-size:15px;text-transform:none;letter-spacing:0;color:var(--txt);display:flex;gap:8px;align-items:center}
#cnm .tabs{display:flex;gap:6px;margin-bottom:8px}#cnm .tabs button{flex:0 0 auto}#cnm .tabs button.on{background:var(--acc,#6c7bff);color:#fff;border-color:transparent}
#cnm textarea,#cnm input[type=text],#cnm select{background:rgba(0,0,0,.25);border:1px solid var(--line);border-radius:9px;color:var(--txt);padding:6px 9px;font:12.5px inherit;outline:0}
#cnm textarea{width:100%;box-sizing:border-box;min-height:64px;resize:vertical}#cnm .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:6px 0}
#cnm .row input[type=text]{flex:1 1 140px;min-width:0}.cnn{border:1px solid var(--line);border-radius:10px;padding:7px 9px;margin:6px 0;font-size:12.5px;background:rgba(0,0,0,.12)}
.cnn .hd{display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:11px;color:var(--mut)}.cnn .hd b{color:var(--txt)}.cnn .tx{white-space:pre-wrap;overflow-wrap:anywhere;margin-top:4px}
.cnn.del .tx{text-decoration:line-through;opacity:.55}.cnn .tg{padding:0 7px;border-radius:999px;border:1px solid var(--line);font-size:10.5px}.cnn .tgt{font-family:var(--mono);font-size:10.5px;cursor:pointer;color:#9fb4ff}
.cnn .acts{margin-left:auto;display:flex;gap:4px}.cnn .rev{font-size:11px;color:var(--mut);border-left:2px solid var(--line);padding-left:8px;margin-top:4px;white-space:pre-wrap}
#cnm .tw{overflow:auto;max-height:56vh;border:1px solid var(--line);border-radius:10px;-webkit-overflow-scrolling:touch}
#cnm table{width:100%;border-collapse:collapse;font-size:11.5px}#cnm td,#cnm th{padding:5px 7px;border-top:1px solid var(--line);text-align:left;vertical-align:top}
#cnm th{position:sticky;top:0;background:rgba(16,21,36,.98);color:var(--mut);font-size:10.5px;text-transform:uppercase}#cnm .mono{font-family:var(--mono);font-size:10.5px;overflow-wrap:anywhere}
#cnm .vok{color:#2ee59d}#cnm .vbad{color:#ff8da1}#cnm .dim{color:var(--mut)}
#noteCard .cnn{margin:5px 0}
@media (max-width:700px){#cnm{align-items:flex-end;padding:0}#cnm .card{border-radius:16px 16px 0 0;max-height:94vh;max-height:94dvh;padding:12px}#cnm textarea,#cnm input[type=text],#cnm select{font-size:16px}
#cnm table,#cnm tbody,#cnm tr,#cnm td{display:block;width:auto}#cnm tr:first-child{display:none}#cnm tr{border-top:1px solid var(--line);padding:6px 8px}#cnm td{border:0;padding:1px 0}.hide-s{display:none!important}}`;
document.head.appendChild(css);
const ZERO='0'.repeat(64);
const hex=b=>[...new Uint8Array(b)].map(x=>x.toString(16).padStart(2,'0')).join('');
const sha=async s=>hex(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s)));
const tUK=t=>new Date(t).toLocaleString('en-GB',{timeZone:'Europe/London',day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZoneName:'short'}).replace(/GMT\+1\b/,'BST').replace(/GMT\+0\b/,'GMT');
const tUTC=t=>new Date(t).toISOString().replace('T',' ').slice(0,19)+' UTC';
const author=()=>localStorage.ct_author||'investigator';
const writable=()=>curCase&&!curCase.readonly;
const short2=id=>typeof short==='function'?short(id):id;
// ---------- audit log ----------
let Q=Promise.resolve();
const clean=d=>{const o={};for(const[k,v]of Object.entries(d||{})){if(v==null||v===''||(Array.isArray(v)&&!v.length))continue;o[k]=typeof v==='number'?Math.round(v):typeof v==='boolean'?(v?1:0):Array.isArray(v)?v.slice(0,12).map(String).join(', ').slice(0,400):String(v).slice(0,400)}return o};
const entryStr=e=>JSON.stringify([e.seq,e.t,e.actor,e.action,e.target,e.detail,e.prev]);
function audit(action,detail,target,cc){const c=cc||curCase;if(!c||c.readonly)return Q;
 Q=Q.then(async()=>{if(!c.audit)c.audit=[];const last=c.audit[c.audit.length-1];
  const e={seq:last?last.seq+1:1,t:Date.now(),actor:author(),action,target:target?String(target).slice(0,200):'',detail:clean(detail),prev:last?last.h:ZERO};
  e.h=await sha(entryStr(e));c.audit.push(e);if(c===curCase){autosave();if(M.classList.contains('on')&&TAB==='audit')paint()}}).catch(()=>{});return Q}
window.ctAudit=(action,detail,target)=>audit(action,detail,target);
window.ctAuditVerify=async(c=curCase)=>{const a=(c&&c.audit)||[];let prev=ZERO;
 for(let i=0;i<a.length;i++){const e=a[i];if(e.prev!==prev||e.seq!==i+1)return{ok:false,at:e.seq||i+1,n:a.length,why:'sequence/link broken'};
  if(await sha(entryStr(e))!==e.h)return{ok:false,at:e.seq,n:a.length,why:'entry altered'};prev=e.h}
 return{ok:true,n:a.length,head:prev}};
// graph / summary changes are diffed at save time (covers expand, trace, AutoTrace, delete, import)
const nodeIds=()=>cy.nodes().map(n=>n.id()).filter(i=>!/^grp:|^cluster:/.test(i));
function diffGraph(){if(!writable())return;const c=curCase;const now=nodeIds();const was=c.audit_ids;
 if(!was){c.audit_ids=now;if(!c.audit||!c.audit.length)audit(c.created&&Date.now()-c.created<60000?'case.created':'audit.started',{name:c.name,nodes:now.length,note:c.created&&Date.now()-c.created<60000?'':'earlier history of this case was not recorded'});return}
 const W=new Set(was),N=new Set(now);const add=now.filter(i=>!W.has(i)),rem=was.filter(i=>!N.has(i));
 if(add.length||rem.length){c.audit_ids=now;audit('graph.changed',{added:add.length,removed:rem.length,first_added:add.slice(0,6).map(short2),first_removed:rem.slice(0,6).map(short2),nodes:now.length,mode:c.mode||''})}
 const s=(c.notes&&c.notes.case)||'';if(s!==(c.audit_summary??'')){const prev=c.audit_summary;c.audit_summary=s;if(prev!==undefined)sha(s).then(h=>audit('summary.edited',{chars:s.length,sha256:h.slice(0,16)}))}}
const _blank=window.blankCase;window.blankCase=function(){const c=_blank.apply(this,arguments);c.audit=[];c.audit_ids=[];c.journal=[];audit('case.created',{name:c.name},'',c);return c};
const _persist=window.persist;window.persist=async function(){try{if(curCase&&!restoring)diffGraph()}catch(e){}return _persist.apply(this,arguments)};
const wrap=(name,fn)=>{const o=window[name];if(typeof o!=='function')return;window[name]=async function(...a){const pre=fn.pre?fn.pre(...a):null;const r=await o.apply(this,a);try{fn.post(pre,...a)}catch(e){}return r}};
wrap('saveLabel',{pre:id=>({name:($('clName')||{}).value,kind:($('clKind')||{}).value,global:($('clGlobal')||{}).checked}),post:(p,id)=>{if(p.name&&p.name.trim())audit('label.set',{name:p.name.trim(),category:p.kind||'',all_cases:p.global},id)}});
wrap('clearLabel',{post:(p,id)=>audit('label.cleared',{},id)});
wrap('renameCase',{pre:id=>curCase&&curCase.id===id?curCase.name:null,post:(old,id)=>{if(old!=null&&curCase&&curCase.name!==old)audit('case.renamed',{from:old,to:curCase.name})}});
wrap('exportCase',{post:(p,id)=>{if(!id||(curCase&&curCase.id===id))audit('case.exported',{format:'chaintrace-case JSON'})}});
wrap('openCase',{post:(p,id)=>{if(curCase&&curCase.id===id&&!curCase.readonly){if(!curCase.audit_ids)curCase.audit_ids=nodeIds();migrate(curCase);audit('case.opened',{nodes:curCase.graph?.nodes?.length||0})}}});
if(typeof window.ctLossMark==='function'){const o=window.ctLossMark;window.ctLossMark=function(id,k){const r=o.apply(this,arguments);try{const S=window.CT_LOSS||{};
 const on=k==='v'?(S.victims||[]).includes(id):k==='t'?(S.victim_txs||[]).includes(id):k==='s'?S.suspect===id:null;audit('role.'+(on===false?'unmarked':'marked'),{role:{v:'victim',t:'victim tx',s:'suspect'}[k]||k},id)}catch(e){}return r}}
// report / evidence pack / CSV exports seen on the wire
const _f=window.fetch;window.fetch=async function(u,o){const r=await _f.apply(this,arguments);try{const s=typeof u==='string'?u:(u&&u.url)||'';
 if(r.ok&&(s==='/api/report'||s==='/api/evidence-pack'))audit(s==='/api/report'?'report.pdf':'evidence.pack',{bytes:+(r.headers.get('content-length')||0),sha256:(r.headers.get('X-Pack-SHA256')||r.headers.get('X-Report-SHA256')||'').slice(0,16),case_sha256:(r.headers.get('X-Case-SHA256')||'').slice(0,16)})}catch(e){}return r};
// ---------- notes journal ----------
function migrate(c){if(!c||c.journal)return;c.journal=[];const t=c.updated||Date.now();
 for(const k of['nodes','edges'])for(const[id,txt]of Object.entries((c.notes&&c.notes[k])||{}))if(String(txt).trim())c.journal.push({id:uid(),t,author:'(note from before v21)',kind:k,target:id,text:String(txt),tags:[],rev:[],legacy:1})}
function sync(c=curCase){if(!c||!c.journal)return;const n={nodes:{},edges:{}};
 for(const e of c.journal){if(e.deleted||e.kind==='case')continue;const k=e.kind;n[k][e.target]=(n[k][e.target]?n[k][e.target]+'\n\n':'')+e.text}
 c.notes.nodes=n.nodes;c.notes.edges=n.edges}
const kindOf=(kind,id)=>{if(!id)return'case';const el=cy.getElementById(id);return el&&el.length?(el.isNode()?'nodes':'edges'):(kind==='case'?'case':kind||'nodes')};
window.ctNoteAdd=async(kind,id,text,source,tags)=>{text=String(text||'').trim();if(!text)return null;await ensureCase();if(curCase.readonly)return toast('Read-only case');migrate(curCase);
 const k=kind==='case'?'case':kindOf(kind,id);const e={id:uid(),t:Date.now(),author:author(),kind:k,target:k==='case'?'':id,text:text.slice(0,8000),tags:(tags||[]).slice(0,8),rev:[]};if(source)e.source=source;
 curCase.journal.push(e);sync();applyCaseDecor();autosave();caseCard();const h=await sha(e.text);audit('note.added',{note:e.id,on:k==='case'?'case':k==='nodes'?'address':'flow',chars:e.text.length,sha256:h.slice(0,16),source:source||''},e.target);refreshNoteCard();return e};
window.ctNoteEdit=async(nid,text)=>{const e=(curCase.journal||[]).find(x=>x.id===nid);if(!e||e.deleted)return;text=String(text||'').trim();if(!text||text===e.text)return;
 e.rev.push({t:e.edited||e.t,author:e.editor||e.author,text:e.text});e.text=text.slice(0,8000);e.edited=Date.now();e.editor=author();sync();applyCaseDecor();autosave();
 audit('note.edited',{note:nid,revision:e.rev.length+1,chars:e.text.length,sha256:(await sha(e.text)).slice(0,16)},e.target);refreshNoteCard();if(M.classList.contains('on'))paint()};
window.ctNoteDel=async nid=>{const e=(curCase.journal||[]).find(x=>x.id===nid);if(!e||e.deleted)return;if(!confirm('Delete this note? It stays in the case history (struck through) and in the audit log.'))return;
 e.deleted={t:Date.now(),author:author()};sync();applyCaseDecor();autosave();caseCard();audit('note.deleted',{note:nid},e.target);refreshNoteCard();if(M.classList.contains('on'))paint()};
const tgtH=e=>e.kind==='case'?'<span class="tg">case</span>':`<span class="tgt" title="${esc(e.target)}" onclick="ctNoteGo('${esc(e.target)}')">${esc((e.kind==='edges'?'flow ':'')+short2(e.target))}</span>`;
const noteH=(e,full)=>`<div class="cnn${e.deleted?' del':''}" data-note="${e.id}"><div class="hd"><b>${esc(e.author)}</b><span title="${tUTC(e.t)}">${tUK(e.t)}</span>${full?`<span class="hide-s">· ${tUTC(e.t)}</span>`:''}${full?tgtH(e):''}${(e.tags||[]).map(t=>`<span class="tg">${esc(t)}</span>`).join('')}${e.source?`<span class="tg">${esc(e.source)}</span>`:''}
 ${e.edited?`<span title="last edit ${tUTC(e.edited)} by ${esc(e.editor||'')}">· edited ${e.rev.length}×</span>`:''}${e.deleted?`<span class="vbad">· deleted ${tUK(e.deleted.t)} by ${esc(e.deleted.author)}</span>`:''}
 ${e.deleted||!writable()?'':`<span class="acts"><button class="btn sm" onclick="ctNoteEditUI('${e.id}')">Edit</button><button class="btn sm" onclick="ctNoteDel('${e.id}')">Delete</button></span>`}</div>
 <div class="tx">${esc(e.text)}</div>${full&&e.rev.length?`<details><summary class="dim" style="font-size:11px;cursor:pointer">${e.rev.length} earlier version(s)</summary>${e.rev.map(r=>`<div class="rev">${tUK(r.t)} · ${esc(r.author)}\n${esc(r.text)}</div>`).join('')}</details>`:''}</div>`;
window.ctNoteEditUI=nid=>{const e=curCase.journal.find(x=>x.id===nid);const box=document.querySelectorAll(`[data-note="${nid}"] .tx`);if(!box.length)return;
 for(const b of box){b.innerHTML=`<textarea class="cne">${esc(e.text)}</textarea><div class="row"><button class="btn sm pri">Save edit</button><button class="btn sm">Cancel</button></div>`;
  const[s,c]=b.querySelectorAll('button');s.onclick=()=>ctNoteEdit(nid,b.querySelector('textarea').value);c.onclick=()=>{refreshNoteCard();if(M.classList.contains('on'))paint()}}};
window.ctNoteGo=id=>{const el=cy.getElementById(id);if(!el||!el.length)return toast('Not in the current graph');cy.elements().unselect();el.select();cy.animate({center:{eles:el},zoom:Math.max(cy.zoom(),1.1)},{duration:300});if(innerWidth<900)ctNotes(false)};
// node / flow side card: list of notes for this target + add box (replaces the single free-text note)
let CUR=null;
window.noteUI=function(kind,id){CUR={kind,id};if(curCase)migrate(curCase);const L=effLabel(id);
 const es=((curCase&&curCase.journal)||[]).filter(e=>e.kind===kind&&e.target===id&&!e.deleted);
 return `<div class="card glass" id="noteCard"><h3>✎ Notes${kind==='nodes'?' & custom label':''}<span class="sp"></span><span class="dim" style="text-transform:none;letter-spacing:0">${es.length||''}</span></h3><div id="noteList">${es.map(e=>noteH(e,false)).join('')}</div>
 <textarea id="noteTxt" placeholder="Add a note for this ${kind==='nodes'?'address':'flow'} (timestamped, attributed to ${esc(author())})…"></textarea><div class="row" style="margin:4px 0"><button class="btn sm pri" id="noteAdd" onclick="ctNoteAddUI()">＋ Add note</button><span class="dim" style="font-size:11px">Edits keep earlier versions; all changes go in the audit log.</span></div>
 ${kind==='nodes'?`<div class="lblrow"><input type="text" id="clName" placeholder="Custom label, e.g. Suspect wallet" value="${esc(L?.name||'')}"><select id="clKind"><option value="">no category</option>${Object.keys(CAT).filter(k=>k!=='tx').map(k=>`<option value="${k}" ${L?.kind===k?'selected':''}>${CAT[k][2]}</option>`).join('')}</select>
 <label class="dim"><input type="checkbox" id="clGlobal" ${GL()[id]?'checked':''}> all cases in this browser</label><button class="btn sm pri" onclick="saveLabel('${esc(id)}')">Apply</button><button class="btn sm" onclick="clearLabel('${esc(id)}')">Reset</button></div>`:''}</div>`};
window.setNote=async function(){};   // the side-card textarea is now a draft box; notes are added with the button
window.ctNoteAddUI=async()=>{if(!CUR)return;const t=$('noteTxt').value;if(!t.trim())return toast('Write a note first');await ctNoteAdd(CUR.kind,CUR.id,t);$('noteTxt').value='';toast('Note added')};
function refreshNoteCard(){const l=$('noteList');if(!l||!CUR||!curCase)return;l.innerHTML=(curCase.journal||[]).filter(e=>e.kind===CUR.kind&&e.target===CUR.id&&!e.deleted).map(e=>noteH(e,false)).join('')}
// summary textarea edits: diffed at save; first open of a case starts the summary baseline
// ---------- panel ----------
const M=document.createElement('div');M.id='cnm';document.body.appendChild(M);let TAB='notes',FQ='',FK='';
M.addEventListener('click',e=>{if(e.target===M)ctNotes(false)});document.addEventListener('keydown',e=>{if(e.key==='Escape'&&M.classList.contains('on'))ctNotes(false)});
window.ctNotes=async(on,tab)=>{on=on===undefined?!M.classList.contains('on'):on;if(tab)TAB=tab;M.classList.toggle('on',!!on);if(on){if(curCase){migrate(curCase);if(writable())diffGraph()}paint()}};
window.ctNotesTab=t=>{TAB=t;paint()};
async function paint(){const c=curCase;
 const head=`<h3>📝 Case notes &amp; audit log<span class="sp" style="flex:1"></span><span class="dim" style="font-size:12px">${c?esc(c.name):'No case open'}</span><button class="btn sm ico" onclick="ctNotes(false)" aria-label="Close">✕</button></h3>
 <div class="tabs"><button class="btn sm ${TAB==='notes'?'on':''}" id="cn-tn" onclick="ctNotesTab('notes')">Notes (${c&&c.journal?c.journal.filter(e=>!e.deleted).length:0})</button><button class="btn sm ${TAB==='audit'?'on':''}" id="cn-ta" onclick="ctNotesTab('audit')">Audit log (${c&&c.audit?c.audit.length:0})</button>
 <span style="flex:1"></span><label class="dim" style="font-size:12px">Your name <input type="text" id="cn-au" value="${esc(author())}" style="width:130px" onchange="localStorage.ct_author=this.value.trim().slice(0,60)||'investigator';ctAudit('author.set',{name:localStorage.ct_author})"></label></div>`;
 if(!c){M.innerHTML=`<div class="card glass">${head}<div class="dim">Open or create a case first (💾 Save case).</div></div>`;return}
 if(TAB==='notes'){const sel=cy.$(':selected')[0];const sid=sel?sel.id():'';
  const list=(c.journal||[]).filter(e=>(!FK||(FK==='deleted'?e.deleted:e.kind===FK&&!e.deleted))&&(!FQ||(e.text+' '+e.target+' '+e.author+' '+(e.tags||[]).join(' ')).toLowerCase().includes(FQ.toLowerCase()))).sort((a,b)=>b.t-a.t);
  M.innerHTML=`<div class="card glass">${head}
  ${writable()?`<textarea id="cn-new" placeholder="New note (summary, hypothesis, call log, next step…)"></textarea><div class="row"><select id="cn-tgt"><option value="case">on the case</option>${sid?`<option value="sel" selected>on selected: ${esc(short2(sid))}</option>`:''}</select>
  <input type="text" id="cn-tags" placeholder="tags, comma separated (optional)"><button class="btn sm pri" id="cn-add" onclick="ctNotesAddPanel()">＋ Add note</button></div>`:'<div class="dim">Read-only case.</div>'}
  <div class="row"><input type="text" id="cn-q" placeholder="Search notes" value="${esc(FQ)}" oninput="ctNotesFilter(this.value,null)"><select id="cn-k" onchange="ctNotesFilter(null,this.value)">${[['','all'],['case','case'],['nodes','addresses'],['edges','flows'],['deleted','deleted']].map(([v,l])=>`<option value="${v}" ${FK===v?'selected':''}>${l}</option>`).join('')}</select>
  <button class="btn sm" onclick="ctNotesCSV()">⬇ Notes CSV</button></div><div id="cn-list">${list.length?list.map(e=>noteH(e,true)).join(''):'<div class="dim">No notes yet.</div>'}</div>
  ${c.notes&&c.notes.case?`<div class="dim" style="font-size:11px;margin-top:6px">The case summary box in the side panel is kept too; its edits are logged (length + hash).</div>`:''}</div>`;
  if(FQ){const q=$('cn-q');q.focus();q.setSelectionRange(FQ.length,FQ.length)}}
 else{const v=await ctAuditVerify(c);const a=c.audit||[];const an=(c.anchors||[]).slice(-1)[0];
  M.innerHTML=`<div class="card glass">${head}
  <div class="row"><b class="${v.ok?'vok':'vbad'}" id="cn-ver">${v.ok?`✓ Chain intact · ${v.n} entr${v.n===1?'y':'ies'}`:`✗ Chain broken at entry ${v.at} (${v.why})`}</b><span class="dim mono hide-s">${v.ok&&v.head?'head '+v.head.slice(0,16)+'…':''}</span>
  <span style="flex:1"></span><button class="btn sm" onclick="ctAuditAnchor()" ${a.length&&writable()?'':'disabled'} title="Get a server-signed receipt for the current head hash">🔏 Anchor</button><button class="btn sm" onclick="ctAuditCheckAnchors()" ${(c.anchors||[]).length?'':'disabled'}>Check receipts</button><button class="btn sm" onclick="ctAuditCSV()">⬇ CSV</button><button class="btn sm" onclick="ctAuditJSON()">⬇ JSON</button></div>
  <div class="dim" style="font-size:11.5px;margin-bottom:6px">Append-only and hash-chained: each entry's SHA-256 covers the previous one, so editing or deleting any entry breaks the chain. ${an?`Last anchored: entry ${an.seq} at ${tUK(an.t*1000)} (server receipt).`:'Not anchored yet: anchoring makes a rewrite of the whole chain detectable.'} <span id="cn-anc"></span></div>
  <div class="tw"><table><tr><th>#</th><th>Time (UK / UTC)</th><th>By</th><th>Action</th><th>Target</th><th>Detail</th><th class="hide-s">Hash</th></tr>${a.slice().reverse().map(e=>`<tr data-seq="${e.seq}"><td>${e.seq}</td><td>${tUK(e.t)}<div class="dim">${tUTC(e.t)}</div></td><td>${esc(e.actor)}</td><td><b>${esc(e.action)}</b></td>
   <td class="mono">${e.target?esc(short2(e.target)):''}</td><td>${esc(Object.entries(e.detail||{}).map(([k,v])=>k+': '+v).join(' · '))}</td><td class="mono hide-s" title="${e.h}">${e.h.slice(0,12)}…</td></tr>`).join('')}</table></div></div>`}}
window.ctNotesFilter=(q,k)=>{if(q!=null)FQ=q;if(k!=null)FK=k;paint()};
window.ctNotesAddPanel=async()=>{const t=$('cn-new').value;if(!t.trim())return toast('Write a note first');const sel=cy.$(':selected')[0];const on=$('cn-tgt').value==='sel'&&sel;
 const tags=$('cn-tags').value.split(',').map(s=>s.trim()).filter(Boolean);await ctNoteAdd(on?(sel.isNode()?'nodes':'edges'):'case',on?sel.id():'',t,null,tags);paint();toast('Note added')};
const q=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
window.ctNotesCSV=()=>{const c=curCase;if(!c)return;const L=['time_uk,time_utc,author,on,target,tags,status,revisions,text'].concat((c.journal||[]).slice().sort((a,b)=>a.t-b.t).map(e=>[tUK(e.t),tUTC(e.t),e.author,e.kind==='case'?'case':e.kind==='nodes'?'address':'flow',e.target,(e.tags||[]).join('; '),e.deleted?'deleted '+tUTC(e.deleted.t):e.edited?'edited':'',e.rev.length,e.text].map(q).join(',')));
 dl('chaintrace-notes-'+c.name.replace(/[^\w-]+/g,'_').slice(0,40)+'.csv',new Blob(['\ufeff'+L.join('\n')],{type:'text/csv'}));audit('notes.exported',{format:'CSV',notes:(c.journal||[]).length})};
window.ctAuditCSV=()=>{const c=curCase;if(!c)return;const L=['seq,time_uk,time_utc,actor,action,target,detail,prev_sha256,sha256'].concat((c.audit||[]).map(e=>[e.seq,tUK(e.t),tUTC(e.t),e.actor,e.action,e.target,JSON.stringify(e.detail),e.prev,e.h].map(q).join(',')));
 dl('chaintrace-audit-'+c.name.replace(/[^\w-]+/g,'_').slice(0,40)+'.csv',new Blob(['\ufeff'+L.join('\n')],{type:'text/csv'}))};
window.ctAuditJSON=()=>{const c=curCase;if(!c)return;dl('chaintrace-audit-'+c.name.replace(/[^\w-]+/g,'_').slice(0,40)+'.json',new Blob([JSON.stringify({format:'chaintrace-audit',version:1,case_id:c.id,case_name:c.name,
 hash:'sha256(JSON.stringify([seq,t,actor,action,target,detail,prev]))',entries:c.audit||[],anchors:c.anchors||[]},null,1)],{type:'application/json'}))};
window.ctAuditAnchor=async()=>{const c=curCase;await Q;const v=await ctAuditVerify(c);if(!v.ok)return toast('Chain is broken: not anchoring');
 try{const r=await fetch('/api/audit/anchor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({case_id:c.id,seq:v.n,head:v.head})});const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);
  (c.anchors=c.anchors||[]).push(j);autosave();await audit('audit.anchored',{seq:j.seq,head:j.head.slice(0,16),receipt:j.sig.slice(0,16)});toast('Anchored: server receipt saved with the case');paint()}catch(e){toast('Anchor failed: '+e.message)}};
window.ctAuditCheckAnchors=async()=>{const c=curCase;const a=c.audit||[];const out=[];
 for(const r of c.anchors||[]){const e=a[r.seq-1];let ok=false;try{const j=await (await fetch('/api/audit/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(r)})).json();ok=j.valid&&e&&e.h===r.head&&r.case_id===c.id}catch(x){}out.push(ok)}
 const bad=out.filter(x=>!x).length;const el=$('cn-anc');if(el){el.className=bad?'vbad':'vok';el.textContent=bad?`✗ ${bad} of ${out.length} receipt(s) do not match this log`:`✓ ${out.length} receipt(s) valid and match this log`}window.CT_ANCHOR_CHECK={n:out.length,bad}};
// toolbar button
const anchor=$('impbtn')||$('tlbtn')||$('rptbtn');if(anchor){const b=document.createElement('button');b.className='btn';b.id='notesbtn';b.title='Case notes & audit log';b.textContent='📝 Notes';b.onclick=()=>ctNotes(true);anchor.after(b)}
// report / evidence pack carry the journal + audit log
const _pl=window.ctReportPayload;if(typeof _pl==='function')window.ctReportPayload=function(meta){const p=_pl.apply(this,arguments);if(curCase){migrate(curCase);p.case.journal=curCase.journal||[];p.case.audit=curCase.audit||[];p.case.anchors=curCase.anchors||[]}return p};
// ?case=<id> deep links open the case before this script loads: record that open once it is there
{const want=new URLSearchParams(location.search).get('case');if(want){let n=0;const iv=setInterval(()=>{n++;
 if(curCase&&curCase.id===want){clearInterval(iv);if(!curCase.readonly){migrate(curCase);if(!curCase.audit_ids)curCase.audit_ids=nodeIds();audit('case.opened',{nodes:curCase.graph?.nodes?.length||0,via:'link'})}}else if(n>40)clearInterval(iv)},250)}}
if(curCase)migrate(curCase);
})();

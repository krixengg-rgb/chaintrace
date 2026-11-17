// ChainTrace v20: bulk import of addresses / transaction hashes from CSV or a pasted list. The server validates (chain detection,
// checksums, de-duplication, per-row errors, size cap) and stores nothing; rows are then added to the case (graph nodes + labels,
// roles, notes) and/or the watchlist, all in this browser. Template: /api/import/template.
(()=>{
const css=document.createElement('style');css.textContent=`
#impm{position:fixed;inset:0;z-index:83;display:none;align-items:center;justify-content:center;background:rgba(3,5,10,.62);padding:12px}#impm.on{display:flex}
#impm .card{width:min(980px,100%);max-height:calc(100vh - 24px);overflow:auto;padding:16px;background:rgba(16,21,36,.97)}
#impm h3{margin:0 0 4px;font-size:15px;text-transform:none;letter-spacing:0;color:var(--txt);display:flex;gap:8px;align-items:center}
#impm textarea{width:100%;box-sizing:border-box;min-height:120px;background:rgba(0,0,0,.25);border:1px solid var(--line);border-radius:10px;padding:8px 10px;color:var(--txt);font:12px var(--mono);outline:0;resize:vertical}
#impm .hint{font-size:11.5px;color:var(--mut);line-height:1.45;margin:4px 0 8px}#impm .acts{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px}
#impm .sum{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px;font-size:12px}#impm .sum span{padding:2px 9px;border-radius:999px;border:1px solid var(--line)}
#impm .sum .ok{border-color:#2ee59d;color:#8ff5c8}#impm .sum .er{border-color:#ff4d6d;color:#ff8da1}#impm .sum .du{border-color:#f6c945;color:#f6dd8a}
#impm .tw{overflow:auto;max-height:46vh;border:1px solid var(--line);border-radius:10px;margin-top:8px;-webkit-overflow-scrolling:touch}
#impm table{width:100%;border-collapse:collapse;font-size:11.5px}#impm td,#impm th{padding:5px 7px;border-top:1px solid var(--line);text-align:left;vertical-align:top}
#impm th{position:sticky;top:0;background:rgba(16,21,36,.98);color:var(--mut);font-size:10.5px;text-transform:uppercase;letter-spacing:.4px}
#impm .mono{font-family:var(--mono);font-size:11px;word-break:break-all}#impm tr.error td{background:rgba(255,77,109,.06)}#impm tr.duplicate td{background:rgba(246,201,69,.05);color:var(--mut)}
#impm .st{white-space:nowrap}#impm .w,#impm .e{white-space:normal;overflow-wrap:anywhere}#impm .w{color:#f6dd8a;font-size:10.5px}#impm .e{color:#ff8da1}
#impm label.ck{display:flex;gap:6px;align-items:center;font-size:12px;color:var(--txt)}
@media (max-width:700px){#impm{align-items:flex-end;padding:0}#impm .card{border-radius:16px 16px 0 0;max-height:94vh;max-height:94dvh;padding:12px}#impm textarea{font-size:16px}
#impm .hide-s{display:none}#impm .acts .btn{flex:1 1 auto}
#impm table,#impm tbody,#impm tr,#impm td{display:block;width:auto}#impm tr:first-child{display:none}#impm tr{border-top:1px solid var(--line);padding:6px 8px;display:grid;grid-template-columns:34px 1fr;gap:2px 6px}
#impm td{border:0;padding:0}#impm td:nth-child(3){grid-column:2}#impm td:nth-child(4){grid-column:2}#impm td:first-child{grid-row:span 3;color:var(--mut)}}`;
document.head.appendChild(css);
const m=document.createElement('div');m.id='impm';m.innerHTML=`<div class="card glass" role="dialog" aria-modal="true" aria-labelledby="imph">
<h3 id="imph">⤒ Bulk import addresses &amp; transactions</h3>
<div class="hint">Paste one address or transaction hash per line (optionally <code>value, label, role, notes</code>), or load a CSV with a header row: <code>value</code> (or address / tx / hash) and optional <code>chain</code>, <code>label</code>, <code>role</code> (victim, suspect, exchange, other) and <code>notes</code>. The chain is detected from the format and checksums are verified. Max ${'500'} rows / 256 KB. The server only validates; nothing is stored there. Imported labels are your own attributions.</div>
<div class="acts" style="margin-top:0"><button class="btn sm" onclick="document.getElementById('impf').click()">📄 Choose CSV…</button><input type="file" id="impf" accept=".csv,.txt,.tsv,text/csv,text/plain" style="display:none"><a class="btn sm" href="/api/import/template" download id="imptpl">⬇ Template CSV</a><span class="dim" id="impfn" style="font-size:11.5px"></span></div>
<textarea id="impt" spellcheck="false" placeholder="bc1q… , Victim wallet, victim&#10;0x… , , suspect&#10;base:0x…&#10;0x<64-hex tx hash>"></textarea>
<div class="acts"><button class="btn pri" id="impv" onclick="ctImpValidate()">Validate</button><span id="impmsg" class="dim" style="font-size:12px"></span></div>
<div id="impres"></div></div>`;
document.body.appendChild(m);m.addEventListener('click',e=>{if(e.target===m)ctImport(false)});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&m.classList.contains('on'))ctImport(false)});
let RES=null;window.CT_IMPORT=()=>RES;
$('impf').onchange=async()=>{const f=$('impf').files[0];if(!f)return;if(f.size>256*1024){toast('File too large (max 256 KB)');return}$('impt').value=await f.text();$('impfn').textContent=f.name;$('impf').value='';ctImpValidate()};
const cname=c=>({btc:'Bitcoin',eth:'Ethereum',sol:'Solana',tron:'TRON',xrp:'XRP',bsc:'BSC',arb:'Arbitrum',base:'Base',polygon:'Polygon',op:'OP',ltc:'Litecoin',doge:'Dogecoin',bch:'Bitcoin Cash'})[c]||c||'–';
window.ctImport=on=>{m.classList.toggle('on',on!==false);if(on!==false)setTimeout(()=>$('impt').focus(),50)};
window.ctImpValidate=async()=>{const t=$('impt').value;if(!t.trim())return toast('Paste addresses or choose a CSV first');const b=$('impv');b.disabled=true;b.textContent='Validating…';
 try{const r=await fetch('/api/import/parse',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t})});const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);RES=j;render()}
 catch(e){$('impres').innerHTML=`<div class="e" style="margin-top:10px">✗ ${esc(e.message)}</div>`;RES=null}finally{b.disabled=false;b.textContent='Validate'}};
function render(){const s=RES.summary;const ok=RES.rows.filter(r=>r.status==='ok');
 $('impres').innerHTML=`<div class="sum"><span class="ok">✓ ${s.ok} valid</span>${s.errors?`<span class="er">✗ ${s.errors} error(s)</span>`:''}${s.duplicates?`<span class="du">⧉ ${s.duplicates} duplicate(s)</span>`:''}${s.warnings?`<span class="du">⚠ ${s.warnings} with warnings</span>`:''}<span>${s.addresses} address(es) · ${s.txs} tx(s)</span><span>${s.chains.map(cname).join(', ')||'–'}</span>${s.capped?`<span class="er">only the first ${s.max_rows} rows were read</span>`:''}</div>
 <div class="tw"><table><tr><th>Row</th><th>Status</th><th>Chain</th><th>Value</th><th class="hide-s">Label</th><th class="hide-s">Role</th><th class="hide-s">Notes</th></tr>${RES.rows.map(r=>`<tr class="${r.status}" data-row="${r.row}"><td>${r.row}</td>
  <td class="st">${r.status==='ok'?'✓':r.status==='duplicate'?'⧉ dup':'✗'}${r.error?`<div class="e">${esc(r.error)}</div>`:''}${(r.warnings||[]).map(w=>`<div class="w">⚠ ${esc(w)}</div>`).join('')}</td>
  <td>${esc(cname(r.chain))}${r.kind?`<div class="dim">${r.kind}</div>`:''}</td><td class="mono">${esc(r.id||r.value)}</td><td class="hide-s">${esc(r.label)}</td><td class="hide-s">${esc(r.role)}</td><td class="hide-s">${esc(r.notes)}</td></tr>`).join('')}</table></div>
 <div class="acts"><label class="ck"><input type="checkbox" id="impexp"> also look up the first 10 addresses</label><span style="flex:1"></span>
  ${s.errors+s.duplicates?'<button class="btn sm" onclick="ctImpErrCSV()">⬇ Error report</button>':''}
  <button class="btn" id="impwatch" onclick="ctImpWatch()" ${ok.some(r=>r.kind==='address')?'':'disabled'}>👁 Add ${ok.filter(r=>r.kind==='address').length} address(es) to watchlist</button>
  <button class="btn pri" id="impcase" onclick="ctImpCase()" ${ok.length?'':'disabled'}>📁 Add ${ok.length} to case &amp; graph</button></div>`}
window.ctImpCase=async()=>{if(!RES)return;const ok=RES.rows.filter(r=>r.status==='ok');if(!ok.length)return;await ensureCase();
 const nodes=ok.map(r=>({id:r.id,chain:r.chain,kind:r.kind==='tx'?'tx':(r.role==='exchange'?'exchange':undefined),name:r.label||(r.kind==='tx'?(cname(r.chain)+' tx '+r.id.slice(3,13)):''),imported:true}));
 add({nodes,edges:[]},null);const L=window.CT_LOSS||{victims:[],victim_txs:[],suspect:''};let nl=0,nn=0,nr=0;
 for(const r of ok){if(r.label){curCase.labels[r.id]={name:r.label,kind:r.role==='exchange'?'exchange':(curCase.labels[r.id]||{}).kind||null,at:Date.now(),source:'import'};nl++}
  if(r.notes){if(typeof ctNoteAdd==='function')ctNoteAdd(r.kind==='tx'?'edges':'nodes',r.id,r.notes,'import');else curCase.notes.nodes[r.id]=((curCase.notes.nodes[r.id]?curCase.notes.nodes[r.id]+'\n':'')+r.notes);nn++}
  if(r.role==='victim'){if(r.kind==='tx'){if(!L.victim_txs.includes(r.id.slice(3))){ctLossMark(r.id.slice(3),'t');nr++}}else if(!L.victims.includes(r.id)){ctLossMark(r.id,'v');nr++}}
  if(r.role==='suspect'&&r.kind==='address'&&L.suspect!==r.id){ctLossMark(r.id,'s');nr++}}
 applyCaseDecor();autosave();caseCard();if(typeof ctAudit==='function')ctAudit('import',{rows:RES.summary.rows,added:ok.length,labels:nl,notes:nn,roles:nr,errors:RES.summary.errors,duplicates:RES.summary.duplicates});
 $('impmsg').textContent=`✓ ${ok.length} added to “${curCase.name}” (${nl} label(s), ${nn} note(s), ${nr} role mark(s))`;toast(`Imported ${ok.length} item(s)`);window.CT_IMPORT_DONE={added:ok.length,labels:nl,notes:nn,roles:nr};
 if($('impexp').checked){const as=ok.filter(r=>r.kind==='address').slice(0,10);for(const r of as){await expand(r.id);await new Promise(z=>setTimeout(z,1200))}}};
window.ctImpWatch=()=>{if(!RES||typeof ctWatchAddMany!=='function')return;const as=RES.rows.filter(r=>r.status==='ok'&&r.kind==='address');
 const res=ctWatchAddMany(as.map(r=>({address:r.id,chain:r.chain,name:r.label,note:r.notes})));if(typeof ctAudit==='function')ctAudit('import_watchlist',{added:res.added,skipped:res.skipped});
 $('impmsg').textContent=`✓ ${res.added} address(es) added to the watchlist${res.skipped?` (${res.skipped} already watched or over the 200 limit)`:''}; the first check records a baseline`;toast(`${res.added} added to watchlist`);window.CT_IMPORT_WATCH=res};
window.ctImpErrCSV=()=>{const q=v=>'"'+String(v??'').replace(/"/g,'""')+'"';const L=['row,status,value,error,warnings'].concat(RES.rows.filter(r=>r.status!=='ok'||r.warnings.length).map(r=>[r.row,r.status,r.value,r.error||'',r.warnings.join(' | ')].map(q).join(',')));
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([L.join('\n')],{type:'text/csv'}));a.download='chaintrace-import-errors.csv';document.body.appendChild(a);a.click();a.remove()};
const anchor=$('tlbtn')||$('lossbtn')||$('rptbtn');if(anchor){const b=document.createElement('button');b.className='btn';b.id='impbtn';b.title='Bulk import addresses / transactions (CSV or paste)';b.textContent='⤒ Import';b.onclick=()=>ctImport(true);anchor.after(b)}
})();

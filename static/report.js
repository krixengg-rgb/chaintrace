// ChainTrace v8: PDF investigation report (modal -> POST /api/report -> PDF download). Loaded after bridge.js.
(()=>{
const css=document.createElement('style');css.textContent=`
#rptm{position:fixed;inset:0;z-index:80;display:none;align-items:center;justify-content:center;background:rgba(3,5,10,.62);padding:12px}
#rptm.on{display:flex}
#rptm .card{width:min(540px,100%);max-height:calc(100vh - 24px);overflow:auto;padding:16px 16px 14px;background:rgba(16,21,36,.96)}
#rptm h3{margin:0 0 4px;font-size:15px;display:flex;align-items:center;gap:8px}
#rptm label{display:block;font-size:12px;color:var(--mut);margin:10px 0 4px}
#rptm input[type=text]{width:100%;box-sizing:border-box;background:rgba(0,0,0,.25);border:1px solid var(--line);border-radius:10px;padding:8px 10px;color:var(--txt);outline:0;font:13px var(--font)}
#rptm input[type=text]:focus{border-color:rgba(124,92,255,.6)}
#rptm textarea{min-height:84px;box-sizing:border-box}
#rptm .row2{display:grid;grid-template-columns:1fr 1fr;gap:0 10px}
#rptm .chk{display:flex;gap:7px;align-items:center;font-size:12.5px;color:var(--txt);margin-top:9px;cursor:pointer}
#rptm .acts{display:flex;gap:8px;justify-content:flex-end;margin-top:14px;flex-wrap:wrap}
#rptm .sum{font-size:12px;color:var(--mut);margin-top:6px}
#rptm .res{margin-top:10px;font-size:11.5px;word-break:break-all}
#rptm .res code{font-family:var(--mono);font-size:11px;color:#9fe7f5}
#rptm details{margin-top:12px;border:1px solid var(--line);border-radius:12px;padding:8px 10px;background:rgba(0,0,0,.14)}
#rptm summary{cursor:pointer;font-size:13px;font-weight:600;list-style:none;display:flex;align-items:center;gap:6px}
#rptm summary::-webkit-details-marker{display:none}#rptm summary:after{content:'▾';margin-left:auto;color:var(--mut)}#rptm details[open] summary:after{content:'▴'}
#rptm .lenote{font-size:11.5px;color:var(--mut);margin:6px 0 2px;line-height:1.4}#rptm .lenote b{color:#ffcf8a}
#rptm .sub{font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:var(--mut);margin:12px 0 0}
#rptm input[type=date]{width:100%;box-sizing:border-box;background:rgba(0,0,0,.25);border:1px solid var(--line);border-radius:10px;padding:7px 10px;color:var(--txt);color-scheme:dark;font:13px var(--font)}
#lev{font-size:12px;margin-top:8px}#lev .vp{display:inline-block;margin:3px 4px 0 0;padding:3px 8px;border-radius:999px;border:1px solid var(--line);background:rgba(34,211,238,.08)}
#lev .vp.lead{border-color:rgba(255,159,67,.5);background:rgba(255,159,67,.1);color:#ffcf8a}
@media (max-width:600px){#rptm input[type=text],#rptm input[type=date],#rptm textarea{font-size:16px}#rptm .acts .btn{flex:1 1 auto}
#rptm .row2{grid-template-columns:1fr}#rptm{align-items:flex-end;padding:0}#rptm .card{border-radius:16px 16px 0 0;max-height:92vh;max-height:92dvh}}`;
document.head.appendChild(css);
// ---- API query log (kept with the case; listed in the report appendix) ----
window.CT_LOG=window.CT_LOG||[];
const _f=window.fetch.bind(window);
window.fetch=function(u,o){try{const s=typeof u==='string'?u:(u&&u.url)||'';const m=(o&&o.method)||'GET';
  if(s.startsWith('/api/')&&!/^\/api\/(report|trace\/[0-9a-f]+$|cache|prices)/.test(s))CT_LOG.push({t:Date.now(),url:(m!=='GET'?m+' ':'')+s});if(CT_LOG.length>1500)CT_LOG.splice(0,CT_LOG.length-1500)}catch(e){}
 return _f(u,o)};
const mergeLog=()=>{const a=[...((curCase&&curCase.log)||[]),...CT_LOG],seen=new Set(),out=[];
 for(const x of a){const k=x.t+'|'+x.url;if(!seen.has(k)){seen.add(k);out.push(x)}}return out.sort((a,b)=>a.t-b.t).slice(-800)};
const _snap=window.snapshot;window.snapshot=function(){const s=_snap();s.log=mergeLog();return s};
// ---- UI ----
const m=document.createElement('div');m.id='rptm';m.innerHTML=`<div class="card glass" role="dialog" aria-modal="true" aria-labelledby="rpth">
 <h3 id="rpth">📄 Export PDF report</h3><div class="sum" id="rptsum"></div>
 <div class="row2"><div><label for="rptref">Case reference</label><input type="text" id="rptref" maxlength="80" placeholder="e.g. crime / intel ref"></div>
 <div><label for="rptinv">Investigator</label><input type="text" id="rptinv" maxlength="120" placeholder="Name, role / unit"></div></div>
 <label for="rptmk">Handling marking (optional)</label><input type="text" id="rptmk" maxlength="60" placeholder="Printed in the header and footer of every page">
 <label for="rptnotes">Notes for the report (purpose, scope, context)</label><textarea id="rptnotes" maxlength="4000" placeholder="e.g. Tracing proceeds of victim payment on 12/09/2026…"></textarea>
 <label class="chk"><input type="checkbox" id="rptimg" checked> Include graph image</label>
 <label class="chk"><input type="checkbox" id="rptnoise"> Include noise-filtered flows (dust / spam tokens)</label>
 <details id="lepack"><summary>🇬🇧 UK police evidence pack</summary>
  <div class="lenote">Optional fields you fill in. ChainTrace never creates or checks these references; leave anything blank. The pack adds a PDF section, an exchange/VASP schedule and a <b>DRAFT</b> records request per exchange for you to complete and serve through the proper legal route. <b>Drafts are not court orders.</b></div>
  <div class="sub">Case</div>
  <div class="row2"><div><label for="le_crime_ref">Force crime / occurrence ref</label><input type="text" id="le_crime_ref" maxlength="60"></div>
  <div><label for="le_rf_ref">Report Fraud / Action Fraud ref</label><input type="text" id="le_rf_ref" maxlength="60" placeholder="e.g. NFRC…"></div></div>
  <div class="row2"><div><label for="le_nfib_code">NFIB code (if known)</label><input type="text" id="le_nfib_code" maxlength="60" placeholder="Home Office Counting Rules code"></div>
  <div><label for="le_victim_ref">Victim / case ref</label><input type="text" id="le_victim_ref" maxlength="80"></div></div>
  <label for="le_offence">Offence(s) under investigation</label><input type="text" id="le_offence" maxlength="300" placeholder="e.g. Fraud by false representation, Fraud Act 2006 s.2">
  <div class="row2"><div><label for="le_period_from">Period of interest from</label><input type="date" id="le_period_from"></div>
  <div><label for="le_period_to">to</label><input type="date" id="le_period_to"></div></div>
  <label for="le_facts">Facts of the case (short)</label><textarea id="le_facts" maxlength="2500" placeholder="What happened, when, the loss, why the exchange records are needed"></textarea>
  <div class="sub">Officer (remembered on this device)</div>
  <div class="row2"><div><label for="le_officer_name">Name</label><input type="text" id="le_officer_name" maxlength="80" autocomplete="name"></div>
  <div><label for="le_officer_rank">Rank / role</label><input type="text" id="le_officer_rank" maxlength="60"></div></div>
  <div class="row2"><div><label for="le_officer_number">Collar / warrant no.</label><input type="text" id="le_officer_number" maxlength="30"></div>
  <div><label for="le_force">Force / unit</label><input type="text" id="le_force" maxlength="120"></div></div>
  <div class="row2"><div><label for="le_officer_email">Email</label><input type="text" id="le_officer_email" maxlength="120" inputmode="email" autocomplete="email"></div>
  <div><label for="le_officer_phone">Phone</label><input type="text" id="le_officer_phone" maxlength="40" inputmode="tel" autocomplete="tel"></div></div>
  <div id="lev"></div>
 </details>
 <div class="acts"><button class="btn" onclick="ctReportClose()">Cancel</button><button class="btn" id="packgo" onclick="ctPackGo()">🇬🇧 Evidence pack (.zip)</button><button class="btn pri" id="rptgo" onclick="ctReportGo()">Generate PDF</button></div>
 <div class="res" id="rptres"></div></div>`;
document.body.appendChild(m);m.addEventListener('click',e=>{if(e.target===m)ctReportClose()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&m.classList.contains('on'))ctReportClose()});
const sb=$('savebtn');if(sb){const b=document.createElement('button');b.className='btn';b.id='rptbtn';b.title='Export PDF report';b.textContent='📄 Report';b.onclick=()=>ctReportOpen();sb.after(b)}
const dd=document.querySelector('#exportMenu .dd');if(dd){const b=document.createElement('button');b.className='btn sm';b.textContent='PDF report…';b.onclick=()=>{exportMenu.classList.remove('open');ctReportOpen()};dd.prepend(b)}
const _lc=window.listCases;window.listCases=async function(){await _lc();document.querySelectorAll('#caselist .citem').forEach(it=>{const ex=it.querySelector('button[onclick^="exportCase"]');if(!ex||it.querySelector('.rptc'))return;
 const id=(ex.getAttribute('onclick').match(/'([^']+)'/)||[])[1];const b=document.createElement('button');b.className='btn sm rptc';b.textContent='PDF';b.onclick=()=>ctReportCase(id);ex.after(b)})};
const els=noise=>{const keep=x=>!x.data('grp')&&!x.data('meta')&&!x.data('tmp')&&(noise||!x.hasClass('noise'));
 const nodes=cy.nodes().filter(keep).map(n=>({...(n.data('info')||{}),id:n.id()}));
 const ids=new Set(nodes.map(n=>n.id));
 const edges=cy.edges().filter(keep).map(e=>({...(e.data('info')||{}),source:e.data('source'),target:e.data('target'),xchain:e.data('xchain')||undefined,heur:e.data('heur')||undefined})).filter(e=>ids.has(e.source)&&ids.has(e.target));
 return{nodes,edges,hidden:cy.elements('.noise').length}};
window.ctReportOpen=function(){if(!cy.nodes().length)return toast('Nothing to report: run a lookup or open a case first');
 const rm=(curCase&&curCase.report_meta)||{};$('rptref').value=rm.ref||'';$('rptinv').value=rm.investigator||localStorage.ct_inv||'';$('rptmk').value=rm.marking||'';$('rptnotes').value=rm.notes||'';
 const g=els(false);$('rptsum').textContent=`${curCase?'Case “'+curCase.name+'”':'Current graph (not saved as a case)'} · ${g.nodes.length} nodes · ${g.edges.length} flows`+(g.hidden?` · ${g.hidden} noise-hidden`:'');
 const le=Object.assign({},ctOfficer(),rm.le||{});for(const k of LEK)$('le_'+k).value=le[k]||'';ctVaspPreview();
 $('rptres').innerHTML='';m.classList.add('on');if(!matchMedia('(max-width:600px)').matches)setTimeout(()=>$('rptref').focus(),50)};
const LEK=['crime_ref','rf_ref','nfib_code','victim_ref','offence','period_from','period_to','facts','officer_name','officer_rank','officer_number','force','officer_email','officer_phone'];
const OFK=['officer_name','officer_rank','officer_number','force','officer_email','officer_phone'];
window.ctOfficer=()=>{try{return JSON.parse(localStorage.ct_officer||'{}')}catch(e){return{}}};
window.ctLE=()=>{const o={};for(const k of LEK){const v=$('le_'+k).value.trim();if(v)o[k]=k.startsWith('period_')&&/^\d{4}-\d\d-\d\d$/.test(v)?v.split('-').reverse().join('/'):v}return o};
const leRaw=()=>{const o={};for(const k of LEK){const v=$('le_'+k).value.trim();if(v)o[k]=v}return o};
window.ctVaspPreview=function(){const g=els(false),by={};for(const n of g.nodes){if(String(n.id).startsWith('tx:'))continue;const L=effLabel(n.id);let e=null,lead=false;
  if(L&&L.kind==='exchange')e=(L.name||'').split(/[\s:(]/)[0]||L.name;else if(n.kind==='exchange')e=(n.name||'Exchange').split(/[\s:]/)[0];else if(n.suggested&&n.suggested.entity){e=n.suggested.entity;lead=true}
  if(!e)continue;const k=e.toLowerCase();by[k]=by[k]||{e,n:0,lead:true};by[k].n++;by[k].lead=by[k].lead&&lead}
 const v=Object.values(by);$('lev').innerHTML=v.length?'Exchanges / VASPs in this graph (a draft request each): '+v.map(x=>`<span class="vp${x.lead?' lead':''}">${esc(x.e)} · ${x.n}${x.lead?' · inferred':''}</span>`).join(''):'<span class="dim">No exchange / VASP addresses in this graph yet. The pack will still include the PDF and how-to.</span>'};
window.ctReportClose=()=>m.classList.remove('on');
window.ctReportCase=async function(id){if(!curCase||curCase.id!==id)await openCase(id);setTimeout(ctReportOpen,400)};
window.ctReportPayload=function(meta){const g=els(meta.noise);const s=snapshot();
 const labs={};for(const n of g.nodes){const L=effLabel(n.id);if(L)labs[n.id]=L}
 const c=curCase||{name:defaultName(),created:Date.now(),updated:Date.now(),notes:{case:'',nodes:{},edges:{}}};
 const tr=s.trace?Object.fromEntries(Object.entries(s.trace).filter(([k])=>!['nodes','edges'].includes(k))):null;
 let png=null;if(meta.img){try{png=cy.png({full:true,scale:2,maxWidth:3000,maxHeight:3000,bg:'#070a12'})}catch(e){}}
 return{meta:{ref:meta.ref,investigator:meta.investigator,marking:meta.marking,notes:meta.notes,noise_hidden_excluded:meta.noise?0:g.hidden,tz:Intl.DateTimeFormat().resolvedOptions().timeZone},
  case:{id:c.id||null,name:c.name,created:c.created,updated:c.updated,query:s.query,mode:s.mode,params:s.params,notes:c.notes||{},labels:labs,risk:s.risk},
  nodes:g.nodes,edges:g.edges,trace:tr,log:mergeLog(),png}};
const saveLE=()=>{const r=leRaw(),of={};for(const k of OFK)if(r[k])of[k]=r[k];localStorage.ct_officer=JSON.stringify(of);
 if(curCase){const cl={};for(const k of LEK)if(!OFK.includes(k)&&r[k])cl[k]=r[k];curCase.report_meta=Object.assign(curCase.report_meta||{},{le:cl});autosave()}};
const dl=(blob,nm)=>{const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=nm;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),6000)};
window.ctPackGo=async function(){const b=$('packgo');const meta={ref:$('rptref').value.trim(),investigator:$('rptinv').value.trim(),marking:$('rptmk').value.trim(),notes:$('rptnotes').value.trim(),img:$('rptimg').checked,noise:$('rptnoise').checked};
 localStorage.ct_inv=meta.investigator;if(curCase){curCase.report_meta=Object.assign(curCase.report_meta||{},{ref:meta.ref,investigator:meta.investigator,marking:meta.marking,notes:meta.notes})}saveLE();
 b.disabled=true;b.textContent='Building pack…';$('rptres').textContent='';
 try{const pl=ctReportPayload(meta);pl.meta.le=ctLE();pl.meta.evidence_pack=true;
  const r=await fetch('/api/evidence-pack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pl)});
  if(!r.ok){let d='';try{d=(await r.json()).detail}catch(e){}throw new Error(d||('HTTP '+r.status))}
  const blob=await r.blob();const H=k=>r.headers.get(k)||'';let vs=[];try{vs=JSON.parse(H('X-Pack-VASPs')||'[]')}catch(e){}
  const cd=H('Content-Disposition');const nm=(cd.match(/filename="([^"]+)"/)||[])[1]||'ChainTrace-evidence-pack.zip';dl(blob,nm);
  if(curCase){(curCase.reports=curCase.reports||[]).push({at:Date.now(),ref:meta.ref,pack_sha256:H('X-Pack-SHA256'),pdf_sha256:H('X-Report-SHA256'),case_sha256:H('X-Case-SHA256'),pages:+H('X-Report-Pages')||null,vasps:vs.length});autosave()}
  $('rptres').innerHTML=`✅ <b>${esc(nm)}</b> · report ${esc(H('X-Report-Pages'))} pages · ${vs.length} draft request(s)${vs.length?': '+vs.map(v=>esc(v.entity)+(v.lead_only?' (inferred)':'')).join(', '):''}<br>Pack SHA-256 <code>${esc(H('X-Pack-SHA256'))}</code><br>PDF SHA-256 <code>${esc(H('X-Report-SHA256'))}</code><br>Case data SHA-256 <code>${esc(H('X-Case-SHA256'))}</code><div class="dim" style="margin-top:4px">Drafts are marked DRAFT – NOT A COURT ORDER. Complete them, choose the legal route and take legal advice before serving. See HOW_TO_USE.txt in the zip.</div>`;
  window.CT_LAST_PACK={sha:H('X-Pack-SHA256'),pdf:H('X-Report-SHA256'),csha:H('X-Case-SHA256'),vasps:vs,name:nm,size:blob.size};toast('Evidence pack downloaded')}
 catch(e){$('rptres').innerHTML=`<div class="warnbox">Evidence pack failed: ${esc(e.message)}</div>`}
 finally{b.disabled=false;b.textContent='🇬🇧 Evidence pack (.zip)'}};
window.ctReportGo=async function(){const b=$('rptgo');const meta={ref:$('rptref').value.trim(),investigator:$('rptinv').value.trim(),marking:$('rptmk').value.trim(),notes:$('rptnotes').value.trim(),img:$('rptimg').checked,noise:$('rptnoise').checked};
 localStorage.ct_inv=meta.investigator;if(curCase){curCase.report_meta=Object.assign(curCase.report_meta||{},{ref:meta.ref,investigator:meta.investigator,marking:meta.marking,notes:meta.notes});autosave()}
 b.disabled=true;b.textContent='Generating…';$('rptres').textContent='';
 saveLE();const pl=ctReportPayload(meta);const le=ctLE();if(Object.keys(le).length)pl.meta.le=le;
 try{const r=await fetch('/api/report',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pl)});
  if(!r.ok){let d='';try{d=(await r.json()).detail}catch(e){}throw new Error(d||('HTTP '+r.status))}
  const blob=await r.blob();const sha=r.headers.get('X-Report-SHA256')||'',csha=r.headers.get('X-Case-SHA256')||'',pages=r.headers.get('X-Report-Pages')||'?';
  const D=new Date(),z=n=>String(n).padStart(2,'0'),ts=D.getFullYear()+z(D.getMonth()+1)+z(D.getDate())+'-'+z(D.getHours())+z(D.getMinutes());const nm=('ChainTrace-report-'+(meta.ref||(curCase&&curCase.name)||'graph')).replace(/[^A-Za-z0-9._-]+/g,'_').slice(0,70)+'-'+ts+'.pdf';
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=nm;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),4000);
  if(curCase){(curCase.reports=curCase.reports||[]).push({at:Date.now(),ref:meta.ref,pdf_sha256:sha,case_sha256:csha,pages:+pages||null});autosave()}
  $('rptres').innerHTML=`✅ <b>${esc(nm)}</b> · ${esc(pages)} pages<br>PDF SHA-256 <code>${esc(sha)}</code><br>Case data SHA-256 <code>${esc(csha)}</code><div class="dim" style="margin-top:4px">Record the PDF hash in your notes. A file cannot contain its own hash.</div>`;
  window.CT_LAST_REPORT={sha,csha,pages:+pages,name:nm,size:blob.size};toast('PDF report downloaded')}
 catch(e){$('rptres').innerHTML=`<div class="warnbox">Report failed: ${esc(e.message)}</div>`}
 finally{b.disabled=false;b.textContent='Generate PDF'}};
const PP=new URLSearchParams(location.search);if(PP.get('pack')==='1'){let n=0;const iv=setInterval(()=>{n++;if(window.cy&&cy.nodes().length>1){clearInterval(iv);setTimeout(()=>{ctReportOpen();const d=$('lepack');d.open=true;setTimeout(()=>d.scrollIntoView({block:'start'}),120)},900)}else if(n>240)clearInterval(iv)},500)}
})();

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
@media (max-width:600px){#rptm .row2{grid-template-columns:1fr}#rptm{align-items:flex-end;padding:0}#rptm .card{border-radius:16px 16px 0 0;max-height:92vh}}`;
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
 <div class="acts"><button class="btn" onclick="ctReportClose()">Cancel</button><button class="btn pri" id="rptgo" onclick="ctReportGo()">Generate PDF</button></div>
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
 $('rptres').innerHTML='';m.classList.add('on');setTimeout(()=>$('rptref').focus(),50)};
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
window.ctReportGo=async function(){const b=$('rptgo');const meta={ref:$('rptref').value.trim(),investigator:$('rptinv').value.trim(),marking:$('rptmk').value.trim(),notes:$('rptnotes').value.trim(),img:$('rptimg').checked,noise:$('rptnoise').checked};
 localStorage.ct_inv=meta.investigator;if(curCase){curCase.report_meta={ref:meta.ref,investigator:meta.investigator,marking:meta.marking,notes:meta.notes};autosave()}
 b.disabled=true;b.textContent='Generating…';$('rptres').textContent='';
 try{const r=await fetch('/api/report',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(ctReportPayload(meta))});
  if(!r.ok){let d='';try{d=(await r.json()).detail}catch(e){}throw new Error(d||('HTTP '+r.status))}
  const blob=await r.blob();const sha=r.headers.get('X-Report-SHA256')||'',csha=r.headers.get('X-Case-SHA256')||'',pages=r.headers.get('X-Report-Pages')||'?';
  const D=new Date(),z=n=>String(n).padStart(2,'0'),ts=D.getFullYear()+z(D.getMonth()+1)+z(D.getDate())+'-'+z(D.getHours())+z(D.getMinutes());const nm=('ChainTrace-report-'+(meta.ref||(curCase&&curCase.name)||'graph')).replace(/[^A-Za-z0-9._-]+/g,'_').slice(0,70)+'-'+ts+'.pdf';
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=nm;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),4000);
  if(curCase){(curCase.reports=curCase.reports||[]).push({at:Date.now(),ref:meta.ref,pdf_sha256:sha,case_sha256:csha,pages:+pages||null});autosave()}
  $('rptres').innerHTML=`✅ <b>${esc(nm)}</b> · ${esc(pages)} pages<br>PDF SHA-256 <code>${esc(sha)}</code><br>Case data SHA-256 <code>${esc(csha)}</code><div class="dim" style="margin-top:4px">Record the PDF hash in your notes. A file cannot contain its own hash.</div>`;
  window.CT_LAST_REPORT={sha,csha,pages:+pages,name:nm,size:blob.size};toast('PDF report downloaded')}
 catch(e){$('rptres').innerHTML=`<div class="warnbox">Report failed: ${esc(e.message)}</div>`}
 finally{b.disabled=false;b.textContent='Generate PDF'}};
})();

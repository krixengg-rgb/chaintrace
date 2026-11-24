// ChainTrace v33: DRAFT investigator witness statement (generic layout, not the official MG11). The officer's own details are kept in this
// browser (localStorage ct_stmt) and sent only with the request that builds the draft. Output: DOCX, PDF, or zip (both + the evidence pack they cite).
(()=>{
const E=s=>typeof esc==='function'?esc(s):String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const css=document.createElement('style');css.textContent=`#stm{position:fixed;inset:0;z-index:80;display:none;background:rgba(5,8,18,.62);backdrop-filter:blur(3px);overflow:auto;padding:24px 10px}
#stm.on{display:block}#stm>.card{max-width:760px;margin:0 auto;padding:18px}#stm .draft{font-size:15px;font-weight:800;color:#ff8fa3;border:2px solid #ff5c7a;border-radius:10px;padding:8px;text-align:center;background:rgba(255,92,122,.08);letter-spacing:.03em}
#stm .ban{font-size:11.5px;border:1px dashed rgba(246,201,69,.6);border-radius:9px;padding:6px 8px;background:rgba(246,201,69,.07);color:#ffe3a3;margin:8px 0}
#stm .g2{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px}#stm label{display:flex;flex-direction:column;gap:3px;font-size:11.5px;color:var(--mut);min-width:0}
#stm input,#stm textarea{width:100%;box-sizing:border-box;background:rgba(0,0,0,.25);border:1px solid var(--line);border-radius:8px;padding:6px 8px;color:var(--txt);outline:0;font:inherit;font-size:12.5px}
#stm .acts{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}#stm code{font-size:10.5px;word-break:break-all}
@media (max-width:700px){#stm{padding:0}#stm>.card{border-radius:0;min-height:100%;padding:14px 12px}#stm .g2{grid-template-columns:1fr}}`;document.head.appendChild(css);
const F=[['name','Your full name','e.g. as it will appear on the signed statement'],['role','Rank / role (and collar number)',''],['force','Force / organisation',''],['age','Age if under 18',"Over 18"],
 ['prefix','Exhibit reference prefix','your initials, e.g. AB (exhibits become AB/1, AB/2…)'],['date','Statement date (when you sign)','dd/mm/yyyy'],['tool_url','ChainTrace instance URL',location.origin]];
const get=()=>{try{return JSON.parse(localStorage.ct_stmt||'{}')}catch(e){return{}}};
window.ctStatement=function(open=true){let m=document.getElementById('stm');
 if(!m){m=document.createElement('div');m.id='stm';const v=get(),of=(typeof ctOfficer==='function'?ctOfficer():{});
  const val=k=>v[k]??({name:of.officer_name,role:[of.officer_rank,of.officer_number].filter(Boolean).join(' '),force:of.force,age:'Over 18',tool_url:location.origin}[k]||'');
  m.innerHTML=`<div class="card glass"><h3>📝 Investigator statement draft<span class="sp"></span><button class="btn sm" onclick="ctStatement(false)">✕ Close</button></h3>
  <div class="draft">DRAFT – CHECK AND AMEND BEFORE SIGNING</div>
  <div class="ban">Generic witness-statement layout made from this case: methodology, tools and data sources (with versions and list dates), findings with tx hashes, UTC + UK time, amounts in the coin and GBP, heuristics stated as opinion / lead, exhibits = the evidence-pack files with SHA-256, and the audit-log anchor. It is <b>not</b> the official MG11 form; the statement of truth / declaration is left as a placeholder for your force-approved wording. Anything not entered stays as a [placeholder].</div>
  <div class="g2">${F.map(([k,l,p])=>`<label>${E(l)}<input id="st_${k}" value="${E(val(k))}" placeholder="${E(p)}"></label>`).join('')}</div>
  <label style="margin-top:8px">Training and experience (one or two sentences)<textarea id="st_experience" rows="2" placeholder="e.g. I have completed … and have conducted blockchain analysis in … investigations">${E(v.experience||'')}</textarea></label>
  <div class="acts"><button class="btn primary" id="st_zip" onclick="ctStatementGo('zip')">⬇ Draft + evidence pack (.zip)</button><button class="btn" id="st_docx" onclick="ctStatementGo('docx')">⬇ DOCX (editable)</button><button class="btn" id="st_pdf" onclick="ctStatementGo('pdf')">⬇ PDF</button></div>
  <div class="dim" style="font-size:11px;margin-top:6px">The exhibits list cites the SHA-256 of each file in the evidence pack generated in the same request. Use the .zip so the pack you exhibit is exactly the one the draft lists.</div>
  <div id="st_res" style="margin-top:8px;font-size:12px"></div></div>`;document.body.appendChild(m)}
 m.classList.toggle('on',!!open)};
window.ctStatementGo=async function(fmt){const st={};for(const [k] of F)st[k==='prefix'?'exhibit_prefix':k]=document.getElementById('st_'+k).value.trim();st.experience=document.getElementById('st_experience').value.trim();
 const keep={};for(const [k] of F)keep[k]=document.getElementById('st_'+k).value.trim();keep.experience=st.experience;localStorage.ct_stmt=JSON.stringify(keep);
 const res=document.getElementById('st_res');res.textContent='Building the draft (and the evidence pack it cites)…';
 try{const rm=(typeof curCase!=='undefined'&&curCase&&curCase.report_meta)||{};
  const pl=ctReportPayload({ref:rm.ref||'',investigator:st.name||rm.investigator||'',marking:rm.marking||'',notes:rm.notes||'',img:false,noise:false});
  pl.meta.le=Object.assign({},(typeof ctOfficer==='function'?ctOfficer():{}),rm.le||{});pl.meta.evidence_pack=true;pl.meta.statement=st;
  const r=await fetch('/api/statement?fmt='+fmt,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pl)});
  if(!r.ok){let d='';try{d=(await r.json()).detail}catch(e){}throw new Error(d||('HTTP '+r.status))}
  const b=await r.blob();const cd=r.headers.get('Content-Disposition')||'';const nm=(cd.match(/filename="([^"]+)"/)||[])[1]||('DRAFT_statement.'+fmt);
  const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=nm;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),6000);
  const H=k=>r.headers.get(k)||'';window.CT_LAST_STATEMENT={fmt,name:nm,size:b.size,sha:H('X-Statement-SHA256'),pack:H('X-Pack-SHA256'),exhibits:+H('X-Exhibits')};
  res.innerHTML=`✅ <b>${E(nm)}</b> · ${E(H('X-Exhibits'))} exhibits<br>Draft SHA-256 <code>${E(H('X-Statement-SHA256'))}</code><br>Evidence pack SHA-256 (cited in the draft) <code>${E(H('X-Pack-SHA256'))}</code><div class="dim">DRAFT – check every paragraph, insert your force-approved declaration, then transfer to your force's statement form before signing.</div>`;
  if(typeof ctAudit==='function')try{ctAudit('statement.draft',{fmt,sha256:H('X-Statement-SHA256').slice(0,16),pack_sha256:H('X-Pack-SHA256').slice(0,16)})}catch(e){}}
 catch(e){res.innerHTML=`<div class="warnbox">Statement draft failed: ${E(e.message)}</div>`}};
const anchor=document.getElementById('xcbtn')||document.getElementById('intakebtn');if(anchor){const b=document.createElement('button');b.className='btn';b.id='stmtbtn';b.title='DRAFT investigator witness statement (DOCX / PDF) citing the evidence pack';b.textContent='📝 Statement';b.onclick=()=>ctStatement(true);anchor.after(b)}
const nav=(performance.getEntriesByType('navigation')[0]||{}).name||location.href;if(new URL(nav).searchParams.get('statement')==='1')setTimeout(()=>ctStatement(true),300);
})();

// ChainTrace v24: production-order draft list – likely exchange deposit addresses in the graph, per exchange. DRAFT LEAD LIST, not evidence, not legal advice.
(()=>{
const css=document.createElement('style');css.textContent=`#pom{position:fixed;inset:0;z-index:84;display:none;align-items:center;justify-content:center;background:rgba(3,5,10,.62);padding:12px}
#pom .card{width:min(1100px,100%);max-height:calc(100vh - 24px);overflow:auto;padding:14px 16px;background:rgba(16,21,36,.97)}
#pom h3{margin:0 0 8px;font-size:15px;text-transform:none;letter-spacing:0;color:var(--txt);display:flex;gap:8px;align-items:center}
#pom .lead{font-size:12px;color:#ffcf8a;border:1px dashed rgba(246,201,69,.55);border-radius:9px;padding:7px 9px;background:rgba(246,201,69,.07);margin:6px 0}
#pom .grp{border:1px solid var(--line);border-radius:12px;padding:9px 11px;margin-top:10px;background:rgba(0,0,0,.14)}
#pom .grp h4{margin:0 0 4px;font-size:13.5px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
#pom table{width:100%;border-collapse:collapse;font-size:11.5px;margin-top:6px}#pom td,#pom th{border-top:1px solid var(--line);padding:4px 5px;text-align:left;vertical-align:top}
#pom th{color:var(--mut);font-weight:600}#pom .mono{word-break:break-all}#pom .lv{font-size:10.5px;padding:1px 6px;border-radius:8px;border:1px solid var(--line);white-space:nowrap}
#pom .lv.high{border-color:rgba(20,241,149,.5);color:#7ff5c4}#pom .lv.medium{border-color:rgba(246,201,69,.6);color:#f6dd8a}#pom .lv.low{border-color:rgba(255,120,120,.5);color:#ffb0b0}
#pom .ct{font-size:11.5px;color:var(--mut)}#pom .ct a{color:var(--acc2)}
@media (max-width:700px){#pom{align-items:flex-end;padding:0}#pom .card{border-radius:16px 16px 0 0;max-height:94vh;max-height:94dvh;padding:12px}
 #pom table,#pom tbody,#pom tr,#pom td{display:block;width:100%}#pom thead{display:none}#pom tr{border-top:1px solid var(--line);padding:5px 0}#pom td{border:0;padding:1px 0}}`;document.head.appendChild(css);
const m=document.createElement('div');m.id='pom';m.onclick=e=>{if(e.target===m)ctProdOrder(false)};
m.innerHTML=`<div class="card glass"><h3>🏦 Production order draft list <span style="flex:1"></span><button class="btn sm" onclick="ctProdOrder(false)">✕</button></h3>
<div class="lead">⚠ Draft lead list to support a production order / disclosure request. Not evidence and not legal advice: every attribution must be confirmed by the exchange's own records.</div>
<div class="row" style="gap:6px;flex-wrap:wrap"><button class="btn sm" id="porun" onclick="ctProdOrderRun()">↻ Build from graph</button><label class="dim" style="font-size:12px"><input type="checkbox" id="pochk"> live-check unlabelled end-points (up to 8, ~20 s)</label>
<button class="btn sm" onclick="ctProdOrderCSV()">⬇ CSV</button></div><div id="pobody" style="margin-top:6px"></div></div>`;document.body.appendChild(m);
const nf=x=>x==null?'–':(+x).toLocaleString('en-GB',{maximumFractionDigits:8});const g2=x=>x==null?'–':'£'+(+x).toLocaleString('en-GB',{minimumFractionDigits:2,maximumFractionDigits:2});
let LAST=null;
function graph(){const pl=ctReportPayload({noise:false,img:false});return{nodes:pl.nodes,edges:pl.edges,case:{labels:pl.case.labels,name:pl.case.name}}}
function render(r){const b=$('pobody');if(!r.groups.length){b.innerHTML=`<div class="dim" style="font-size:12.5px;margin-top:8px">No likely exchange deposit addresses in this graph yet. Expand towards the end-points, or tick the live check.</div>${chk(r)}`;return}
 b.innerHTML=`<div class="dim" style="font-size:12px">${r.candidates} address(es) · ${r.rows.length} transfer row(s) · ${r.groups.length} exchange(s) · built in ${r.secs}s</div>`+r.groups.map(g=>{const c=g.contact;
 return `<div class="grp"><h4>${esc(g.exchange)} <span class="dim" style="font-weight:400">${g.addresses} address(es) · ${g.rows.length} row(s)${g.gbp_then?' · '+g2(g.gbp_then)+' on the day':''}</span>${g.lead_only?'<span class="lv medium">leads only</span>':''}</h4>
 <div class="ct">${c?`Published law-enforcement route: ${c.portal?`<a target="_blank" rel="noopener" href="${esc(c.portal)}">${esc(c.portal)}</a>`:''}${c.email?' · '+esc(c.email):''} <span class="dim">(source <a target="_blank" rel="noopener" href="${esc(c.source_url)}">${esc(new URL(c.source_url).hostname)}</a>, checked ${esc(c.verified)})</span>`:'Published law-enforcement route: not recorded – check the firm’s own website.'}</div>
 <table><thead><tr><th>Deposit address</th><th>Type</th><th>Transaction</th><th>Time (UK / UTC)</th><th>Amount</th><th>GBP on the day</th><th>Reason</th></tr></thead><tbody>
 ${g.rows.slice(0,200).map(x=>`<tr><td class="mono">${chainTag(x.chain)} ${esc(x.address)}</td><td>${esc(x.type)} <span class="lv ${x.level}">${Math.round(x.confidence*100)}% ${x.level}</span></td>
  <td class="mono">${x.txid?`<a target="_blank" rel="noopener" href="${(CH[x.chain]||{}).tx||''}${esc(x.txid)}">${esc(short(x.txid))}</a>`:`<span class="dim">${esc(x.note||'–')}</span>`}</td>
  <td>${esc(x.time_uk||'–')}<div class="dim">${esc(x.time_utc||'')}</div></td><td>${x.amount!=null?nf(x.amount)+' '+esc(x.asset):'–'}</td><td>${g2(x.gbp_then)}</td><td class="dim">${esc(x.reason)}</td></tr>`).join('')}</tbody></table></div>`}).join('')+chk(r)+`<details style="margin-top:8px"><summary class="dim">Method</summary><div class="dim" style="font-size:11.5px">${esc(r.method)}</div></details>`}
const chk=r=>r.checked&&r.checked.length?`<details style="margin-top:8px"><summary class="dim">Live check (${r.checked.length})</summary>${r.checked.map(c=>`<div class="dim mono" style="font-size:11px">${esc(short(c.id))}: ${esc(c.result||'')}</div>`).join('')}</details>`:'';
window.ctProdOrder=function(on){m.style.display=on?'flex':'none';if(on&&!LAST)ctProdOrderRun()};
window.ctProdOrderRun=async function(){const b=$('pobody');b.innerHTML='<div class="dim" style="font-size:12px;margin-top:8px">Looking for exchange deposit addresses and valuing transfers…</div>';
 try{const r=await fetch('/api/prodorder',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...graph(),opts:{check:$('pochk').checked}})});const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);
  LAST=j;window.CT_LAST_PO=j;render(j);if(typeof ctAudit==='function')try{ctAudit('prodorder.built',{exchanges:j.groups.map(g=>g.exchange),rows:j.rows.length,live_check:$('pochk').checked})}catch(e){}}
 catch(e){b.innerHTML=`<div class="warnbox">${esc(e.message)}</div>`}};
window.ctProdOrderCSV=async function(){try{const r=await fetch('/api/prodorder?format=csv',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...graph(),opts:{check:$('pochk').checked}})});if(!r.ok)throw new Error(r.status);
 const bl=await r.blob();const u=URL.createObjectURL(bl);const a=document.createElement('a');a.href=u;a.download='production_order_draft.csv';a.click();setTimeout(()=>URL.revokeObjectURL(u),2000);
 if(typeof ctAudit==='function')try{ctAudit('prodorder.exported',{format:'csv'})}catch(e){}}catch(e){toast('CSV failed: '+e.message)}};
const anchor=$('notesbtn')||$('impbtn')||$('tlbtn');if(anchor){const b=document.createElement('button');b.className='btn';b.id='pobtn';b.title='Production order draft list (likely exchange deposit addresses)';b.textContent='🏦 Prod. order';b.onclick=()=>ctProdOrder(true);anchor.after(b)}
const nav=(performance.getEntriesByType('navigation')[0]||{}).name||location.href;
if(new URL(nav).searchParams.get('po')==='1'){const t0=Date.now();const iv=setInterval(()=>{if(typeof cy!=='undefined'&&cy.nodes().length>=2&&!document.querySelector('.skel')){clearInterval(iv);setTimeout(()=>ctProdOrder(true),800)}else if(Date.now()-t0>90000)clearInterval(iv)},500)}
})();

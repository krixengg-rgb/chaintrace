// ChainTrace v29: cross-chain swap tracing. Deterministic THORChain/Maya + Chainflip hops come through the bridge panel (protocol indexer links);
// this card adds instant-swapper leads (ChangeNOW, FixedFloat, Changelly, eXch): payouts from publicly labelled swapper wallets matched by timing + USD value.
// Heuristic leads are never added automatically and are drawn dotted amber.
(()=>{
const css=document.createElement('style');css.textContent=`.xscard{overflow-wrap:anywhere;min-width:0;border:1px solid rgba(246,201,69,.35)}
.xscard .cand{padding:8px 9px;border:1px dashed rgba(246,201,69,.55);border-radius:10px;margin-top:7px;background:rgba(246,201,69,.04);font-size:12px}
.xscard .cand .hd{display:flex;gap:6px;align-items:center;flex-wrap:wrap;font-weight:650;font-size:12.5px}
.xscard .det{padding:8px 9px;border:1px solid rgba(34,211,238,.5);border-radius:10px;margin-top:7px;font-size:12px}
.xscard .kv{display:grid;grid-template-columns:64px minmax(0,1fr);gap:2px 9px;font-size:11.5px;margin-top:4px}.xscard .kv>div{min-width:0;overflow:hidden}.xscard .kv>div:nth-child(odd){color:var(--mut)}
.xscard .mono{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block;max-width:100%}
@media (max-width:600px){.xscard .kv{grid-template-columns:minmax(0,1fr)}}`;document.head.appendChild(css);
let LAST=null,PEND=null;
const n4=v=>v==null?'–':(+v).toLocaleString(undefined,{maximumFractionDigits:6});
const $u=v=>v==null?'':'$'+(+v).toLocaleString(undefined,{maximumFractionDigits:2});
const tl=t=>t?new Date(t*1000).toLocaleString('en-GB',{timeZone:'Europe/London'})+' UK':'–';
const lnk=(c,h,kind)=>{const b=(CH[c]||{})[kind==='tx'?'tx':'ad'];return b?`<a target="_blank" rel="noopener" class="mono" href="${b}${esc(h)}">${esc(h)}</a>`:`<span class="mono">${esc(h)}</span>`};
function card(j){const h=j.heuristic||{},cs=h.candidates||[],det=j.deterministic||[],inp=h.input,sw=h.swapper;
 return `<div class="card glass xscard" id="xscard"><h3>🔀 Cross-chain swap</h3>
 ${det.length?det.map(m=>`<div class="det"><div class="hd" style="font-weight:650">⇄ ${esc(m.bridge)} <span class="mth det">deterministic</span> <span class="conf">conf ${Math.round(m.confidence*100)}% · ${esc(m.status)}</span></div>
   <div class="kv"><div>In</div><div>${n4(m.src.amount)} ${esc(m.src.unit||'')} on ${esc(CH[m.src.chain]?.n||m.src.chain)}</div><div>Out</div><div>${n4(m.dst.amount)} ${esc(m.dst.unit||'')} on ${esc(CH[m.dst.chain]?.n||m.dst.chain)}</div>
   <div>Out tx</div><div>${m.dst.tx?lnk(m.dst.chain,m.dst.tx,'tx'):'not sent yet'}</div><div>Recipient</div><div>${m.dst.address?lnk(m.dst.chain,m.dst.address,'ad'):'–'}</div>
   <div>Basis</div><div>${esc(m.evidence)}${m.ref?` · <a target="_blank" rel="noopener" href="${esc(m.ref)}">explorer</a>`:''}</div></div></div>`).join('')
  :`<div class="dim" style="font-size:12px">No deterministic swap match (THORChain / Maya / Chainflip${(j.tried||[]).some(t=>!t.ok)?'; some indexers failed: retry':''}).</div>`}
 <h4 style="margin:10px 0 2px;font-size:12.5px">Instant-swapper leads <span class="mth heu">heuristic · lead only</span></h4>
 ${inp?`<div class="kv"><div>Input</div><div>${n4(inp.amount)} ${esc(inp.unit)} (${$u(inp.usd)} at $${(+inp.price).toLocaleString()}) · ${tl(inp.time)}</div>
   <div>Swapper</div><div>${sw?`${esc(sw.service)} – ${sw.kind==='direct'?'paid directly to':'deposit address swept to'} <a target="_blank" rel="noopener" href="${(CH.eth||{}).ad||''}${esc(sw.wallet)}">${esc(sw.name)}</a> <span class="dim">(label: ${esc(sw.src)}, <a target="_blank" rel="noopener" href="${esc(sw.url)}">source</a>)</span>`:'<span class="dim">not confirmed (no labelled swapper wallet reached)</span>'}</div></div>`:''}
 ${cs.map((x,i)=>`<div class="cand" data-i="${i}"><div class="hd">${esc(x.service)} payout <span class="conf">conf ${Math.round(x.confidence*100)}%</span><span class="dim">ratio ${x.ratio} · ${x.dt_min>=0?'+':''}${x.dt_min} min</span></div>
   <div class="kv"><div>Paid</div><div>${n4(x.amount)} ${esc(x.unit)} (${$u(x.usd)}) on ${esc(CH[x.chain]?.n||x.chain)} · ${tl(x.time)}</div><div>To</div><div>${lnk(x.chain,x.to,'ad')}</div>
   <div>Tx</div><div>${lnk(x.chain,x.tx,'tx')}</div><div>From</div><div>${esc(x.wallet_name)} <span class="dim">(${esc(x.src)}, <a target="_blank" rel="noopener" href="${esc(x.url)}">source</a>)</span></div></div>
   <div class="row" style="margin-top:5px"><button class="btn sm xsadd" onclick="ctXSwapAdd(${i})">+ Add lead to graph</button></div></div>`).join('')}
 ${(h.notes||[]).map(n=>`<div class="xnote">• ${esc(n)}</div>`).join('')}
 ${h.lead?`<div class="caveat">⚠ ${esc(h.lead)}</div>`:''}
 ${h.method?`<details style="margin-top:6px;font-size:11px"><summary class="dim">Method</summary><div class="dim">${esc(h.method)}</div>${(h.checked||[]).length?`<div class="dim" style="margin-top:4px">Checked ${h.checked.length} labelled wallet(s): ${h.checked.map(c=>esc(c.service+' '+c.chain+' '+c.wallet.slice(0,10)+'… ('+c.payouts+')')).join(', ')}</div>`:''}</details>`:''}
 <div class="dim" style="font-size:11px;margin-top:6px">${esc(j.caveat||'')}</div></div>`}
const PH=`<div class="card glass xscard" id="xscard"><h3>🔀 Cross-chain swap</h3><div class="dim" style="font-size:12px">Asking THORChain / Maya / Chainflip and scanning payouts from labelled instant-swapper wallets (up to ~30 s)…</div></div>`;
const put=h=>{const el=$('xscard');if(el)el.outerHTML=h;else $('side').insertAdjacentHTML('beforeend',h)};
window.ctXSwap=async function(tx){PEND=tx;LAST=null;put(PH);
 try{const r=await fetch('/api/xswap?tx='+encodeURIComponent(tx)+(typeof cur!=='undefined'&&cur&&cur.chain?'&chain='+cur.chain:''));const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);
  LAST=j;PEND=null;window.CT_LAST_XSWAP=j;put(card(j));
  for(const m of j.deterministic||[])if(m.confidence>=.95&&m.graph){const g=JSON.parse(JSON.stringify(m.graph));for(const e of g.edges){if(m.side==='dst')e.target='tx:'+tx;else e.source='tx:'+tx}add(g,null)}
  if(typeof ctAudit==='function')try{ctAudit('xswap.view',{tx,deterministic:(j.deterministic||[]).length,leads:((j.heuristic||{}).candidates||[]).length})}catch(e){}}
 catch(e){PEND=null;const c=$('xscard');if(c)c.innerHTML=`<h3>🔀 Cross-chain swap</h3><div class="warnbox">${esc(e.message)}</div>`}};
window.ctXSwapAdd=function(i){const x=((LAST||{}).heuristic||{}).candidates?.[i];if(!x||!x.graph)return;add(JSON.parse(JSON.stringify(x.graph)),null);
 const e=x.graph.edges[0];const el=cy.getElementById(e.source+'>'+e.target+(e.unit||''));if(el.length){cy.elements().unselect();el.select();cy.animate({fit:{eles:el.connectedNodes(),padding:90}},{duration:400})}
 toast('Heuristic swap lead added (dotted amber edge): verify before relying on it');if(typeof ctAudit==='function')try{ctAudit('xswap.lead_added',{tx:x.tx,to:x.to,confidence:x.confidence})}catch(e){}};
const nav=(performance.getEntriesByType('navigation')[0]||{}).name||location.href;const P=new URL(nav).searchParams;let auto=P.get('xswap')==='1';
const _render=window.render;window.render=function(d){_render(d);try{if(d&&d.tx){const r=$('side').querySelector('.card .row')||$('side').querySelector('.card');
  if(r&&!$('side').querySelector('.xsbtn'))r.insertAdjacentHTML('beforeend',`<button class="btn sm xsbtn" title="THORChain / Chainflip swap hops + instant-swapper payout leads" onclick="ctXSwap('${esc(d.tx)}')">🔀 Swap hops</button>`);
  if(auto){auto=false;ctXSwap(d.tx)}else if(LAST&&LAST.query===d.tx)put(card(LAST));else if(PEND===d.tx)put(PH)}}catch(e){console.warn(e)}};
setTimeout(()=>{if(auto&&typeof cur!=='undefined'&&cur&&cur.tx){auto=false;ctXSwap(cur.tx)}},0);
})();

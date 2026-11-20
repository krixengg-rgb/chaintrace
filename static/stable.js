// ChainTrace v27: USDT / USDC across chains: issuer blacklist / freeze status (on-chain), stablecoin flows, stablecoin-only graph + AutoTrace,
// Circle CCTP burn -> mint matches (deterministic) via the bridge panel. Heuristic bridge hops stay marked as leads.
(()=>{
const SU=new Set(['USDT','USDC','USDT0','USD₮0','USDC.E','USDBC','BSC-USD']);
const isS=u=>SU.has(String(u||'').replace('⇄','').toUpperCase());
const css=document.createElement('style');css.textContent=`.stcard .bl{display:flex;gap:6px;align-items:center;font-size:12.5px;padding:4px 0;border-top:1px solid var(--line)}
.stcard .pill{font-size:10.5px;padding:1px 7px;border-radius:9px;border:1px solid;white-space:nowrap}.stcard .pill.bad{border-color:#ff5c7a;color:#ffb3c1;background:rgba(255,92,122,.1)}.stcard .pill.ok{border-color:rgba(123,216,143,.6);color:#b8f0c4}.stcard .pill.unk{border-color:#888;color:#bbb}
.stcard table{width:100%;border-collapse:collapse;font-size:12px;margin-top:6px}.stcard td,.stcard th{padding:3px 4px;border-top:1px solid var(--line);text-align:left;vertical-align:top}.stcard th{color:var(--dim,#9aa);font-weight:600}
.stcard .warn2{font-size:11.5px;color:#ffcf8a;margin-top:4px}.stbp{display:none}@media(max-width:600px){.stbl{display:none}.stbp{display:inline}.stbchk{margin:0!important;padding-left:2px!important;padding-right:2px!important;gap:1px!important}}.stcard h4{margin:10px 0 2px;font-size:12.5px}`;document.head.appendChild(css);
cy.style().selector('.stbhide').style({display:'none'}).update();
let LAST=null,PEND=null,ONLY=false;
const n2=v=>(+v).toLocaleString(undefined,{maximumFractionDigits:2});
function card(j){const bl=j.blacklist||[];
 return `<div class="card glass stcard" id="stcard"><h3>💵 Stablecoins (USDT / USDC)</h3>
 <h4>Issuer blacklist / freeze status <span class="dim" style="font-weight:400">· read live from the token contracts</span></h4>
 ${bl.length?bl.map(b=>`<div class="bl" data-sym="${esc(b.symbol)}"><b>${esc(b.symbol)}</b><span class="dim">${esc(b.issuer)} · ${esc(CH[b.chain]?.n||b.chain)}</span><span style="flex:1"></span>
  ${b.blacklisted===true?`<span class="pill bad">⛔ BLACKLISTED${b.frozen_balance!=null?' · '+n2(b.frozen_balance)+' frozen':' · frozen balance n/a'}</span>`:b.blacklisted===false?'<span class="pill ok">not blacklisted</span>':`<span class="pill unk" title="${esc(b.error||'')}">unknown</span>`}</div>
  <div class="dim" style="font-size:10.5px">${Object.entries(b.calls||{}).map(([k,v])=>esc(k)+'() = '+v).join(' · ')} on <a target="_blank" rel="noopener" href="${(CH[b.chain]?.ad||'')}${esc(b.token)}">${esc(short(b.token))}</a></div>`).join('')
  :`<div class="dim" style="font-size:12px">No issuer blacklist check for ${esc(CH[j.chain]?.n||j.chain)} (supported: Tether USDT on Ethereum + TRON, Circle USDC on Ethereum, Arbitrum, Base, Optimism, Polygon).</div>`}
 ${j.blacklist_error?`<div class="warn2">⚠ ${esc(j.blacklist_error)}</div>`:''}
 <h4>Stablecoin flows <span class="dim" style="font-weight:400">· fetched history</span></h4>
 ${(j.flows||[]).length?`<table><tr><th>Token</th><th>In</th><th>Out</th><th>Top counterparties</th></tr>${j.flows.map(f=>`<tr data-unit="${esc(f.unit)}"><td><b>${esc(f.unit)}</b>${f.official===false?'<div class="warn2">⚠ not the official contract</div>':f.official?'<div class="dim" style="font-size:10.5px">official contract</div>':''}</td>
  <td>${n2(f.in)}<div class="dim" style="font-size:10.5px">${f.n_in} tx</div></td><td>${n2(f.out)}<div class="dim" style="font-size:10.5px">${f.n_out} tx</div></td>
  <td style="font-size:11px">${f.top.slice(0,3).map(t=>`<a class="mono" href="?q=${encodeURIComponent(t.id)}">${esc(short(t.id))}</a> ${n2(t.amount)}`).join('<br>')}${f.issuer_events.length?`<div class="warn2">${f.issuer_events.length} issuer mint/burn transfer(s)</div>`:''}</td></tr>`).join('')}</table>`
  :'<div class="dim" style="font-size:12px">No USDT / USDC transfers in the fetched history.</div>'}
 <div class="row" style="margin-top:8px;gap:6px;flex-wrap:wrap"><button class="btn sm" id="stbtog" onclick="ctStableOnly()">${ONLY?'Show all assets':'💵 Show stablecoin flows only'}</button></div>
 <div class="dim" style="font-size:11px;margin-top:6px">${esc(j.note)}</div></div>`}
const PH=`<div class="card glass stcard" id="stcard"><h3>💵 Stablecoins</h3><div class="dim" style="font-size:12px">Reading blacklist status on-chain and summarising USDT / USDC flows…</div></div>`;
const put=h=>{const el=$('stcard');if(el)el.outerHTML=h;else $('side').insertAdjacentHTML('beforeend',h)};
function apply(){cy.batch(()=>{cy.elements().removeClass('stbhide');if(!ONLY)return;
 cy.edges().forEach(e=>{if(e.data('meta'))return;const i=e.data('info')||{};if(!isS(i.unit))e.addClass('stbhide')});
 cy.nodes().forEach(n=>{if(n.data('grp')||n.data('focus'))return;const es=n.connectedEdges().filter(e=>!e.data('meta'));if(es.length&&es.every(e=>e.hasClass('stbhide')))n.addClass('stbhide')})})}
let _at=null;cy.on('add data','edge',()=>{if(ONLY){clearTimeout(_at);_at=setTimeout(apply,80)}});
window.ctStableOnly=function(on){ONLY=on===undefined?!ONLY:!!on;apply();const b=$('stbtog');if(b)b.textContent=ONLY?'Show all assets':'💵 Show stablecoin flows only';
 toast(ONLY?'Showing USDT / USDC flows only':'Showing all assets')};
window.ctStable=async function(a){PEND=a;LAST=null;put(PH);
 try{const r=await fetch('/api/stable?q='+encodeURIComponent(a)+(typeof cur!=='undefined'&&cur&&cur.chain?'&chain='+cur.chain:''));const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);
  LAST=j;PEND=null;window.CT_LAST_STABLE=j;put(card(j));
  if(typeof ctAudit==='function')try{ctAudit('stable.view',{address:a,blacklisted:(j.blacklist||[]).filter(b=>b.blacklisted).map(b=>b.symbol)})}catch(e){}}
 catch(e){PEND=null;const c=$('stcard');if(c)c.innerHTML=`<h3>💵 Stablecoins</h3><div class="warnbox">${esc(e.message)}</div>`}};
// AutoTrace option
const seg=$('amin')?.parentElement;if(seg&&!$('stbonly'))seg.insertAdjacentHTML(innerWidth<600?'afterend':'beforeend',`<label class="chk stbchk" title="AutoTrace follows only official USDT / USDC transfers (and bridge hops of them)"><input type="checkbox" id="stbonly"> 💵<span class="stbl"> stables</span><span class="stbp"> USDT/USDC only</span></label>`);
const nav=(performance.getEntriesByType('navigation')[0]||{}).name||location.href;const P=new URL(nav).searchParams;
let auto=P.get('stable')==='1';if(P.get('stables')==='1'){const c=$('stbonly');if(c)c.checked=true}
const _render=window.render;window.render=function(d){_render(d);try{if(ONLY)setTimeout(apply,50);if(d&&d.address&&!d.tx){const r=$('side').querySelector('.card .row')||$('side').querySelector('.card');
  if(r&&!$('side').querySelector('.stbtn'))r.insertAdjacentHTML('beforeend',`<button class="btn sm stbtn" title="USDT / USDC: blacklist status + flows" onclick="ctStable('${esc(d.address)}')">💵 Stablecoins</button>`);
  if(auto){auto=false;ctStable(d.address)}else if(LAST&&LAST.address===d.address)put(card(LAST));else if(PEND===d.address)put(PH)}}catch(e){}};
setTimeout(()=>{if(auto&&typeof cur!=='undefined'&&cur&&cur.address&&!cur.tx){auto=false;ctStable(cur.address)}},0);
})();

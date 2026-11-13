// ChainTrace v16: EVM chains beyond Ethereum (BNB Smart Chain, Arbitrum One, Base, Polygon PoS, OP Mainnet).
// Chain selector + "All EVM" activity scan, chain-coloured nodes/edges, tx-hash chain detection notes. Loaded last; wraps globals.
(()=>{
const NAME={eth:'Ethereum',bsc:'BNB Smart Chain',arb:'Arbitrum One',base:'Base',polygon:'Polygon PoS',op:'OP Mainnet'};
const css=document.createElement('style');css.textContent=`
#chainSel{background:rgba(0,0,0,.28);border:1px solid var(--line);border-radius:9px;padding:5px 6px;font-size:12px;color:var(--txt);max-width:92px;outline:0}
.badge.bsc{color:#f3ba2f;border-color:rgba(243,186,47,.55);background:rgba(243,186,47,.1)}.badge.arb{color:#5cbcff;border-color:rgba(40,160,240,.55);background:rgba(40,160,240,.1)}
.badge.base{color:#7aa2ff;border-color:rgba(61,123,255,.6);background:rgba(61,123,255,.12)}.badge.polygon{color:#c4a1ff;border-color:rgba(164,107,255,.55);background:rgba(164,107,255,.1)}
.badge.op{color:#ff7a85;border-color:rgba(255,59,74,.55);background:rgba(255,59,74,.1)}
.evmscan table{width:100%;border-collapse:collapse;font-size:12px}.evmscan td,.evmscan th{padding:6px 4px;border-top:1px solid var(--line);text-align:left;vertical-align:top}
.evmscan th{color:var(--mut);font-weight:600;font-size:11px}.evmscan tr.idle td{opacity:.5}.evmscan .act{color:#2ee59d;font-weight:700}
.evmscan .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:middle}
.evmalso{margin-top:8px;font-size:12px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}.evmalso .btn{padding:3px 8px}
.chlegend{display:flex;flex-wrap:wrap;gap:8px;font-size:11px;margin-top:4px}.chlegend b{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;border:2px solid}
.leadnote{margin-top:8px;padding:7px 10px;border-radius:10px;font-size:11.5px;color:#f6dd8a;border:1px dashed rgba(246,201,69,.55);background:rgba(246,201,69,.06)}
@media (max-width:900px){#chainSel{max-width:92px;font-size:11.5px}.evmscan td:nth-child(4),.evmscan th:nth-child(4){display:none}}`;
document.head.appendChild(css);
const ALL=['eth',...EVMX];const col=c=>(CH[c]||{}).c;
// ---------- graph: chain colours ----------
cy.style().selector('node[cc]').style({'border-color':'data(cc)','border-width':e=>e.data('focus')?3.5:2.6})
 .selector('edge[cc]').style({'line-color':'data(cc)','target-arrow-color':'data(cc)','line-opacity':.62})
 .selector('node[cc]:selected').style({'border-color':'#f6c945','border-width':4}).update();
function chainLegend(){const lg=$('legend');if(!lg)return;let el=lg.querySelector('.chlegend');const present=new Set();
 cy.nodes().forEach(n=>{const c=(n.data('info')||{}).chain;if(ALL.includes(c))present.add(c)});
 if(!present.size||(present.size===1&&present.has('eth'))){if(el)el.remove();return}
 if(!el){el=document.createElement('div');el.className='chlegend';lg.appendChild(el)}
 el.innerHTML=[...present].map(c=>`<span><b style="border-color:${col(c)};background:${c==='eth'?'transparent':col(c)+'33'}"></b>${NAME[c]}</span>`).join('')}
function paint(){cy.batch(()=>{cy.nodes().forEach(n=>{const i=n.data('info')||{};const c=i.chain||(/^(bsc|arb|base|polygon|op):/.exec(n.id())||[])[1];
  if(EVMX.includes(c)){if(n.data('cc')!==col(c))n.data('cc',col(c));if(!i.name&&!n.data('note')&&i.kind!=='swap'&&i.kind!=='tx'){const l=CH[c].sym+' '+short(n.id());if(n.data('lbl')!==l)n.data('lbl',l)}}});
 cy.edges().forEach(e=>{if(e.data('xchain')||e.data('swapleg'))return;const a=e.source().data('info')||{},b=e.target().data('info')||{};const c=EVMX.includes(a.chain)?a.chain:EVMX.includes(b.chain)?b.chain:null;
  if(c&&e.data('cc')!==col(c))e.data('cc',col(c))})});chainLegend()}
window.ctEvmPaint=paint;
const _add=window.add;window.add=function(d,focus){_add(d,focus);try{paint()}catch(e){console.warn(e)}};
// ---------- All-EVM scan ----------
const nf=(x,d=6)=>x==null?'–':(+x).toLocaleString('en-GB',{maximumFractionDigits:Math.abs(x)>=1000?2:d});
function scanCard(j){const rows=j.chains.map(r=>`<tr class="${r.active?'':'idle'}"><td><span class="dot" style="background:${col(r.chain)}"></span><span title="${esc(r.name)}">${esc(r.short==='POL'?'Polygon':r.short==='ARB'?'Arbitrum':r.short==='BSC'?'BSC':r.short==='OP'?'Optimism':r.name)}</span>${r.is_contract?' <span class="dim">(contract)</span>':''}</td>
  <td class="r">${nf(r.balance,5)} ${esc(r.unit)}<div class="dim">${usd(r.balance_usd)}</div></td>
  <td class="r">${r.nonce!=null?r.nonce.toLocaleString('en-GB'):'–'}${r.tx_count!=null?`<div class="dim">${r.tx_count.toLocaleString('en-GB')} txs${r.token_transfers?' · '+r.token_transfers.toLocaleString('en-GB')+' token tf':''}</div>`:''}</td>
  <td>${r.active?'<span class="act">active</span>':'<span class="dim">no activity seen</span>'}${r.rpc_ok?'':' <span class="dim">(RPC down)</span>'}</td>
  <td><button class="btn sm" onclick="ctOpenOn('${r.chain}','${esc(j.address)}')">Open</button> <a class="copy" target="_blank" rel="noopener" href="${esc(r.explorer_url)}">↗</a></td></tr>`).join('');
 return `<div class="card glass evmscan"><h3>⛓ All-EVM scan<span class="sp"></span><span class="dim" style="text-transform:none;letter-spacing:0">${j.active.length} of ${j.chains.length} chains active</span></h3>
  ${addrLine(j.address,null,false)}<table><tr><th>Chain</th><th class="r">Balance</th><th class="r">Out txs (nonce)</th><th>Activity</th><th></th></tr>${rows}</table>
  <div class="dim" style="font-size:11px;margin-top:6px">${esc(j.note)}</div></div>`}
window.ctOpenOn=function(c,a){$('chainSel').value=c;$('q').value=c==='eth'?a:c+':'+a;setBadge();go()};
async function scan(a){mode='lookup';cy.elements().remove();expanded.clear();$('det').innerHTML='';skeleton();$('empty').style.display='none';share();busy(true,'Scanning 6 EVM chains…');
 try{const r=await fetch('/api/evm/scan?addr='+encodeURIComponent(a));const j=await r.json();busy(false,'');if(!r.ok){toast(j.detail||'scan failed');$('side').innerHTML='';return}
  window.CT_LASTSCAN=j;$('side').innerHTML=scanCard(j);
  const nodes=j.chains.filter(x=>x.active).map(x=>({id:x.chain==='eth'?j.address:x.chain+':'+j.address,chain:x.chain,name:`${x.short} · ${nf(x.balance,4)} ${x.unit}`,kind:null,tags:[],risk:0}));
  if(nodes.length){add({chain:'eth',nodes,edges:[]},null);cy.layout({name:'circle',padding:80,animate:false}).run();cy.fit(undefined,80);if(cy.zoom()>1.1){cy.zoom(1.1);cy.center()}}else $('empty').style.display=''}
 catch(e){busy(false,'');toast('scan failed')}}
window.ctEvmScan=scan;
const _go=window.go;window.go=async function(){const q=$('q').value.trim();
 if($('chainSel').value==='all'){const a=bareId(q).replace(/^eth:/,'');if(/^0x[0-9a-fA-F]{40}$/.test(a)){$('q').value=a;setBadge();return scan(a)}
  if(/^0x[0-9a-fA-F]{64}$/.test(a)){$('chainSel').value='auto';$('q').value=a;setBadge()}}
 return _go()};
// after a plain 0x lookup in Auto mode, look for activity on the other EVM chains (cheap RPC reads) and offer one-tap switches
async function alsoOn(d){try{if(!d||d.kind!=='address'||$('chainSel').value!=='auto')return;const a=bareId(d.address);if(!/^0x[0-9a-fA-F]{40}$/.test(a))return;
 const r=await fetch('/api/evm/scan?addr='+encodeURIComponent(a));if(!r.ok)return;const j=await r.json();if(cur!==d)return;
 const oth=j.chains.filter(x=>x.active&&x.chain!==d.chain);if(!oth.length)return;
 const card=$('side').querySelector('.card');if(!card||card.querySelector('.evmalso'))return;
 card.insertAdjacentHTML('beforeend',`<div class="evmalso"><span class="dim">Same address also active on:</span>${oth.map(x=>`<button class="btn sm" onclick="ctOpenOn('${x.chain}','${esc(a)}')"><span class="dot" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${x.color};margin-right:4px"></span>${esc(x.short)}</button>`).join('')}
  <span class="dim" style="font-size:11px">(an EOA is the same key holder on every EVM chain; a contract usually is not)</span></div>`)}catch(e){}}
const _render=window.render;window.render=function(d){_render(d);try{
 const card=$('side').querySelector('.card');
 if(card&&d&&d.found_on&&d.found_on.length>1)card.insertAdjacentHTML('beforeend',`<div class="leadnote">This transaction hash exists on ${d.found_on.map(c=>NAME[c]||c).join(', ')}. Showing ${NAME[d.chain]||d.chain}; pick another chain in the selector to switch.</div>`);
 if(card&&d&&(d.chain==='eth'||EVMX.includes(d.chain))&&d.label&&(d.label.sources||[]).some(s=>/\(Ethereum, same address\)/.test(s.source||'')))
  card.insertAdjacentHTML('beforeend',`<div class="leadnote">Label carried over from the same address on Ethereum: a lead, not evidence. It holds for an externally owned wallet (same key on every EVM chain) but not necessarily for a contract.</div>`);
 if(d&&d.kind==='address'&&!d._evmAlso){d._evmAlso=1;alsoOn(d)}}catch(e){console.warn(e)}};
setBadge();
if(window.CT_SCAN_PENDING){const a=window.CT_SCAN_PENDING;window.CT_SCAN_PENDING=null;scan(a)}
})();

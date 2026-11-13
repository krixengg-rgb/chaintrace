// ChainTrace v13: readable ETH DEX swap steps. Lookups return swap_candidates; /api/eth/swaps decodes them (public RPC receipt logs)
// into one grouped step per swap: trader -> [swap node "10 ETH → 25,000 USDT"] -> recipient. Raw transfers stay in the graph.
(()=>{
CAT.swap=['#14b8a6','⇆','DEX swap'];
cy.style().selector('node[kind="swap"]').style({shape:'round-rectangle',width:30,height:22,'background-color':'#0f766e','border-color':'#2ee6d6','border-width':2,
  'text-wrap':'wrap','text-max-width':150,color:'#9ff3ea','font-size':8.5,'font-weight':600})
 .selector('edge[?swapleg]').style({'line-color':'#2ee6d6','target-arrow-color':'#2ee6d6','line-style':'dashed','line-dash-pattern':[6,3],color:'#9ff3ea'})
 .selector('edge[swapleg="inferred"]').style({'line-color':'#f6c945','target-arrow-color':'#f6c945',color:'#f6dd8a'}).update();
const css=document.createElement('style');css.textContent=`.swapcard .pair{font-size:15px;font-weight:700;margin:4px 0 2px}.swapcard .pair .ar{color:#2ee6d6;margin:0 6px}
.swapcard .hop{font-size:12px;padding:6px 8px;margin-top:6px;border:1px solid var(--line);border-radius:10px;background:rgba(0,0,0,.18);word-break:break-word}
.swapcard .inf{margin-top:8px;font-size:11.5px;color:#f6dd8a}.swapcard .ok{color:#2ee59d;font-size:11.5px;margin-top:6px}`;document.head.appendChild(css);
const nf=x=>x==null?'?':(Math.abs(x)>=1e5?Math.round(x).toLocaleString('en-GB'):Math.abs(x)>=1000?x.toLocaleString('en-GB',{maximumFractionDigits:2}):(+x.toPrecision(6)).toLocaleString('en-GB',{maximumFractionDigits:6}));
const label=s=>`⇆ ${nf(s.sold[0].amount)} ${s.sold[0].symbol} → ${nf(s.bought[0].amount)} ${s.bought[0].symbol}\n${s.venue}`;
function decorate(){cy.nodes('[kind="swap"]').forEach(n=>{const s=(n.data('info')||{}).swap;if(s)n.data('lbl',label(s))});
 cy.edges().forEach(e=>{const sw=(e.data('info')||{}).swap;if(sw&&!e.data('swapleg'))e.data('swapleg',sw.decoded?'decoded':'inferred')})}
window.ctSwapDecorate=decorate;
const asked=new Set();window.CT_SWAPS=window.CT_SWAPS||{};
window.ctDecodeSwaps=async function(cands,trader){const txs=(cands||[]).map(c=>c.tx).filter(h=>h&&!asked.has(h+trader));if(!txs.length)return;txs.forEach(h=>asked.add(h+trader));
 const ch=(/^(bsc|arb|base|polygon|op):/.exec(trader)||[,'eth'])[1];
 try{const r=await fetch('/api/eth/swaps',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({txs,trader,chain:ch})});if(!r.ok)return;const j=await r.json();
  for(const s of j.swaps||[])CT_SWAPS[s.tx]=s;
  if((j.nodes||[]).length){_add({chain:ch,unit:'',nodes:j.nodes,edges:j.edges},null);decorate();
   toast(`${j.swaps.length} DEX swap${j.swaps.length>1?'s':''} decoded into readable steps`)}}catch(e){}};
const _add=window.add;
window.add=function(d,focus){_add(d,focus);try{decorate();
  if(d&&(d.chain==='eth'||EVMX.includes(d.chain))&&d.swap_candidates&&d.swap_candidates.length&&d.address)ctDecodeSwaps(d.swap_candidates,d.address);
  if(d&&d.swaps)for(const s of d.swaps)CT_SWAPS[s.tx]=s}catch(e){}};
const card=s=>{const tx=s.tx;const u=x=>x.usd!=null?` <span class="usd">${usd(x.usd)}</span>`:'';
 const sc=s.chain||'eth';return `<div class="card glass swapcard"><h3>${chainTag(sc)} DEX swap ${tagH('swap')}</h3>
 <div class="pair">${s.sold.map(x=>esc(nf(x.amount)+' '+x.symbol)).join(' + ')}<span class="ar">→</span>${s.bought.map(x=>esc(nf(x.amount)+' '+x.symbol)).join(' + ')}</div>
 <div class="dim" style="font-size:12px">${esc(s.text)}</div>
 <div class="kv" style="margin-top:8px"><div>Sold</div><div>${s.sold.map(x=>esc(nf(x.amount)+' '+x.symbol)+u(x)).join('<br>')}</div><div>Bought</div><div>${s.bought.map(x=>esc(nf(x.amount)+' '+x.symbol)+u(x)).join('<br>')}</div>
 <div>Venue</div><div>${esc(s.venue)}</div><div>Called</div><div>${esc(s.router&&s.router.name||'')} <span class="mono" style="font-size:11px">${esc(short(s.router&&s.router.address||''))}</span></div>
 <div>Trader</div><div class="mono">${esc(s.trader||'')}</div>${s.recipient&&s.trader&&s.recipient.toLowerCase()!==s.trader.toLowerCase()?`<div>Recipient</div><div class="mono">${esc(s.recipient)}</div>`:''}
 <div>Time</div><div>${s.time?tfmt(s.time):'–'}</div><div>Tx</div><div><a class="mono" target="_blank" rel="noopener" href="${CH[sc].tx}${esc(tx)}">${short(tx)}</a><button class="copy" onclick="copy('${esc(tx)}')">⧉</button></div></div>
 ${(s.hops||[]).map((h,i)=>`<div class="hop"><b>Hop ${i+1}</b> · ${esc(h.dex||'?')}${h.fee?' · fee '+esc(h.fee):''}<br>${h.sym_in?esc(nf(h.amount_in)+' '+h.sym_in)+' → '+esc(nf(h.amount_out)+' '+h.sym_out):esc(h.note||'')}<br><span class="dim mono" style="font-size:10.5px">pool ${esc(h.pool||'')}</span></div>`).join('')}
 <div class="${s.decoded?'ok':'inf'}">${s.decoded?'✓ Decoded from the DEX’s own Swap event logs and the trader’s token transfers.':'⚠ Partly inferred: '+esc((s.inferred||[]).join('; ')||s.method)}</div>
 ${s.decoded&&(s.inferred||[]).length?`<div class="inf">Inferred: ${esc(s.inferred.join('; '))}</div>`:''}
 <div class="dim" style="font-size:11px;margin-top:6px">USD at trace-time prices. Source: ${esc(s.source||'')}.</div></div>`};
cy.on('tap','node',e=>{const i=e.target.data('info')||{};if(i.kind!=='swap'||!i.swap)return;setTimeout(()=>{const det=$('det');if(det.querySelector('.swapcard'))return;det.insertAdjacentHTML('afterbegin',card(i.swap))},0)});
cy.on('tap','edge',e=>{const i=e.target.data('info')||{};if(!i.swap)return;const s=CT_SWAPS[i.tx]||(cy.getElementById('tx:'+i.tx).data('info')||{}).swap;if(!s)return;
 setTimeout(()=>{const det=$('det');if(det.querySelector('.swapcard'))return;det.insertAdjacentHTML('afterbegin',card(s))},0)});
decorate();
})();

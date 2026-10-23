// ChainTrace v7: cross-chain bridge tracing (loaded after v6.js; wraps globals the same way)
(function(){
// ---------- chains beyond BTC/ETH/SOL (display + explorer links only; not expandable) ----------
const XC={base:['#3d7bff','Base','B','https://basescan.org/tx/','https://basescan.org/address/'],arb:['#2d9cdb','Arbitrum','A','https://arbiscan.io/tx/','https://arbiscan.io/address/'],
 op:['#ff3b4a','Optimism','O','https://optimistic.etherscan.io/tx/','https://optimistic.etherscan.io/address/'],polygon:['#a46bff','Polygon','P','https://polygonscan.com/tx/','https://polygonscan.com/address/'],
 bsc:['#f3ba2f','BNB','◆','https://bscscan.com/tx/','https://bscscan.com/address/'],avax:['#e84142','Avalanche','▲','https://snowtrace.io/tx/','https://snowtrace.io/address/'],
 linea:['#9fe1ff','Linea','L','https://lineascan.build/tx/','https://lineascan.build/address/'],hyperevm:['#5ef2c8','HyperEVM','H','https://hyperevmscan.io/tx/','https://hyperevmscan.io/address/'],
 unichain:['#ff4fd8','Unichain','U','https://uniscan.xyz/tx/','https://uniscan.xyz/address/'],zksync:['#8c8dfc','zkSync','Z','https://era.zksync.network/tx/','https://era.zksync.network/address/'],
 scroll:['#ffdbb0','Scroll','S','https://scrollscan.com/tx/','https://scrollscan.com/address/'],blast:['#fcfc03','Blast','B','https://blastscan.io/tx/','https://blastscan.io/address/'],
 tron:['#ff0013','Tron','T','https://tronscan.org/#/transaction/','https://tronscan.org/#/address/'],doge:['#c2a633','DOGE','Ð','https://blockchair.com/dogecoin/transaction/','https://blockchair.com/dogecoin/address/'],
 ltc:['#a6a9aa','LTC','Ł','https://blockchair.com/litecoin/transaction/','https://blockchair.com/litecoin/address/'],bch:['#8dc351','BCH','Ƀ','https://blockchair.com/bitcoin-cash/transaction/','https://blockchair.com/bitcoin-cash/address/'],
 xrp:['#cfd8e3','XRP','✕','https://xrpscan.com/tx/','https://xrpscan.com/account/'],thor:['#33ff99','THOR','ᚱ','https://runescan.io/tx/','https://runescan.io/address/'],
 sui:['#4da2ff','Sui','S','https://suiscan.xyz/mainnet/tx/','https://suiscan.xyz/mainnet/account/'],gaia:['#6f7390','Cosmos','⚛','https://www.mintscan.io/cosmos/tx/','https://www.mintscan.io/cosmos/address/']};
for(const[k,[c,n,sym,tx,ad]]of Object.entries(XC))if(!CH[k])CH[k]={c,n,sym,tx,ad,foreign:1};
const NATIVE=['btc','eth','sol'];
const css=document.createElement('style');css.textContent=`
.badge.xc{color:#9fe7f5;border-color:rgba(34,211,238,.45);background:rgba(34,211,238,.08)}
.xcard{overflow-wrap:anywhere;min-width:0;border:1px solid rgba(34,211,238,.35);box-shadow:0 0 0 1px rgba(34,211,238,.08) inset}
.xm{overflow-wrap:anywhere;word-break:break-word;min-width:0;padding:9px 10px;border:1px solid var(--line);border-radius:11px;margin-top:8px;background:rgba(255,255,255,.02)}
.xm.heur{border:1px dashed rgba(246,201,69,.6);background:rgba(246,201,69,.05)}
.xm .hd{display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-weight:650;font-size:13px}
.xm .lg{display:grid;grid-template-columns:auto 1fr;gap:3px 10px;font-size:12px;margin-top:6px}
.xm .lg>div:nth-child(odd){color:var(--mut)}
.xm .lg .mono{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block;max-width:100%}
.mth{font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding:1px 6px;border-radius:6px}
.mth.det{color:#22d3ee;border:1px solid rgba(34,211,238,.6)}.mth.heu{color:#f6c945;border:1px dashed rgba(246,201,69,.7)}
.conf{font-size:11px;color:var(--mut)}.xnote{overflow-wrap:anywhere;font-size:11px;color:#b8c2da;margin-top:5px}
.caveat{margin-top:8px;padding:7px 10px;border-radius:10px;font-size:11.5px;color:#f6dd8a;border:1px solid rgba(246,201,69,.45);background:rgba(246,201,69,.07)}
.xarrow{color:#22d3ee;font-weight:700}
.chk{display:inline-flex;align-items:center;gap:4px;font-size:12px;color:var(--mut);cursor:pointer}
@media (max-width:900px){.xm .lg{grid-template-columns:1fr}.xm .lg>div:nth-child(odd){margin-top:4px}}`;
document.head.appendChild(css);
const ctag=c=>c&&CH[c]?`<span class="badge ${CH[c].foreign?'xc':c}">${CH[c].sym} ${CH[c].n}</span>`:`<span class="badge xc">${esc(c||'?')}</span>`;
const rawId=id=>{const m=/^([a-z0-9]+):(.+)$/.exec(id||'');return m&&!id.startsWith('tx:')&&CH[m[1]]?[m[1],m[2]]:[null,id]};
const isForeign=id=>{const[c]=rawId(id);return !!c||!NATIVE.includes(chainOf[id]||'eth')};
// ---------- graph style ----------
cy.style().selector('edge[?xchain]').style({'line-style':'dashed','line-dash-pattern':[8,5],'line-color':'#22d3ee','target-arrow-color':'#22d3ee',color:'#9fe7f5','curve-style':'unbundled-bezier','control-point-distances':[40],'z-index':7,width:e=>Math.max(2.2,ew(e))})
 .selector('edge[?heur]').style({'line-style':'dotted','line-color':'#f6c945','target-arrow-color':'#f6c945',color:'#f6dd8a'})
 .selector('edge[?xchain].hot').style({'line-color':'#ff4d6d','target-arrow-color':'#ff4d6d'})
 .selector('node[?xnode]').style({'border-color':'#22d3ee','border-width':2.5,'border-style':'double'}).update();
// ---------- add(): decorate cross-chain edges/nodes ----------
const _addB=window.add;window.add=function(d,focus){_addB(d,focus);
 cy.batch(()=>{for(const n of d.nodes||[]){if(n.foreign||(n.chain&&!NATIVE.includes(n.chain))){const x=cy.getElementById(n.id);if(x.length){x.data('xnode',1);if(!n.name)x.data('lbl',(CH[n.chain]?.sym||'')+' '+short(rawId(n.id)[1]))}}}
  for(const e of d.edges||[]){if(!e.xchain)continue;const x=cy.getElementById(e.source+'>'+e.target+(e.unit||''));if(!x.length)continue;const b=e.bridge||{};
   x.data('xchain',1);if(b.method==='heuristic')x.data('heur',1);
   x.data('lbl','⇄ '+(b.bridge||'bridge').replace(/ \(.*\)$/,'')+' · '+fmt(e.amount,4)+' '+String(e.unit||'').replace('⇄','')+(e.usd?' · '+usd(e.usd):'')+(b.method==='heuristic'?' · lead':''))}})};
// ---------- expand guard: other chains are display-only ----------
const _expB=window.expand;window.expand=function(id){if(isForeign(id)&&!String(id).startsWith('grp:')){const[c,a]=rawId(id);toast((CH[c||chainOf[id]]?.n||'This chain')+' is shown for context only — open it in the explorer');return}return _expB(id)};
// ---------- API ----------
async function bapi(q,anchor,heur=true){const r=await fetch('/api/bridge?q='+encodeURIComponent(q)+(anchor?'&anchor='+encodeURIComponent(anchor):'')+(heur==='always'?'&heuristic=always':heur?'':'&heuristic=false'));
 const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.detail||('HTTP '+r.status));return j}
window.ctBridgeApi=bapi;
const legH=(s,lab)=>`<div>${lab}</div><div>${ctag(s.chain)} ${s.address?`<a class="mono" target="_blank" rel="noopener" href="${esc(s.address_url||'#')}" title="${esc(s.address)}">${short(s.address)}</a>`:'<span class="dim">recipient not decoded</span>'}
 ${s.amount!=null?`<b>${fmt(s.amount,6)} ${esc(s.unit||'')}</b>`:''}<div class="dim" style="font-size:11px">${s.tx?`tx <a class="mono" target="_blank" rel="noopener" href="${esc(s.tx_url||'#')}" title="${esc(s.tx)}">${short(s.tx)}</a> <button class="copy" onclick="copy('${esc(s.tx)}')">⧉</button>`:'<span>no tx yet</span>'} · ${s.time?tfmt(s.time)+' UTC':'time n/a'}</div></div>`;
function matchH(m,i,opts={}){const h=m.method==='heuristic';
 return `<div class="xm ${h?'heur':''}"><div class="hd">⇄ ${esc(m.bridge)} <span class="mth ${h?'heu':'det'}">${h?'heuristic · lead only':'deterministic'}</span><span class="conf">conf ${Math.round((m.confidence||0)*100)}% · ${esc(m.status||'')}</span>${m.usd?`<span class="usd">${usd(m.usd)}</span>`:''}</div>
 <div class="lg">${legH(m.src,'From')}${legH(m.dst,'To')}</div>
 <div class="xnote">${esc(m.evidence||'')}${m.ref?` · <a target="_blank" rel="noopener" href="${esc(m.ref)}">bridge explorer ↗</a>`:''}</div>
 ${(m.notes||[]).map(n=>`<div class="xnote">• ${esc(n)}</div>`).join('')}
 ${opts.noAdd?'':`<div class="row"><button class="btn sm ${h?'':'pri'}" onclick="ctBridgeAdd(${i})">${h?'Add as lead (dashed)':'＋ Add cross-chain hop'}</button>${m.dst.expandable&&m.dst.address?`<button class="btn sm" onclick="ctBridgeTrace(${i})">Trace destination as root</button>`:''}</div>`}</div>`}
const CAVEAT='<div class="caveat">⚠ Deterministic = linked by the bridge’s own indexer (message / order id). <b>Heuristic matches are investigative leads, not evidence</b>: amount + time + same-address coincidence only. Verify on both explorers before relying on any link.</div>';
let LAST=[];   // matches currently listed (index = button arg)
window.ctBridgeAdd=i=>{const m=LAST[i];if(!m||!m.graph)return;add(m.graph,null);const e=m.graph.edges[0];if(e){const x=cy.getElementById(e.source+'>'+e.target+(e.unit||''));if(x.length){cy.elements().unselect();x.select();cy.animate({fit:{eles:x.connectedNodes(),padding:90}},{duration:400})}}toast(m.method==='heuristic'?'Lead added (dashed amber)':'Cross-chain hop added')};
window.ctBridgeTrace=i=>{const m=LAST[i];if(!m)return;$('q').value=m.dst.address;setBadge();go()};
function listH(j,title,opts={}){const ms=j.matches||[],hs=j.heuristic||[];const all=ms.concat(hs);const base=LAST.length;LAST=LAST.concat(all);
 const tried=(j.tried||[]).map(t=>`${esc(t.provider)}${t.error?' ⚠':''}`).join(' · ');
 return `<div class="card glass xcard" id="${opts.id||''}"><h3>⇄ ${title}<span class="sp"></span><span class="dim" style="text-transform:none;letter-spacing:0">${all.length} match(es)${j.cached?' · cached':''}</span></h3>
 ${all.map((m,k)=>matchH(m,base+k,opts)).join('')||`<div class="dim" style="font-size:12.5px">No bridge transfer found for this ${j.kind==='address'?'address':'transaction'}.</div>`}
 ${j.heuristic_note?`<div class="xnote">Heuristic search: ${esc(j.heuristic_note)}</div>`:''}
 <div class="dim" style="font-size:10.5px;margin-top:6px">Checked: ${tried||'–'}${(j.tried||[]).some(t=>t.error)?' (⚠ = provider unavailable, result may be incomplete)':''}</div>${CAVEAT}</div>`}
window.ctBridgeList=listH;
// ---------- follow across a bridge (from a bridge node or edge) ----------
async function follow(txs,anchor,where){txs=[...new Set(txs.filter(Boolean))].slice(0,4);if(!txs.length){toast('No transaction hash on these flows');return}
 const box=$(where)||$('det');const id='xf'+Date.now();box.insertAdjacentHTML('afterbegin',`<div class="card glass xcard" id="${id}"><h3>⇄ Following across bridge…</h3><div class="sk"></div><div class="sk" style="width:70%"></div></div>`);
 busy(true,'Checking bridge indexers for '+txs.length+' tx(s)…');LAST=[];let html='',added=0,leads=0;
 const res=await Promise.all(txs.map(t=>bapi(t,anchor).catch(e=>({error:e.message,query:t,matches:[],heuristic:[]}))));
 for(const j of res){if(j.error){html+=`<div class="warnbox">${short(j.query)}: ${esc(j.error)}</div>`;continue}
  for(const m of j.matches||[]){if(m.method==='deterministic'&&m.confidence>=.95&&m.graph){add(m.graph,null);added++}}
  leads+=(j.heuristic||[]).length;html+=listH(j,'Bridge match · '+short(j.query))}
 busy(false,added?`Added ${added} deterministic cross-chain hop(s)`:leads?`${leads} heuristic lead(s): review before adding`:'No cross-chain match found');
 const el=$(id);if(el)el.outerHTML=html||'<div class="card glass">No result</div>';toast(added?`+${added} cross-chain hop(s)`:leads?'Heuristic leads only: not auto-added':'No bridge match')}
window.ctFollowNode=id=>{const n=cy.getElementById(id);if(!n.length)return;const ins=n.connectedEdges().filter(e=>!e.data('xchain')&&!e.data('meta'));
 follow(ins.map(e=>(e.data('info')||{}).tx),id)};
window.ctFollowEdge=id=>{const e=cy.getElementById(id);if(!e.length)return;const x=e.data('info')||{};const tgt=cy.getElementById(x.target),src=cy.getElementById(x.source);
 const anchor=tgt.data('kind')==='bridge'?x.target:src.data('kind')==='bridge'?x.source:null;follow([x.tx],anchor)};
window.ctXActivity=async(a)=>{const box=$('side');const id='xact';$(id)?.remove();box.insertAdjacentHTML('beforeend',`<div class="card glass xcard" id="${id}"><h3>⇄ Cross-chain activity</h3><div class="sk"></div><div class="sk"></div></div>`);
 LAST=[];try{const j=await bapi(a);$(id).outerHTML=listH(j,'Cross-chain activity',{id})}catch(e){$(id).innerHTML=`<h3>⇄ Cross-chain activity</h3><div class="warnbox">${esc(e.message)}</div>`}};
// ---------- edge tap: bridge card ----------
cy.on('tap','edge',e=>{const x=e.target.data('info')||{};const det=$('det');const first=det.querySelector('.card');
 if(x.xchain&&x.bridge){LAST=[x.bridge];const html=`<div class="card glass xcard"><h3>⇄ Cross-chain hop</h3>${matchH(x.bridge,0,{noAdd:1})}${CAVEAT}</div>`;if(first)first.outerHTML=html;else det.insertAdjacentHTML('afterbegin',html);return}
 const t=cy.getElementById(x.target),s=cy.getElementById(x.source);
 if((t.data('kind')==='bridge'||s.data('kind')==='bridge')&&x.tx&&first)first.insertAdjacentHTML('beforeend',`<div class="row"><button class="btn sm pri" onclick="ctFollowEdge('${esc(e.target.id())}')">⇄ Follow across bridge</button></div><div class="dim" style="font-size:11px;margin-top:4px">Looks up this tx in Wormhole, deBridge, Mayan, Across, THORChain/Maya, LayerZero/Stargate and Relay indexers.</div>`)});
// ---------- node tap: bridge + foreign nodes ----------
cy.on('tap','node',e=>{const n=e.target.data('info')||{};const det=$('det');const first=det.querySelector('.card');if(!first||e.target.data('grp'))return;
 const[c,a]=rawId(n.id);
 if(c||(n.chain&&!NATIVE.includes(n.chain))){const ch=c||n.chain;const addr=a||n.id;
  first.innerHTML=`<h3>${ctag(ch)} ${esc(n.name||(String(addr).startsWith('tx:')?'Transaction':'Address'))} ${tagH(n.kind)}</h3><div class="addr"><span class="mono">${esc(addr)}</span><button class="copy" onclick="copy('${esc(addr)}')">⧉</button>${CH[ch]?`<a class="copy" target="_blank" rel="noopener" href="${esc(n.address_url||(CH[ch].ad+addr))}">↗</a>`:''}</div>
  <div class="dim" style="font-size:12px;margin-top:8px">Reached through a cross-chain bridge. ${esc(CH[ch]?.n||ch)} is shown for context: ChainTrace expands BTC, ETH and SOL only, so continue in the explorer.</div>`;return}
 if(n.kind==='bridge'){const r=first.querySelector('.row')||first.appendChild(Object.assign(document.createElement('div'),{className:'row'}));
  r.insertAdjacentHTML('afterbegin',`<button class="btn sm pri" onclick="ctFollowNode('${esc(n.id)}')">⇄ Follow across bridge</button>`);
  first.insertAdjacentHTML('beforeend','<div class="dim" style="font-size:11px;margin-top:6px">Follows the flows touching this bridge to the destination chain. Deterministic matches are added as dashed cyan edges; heuristic leads are listed for review only.</div>')}});
// ---------- lookups: auto-check bridge txs, cross-chain activity button ----------
const _renderB=window.render;window.render=function(d){_renderB(d);try{
 if(d&&d.kind==='tx'){const id='xtx';$('side').insertAdjacentHTML('beforeend',`<div class="card glass xcard" id="${id}"><h3>⇄ Cross-chain</h3><div class="dim" style="font-size:12px">Checking bridge indexers…</div></div>`);
  LAST=[];bapi(d.tx).then(j=>{const el=$(id);if(!el)return;if(!(j.matches||[]).length&&!(j.heuristic||[]).length&&!(d.nodes||[]).some(n=>n.kind==='bridge')){el.innerHTML=`<h3>⇄ Cross-chain</h3><div class="dim" style="font-size:12px">Not a recognised bridge transfer.</div>`;return}
   el.outerHTML=listH(j,'Cross-chain match',{id});
   for(const m of j.matches||[])if(m.method==='deterministic'&&m.confidence>=.95&&m.graph){const anchor='tx:'+d.tx;const g=JSON.parse(JSON.stringify(m.graph));
    for(const e of g.edges){if(m.side==='dst')e.target=anchor;else e.source=anchor}add(g,null)}
  }).catch(e=>{const el=$(id);if(el)el.innerHTML=`<h3>⇄ Cross-chain</h3><div class="warnbox">${esc(e.message)}</div>`})}
 else if(d&&d.kind==='address'){const f=$('side').querySelector('.card');const r=f&&(f.querySelector('.row')||f.appendChild(Object.assign(document.createElement('div'),{className:'row'})));
  if(r&&!r.querySelector('.xbtn'))r.insertAdjacentHTML('beforeend',`<button class="btn sm xbtn" onclick="ctXActivity('${esc(d.address)}')">⇄ Cross-chain activity</button>`)}}catch(e){console.warn(e)}};
// ---------- AutoTrace: follow bridges (deterministic only) ----------
const seg=$('amin')?.parentElement;if(seg&&!$('xfollow'))seg.insertAdjacentHTML('beforeend',` <label class="chk" title="Continue the trace across bridges when the bridge's own indexer links the destination (deterministic matches only)"><input type="checkbox" id="xfollow" checked> ⇄ bridges</label>`);
window.autoTrace=async function(){const q=$('q').value.trim();if(!q)return;let dir=$('dir').value;if(dir==='both'){dir='forward';toast('AutoTrace follows one direction: using forward')}
 mode='auto';share();cy.elements().remove();expanded.clear();$('det').innerHTML='';skeleton();
 const p=`q=${encodeURIComponent(q)}&direction=${dir}&max_hops=${$('amax').value}&min_usd=${+$('amin').value||0}&topk=${$('topk').value}&follow_bridges=${$('xfollow')?.checked?'true':'false'}`;
 const r=await fetch('/api/autotrace?'+p,{method:'POST'});const j=await r.json();if(!r.ok){busy(false,'Error: '+j.detail);toast(j.detail);$('side').innerHTML='';return}
 job=j.job;$('tracebtn').disabled=true;$('autobtn').disabled=true;$('cancelbtn').style.display='';busy(true,'AutoTrace queued…');poll(job)};
const _renderAutoB=window.renderAuto;window.renderAuto=function(j){_renderAutoB(j);const bs=j.bridges||[];if(!bs.length&&!j.params?.follow_bridges)return;
 LAST=bs.map(b=>({...b,evidence:'',notes:[],status:'completed'}));
 $('side').insertAdjacentHTML('beforeend',`<div class="card glass xcard"><h3>⇄ Cross-chain hops · ${bs.length}</h3>${bs.map(b=>`<div class="path" onclick="(()=>{const n=cy.getElementById('${esc(b.node)}');if(n.length){cy.nodes().unselect();n.select();cy.animate({center:{eles:n},zoom:1.3},{duration:350})}})()">
  <span class="mth det">det</span><div style="flex:1;min-width:0"><div style="font-weight:600">${esc(b.bridge)} <span class="xarrow">${esc(CH[b.src.chain]?.n||b.src.chain)} → ${esc(CH[b.dst.chain]?.n||b.dst.chain)}</span></div>
  <div class="dim" style="font-size:11px">${fmt(b.src.amount,6)} ${esc(b.src.unit||'')} → ${fmt(b.dst.amount,6)} ${esc(b.dst.unit||'')} · conf ${Math.round(b.confidence*100)}% · ${esc(b.provider)}</div></div></div>`).join('')||'<div class="dim" style="font-size:12px">No bridge reached, or no deterministic match for the bridges reached.</div>'}
  <div class="dim" style="font-size:11px;margin-top:6px">Only deterministic matches (bridge indexer links) are followed automatically. Tap a bridge node → “Follow across bridge” to see heuristic leads.</div></div>`)};
})();

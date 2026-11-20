// ChainTrace v23: BTC "likely same wallet" clustering (common-input heuristic, CoinJoins excluded, optional change heuristic).
// HEURISTIC LEAD, never attribution. Members can be added to the graph and collapsed into one compound node.
(()=>{
CAT.cluster=['#c792ea','🧩','Likely same wallet (lead)'];
cy.style().selector('node[?grp][gkind="cluster"]').style({'border-style':'dashed','border-color':'#c792ea','border-width':2.5,'background-color':'#c792ea','background-opacity':.08,color:'#e3c6ff'}).update();
const css=document.createElement('style');css.textContent=`.clucard .lead{margin-top:8px;font-size:11.5px;color:#e3c6ff;border:1px dashed rgba(199,146,234,.55);border-radius:9px;padding:6px 8px;background:rgba(199,146,234,.07)}
.clucard .m{display:flex;gap:6px;align-items:center;font-size:12px;padding:4px 0;border-top:1px solid var(--line)}.clucard .m .mono{flex:1;word-break:break-all}
.clucard .rs{font-size:10.5px;padding:1px 6px;border-radius:8px;border:1px solid rgba(199,146,234,.5);color:#e3c6ff;white-space:nowrap}.clucard .rs.ch{border-color:rgba(246,201,69,.6);color:#f6dd8a}
.clucard .lst{max-height:300px;overflow:auto;margin-top:6px}.clucard .cj{font-size:11.5px;margin-top:6px}.clucard .warn2{font-size:11.5px;margin-top:6px;color:#ffcf8a}`;document.head.appendChild(css);
let LAST=null,PEND=null;
const ttxt=t=>t?new Date(t*1000).toISOString().slice(0,10):'';
function card(j){const a=j.addresses||[];const r=j.by_reason||{};
 return `<div class="card glass clucard" id="clucard"><h3>🧩 Likely same wallet ${tagH('cluster')}</h3>
 <div style="font-size:13px"><b>${a.length}</b> address${a.length===1?'':'es'} · ${r['common-input']||0} by common input${r.change?` · ${r.change} by change`:''} · ${j.txs_scanned} txs scanned · ${j.coinjoin_count} CoinJoin tx${j.coinjoin_count===1?'':'s'} excluded</div>
 ${j.truncated?`<div class="warn2">⚠ Search stopped early: ${esc(j.truncated)} – the cluster may be larger.</div>`:''}
 ${(j.notes||[]).map(n=>`<div class="warn2">⚠ ${esc(n)}</div>`).join('')}
 <div class="row" style="margin-top:8px;flex-wrap:wrap;gap:6px"><button class="btn sm" id="cluadd" onclick="ctClusterAdd(false)">＋ Add to graph</button><button class="btn sm" id="clucol" onclick="ctClusterAdd(true)">▣ Collapse into one node</button>
  <button class="btn sm" onclick="ctClusterCSV()">⬇ CSV</button><label class="dim" style="font-size:11.5px"><input type="checkbox" id="cluchg" ${j.caps&&j.caps.change?'checked':''} onchange="ctCluster('${esc(j.root)}')"> + change heuristic</label></div>
 <div class="lst">${a.map(m=>`<div class="m"><span class="mono">${esc(m.address)}${m.name?` <span class="dim">· ${esc(m.name)}</span>`:''}</span>
  <span class="rs ${m.reason==='change'?'ch':''}" title="${esc(m.tx?('tx '+m.tx+(m.with?' with '+m.with:'')+(m.why?' – '+m.why:'')):'')}">${m.reason==='root'?'searched':m.reason==='change'?'change '+Math.round((m.confidence||0)*100)+'%':'co-spent'}${m.hop?' · hop '+m.hop:''}</span>
  ${m.tx?`<a class="copy" target="_blank" rel="noopener" title="Evidence transaction" href="${CH.btc.tx+esc(m.tx)}">↗</a>`:''}</div>`).join('')}</div>
 ${j.coinjoin_count?`<details class="cj"><summary class="dim">CoinJoin transactions excluded (${j.coinjoin_count})</summary>${(j.coinjoin_skipped||[]).map(c=>`<div><a class="mono" target="_blank" rel="noopener" href="${CH.btc.tx+esc(c.tx)}">${esc(short(c.tx))}</a> ${ttxt(c.time)} – ${esc(c.why)}</div>`).join('')}</details>`:''}
 <details class="cj"><summary class="dim">Method and caps</summary><div class="dim">${esc(j.method)} Caps: depth ${j.caps.depth}, ${j.caps.max_txs} txs, ${j.caps.max_addrs} addresses, ${j.caps.max_secs}s (took ${j.secs}s).</div></details>
 <div class="lead">⚠ ${esc(j.lead)}</div></div>`}
const PH=`<div class="card glass clucard" id="clucard"><h3>🧩 Likely same wallet</h3><div class="dim" style="font-size:12px">Clustering by common inputs (bounded search, up to ~20 s)…</div></div>`;
const put=h=>{const el=$('clucard');if(el)el.outerHTML=h;else $('side').insertAdjacentHTML('beforeend',h)};
window.ctCluster=async function(a){const chg=($('cluchg')||{}).checked?1:0;PEND=a;LAST=null;put(PH);
 try{const r=await fetch('/api/btc/cluster?address='+encodeURIComponent(a)+'&change='+chg);const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);LAST=j;PEND=null;window.CT_LAST_CLUSTER=j;put(card(j));
  if(typeof ctAudit==='function')try{ctAudit('cluster.run',{root:a,size:j.size,coinjoin_excluded:j.coinjoin_count,change:!!chg})}catch(e){}}
 catch(e){PEND=null;const c=$('clucard');if(c)c.innerHTML=`<h3>🧩 Likely same wallet</h3><div class="warnbox">${esc(e.message)}</div>`}};
window.ctClusterAdd=function(col){const j=LAST;if(!j)return;const root=j.root;const clu={root,size:j.size,lead:true};
 const nodes=j.addresses.map(m=>({id:m.address,chain:'btc',name:m.name||null,kind:m.kind||null,cluster:{...clu,reason:m.reason,tx:m.tx||null}}));
 add({nodes,edges:[],unit:'BTC'},null);
 cy.batch(()=>{for(const m of j.addresses){const n=cy.getElementById(m.address);if(n.length)n.data('info',{...(n.data('info')||{}),id:m.address,chain:'btc',cluster:{...clu,reason:m.reason,tx:m.tx||null}})}});
 ctGroupOn();ctRefresh(false);const gid='grp:wal:'+root;
 if(col){ctCollapse(gid);toast('Collapsed '+j.size+' addresses into one node (heuristic lead)')}else{ctSplit(gid);toast('Added '+j.size+' addresses as a “likely same wallet” group')}
 relayout();
 if(typeof ctAudit==='function')try{ctAudit('cluster.added',{root,size:j.size,collapsed:!!col})}catch(e){}};
window.ctClusterCSV=function(){const j=LAST;if(!j)return;const q=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
 const rows=[['address','reason','hop','evidence_tx','with','time_utc','confidence','label'].join(',')].concat(j.addresses.map(m=>[m.address,m.reason,m.hop,m.tx||'',m.with||'',m.time?new Date(m.time*1000).toISOString():'',m.confidence||'',m.name||''].map(q).join(',')));
 rows.push('');rows.push(q('Heuristic lead – not attribution. '+j.method));const b=new Blob([rows.join('\n')],{type:'text/csv'});const u=URL.createObjectURL(b);const x=document.createElement('a');x.href=u;x.download='cluster_'+j.root.slice(0,12)+'.csv';x.click();setTimeout(()=>URL.revokeObjectURL(u),2000)};
const nav=(performance.getEntriesByType('navigation')[0]||{}).name||location.href;   // the page rewrites ?q= before this script loads
let auto=new URL(nav).searchParams.get('cluster')==='1';
const _render=window.render;window.render=function(d){_render(d);try{if(d&&d.chain==='btc'&&d.address&&!d.tx){const r=$('side').querySelector('.card .row')||$('side').querySelector('.card');
  if(r&&!$('side').querySelector('.clubtn'))r.insertAdjacentHTML(r.classList.contains('row')?'beforeend':'beforeend',`<button class="btn sm clubtn" title="Common-input clustering (heuristic lead)" onclick="ctCluster('${esc(d.address)}')">🧩 Likely same wallet</button>`);
  if(auto){auto=false;ctCluster(d.address)}else if(LAST&&LAST.root===d.address)put(card(LAST));else if(PEND===d.address)put(PH)}}catch(e){}};
setTimeout(()=>{if(auto&&typeof cur!=='undefined'&&cur&&cur.chain==='btc'&&cur.address&&!cur.tx){auto=false;ctCluster(cur.address)}},0);
})();

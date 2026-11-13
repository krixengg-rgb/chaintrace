// ChainTrace v15: BTC change-address heuristics + peel-chain detection. Everything here is a HEURISTIC LEAD (amber / dotted), never attribution.
(()=>{
CAT.peel=['#f6c945','⤳','Peel chain (lead)'];
cy.style().selector('edge[?peel]').style({'line-style':'dotted','line-color':'#f6c945','target-arrow-color':'#f6c945',color:'#f6dd8a',width:e=>Math.max(2.4,ew(e))})
 .selector('edge[?peeled]').style({'line-color':'rgba(255,159,67,.75)','target-arrow-color':'rgba(255,159,67,.9)',color:'#ffd9b0'})
 .selector('node[?grp][gkind="peel"]').style({'border-style':'dashed','border-color':'#f6c945','border-width':2,'background-color':'#f6c945','background-opacity':.06,color:'#f6dd8a'}).update();
const css=document.createElement('style');css.textContent=`.chgcard .out{border:1px solid var(--line);border-radius:10px;padding:7px 9px;margin-top:6px;font-size:12px;background:rgba(0,0,0,.16)}
.chgcard .out.best{border-color:rgba(246,201,69,.6);background:rgba(246,201,69,.07)}.chgcard .pb{height:6px;border-radius:3px;background:rgba(255,255,255,.07);margin-top:5px;overflow:hidden}.chgcard .pb i{display:block;height:100%;background:#f6c945}
.chgcard .hl{font-size:11.5px;margin-top:8px}.chgcard .hl div{margin:3px 0}.chgcard .hl b{color:#f6dd8a}.chgcard .hl .no{color:var(--mut)}
.chgcard .lead,.peelcard .lead{margin-top:8px;font-size:11.5px;color:#ffcf8a;border:1px dashed rgba(246,201,69,.5);border-radius:9px;padding:6px 8px;background:rgba(246,201,69,.06)}
.peelcard .st{font-size:12px;padding:6px 8px;border-top:1px solid var(--line);cursor:pointer}.peelcard .st:hover{background:rgba(255,255,255,.03)}.peelcard .st .dim{font-size:11px}
.peelcard .vd{font-size:13px;margin:6px 0;padding:8px 10px;border-radius:10px;background:rgba(246,201,69,.08);border:1px solid rgba(246,201,69,.4)}`;document.head.appendChild(css);
const nf=x=>x==null?'–':(+x).toLocaleString('en-GB',{maximumFractionDigits:8});
const LEADTXT='Heuristic lead – not attribution. Change detection can be defeated by wallets (same-type or round change, address reuse, coin control, CoinJoin, PayJoin). Corroborate before relying on it.';
function decorate(){cy.edges().forEach(e=>{const i=e.data('info')||{};
  if(i.peel&&!e.data('peel')){e.data('peel',1);e.data('heur',1);const c=i.change||{};e.data('lbl','change? '+Math.round((c.confidence||0)*100)+'% · '+fmt(i.amount,6)+' BTC · lead')}
  if(i.peeled&&!e.data('peeled')){e.data('peeled',1);e.data('lbl','peeled · '+fmt(i.amount,6)+' BTC')}})}
window.ctPeelDecorate=decorate;
const _add=window.add;window.add=function(d,f){_add(d,f);try{decorate()}catch(e){}};
// ---------- change analysis card (BTC tx) ----------
const card=A=>{const best=A.change;const outs=A.outputs||[];
 return `<div class="card glass chgcard"><h3>🔀 Change analysis ${tagH('peel')}</h3>
 ${A.note?`<div class="dim" style="font-size:12px">${esc(A.note)}</div>`:best?`<div style="font-size:12.5px">Likely change: <b class="mono">${esc(short(best.address))}</b> · ${nf(best.value)} BTC · <b>${Math.round(best.confidence*100)}%</b> (${esc(best.level)})</div>`:`<div style="font-size:12.5px">No output reaches the ${Math.round((A.min_conf||.6)*100)}% threshold (best ${Math.round((A.p_best||0)*100)}%).</div>`}
 ${outs.map(o=>`<div class="out${best&&o.n===best.n?' best':''}"><div style="display:flex;gap:6px;align-items:center"><span class="mono" style="flex:1;word-break:break-all">#${o.n} ${esc(o.address)}</span><b>${Math.round(o.p_change*100)}%</b></div>
  <div class="dim" style="font-size:11px">${nf(o.value)} BTC · ${esc(o.type||'')}${o.name?' · '+esc(o.name):''}${o.spent===false?' · unspent':''}</div><div class="pb"><i style="width:${Math.round(o.p_change*100)}%"></i></div></div>`).join('')}
 <div class="hl">${(A.heuristics||[]).map(h=>`<div>${h.output!=null?`<b>${esc(h.name)} → #${h.output}</b> (${Math.round(h.weight*100)}%)`:`<span class="no">${esc(h.name)}: no vote</span>`} <span class="dim">${esc(h.saw)}</span></div>`).join('')}</div>
 ${outs.length>1?`<div class="row" style="margin-top:8px"><button class="btn sm" onclick="ctPeel('${esc(A.tx)}')">⤳ Follow peel chain</button></div>`:''}
 <div class="lead">⚠ ${esc(LEADTXT)}</div></div>`};
window.ctChange=async function(tx,el){try{const r=await fetch('/api/btc/change?tx='+encodeURIComponent(tx));const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);window.CT_LAST_CHANGE=j;
  const h=card(j);if(el&&document.body.contains(el))el.outerHTML=h;else $('det').insertAdjacentHTML('afterbegin',h)}catch(e){if(el&&document.body.contains(el))el.innerHTML=`<h3>🔀 Change analysis</h3><div class="warnbox">${esc(e.message)}</div>`}};
const ph=id=>`<div class="card glass chgcard" id="${id}"><h3>🔀 Change analysis</h3><div class="dim" style="font-size:12px">Scoring outputs…</div></div>`;
cy.on('tap','node',e=>{const i=e.target.data('info')||{};const id=e.target.id();if(i.chain!=='btc'||e.target.data('grp'))return;
 setTimeout(()=>{const det=$('det');if(id.startsWith('tx:')){if(det.querySelector('.chgcard'))return;det.insertAdjacentHTML('beforeend',ph('chgph'));ctChange(id.slice(3),$('chgph'));return}
  const r=det.querySelector('.card .row');if(r&&!r.querySelector('.pbtn'))r.insertAdjacentHTML('beforeend',`<button class="btn sm pbtn" title="Follow likely change outputs (heuristic lead)" onclick="ctPeel('${esc(id)}')">⤳ Peel chain</button>`);
  if(i.peel)det.insertAdjacentHTML('beforeend',`<div class="card glass peelcard"><h3>⤳ Peel chain member ${tagH('peel')}</h3><div class="dim" style="font-size:12px">Step ${i.peel.index} of a ${i.peel.hops}-hop chain inferred from change heuristics.</div><div class="lead">⚠ ${esc(LEADTXT)}</div></div>`)},0)});
cy.on('tap','edge',e=>{const i=e.target.data('info')||{};if(!i.change)return;setTimeout(()=>{const det=$('det');if(det.querySelector('.chgedge'))return;const c=i.change;
 det.insertAdjacentHTML('afterbegin',`<div class="card glass chgcard chgedge"><h3>⤳ Likely change (heuristic) ${tagH('peel')}</h3><div style="font-size:12.5px"><b>${Math.round(c.confidence*100)}%</b> (${esc(c.level)}) that output #${c.vout} of tx <span class="mono">${esc(short(i.tx||''))}</span> is the sender's change.</div>
  <div class="hl">${(c.reasons||[]).map(r=>`<div><b>✓</b> ${esc(r)}</div>`).join('')}${(c.against||[]).map(r=>`<div><span class="no">✗ against:</span> ${esc(r)}</div>`).join('')}</div><div class="lead">⚠ ${esc(LEADTXT)}</div></div>`)},0)});
// tx lookups: add the card to the side panel
const _render=window.render;window.render=function(d){_render(d);try{if(d&&d.chain==='btc'&&d.tx&&(d.outputs||[]).length>1){$('side').insertAdjacentHTML('beforeend',ph('chgside'));ctChange(d.tx,$('chgside'))}}catch(e){}};
// ---------- peel chain ----------
const LASTP={};
window.ctPeel=async function(q,opts={}){busy(true,'Following likely change outputs…');
 try{const r=await fetch('/api/btc/peel?q='+encodeURIComponent(q)+'&max_hops='+(opts.hops||12));const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);window.CT_LAST_PEEL=j;LASTP[j.id]=j;
  j.nodes.forEach(n=>{if(!n.peel)return;const c=cy.getElementById(n.id);if(c.length&&!c.data('focus'))c.data('info',Object.assign({},c.data('info')||{},{peel:n.peel}))});   // nodes already on the graph join the group too
  add({chain:'btc',unit:'BTC',nodes:j.nodes,edges:j.edges},null);decorate();busy(false,'');
  toast(j.is_peel?`Peel chain: ${j.hops} hops (heuristic lead)`:`${j.hops} change hop(s) followed`);
  $('det').innerHTML=pcard(j);if(innerWidth<900)$('det').scrollIntoView({behavior:'smooth'});
  const ids=new Set();j.edges.forEach(e=>{ids.add(e.source);ids.add(e.target)});const els=cy.nodes().filter(n=>ids.has(n.id()));if(els.length)cy.animate({fit:{eles:els,padding:50}},{duration:450})}
 catch(e){busy(false,'Peel chain: '+e.message);toast(e.message)}};
const pcard=j=>`<div class="card glass peelcard"><h3>⤳ ${j.is_peel?'Peel chain':'Change hops'} · ${j.hops} ${tagH('peel')}</h3>
 <div class="vd">${esc(j.verdict)}</div><div class="kv"><div>Peeled</div><div>${nf(j.total_peeled)} BTC in ${j.payments} payment(s)</div><div>End</div><div>${j.end?`<span class="mono">${esc(short(j.end.address))}</span> · ${nf(j.end.value)} BTC`:'–'}</div><div>Stopped</div><div>${esc(j.stop_reason)}</div></div>
 ${j.steps.map((s,k)=>`<div class="st" onclick="(()=>{const n=cy.getElementById('${esc(s.change?s.change.address:s.from)}');if(n.length){cy.nodes().unselect();n.select();cy.animate({center:{eles:n},zoom:1.2},{duration:300})}})()"><b>${k+1}.</b> ${s.time?tfmt(s.time):'pending'} · in ${nf(s.in_value)} BTC → ${s.change?`change ${nf(s.change.value)} (${Math.round(s.change.confidence*100)}%)`:'no confident change'}<div class="dim">peeled: ${s.payments.map(p=>nf(p.value)+' → '+esc(p.name||short(p.address))).join(', ')||'–'}</div></div>`).join('')}
 ${j.continue_from?`<div class="row" style="margin-top:6px"><button class="btn sm" onclick="ctPeel('${esc(j.continue_from)}')">Continue from ${esc(short(j.continue_from))}</button></div>`:''}
 <div class="lead">⚠ ${esc(LEADTXT)}</div></div>`;
// ---------- AutoTrace option ----------
const seg=$('amin')?.parentElement;if(seg&&!$('pfollow'))seg.insertAdjacentHTML('beforeend',` <label class="chk" title="BTC: follow the likely change output of each spend (heuristic lead); other outputs are shown as peeled payments"><input type="checkbox" id="pfollow"> ⤳ change</label>`);
const PP=new URLSearchParams(window.CT_URL0||location.search);if(PP.get('change')==='1'&&$('pfollow'))$('pfollow').checked=true;
if(PP.get('peel')){const q=PP.get('peel');let n=0;const iv=setInterval(()=>{n++;if(!document.body.classList.contains('busy')&&(cy.nodes().length>0||!PP.get('q'))){clearInterval(iv);setTimeout(()=>ctPeel(q,{hops:+PP.get('hops')||12}),700)}else if(n>200)clearInterval(iv)},400)}
const _renderAuto=window.renderAuto;window.renderAuto=function(j){_renderAuto(j);try{decorate();const ps=j.peel||[];if(!ps.length&&!(j.params||{}).follow_change)return;
 $('side').insertAdjacentHTML('beforeend',`<div class="card glass peelcard"><h3>⤳ Change followed · ${ps.length} ${tagH('peel')}</h3>${ps.slice(0,30).map(p=>`<div class="st"><span class="mono">${esc(short(p.from))}</span> → <span class="mono">${esc(short(p.change))}</span> · ${nf(p.value)} BTC · ${Math.round(p.confidence*100)}%<div class="dim">${esc((p.reasons||[]).join('; '))}</div></div>`).join('')||'<div class="dim" style="font-size:12px">No confident change output found on the spends checked.</div>'}<div class="lead">⚠ ${esc(LEADTXT)}</div></div>`)}catch(e){}};
decorate();
})();

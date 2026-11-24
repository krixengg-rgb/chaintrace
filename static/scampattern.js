// ChainTrace v31: fake-recovery / pig-butchering scam-pattern flags + public scam reports with sources. Heuristic lead, not evidence.
(()=>{
const css=document.createElement('style');css.textContent=`.spcard .ban{margin:6px 0;font-size:11.5px;color:#ffe3a3;border:1px dashed rgba(246,201,69,.6);border-radius:9px;padding:6px 8px;background:rgba(246,201,69,.07);font-weight:600}
.spcard .fl{border-top:1px solid var(--line);padding:6px 0}.spcard .fl b{font-size:12.5px}.spcard .st{display:inline-block;font-size:10.5px;padding:1px 6px;border-radius:8px;background:rgba(246,201,69,.15);color:#f6c945;margin-left:6px}
.spcard ul{margin:3px 0 0 16px;padding:0;font-size:11.5px;color:var(--dim,#9aa)}.spcard .tx{font:10.5px var(--mono,monospace);word-break:break-all}.spcard .tx a{color:#8fb8ff}
.spcard .rp{font-size:11.5px;border-top:1px solid var(--line);padding:4px 0;overflow-wrap:anywhere}.spcard .rp a{color:#8fb8ff}.spcard .none{font-size:11.5px;color:var(--dim,#9aa)}`;document.head.appendChild(css);
let LAST=null,PEND=null;const E=s=>typeof esc==='function'?esc(s):String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const PH=`<div class="card glass spcard" id="spcard"><h3>🎣 Scam-pattern flags</h3><div class="none">Checking fee-deposit, fan-in, fee-after-loss and recovery-fee patterns…</div></div>`;
function card(j){
 const fl=(j.flags||[]).map(f=>`<div class="fl"><b>${E(f.name)}</b><span class="st">strength ${Math.round(f.strength*100)}%</span><ul>${(f.evidence||[]).map(x=>`<li>${E(x)}</li>`).join('')}</ul>${(f.txs||[]).length?`<div class="tx">txs: ${[...new Set(f.txs)].slice(0,5).map(t=>`<a href="/?q=${encodeURIComponent(t)}" target="_blank" rel="noopener">${E(String(t).slice(0,14))}…</a>`).join(' · ')}</div>`:''}</div>`).join('');
 const rp=(j.reports||[]).map(r=>`<div class="rp">${r.who==='this address'?'🚩 this address':'↔ counterparty '+E(String(r.address).slice(0,12))+'…'}: <b>${E(r.name||r.category)}</b> (${E(r.category)}) · source: <a href="${E(r.url)}" target="_blank" rel="noopener">${E(r.source)}</a></div>`).join('');
 const ca=j.chainabuse||{};
 return `<div class="card glass spcard" id="spcard"><h3>🎣 Scam-pattern flags <span class="st">${(j.flags||[]).length} flag(s)</span></h3>
 <div class="ban">⚠ HEURISTIC LEAD, NOT EVIDENCE. ${E(String(j.lead||'').replace(/^Heuristic lead, not evidence:\s*/i,''))}</div>
 ${fl||`<div class="none">No pattern matched in the fetched history (${j.history?.edges||0} transfers${j.history&&!j.history.complete?', most recent page only':''}). Checked: ${E((j.checked||[]).join('; '))}.</div>`}
 <h4 style="margin:8px 0 2px;font-size:12px">Public scam reports (sources cited)</h4>${rp||'<div class="none">No scam / phishing labels on this address or its direct counterparties in the loaded datasets.</div>'}
 <div class="none" style="margin-top:4px">Chainabuse: ${ca.status==='ok'||ca.status==='cached'?`${ca.count||0} report(s)`:E(ca.note||ca.status||'not checked')} · <a href="${E(ca.search_url||('https://chainabuse.com/address/'+j.address))}" target="_blank" rel="noopener">search Chainabuse</a></div>
 <div class="none" style="margin-top:4px">Feeds the risk score as the weighted “Scam-pattern flags” factor (10 of 100 points).</div></div>`}
const put=h=>{const el=document.getElementById('spcard');if(el)el.outerHTML=h;else document.getElementById('side').insertAdjacentHTML('beforeend',h)};
window.ctScamPattern=async function(a){PEND=a;LAST=null;put(PH);
 try{const r=await fetch('/api/scampattern?q='+encodeURIComponent(a)+(typeof cur!=='undefined'&&cur&&cur.chain?'&chain='+cur.chain:''));const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);
  LAST=j;PEND=null;window.CT_LAST_SCAMPATTERN=j;put(card(j));
  if(typeof ctAudit==='function')try{ctAudit('scampattern.check',{address:a,flags:(j.flags||[]).map(f=>f.key),reports:(j.reports||[]).length})}catch(e){}}
 catch(e){PEND=null;const c=document.getElementById('spcard');if(c)c.innerHTML=`<h3>🎣 Scam-pattern flags</h3><div class="warnbox">${E(e.message)}</div>`}};
const nav=(performance.getEntriesByType('navigation')[0]||{}).name||location.href;
let auto=new URL(nav).searchParams.get('scam')==='1';
const _render=window.render;window.render=function(d){_render(d);try{if(d&&d.address&&!d.tx){const r=document.getElementById('side').querySelector('.card .row')||document.getElementById('side').querySelector('.card');
  if(r&&!document.getElementById('side').querySelector('.spbtn'))r.insertAdjacentHTML('beforeend',`<button class="btn sm spbtn" title="Fake-recovery / pig-butchering pattern flags (heuristic lead)" onclick="ctScamPattern('${E(d.address)}')">🎣 Scam patterns</button>`);
  if(auto){auto=false;ctScamPattern(d.address)}else if(LAST&&LAST.address===d.address)put(card(LAST));else if(PEND===d.address)put(PH)}}catch(e){}};
setTimeout(()=>{if(auto&&typeof cur!=='undefined'&&cur&&cur.address&&!cur.tx){auto=false;ctScamPattern(cur.address)}},0);
})();

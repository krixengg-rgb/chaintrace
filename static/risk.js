// ChainTrace v26: per-address risk score 0-100 with a transparent weighted breakdown. Indicative lead, not evidence.
(()=>{
const LC={severe:'#ff5c7a',high:'#ff9f43',medium:'#f6c945',low:'#7bd88f',minimal:'#5cc8ff'};
const css=document.createElement('style');css.textContent=`.rkcard .ban{margin:6px 0;font-size:11.5px;color:#ffe3a3;border:1px dashed rgba(246,201,69,.6);border-radius:9px;padding:6px 8px;background:rgba(246,201,69,.07);font-weight:600}
.rkcard .big{display:flex;align-items:center;gap:12px}.rkcard .num{font-size:30px;font-weight:800;line-height:1}.rkcard .gauge{flex:1;height:10px;border-radius:5px;background:rgba(255,255,255,.08);overflow:hidden}.rkcard .gauge i{display:block;height:100%}
.rkcard table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}.rkcard td,.rkcard th{padding:4px;border-top:1px solid var(--line);vertical-align:top;text-align:left}.rkcard th{font-weight:600;color:var(--dim,#9aa)}
.rkcard .ev{font-size:10.8px;color:var(--dim,#9aa)}.rkcard .pb{height:5px;border-radius:3px;background:rgba(255,255,255,.08);margin-top:3px}.rkcard .pb i{display:block;height:100%;border-radius:3px;background:#f6c945}
.rkcard select{background:#161b2a;color:inherit;border:1px solid var(--line);border-radius:6px;padding:1px 4px}`;document.head.appendChild(css);
let LAST=null,PEND=null;
function card(j){const c=LC[j.level]||'#ccc';
 return `<div class="card glass rkcard" id="rkcard"><h3>🎯 Risk score</h3>
 <div class="ban">⚠ Indicative lead, not evidence</div>
 <div class="big"><span class="num" style="color:${c}" id="rknum">${j.score}</span><div style="flex:1"><div style="font-size:12.5px"><b style="color:${c}">${esc(j.level)}</b> / 100${j.pinned?` · <span title="factor total ${j.raw_score}">pinned: sanctions-list match</span>`:''}</div><div class="gauge"><i style="width:${j.score}%;background:${c}"></i></div></div></div>
 <table><tr><th>Factor</th><th>Weight</th><th>Points</th></tr>${j.factors.map(f=>`<tr data-k="${f.key}"><td><b>${esc(f.label)}</b><div class="ev">${f.evidence.map(esc).join('<br>')}</div></td><td>${f.weight}</td>
  <td>${f.points}<div class="pb"><i style="width:${f.weight?100*f.points/f.weight:0}%"></i></div></td></tr>`).join('')}</table>
 ${(j.notes||[]).map(n=>`<div class="ev" style="color:#ffcf8a">⚠ ${esc(n)}</div>`).join('')}
 <details style="font-size:11.5px;margin-top:6px"><summary class="dim">What each factor measures</summary><div class="dim">${j.factors.map(f=>`<div><b>${esc(f.label)} (${f.weight})</b>: ${esc(f.measures)}</div>`).join('')}<div style="margin-top:4px">${esc(j.method)}</div></div></details>
 <div class="ev" style="margin-top:6px">${esc(j.lead)}</div></div>`}
const PH=`<div class="card glass rkcard" id="rkcard"><h3>🎯 Risk score</h3><div class="dim" style="font-size:12px">Scoring (labels, exposure within 2 hops, patterns; up to ~20 s)…</div></div>`;
const put=h=>{const el=$('rkcard');if(el)el.outerHTML=h;else $('side').insertAdjacentHTML('beforeend',h)};
window.ctRisk=async function(a){PEND=a;LAST=null;put(PH);
 try{const r=await fetch('/api/risk?q='+encodeURIComponent(a)+(typeof cur!=='undefined'&&cur&&cur.chain?'&chain='+cur.chain:''));const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);
  LAST=j;PEND=null;window.CT_LAST_RISK=j;put(card(j));
  if(typeof ctAudit==='function')try{ctAudit('risk.score',{address:a,score:j.score,level:j.level})}catch(e){}}
 catch(e){PEND=null;const c=$('rkcard');if(c)c.innerHTML=`<h3>🎯 Risk score</h3><div class="warnbox">${esc(e.message)}</div>`}};
const nav=(performance.getEntriesByType('navigation')[0]||{}).name||location.href;
let auto=new URL(nav).searchParams.get('risk')==='1';
const _render=window.render;window.render=function(d){_render(d);try{if(d&&d.address&&!d.tx){const r=$('side').querySelector('.card .row')||$('side').querySelector('.card');
  if(r&&!$('side').querySelector('.rkbtn'))r.insertAdjacentHTML('beforeend',`<button class="btn sm rkbtn" title="Risk score 0-100 with breakdown (indicative lead)" onclick="ctRisk('${esc(d.address)}')">🎯 Risk score</button>`);
  if(auto){auto=false;ctRisk(d.address)}else if(LAST&&LAST.address===d.address)put(card(LAST));else if(PEND===d.address)put(PH)}}catch(e){}};
setTimeout(()=>{if(auto&&typeof cur!=='undefined'&&cur&&cur.address&&!cur.tx){auto=false;ctRisk(cur.address)}},0);
})();

// ChainTrace v25: mixer / privacy / no-KYC swap / gambling exposure (direct + n-hop indirect, % of value). Indicative lead, not evidence.
(()=>{
const COL={mixer:'#ff5c7a',privacy:'#c792ea',nokyc_swap:'#f6c945',gambling:'#5cc8ff'};
const css=document.createElement('style');css.textContent=`.excard .lead{margin-top:8px;font-size:11.5px;color:#ffd6de;border:1px dashed rgba(255,92,122,.55);border-radius:9px;padding:6px 8px;background:rgba(255,92,122,.07)}
.excard table{width:100%;border-collapse:collapse;font-size:12px;margin-top:4px}.excard td,.excard th{padding:3px 4px;border-top:1px solid var(--line);text-align:left}.excard th{font-weight:600;color:var(--dim,#9aa)}
.excard .bar{height:6px;border-radius:3px;background:rgba(255,255,255,.08);overflow:hidden;min-width:60px}.excard .bar i{display:block;height:100%}
.excard .hit{font-size:11.5px;padding:4px 0;border-top:1px solid var(--line);word-break:break-all}.excard .cat{font-size:10.5px;padding:1px 6px;border-radius:8px;border:1px solid;white-space:nowrap}
.excard select{background:#161b2a;color:inherit;border:1px solid var(--line);border-radius:6px;padding:1px 4px}.excard .warn2{font-size:11.5px;margin-top:6px;color:#ffcf8a}.excard h4{margin:10px 0 2px;font-size:12.5px}.excard .self{margin-top:6px;font-size:12.5px;color:#ffb3c1}`;document.head.appendChild(css);
let LAST=null,PEND=null;
const pct=v=>(v>=10?Math.round(v):v>=0.1?v.toFixed(1):v>0?'<0.1':'0')+'%';
const money=(v,b)=>b==='USD'?'$'+Math.round(v).toLocaleString():(+v).toPrecision(4)+' coin';
const catH=(c,j)=>`<span class="cat" style="border-color:${COL[c]||'#aaa'};color:${COL[c]||'#ccc'}">${esc((j.labels||{})[c]||c)}</span>`;
function dir(name,o,j){const cs=Object.entries(o.categories||{});
 if(!cs.length)return `<h4>${name}</h4><div class="dim" style="font-size:12px">No labelled mixer / privacy / no-KYC swap / gambling exposure found within ${j.hops} hop${j.hops>1?'s':''} (of ${money(o.total,o.basis)} fetched).</div>`;
 return `<h4>${name} <span class="dim" style="font-weight:400">· of ${money(o.total,o.basis)}</span></h4><table><tr><th>Category</th><th>Direct</th><th>Indirect (≤${j.hops} hops)</th><th></th></tr>
 ${cs.map(([c,x])=>`<tr data-cat="${c}"><td>${catH(c,j)}<div class="dim" style="font-size:10.5px">${esc(x.names.join(', '))}</div></td><td class="xd">${pct(x.direct_pct)}</td><td class="xi">${pct(x.indirect_pct)}</td>
  <td><div class="bar"><i style="width:${Math.min(100,x.direct_pct+x.indirect_pct)}%;background:${COL[c]}"></i></div></td></tr>`).join('')}</table>
 ${(o.hits||[]).slice(0,8).map(h=>`<div class="hit">${catH(h.cat,j)} <b>${esc(h.name)}</b> · hop ${h.hop} · ${pct(h.share*100)} (${money(h.value,o.basis)})<br>
  <span class="dim">path: ${h.path.map(p=>`<a href="?q=${encodeURIComponent(p)}" class="mono">${esc(short(p))}</a>`).join(' → ')}</span><br>
  <span class="dim">source: ${h.url?`<a target="_blank" rel="noopener" href="${esc(h.url)}">${esc(h.src||'link')}</a>`:esc(h.src||'')}${h.note?' – '+esc(h.note):''}</span></div>`).join('')}`}
function card(j){const s=j.self;
 return `<div class="card glass excard" id="excard"><h3>🌀 Exposure: mixers · privacy · no-KYC · gambling</h3>
 <div class="row" style="gap:6px;flex-wrap:wrap;font-size:12px">Hops <select id="exhops" onchange="ctExposure('${esc(j.address)}')">${[1,2,3,4].map(n=>`<option ${n===j.hops?'selected':''}>${n}</option>`).join('')}</select>
  <span class="dim">${j.fetched} address${j.fetched>1?'es':''} fetched · ${j.secs}s</span></div>
 ${s?`<div class="self">⚠ This address itself is labelled ${catH(s.cat,j)} <b>${esc(s.name)}</b> (source: ${s.url?`<a target="_blank" rel="noopener" href="${esc(s.url)}">${esc(s.src)}</a>`:esc(s.src)})${s.note?' – '+esc(s.note):''}</div>`:''}
 ${(j.notes||[]).map(n=>`<div class="warn2">⚠ ${esc(n)}</div>`).join('')}
 ${dir('Outgoing (where funds went)',j.outgoing,j)}${dir('Incoming (where funds came from)',j.incoming,j)}
 <details style="font-size:11.5px;margin-top:6px"><summary class="dim">Method</summary><div class="dim">${esc(j.method)}</div></details>
 <div class="lead">⚠ ${esc(j.lead)}</div></div>`}
const PH=`<div class="card glass excard" id="excard"><h3>🌀 Exposure</h3><div class="dim" style="font-size:12px">Checking direct and indirect exposure (bounded, up to ~20 s)…</div></div>`;
const put=h=>{const el=$('excard');if(el)el.outerHTML=h;else $('side').insertAdjacentHTML('beforeend',h)};
window.ctExposure=async function(a){const hops=+(($('exhops')||{}).value||2);PEND=a;LAST=null;put(PH);
 try{const r=await fetch('/api/exposure?q='+encodeURIComponent(a)+'&hops='+hops+(typeof cur!=='undefined'&&cur&&cur.chain?'&chain='+cur.chain:''));const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);
  LAST=j;PEND=null;window.CT_LAST_EXPOSURE=j;put(card(j));
  if(typeof ctAudit==='function')try{ctAudit('exposure.run',{address:a,hops,out:Object.keys(j.outgoing.categories),in:Object.keys(j.incoming.categories)})}catch(e){}}
 catch(e){PEND=null;const c=$('excard');if(c)c.innerHTML=`<h3>🌀 Exposure</h3><div class="warnbox">${esc(e.message)}</div>`}};
const nav=(performance.getEntriesByType('navigation')[0]||{}).name||location.href;
let auto=new URL(nav).searchParams.get('exposure')==='1';
const _render=window.render;window.render=function(d){_render(d);try{if(d&&d.address&&!d.tx){const r=$('side').querySelector('.card .row')||$('side').querySelector('.card');
  if(r&&!$('side').querySelector('.exbtn'))r.insertAdjacentHTML('beforeend',`<button class="btn sm exbtn" title="Mixer / privacy / no-KYC swap / gambling exposure (lead)" onclick="ctExposure('${esc(d.address)}')">🌀 Exposure</button>`);
  if(auto){auto=false;ctExposure(d.address)}else if(LAST&&LAST.address===d.address)put(card(LAST));else if(PEND===d.address)put(PH)}}catch(e){}};
setTimeout(()=>{if(auto&&typeof cur!=='undefined'&&cur&&cur.address&&!cur.tx){auto=false;ctExposure(cur.address)}},0);
})();

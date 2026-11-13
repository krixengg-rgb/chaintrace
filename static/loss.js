// ChainTrace v14: victim-loss calculator / fund-flow summary. Marks victim addresses / payments (+ optional suspect start),
// POSTs the graph to /api/loss and shows totals (on the day + today, GBP/USD), destinations, held balances and a hop table. Loaded after report.js.
(()=>{
const css=document.createElement('style');css.textContent=`
#lossm{position:fixed;inset:0;z-index:82;display:none;align-items:center;justify-content:center;background:rgba(3,5,10,.62);padding:12px}#lossm.on{display:flex}
#lossm .card{width:min(920px,100%);max-height:calc(100vh - 24px);overflow:auto;padding:16px;background:rgba(16,21,36,.97)}
#lossm h3{margin:0 0 4px;font-size:15px;display:flex;align-items:center;gap:8px;text-transform:none;letter-spacing:0;color:var(--txt)}
#lossm h4{margin:14px 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:var(--mut)}
#lossm label{display:block;font-size:12px;color:var(--mut);margin:10px 0 4px}
#lossm textarea,#lossm input[type=text],#lossm select{width:100%;box-sizing:border-box;background:rgba(0,0,0,.25);border:1px solid var(--line);border-radius:10px;padding:8px 10px;color:var(--txt);font:12px var(--mono);outline:0}
#lossm textarea{min-height:58px;resize:vertical}#lossm select{font:13px var(--font);color-scheme:dark}
#lossm .row2{display:grid;grid-template-columns:1fr 1fr;gap:0 12px}
#lossm .mini{display:flex;gap:6px;margin-top:5px;flex-wrap:wrap}
#lossm .acts{display:flex;gap:8px;justify-content:flex-end;margin-top:12px;flex-wrap:wrap}
#lossm .hint{font-size:11.5px;color:var(--mut);margin-top:4px;line-height:1.4}
#lossm .tw{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);border-radius:10px;margin-top:6px}
#lossm table{width:100%;border-collapse:collapse;font-size:12px}#lossm td,#lossm th{padding:6px 7px;border-top:1px solid var(--line);vertical-align:top;text-align:left}
#lossm tr:first-child td,#lossm tr:first-child th{border-top:0}#lossm th{color:var(--mut);font-weight:600;font-size:10.5px;text-transform:uppercase;letter-spacing:.4px;white-space:nowrap}
#lossm td.r,#lossm th.r{text-align:right;white-space:nowrap}#lossm .mono{font-family:var(--mono);font-size:11px;word-break:break-all}
#lossm .stmt{font-size:13.5px;line-height:1.5;padding:10px 12px;border-radius:12px;background:rgba(124,92,255,.10);border:1px solid rgba(124,92,255,.35);margin-top:10px}
#lossm .big{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-top:10px}
#lossm .big div{padding:9px 11px;border:1px solid var(--line);border-radius:12px;background:rgba(0,0,0,.18)}#lossm .big b{display:block;font-size:17px;margin-top:2px}#lossm .big span{font-size:11px;color:var(--mut)}
#lossm .bar{display:flex;height:14px;border-radius:7px;overflow:hidden;margin-top:8px;background:rgba(255,255,255,.05)}#lossm .bar i{display:block;height:100%}
#lossm .cat{display:flex;align-items:center;gap:7px;font-size:12px;margin-top:6px}#lossm .cat b.sw{width:10px;height:10px;border-radius:3px;flex:0 0 10px}
#lossm .lead{color:#ffcf8a}#lossm .pill{display:inline-block;padding:1px 7px;border-radius:999px;font-size:10.5px;border:1px solid rgba(255,159,67,.5);background:rgba(255,159,67,.12);color:#ffcf8a;margin-left:4px}
#lossm .meth{font-size:12px;padding:8px 10px;border-radius:10px;border:1px solid rgba(34,211,238,.35);background:rgba(34,211,238,.07);margin-top:10px;line-height:1.45}
#lossm .cav{font-size:11.5px;color:#f6dd8a;margin-top:10px;line-height:1.45}
.lossbtn.on{border-color:#2ee59d!important;color:#2ee59d}
@media (max-width:700px){#lossm{align-items:flex-end;padding:0}#lossm .card{border-radius:16px 16px 0 0;max-height:94vh;max-height:94dvh;padding:12px}
#lossm .row2{grid-template-columns:1fr}#lossm textarea,#lossm input[type=text],#lossm select{font-size:16px}#lossm .acts .btn{flex:1 1 auto}#lossm table{font-size:11.5px}}`;
document.head.appendChild(css);
const CC={exchange:'#4c8dff',bridge:'#22d3ee',mixer:'#ff9f43',sanctioned:'#ff4d6d',held:'#2ee59d',end:'#a78bfa',untraced:'#6b7591',returned:'#f6c945'};
cy.style().selector('edge.losshl').style({'line-color':'#2ee59d','target-arrow-color':'#2ee59d','z-index':12,width:e=>Math.max(3,ew(e)+1.5),color:'#b9f8dc'})
 .selector('node.lossv').style({'border-width':5,'border-color':'#ff4d6d','border-style':'double'})
 .selector('node.losss').style({'border-width':5,'border-color':'#f6c945','border-style':'double'}).update();
const S=window.CT_LOSS={victims:[],victim_txs:[],suspect:'',method:'proportional',result:null};
const gbp=n=>n==null?'–':'£'+(+n).toLocaleString('en-GB',{maximumFractionDigits:Math.abs(n)>=100?0:2});
const usd2=n=>n==null?'–':'$'+(+n).toLocaleString('en-GB',{maximumFractionDigits:Math.abs(n)>=100?0:2});
const nf=x=>x==null?'–':(+x).toLocaleString('en-GB',{maximumFractionDigits:Math.abs(x)>=1000?2:8});
const lines=s=>[...new Set(String(s||'').split(/[\s,;]+/).map(x=>x.trim()).filter(Boolean))];
const m=document.createElement('div');m.id='lossm';m.innerHTML=`<div class="card glass" role="dialog" aria-modal="true" aria-labelledby="lossh">
 <h3 id="lossh">💷 Victim loss &amp; fund flow</h3>
 <div class="hint">Mark the victim's address(es) or payment(s). ChainTrace totals the loss and follows it through the flows already on the graph. Tip: tap a node or flow on the graph and use <b>💷 Victim</b> / <b>🎯 Suspect</b>.</div>
 <div class="row2"><div><label for="lossv">Victim addresses (one per line)</label><textarea id="lossv" spellcheck="false" placeholder="bc1q… / 0x… / T… / r…"></textarea><div class="mini"><button class="btn sm" onclick="ctLossAddSel('v')">+ selected node</button></div></div>
 <div><label for="losst">Victim payments: tx hashes (optional)</label><textarea id="losst" spellcheck="false" placeholder="Only these payments count as the loss"></textarea><div class="mini"><button class="btn sm" onclick="ctLossAddSel('t')">+ selected flow</button></div></div></div>
 <div class="row2"><div><label for="losss">Suspect start address (optional)</label><input type="text" id="losss" spellcheck="false" placeholder="Only payments to this address count"><div class="mini"><button class="btn sm" onclick="ctLossAddSel('s')">use selected node</button></div></div>
 <div><label for="lossmth">Tracing method</label><select id="lossmth"><option value="proportional">Proportional (haircut) – default</option><option value="fifo">FIFO – first in, first out</option><option value="lifo">LIFO – last in, first out</option></select>
 <div class="hint" id="lossmh"></div></div></div>
 <div class="acts"><button class="btn" onclick="ctLossClose()">Close</button><button class="btn" id="losscsv" onclick="ctLossCSV()" disabled>⬇ CSV</button><button class="btn pri" id="lossgo" onclick="ctLossGo()">Calculate</button></div>
 <div id="lossres"></div></div>`;
document.body.appendChild(m);m.addEventListener('click',e=>{if(e.target===m)ctLossClose()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&m.classList.contains('on'))ctLossClose()});
const MH={proportional:'Each transfer out carries the victim share the address held at that moment. Mixing dilutes it.',fifo:'Funds leave in the order they arrived (earliest first).',lifo:'The latest funds to arrive leave first.'};
$('lossmth').onchange=()=>{$('lossmh').textContent=MH[$('lossmth').value]};$('lossmh').textContent=MH.proportional;
const anchor=$('rptbtn')||$('savebtn');const hb=document.createElement('button');hb.className='btn lossbtn';hb.id='lossbtn';hb.title='Victim loss calculator';hb.textContent='💷 Loss';hb.onclick=()=>ctLossOpen();anchor.after(hb);
const dd=document.querySelector('#exportMenu .dd');if(dd){const b=document.createElement('button');b.className='btn sm';b.textContent='Victim loss summary…';b.onclick=()=>{exportMenu.classList.remove('open');ctLossOpen()};dd.appendChild(b)}
function readForm(){S.victims=lines($('lossv').value);S.victim_txs=lines($('losst').value);S.suspect=$('losss').value.trim();S.method=$('lossmth').value}
function fillForm(){$('lossv').value=S.victims.join('\n');$('losst').value=S.victim_txs.join('\n');$('losss').value=S.suspect||'';$('lossmth').value=S.method||'proportional';$('lossmh').textContent=MH[$('lossmth').value]}
function persist(){if(curCase){curCase.loss={victims:S.victims,victim_txs:S.victim_txs,suspect:S.suspect||null,method:S.method};try{autosave()}catch(e){}}decor()}
function decor(){cy.nodes().removeClass('lossv losss');for(const v of S.victims){const n=cy.getElementById(v);if(n.length)n.addClass('lossv')}if(S.suspect){const n=cy.getElementById(S.suspect);if(n.length)n.addClass('losss')}}
window.ctLossSpec=()=>(S.victims.length||S.victim_txs.length)?{victims:S.victims,victim_txs:S.victim_txs,suspect:S.suspect||null,method:S.method}:null;
window.ctLossOpen=function(){if(curCase&&curCase.loss&&!S.victims.length&&!S.victim_txs.length)Object.assign(S,curCase.loss,{suspect:curCase.loss.suspect||''});fillForm();m.classList.add('on');if(S.result)render(S.result)};
window.ctLossClose=()=>{readForm();persist();m.classList.remove('on')};
window.ctLossAddSel=function(k){const sel=cy.$(':selected');if(!sel.length)return toast('Select a node or flow on the graph first');readForm();
 if(k==='t'){const e=sel.filter('edge')[0];const tx=e&&(e.data('info')||{}).tx;if(!tx)return toast('Select a flow with a transaction hash');S.victim_txs=[...new Set([...S.victim_txs,tx])]}
 else{const n=sel.filter('node')[0];if(!n)return toast('Select a node');if(k==='v')S.victims=[...new Set([...S.victims,n.id()])];else S.suspect=n.id()}fillForm();persist()};
window.ctLossMark=function(id,k){if(k==='v'){S.victims=S.victims.includes(id)?S.victims.filter(x=>x!==id):[...S.victims,id];toast(S.victims.includes(id)?'Marked as victim address':'Victim mark removed')}
 else if(k==='s'){S.suspect=S.suspect===id?'':id;toast(S.suspect?'Marked as suspect start':'Suspect mark removed')}
 else if(k==='t'){S.victim_txs=S.victim_txs.includes(id)?S.victim_txs.filter(x=>x!==id):[...S.victim_txs,id];toast(S.victim_txs.includes(id)?'Marked as victim payment':'Victim payment removed')}
 persist();if(m.classList.contains('on'))fillForm()};
cy.on('tap','node',e=>{const n=e.target;if(n.data('grp'))return;const id=n.id();if(id.startsWith('tx:'))return;
 setTimeout(()=>{const r=$('det').querySelector('.card .row');if(!r||r.querySelector('.lvbtn'))return;
  r.insertAdjacentHTML('beforeend',`<button class="btn sm lvbtn lossbtn${S.victims.includes(id)?' on':''}" onclick="ctLossMark('${esc(id)}','v')">💷 Victim</button><button class="btn sm lossbtn${S.suspect===id?' on':''}" onclick="ctLossMark('${esc(id)}','s')">🎯 Suspect</button>`)},0)});
cy.on('tap','edge',e=>{const x=e.target.data('info')||{};if(!x.tx)return;setTimeout(()=>{const c=$('det').querySelector('.card');if(!c||c.querySelector('.ltbtn'))return;
 c.insertAdjacentHTML('beforeend',`<div class="row" style="margin-top:8px"><button class="btn sm ltbtn lossbtn${S.victim_txs.includes(x.tx)?' on':''}" onclick="ctLossMark('${esc(x.tx)}','t')">💷 Victim payment</button></div>`)},0)});
const _rp=window.ctReportPayload;window.ctReportPayload=function(meta){const pl=_rp(meta);const sp=ctLossSpec();if(sp)pl.loss=sp;return pl};
function payload(){const pl=ctReportPayload({noise:false,img:false});return{nodes:pl.nodes,edges:pl.edges,case:{labels:pl.case.labels,name:pl.case.name},loss:ctLossSpec()}}
window.ctLossGo=async function(){readForm();persist();if(!S.victims.length&&!S.victim_txs.length)return toast('Add a victim address or payment first');
 const b=$('lossgo');b.disabled=true;b.textContent='Calculating…';$('lossres').innerHTML='<div class="hint" style="margin-top:12px">Following the victim funds and fetching prices…</div>';
 try{const r=await fetch('/api/loss',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});const j=await r.json();
  if(!r.ok)throw new Error(j.detail||('HTTP '+r.status));S.result=j;window.CT_LOSS_LAST=j;render(j);highlight(j);$('losscsv').disabled=false;
  if(curCase){curCase.loss_last={at:Date.now(),method:j.method,total_gbp_now:j.total_gbp_now,held_gbp_now:j.held_gbp_now};try{autosave()}catch(e){}}}
 catch(e){$('lossres').innerHTML=`<div class="warnbox">Calculation failed: ${esc(e.message)}</div>`}
 finally{b.disabled=false;b.textContent='Calculate'}};
function highlight(j){cy.edges().removeClass('losshl');for(const h of j.hops||[]){cy.edges().filter(e=>e.data('source')===h.from&&e.data('target')===h.to).addClass('losshl')}}
window.ctLossCSV=function(){const j=S.result;if(!j)return;const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([j.csv],{type:'text/csv'}));
 a.download=('ChainTrace-victim-loss-'+((curCase&&curCase.name)||'graph')).replace(/[^A-Za-z0-9._-]+/g,'_').slice(0,70)+'.csv';document.body.appendChild(a);a.click();a.remove();toast('Loss CSV downloaded')};
const tline=(uk,utc)=>uk?`${esc(uk)}<div class="dim" style="font-size:10.5px">${esc(utc)}</div>`:'<span class="dim">no date</span>';
const addrH=(id,lab)=>`${lab?`<div>${esc(lab)}</div>`:''}<span class="mono">${esc(id)}</span>`;
function render(j){const T=j.totals||[];const ts=(j.payments||[]).map(p=>p.time).filter(Boolean);
 const amt=T.map(t=>nf(t.amount)+' '+t.asset).join(' + ');
 const when=ts.length?(Math.min(...ts)===Math.max(...ts)?' on '+(j.payments.find(p=>p.time)||{}).time_uk:` between ${j.payments.filter(p=>p.time).sort((a,b)=>a.time-b.time)[0].time_uk} and ${j.payments.filter(p=>p.time).sort((a,b)=>b.time-a.time)[0].time_uk}`):'';
 let h=`<div class="stmt">From the transactions on this graph, <b>${T.reduce((a,t)=>a+t.payments,0)} payment(s)</b> were made from the victim address(es)${esc(when)} totalling <b>${esc(amt)}</b>.`
  +(j.total_gbp_then!=null?` On the day of each payment this was worth <b>${gbp(j.total_gbp_then)}</b> (${usd2(j.total_usd_then)})${j.then_complete?'':' for the payments with a daily price'}.`:'')
  +(j.total_gbp_now!=null?` At today's prices it is worth <b>${gbp(j.total_gbp_now)}</b> (${usd2(j.total_usd_now)}).`:'')+`</div>`;
 h+=`<div class="big"><div><span>Total lost · today</span><b>${gbp(j.total_gbp_now)}</b><span>${usd2(j.total_usd_now)}</span></div><div><span>Total lost · on the day</span><b>${gbp(j.total_gbp_then)}</b><span>${j.total_usd_then!=null?usd2(j.total_usd_then)+(j.then_complete?'':' · partial'):'no dated payments'}</span></div><div><span>Still held in identified wallets</span><b style="color:#2ee59d">${gbp(j.held_gbp_now)}</b><span>${(j.held||[]).length} address(es) · for restraint</span></div></div>`;
 h+=`<div class="meth"><b>Method: ${esc(j.method_name)}.</b> ${esc(j.method_text)} Other methods can give different figures; quote the method with any figure.</div>`;
 h+=`<h4>Total lost per asset</h4><div class="tw"><table><tr><th>Asset</th><th class="r">Amount</th><th class="r">Payments</th><th class="r">On the day</th><th class="r">Today</th></tr>`+T.map(t=>`<tr><td><b>${esc(t.asset)}</b></td><td class="r">${nf(t.amount)}</td><td class="r">${t.payments}</td><td class="r">${gbp(t.gbp_then)}<div class="dim">${usd2(t.usd_then)}${t.then_complete||t.usd_then==null?'':' · part'}</div></td><td class="r">${gbp(t.gbp_now)}<div class="dim">${usd2(t.usd_now)}</div></td></tr>`).join('')+`</table></div>`;
 const C=j.categories||[];h+=`<h4>Where the funds went</h4><div class="bar">${C.map(c=>`<i title="${esc(c.name)}" style="width:${Math.max(0,Math.min(100,c.pct_of_loss||0))}%;background:${CC[c.cat]}"></i>`).join('')}</div>`
  +C.map(c=>`<div class="cat"><b class="sw" style="background:${CC[c.cat]}"></b><span style="flex:1">${esc(c.name)}${c.lead?'<span class="pill">includes leads</span>':''}<div class="dim" style="font-size:11px">${Object.entries(c.by_asset).map(([u,a])=>esc(nf(a)+' '+u)).join(' · ')}</div></span><span class="r" style="text-align:right">${gbp(c.gbp_now)}<div class="dim" style="font-size:11px">${c.pct_of_loss!=null?c.pct_of_loss+'%':''}</div></span></div>`).join('');
 const D=(j.destinations||[]).filter(d=>['exchange','bridge','mixer','sanctioned','returned'].includes(d.cat));
 if(D.length)h+=`<h4>Exchanges, VASPs and other endpoints</h4><div class="tw"><table><tr><th>Destination</th><th>Address</th><th class="r">Victim funds</th><th>Deposit ref / notes</th></tr>`+D.map(d=>`<tr><td><b style="color:${CC[d.cat]}">${esc(d.cat_name)}</b><div>${esc(d.entity||d.label||'Unlabelled')}</div></td><td>${addrH(d.id,'')}</td><td class="r">${nf(d.amount)} ${esc(d.unit)}<div class="dim">${gbp(d.gbp_now)}</div></td><td>${d.destination_tags?'XRP tag '+esc(d.destination_tags.join(', ')):''}${(d.sanctions||[]).map(s=>`<div style="color:#ff8fa3">${esc(s)}</div>`).join('')}${(d.lead||[]).length?`<div class="lead">Lead: ${esc(d.lead.join('; '))}</div>`:''}</td></tr>`).join('')+`</table></div>`;
 const Hd=j.held||[];if(Hd.length)h+=`<h4>Still held in identified wallets (restraint / freezing)</h4><div class="tw"><table><tr><th>Address</th><th class="r">Victim funds</th><th class="r">Balance</th><th>Checked</th></tr>`+Hd.map(d=>`<tr><td>${addrH(d.id,d.label)}</td><td class="r">${nf(d.amount)} ${esc(d.unit)}<div class="dim">${gbp(d.gbp_now)}</div></td><td class="r">${nf(d.balance)} ${esc(d.unit)}</td><td>${d.balance_src==='live'?'live, just now':'as on the graph'}</td></tr>`).join('')+`</table></div>`;
 const O=(j.destinations||[]).filter(d=>['end','untraced'].includes(d.cat));
 if(O.length)h+=`<details style="margin-top:10px"><summary class="hint" style="cursor:pointer">Last seen / not traced further (${O.length})</summary><div class="tw"><table>`+O.map(d=>`<tr><td>${esc(d.cat_name)}</td><td>${addrH(d.id,d.label)}</td><td class="r">${nf(d.amount)} ${esc(d.unit)}</td></tr>`).join('')+`</table></div></details>`;
 const H=j.hops||[];h+=`<h4>Hop-by-hop (${H.length})</h4><div class="tw"><table><tr><th>Hop</th><th>Time (UK / UTC)</th><th>From → To</th><th class="r">Amount</th><th class="r">Victim funds</th><th>Basis</th></tr>`
  +H.slice(0,150).map(x=>`<tr><td>${x.hop}</td><td>${tline(x.time_uk,x.time_utc)}</td><td>${addrH(x.from,x.from_label)}<div class="dim">→</div>${addrH(x.to,x.to_label)}${x.tx?`<div class="dim mono">tx ${esc(x.tx.slice(0,18))}…</div>`:''}</td><td class="r">${nf(x.amount)} ${esc(x.asset)}${x.count>1?' ×'+x.count:''}</td><td class="r">${nf(x.tainted)}<div class="dim">${x.pct!=null?x.pct+'%':''}</div></td><td>${esc(x.basis)} → ${esc(x.onward)}${x.lead.length?`<div class="lead">Lead: ${esc(x.lead.join('; '))}</div>`:''}</td></tr>`).join('')+`</table></div>`;
 if((j.warnings||[]).length)h+=`<div class="warnbox">${j.warnings.map(esc).join('<br>')}</div>`;
 if((j.errors||[]).length)h+=`<div class="hint">Data notes: ${j.errors.map(esc).join('; ')}</div>`;
 h+=`<div class="cav">⚠ ${j.leads_present?'This summary includes heuristic leads (marked). ':''}Intelligence lead – not evidence; corroborate (e.g. production order to the VASP). ${esc(j.caveats.slice(0,3).join(' '))}</div>
  <div class="hint">Included automatically in the 📄 PDF report and the 🇬🇧 evidence pack while these victims are marked. Generated ${esc(j.generated_uk)} (${esc(j.generated_utc)}).</div>`;
 $('lossres').innerHTML=h;setTimeout(()=>{const s=$('lossres').querySelector('.stmt');if(s&&matchMedia('(max-width:700px)').matches)s.scrollIntoView({block:'start',behavior:'smooth'})},60)}
// restore marks with a case; deep link ?loss=1&victims=a,b&vtx=h&suspect=x&method=fifo
const _oc=window.openCase;if(_oc)window.openCase=async function(id){const r=await _oc.apply(this,arguments);try{if(curCase&&curCase.loss){Object.assign(S,curCase.loss,{suspect:curCase.loss.suspect||'',result:null});decor()}}catch(e){}return r};
const P=new URLSearchParams(window.CT_URL0||location.search);
if(P.get('loss')==='1'||P.get('victims')||P.get('vtx')){S.victims=lines(P.get('victims'));S.victim_txs=lines(P.get('vtx'));S.suspect=P.get('suspect')||'';if(['fifo','lifo','proportional'].includes(P.get('method')))S.method=P.get('method');
 let n=0;const iv=setInterval(()=>{n++;const ready=window.cy&&cy.nodes().length>1&&!document.body.classList.contains('busy');
  if(ready){clearInterval(iv);setTimeout(()=>{decor();m.classList.add('on');fillForm();if(S.victims.length||S.victim_txs.length)ctLossGo()},1200)}else if(n>240)clearInterval(iv)},500)}
})();

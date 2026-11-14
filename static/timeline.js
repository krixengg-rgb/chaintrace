// ChainTrace v19: Timeline of fund movements. Chronological list of every flow on the current graph/case, filterable by chain, asset,
// address and date range; amounts in coin and GBP (today's prices); victim / suspect / exchange hops marked; synced with the graph.
// The filter is saved in the case and sent with the PDF report (timeline section). Loaded after loss.js.
(()=>{
const css=document.createElement('style');css.textContent=`
#tlp{position:fixed;right:12px;top:12px;bottom:12px;width:480px;z-index:46;padding:12px;display:flex;flex-direction:column;gap:8px;transform:translateX(110%);transition:transform .25s ease;background:rgba(14,19,32,.95)}
#tlp.open{transform:none}#tlp h2{margin:0;font-size:15px;display:flex;align-items:center;gap:8px}#tlp h2 .sp{flex:1}
#tlp .tlf{display:grid;grid-template-columns:1fr 1fr;gap:6px}#tlp .tlf label{font-size:10.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.4px;display:block;margin-bottom:2px}
#tlp select,#tlp input{width:100%;box-sizing:border-box;background:rgba(0,0,0,.25);border:1px solid var(--line);border-radius:9px;padding:6px 8px;color:var(--txt);font:12px var(--font);color-scheme:dark;outline:0}
#tlp .tlsum{font-size:11.5px;color:var(--mut);display:flex;gap:8px;flex-wrap:wrap;align-items:center}#tlp .tlsum b{color:var(--txt)}
#tlbody{flex:1;overflow:auto;-webkit-overflow-scrolling:touch;display:flex;flex-direction:column;gap:0;border-top:1px solid var(--line)}
.tlday{font-size:10.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px;padding:8px 2px 4px;position:sticky;top:0;background:rgba(14,19,32,.97);z-index:1}
.tlr{display:grid;grid-template-columns:52px 1fr auto;gap:8px;padding:7px 6px;border-radius:10px;cursor:pointer;border:1px solid transparent;align-items:start}
.tlr:hover{background:rgba(255,255,255,.04)}.tlr.on{border-color:#f6c945;background:rgba(246,201,69,.08)}
.tlr .tm{font:11px var(--mono);color:var(--mut);line-height:1.35}.tlr .fl{font-size:12px;min-width:0;line-height:1.4}.tlr .fl .ad{font-family:var(--mono);font-size:11px;word-break:break-all}
.tlr .am{text-align:right;font-size:12px;white-space:nowrap;line-height:1.35}.tlr .am b{display:block}.tlr .am span{color:var(--mut);font-size:11px}
.tlb{display:inline-block;padding:0 6px;border-radius:999px;font-size:10px;line-height:16px;margin-right:3px;border:1px solid var(--line);vertical-align:1px}
.tlb.v{border-color:#ff4d6d;color:#ff8da1}.tlb.s{border-color:#f6c945;color:#f6dd8a}.tlb.x{border-color:#4c8dff;color:#9cc0ff}.tlb.c{color:var(--mut)}.tlb.b{border-color:#22d3ee;color:#7be7f7}.tlb.l{border-color:rgba(255,159,67,.6);color:#ffcf8a}
#tlp .tlcav{font-size:10.5px;color:var(--mut);line-height:1.4}#tlp .tlfb{display:none}
@media (max-width:900px){#tlp{right:0;left:0;top:auto;bottom:0;width:auto;height:58vh;height:58dvh;border-radius:16px 16px 0 0;transform:translateY(110%);box-sizing:border-box}
#tlp.open{transform:none}#tlp select,#tlp input{font-size:16px}.tlr{grid-template-columns:46px 1fr auto}
#tlp .tlf{display:none}#tlp.filt .tlf{display:grid}#tlp .tlfb{display:inline-flex}#tlp.min{height:auto}#tlp.min>*:not(h2){display:none}#tlp.min h2{cursor:pointer}}`;
document.head.appendChild(css);
const d=document.createElement('div');d.id='tlp';d.className='glass';d.setAttribute('role','dialog');d.setAttribute('aria-label','Timeline of fund movements');
d.innerHTML=`<h2 onclick="if(this.parentNode.classList.contains('min')&&event.target===this)ctTlMin(false)">🕒 Timeline<span class="sp"></span><button class="btn sm tlfb" onclick="event.stopPropagation();document.getElementById('tlp').classList.toggle('filt')">⚙ Filters</button><button class="btn sm tlfb" id="tlminb" onclick="event.stopPropagation();ctTlMin(!document.getElementById('tlp').classList.contains('min'))">▾</button><button class="btn sm" onclick="ctTlCSV()" title="Download the filtered timeline as CSV">⬇ CSV</button><button class="btn sm ico" onclick="ctTimeline(false)" aria-label="Close">✕</button></h2>
<div class="tlf"><div><label for="tlch">Chain</label><select id="tlch"></select></div><div><label for="tlas">Asset</label><select id="tlas"></select></div>
<div style="grid-column:1/-1"><label for="tlad">Address or label contains</label><input id="tlad" type="text" spellcheck="false" placeholder="0x… / bc1… / Binance"></div>
<div><label for="tlfr">From (UK date)</label><input id="tlfr" type="date"></div><div><label for="tlto">To (UK date)</label><input id="tlto" type="date"></div></div>
<div class="tlsum" id="tlsum"></div><div id="tlbody"></div>
<div class="tlcav">Times in UK time (UTC shown on hover). GBP is indicative: today's price × today's ECB USD→GBP rate (the PDF values each flow on its own day). Aggregated rows (×N) are repeated transfers between the same pair. “Suggested” labels and heuristic hops are leads, not evidence.</div>`;
document.body.appendChild(d);
const F=window.CT_TL={chain:'',asset:'',addr:'',from:'',to:''};let RATE=null,PX={},SEL=null;
fetch('/api/fx').then(r=>r.json()).then(j=>{RATE=j.usd_gbp;if(d.classList.contains('open'))render()}).catch(()=>{});
fetch('/api/prices').then(r=>r.json()).then(j=>{PX=j||{}}).catch(()=>{});
const UK=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',day:'2-digit',month:'short',year:'numeric'});
const UKT=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',hour:'2-digit',minute:'2-digit'});
const UKD=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/London'});   // yyyy-mm-dd in UK time
const gbp=n=>n==null?'–':'£'+(+n).toLocaleString('en-GB',{minimumFractionDigits:Math.abs(n)>=100?0:2,maximumFractionDigits:Math.abs(n)>=100?0:2});
const nf=x=>x==null?'–':(+x).toLocaleString('en-GB',{maximumFractionDigits:Math.abs(x)>=1000?2:8});
const chainName=c=>({btc:'Bitcoin',eth:'Ethereum',sol:'Solana',tron:'TRON',xrp:'XRP',bsc:'BSC',arb:'Arbitrum',base:'Base',polygon:'Polygon',op:'OP',ltc:'Litecoin',doge:'Dogecoin',bch:'Bitcoin Cash'})[c]||(c||'?').toUpperCase();
function nodeKind(id){const L=typeof effLabel==='function'?effLabel(id):null;if(L&&L.kind)return L.kind;const n=cy.getElementById(id);return n.length?(n.data('kind')||((n.data('info')||{}).kind)||''):''}
function nodeName(id){const L=typeof effLabel==='function'?effLabel(id):null;if(L&&L.name)return L.name;const n=cy.getElementById(id);const i=n.length?(n.data('info')||{}):{};return i.name||(i.suggested&&i.suggested.label?i.suggested.label+' (suggested)':'')||''}
function rows(){const L=window.CT_LOSS||{victims:[],victim_txs:[],suspect:''};const vs=new Set(L.victims||[]),vt=new Set(L.victim_txs||[]);
 return cy.edges().filter(e=>!e.data('grp')&&!e.data('meta')&&!e.data('tmp')&&!e.hasClass('noise')).map(e=>{const x=e.data('info')||{};const b=x.bridge&&typeof x.bridge==='object'?x.bridge:null;
  const ch=chainOf[x.source]||chainOf[x.target]||(cy.getElementById(x.source).data('info')||{}).chain||'';
  const t=x.time||x.last||x.first||(b&&(b.src||{}).time)||null;const unit=(x.unit||'').replace('⇄','').trim()||(b&&(b.src||{}).unit)||'';
  const amt=x.amount!=null?+x.amount:(b&&(b.src||{}).amount!=null?+(b.src.amount):null);
  let u=x.usd!=null?+x.usd:(amt!=null&&PX[unit.toUpperCase()]!=null?amt*PX[unit.toUpperCase()]:null);
  const role=[];if(vs.has(x.source)||vt.has(x.tx))role.push('v');if(L.suspect&&(x.source===L.suspect||x.target===L.suspect))role.push('s');
  const ks=nodeKind(x.source),kt=nodeKind(x.target);if(ks==='exchange'||kt==='exchange')role.push('x');
  const lead=!!(x.heuristic||x.lead||(x.flags||[]).includes('heuristic')||e.hasClass('heur')||(b&&b.heuristic));
  return{id:e.id(),t,ch,unit,amt,usd:u,gbp:u!=null&&RATE?u*RATE:null,src:x.source,dst:x.target,tx:x.tx||(b&&(b.src||{}).tx)||'',count:x.count||1,first:x.first,role,ks,kt,bridge:!!(x.xchain||b),lead,
   sn:nodeName(x.source),tn:nodeName(x.target),vt:vt.has(x.tx)}}).sort((a,b)=>(a.t||9e12)-(b.t||9e12))}
function filt(R){const q=F.addr.trim().toLowerCase();const fr=F.from?Date.parse(F.from+'T00:00:00Z')/1000-86400:null,to=F.to?Date.parse(F.to+'T23:59:59Z')/1000+86400:null;
 return R.filter(r=>{if(F.chain&&r.ch!==F.chain)return false;if(F.asset&&r.unit!==F.asset)return false;
  if(q&&![r.src,r.dst,r.sn,r.tn,r.tx].some(v=>(v||'').toLowerCase().includes(q)))return false;
  if((F.from||F.to)&&r.t){const dd=UKD.format(new Date(r.t*1000));if(F.from&&dd<F.from)return false;if(F.to&&dd>F.to)return false}
  if((F.from||F.to)&&!r.t)return false;return true})}
window.ctTlRows=()=>filt(rows());
function opts(sel,vals,lab){const v=sel.value;sel.innerHTML=`<option value="">All ${lab}</option>`+vals.map(x=>`<option value="${esc(x)}">${esc(lab==='chains'?chainName(x):x)}</option>`).join('');sel.value=vals.includes(v)?v:''}
function addrH(id,name){const a=String(id||'');const bare=a.replace(/^(bsc|arb|base|polygon|op|ltc|doge|bch):/,'');
 return a.startsWith('tx:')?'<span class="dim">(transaction)</span>':(name?`${esc(name)} `:'')+`<span class="ad">${esc(short(bare))}</span>`}
function render(){const R=rows();opts($('tlch'),[...new Set(R.map(r=>r.ch).filter(Boolean))].sort(),'chains');opts($('tlas'),[...new Set(R.map(r=>r.unit).filter(Boolean))].sort(),'assets');
 F.chain=$('tlch').value;F.asset=$('tlas').value;const X=filt(R);
 const tg=X.reduce((s,r)=>s+(r.gbp||0),0),pr=X.filter(r=>r.gbp!=null).length;const ts=X.map(r=>r.t).filter(Boolean);
 $('tlsum').innerHTML=`<b>${X.length}</b> of ${R.length} flow(s)`+(ts.length?` · ${UK.format(new Date(Math.min(...ts)*1000))} → ${UK.format(new Date(Math.max(...ts)*1000))}`:'')
  +(pr?` · <b>${gbp(tg)}</b> total${pr<X.length?` (${pr} priced)`:''}`:'')+` <span class="tlb v">💷 victim</span><span class="tlb s">🎯 suspect</span><span class="tlb x">🏦 exchange</span>`;
 let h='',day='';for(const r of X){const dd=r.t?UK.format(new Date(r.t*1000)):'Undated';if(dd!==day){day=dd;h+=`<div class="tlday">${esc(dd)}</div>`}
  const utc=r.t?new Date(r.t*1000).toISOString().replace('T',' ').slice(0,19)+' UTC':'';
  const bd=(r.role.includes('v')?`<span class="tlb v">💷 ${r.vt?'victim payment':'victim'}</span>`:'')+(r.role.includes('s')?'<span class="tlb s">🎯 suspect</span>':'')+(r.role.includes('x')?`<span class="tlb x">🏦 ${r.kt==='exchange'?'to exchange':'from exchange'}</span>`:'')
   +(r.bridge?'<span class="tlb b">⇄ bridge</span>':'')+(r.lead?'<span class="tlb l">lead</span>':'')+`<span class="tlb c">${esc(chainName(r.ch))}</span>`;
  h+=`<div class="tlr${SEL===r.id?' on':''}" data-id="${esc(r.id)}" title="${esc(utc)}${r.tx?' · tx '+esc(r.tx):''}" onclick="ctTlPick(this.dataset.id)">
   <div class="tm">${r.t?UKT.format(new Date(r.t*1000)):'–'}${r.count>1&&r.first?`<br>×${r.count}`:''}</div>
   <div class="fl">${addrH(r.src,r.sn)} → ${addrH(r.dst,r.tn)}<div style="margin-top:2px">${bd}</div></div>
   <div class="am"><b>${nf(r.amt)} ${esc(r.unit)}</b><span>${r.gbp!=null?gbp(r.gbp):r.usd!=null?'$'+nf(r.usd):'unpriced'}</span></div></div>`}
 $('tlbody').innerHTML=h||'<div class="dim" style="padding:14px 4px">No flows match these filters.</div>';persist()}
function persist(){if(typeof curCase!=='undefined'&&curCase){curCase.timeline={...F};try{autosave()}catch(e){}}}
window.ctTimelineSpec=()=>({...F,rate:RATE});
window.ctTlPick=id=>{SEL=id;const e=cy.getElementById(id);if(!e.length)return;clearHl();cy.elements().addClass('faded');const ns=e.connectedNodes();e.removeClass('faded').addClass('hot').select();ns.removeClass('faded').addClass('hot');
 cy.animate({fit:{eles:e.union(ns),padding:innerWidth<900?60:140}},{duration:350});document.querySelectorAll('.tlr').forEach(x=>x.classList.toggle('on',x.dataset.id===id));
 if(innerWidth<900){ctTlMin(true);cy.container().scrollIntoView({block:'start',behavior:'smooth'})}};
window.ctTlMin=on=>{d.classList.toggle('min',on);$('tlminb').textContent=on?'▴ List':'▾';if(!on){const r=document.querySelector('.tlr.on');if(r)r.scrollIntoView({block:'nearest'})}};
window.ctTimeline=on=>{on=on===undefined?!d.classList.contains('open'):on;d.classList.toggle('open',on);d.classList.remove('min');if(on){const cc=typeof curCase!=='undefined'?curCase:null;if(cc&&cc.timeline)Object.assign(F,cc.timeline);
 $('tlad').value=F.addr||'';$('tlfr').value=F.from||'';$('tlto').value=F.to||'';render();setTimeout(()=>{$('tlch').value=F.chain||'';$('tlas').value=F.asset||'';render()},0)}};
$('tlch').onchange=()=>{F.chain=$('tlch').value;render()};$('tlas').onchange=()=>{F.asset=$('tlas').value;render()};
let th;$('tlad').oninput=()=>{clearTimeout(th);th=setTimeout(()=>{F.addr=$('tlad').value;render()},200)};
$('tlfr').onchange=()=>{F.from=$('tlfr').value;render()};$('tlto').onchange=()=>{F.to=$('tlto').value;render()};
// graph -> timeline: tapping a flow selects its row
cy.on('tap','edge',e=>{if(!d.classList.contains('open'))return;SEL=e.target.id();document.querySelectorAll('.tlr').forEach(x=>{const on=x.dataset.id===SEL;x.classList.toggle('on',on);if(on)x.scrollIntoView({block:'nearest'})})});
cy.on('add remove',()=>{if(d.classList.contains('open')){clearTimeout(window._tlr);window._tlr=setTimeout(render,300)}});
window.ctTlCSV=()=>{const X=filt(rows());const q=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
 const L=[['time_uk','time_utc','chain','from','from_label','to','to_label','amount','asset','gbp_today','usd_today','tx','count','roles','lead'].join(',')]
  .concat(X.map(r=>[r.t?new Date(r.t*1000).toLocaleString('en-GB',{timeZone:'Europe/London'}):'',r.t?new Date(r.t*1000).toISOString():'',r.ch,r.src,r.sn,r.dst,r.tn,r.amt,r.unit,r.gbp!=null?r.gbp.toFixed(2):'',r.usd!=null?r.usd.toFixed(2):'',r.tx,r.count,r.role.map(x=>({v:'victim',s:'suspect',x:'exchange'})[x]).join(' '),r.lead?'yes':''].map(q).join(',')));
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([L.join('\n')],{type:'text/csv'}));a.download=('ChainTrace-timeline-'+((typeof curCase!=='undefined'&&curCase&&curCase.name)||'graph')).replace(/[^A-Za-z0-9._-]+/g,'_').slice(0,70)+'.csv';document.body.appendChild(a);a.click();a.remove();toast('Timeline CSV downloaded')};
const anchor=$('lossbtn')||$('rptbtn')||$('savebtn');if(anchor){const b=document.createElement('button');b.className='btn';b.id='tlbtn';b.title='Timeline of fund movements';b.textContent='🕒 Timeline';b.onclick=()=>ctTimeline();anchor.after(b)}
const dd=document.querySelector('#exportMenu .dd');if(dd){const b=document.createElement('button');b.className='btn sm';b.textContent='Timeline of fund movements…';b.onclick=()=>{exportMenu.classList.remove('open');ctTimeline(true)};dd.appendChild(b)}
const _rp=window.ctReportPayload;window.ctReportPayload=function(meta){const pl=_rp(meta);pl.timeline={...F,include:true};return pl};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&d.classList.contains('open'))ctTimeline(false)});
})();

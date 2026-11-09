// ChainTrace screening: official sanctions lists (OFAC SDN + UK Sanctions List) = hard red flag; community scam reports = amber unverified leads.
// Loaded last; wraps add/render/renderTrace/renderAuto like v6.js does.
(function(){
const SC={flagOnly:false,status:null};window.CT_SCREEN=SC;
const css=document.createElement('style');css.textContent=`
.sdnbox{margin-top:10px;padding:10px 11px;border:1.5px solid #ff4d6d;background:linear-gradient(135deg,rgba(255,77,109,.22),rgba(255,77,109,.08));border-radius:12px;font-size:12.5px;color:#ffd5dc;box-shadow:0 0 22px rgba(255,77,109,.25)}
.sdnbox b.h{display:flex;align-items:center;gap:6px;color:#fff;font-size:12px;letter-spacing:.6px;text-transform:uppercase;margin-bottom:4px}
.sdnbox .w{font-weight:650;color:#fff}.sdnbox .m{font-size:11.5px;color:#ffc2cd;margin-top:4px}.sdnbox a{color:#ffd5dc}
.repbox{margin-top:10px;padding:9px 11px;border:1px dashed #ff9f43;background:rgba(255,159,67,.08);border-radius:12px;font-size:12.5px;color:#ffd9b0}
.repbox b.h{display:block;color:#ffb366;font-size:11.5px;letter-spacing:.5px;text-transform:uppercase;margin-bottom:3px}.repbox a{color:#ffd9b0}
.repbox ul{margin:5px 0 0 16px;padding:0;font-size:11.5px}.repbox .btn{margin-top:6px}
.tag.sdn{color:#fff;background:#ff4d6d;border-color:#ff4d6d;font-weight:800}.tag.rep{color:#ffb366;border-color:#ff9f4366;background:#ff9f4318}
.gtools .btn.flt{position:relative}.gtools .btn.flt.on{border-color:#ff4d6d;background:rgba(255,77,109,.3)}
.gtools .btn.flt i{position:absolute;right:-5px;top:-5px;min-width:16px;height:16px;border-radius:9px;background:#ff4d6d;color:#fff;font:700 10px/16px var(--font);font-style:normal;padding:0 3px}
.gtools .btn.flt i.a{background:#ff9f43;color:#1b1206}
#scrm{position:fixed;inset:0;z-index:80;display:none;align-items:center;justify-content:center;background:rgba(3,5,10,.62);padding:12px}#scrm.on{display:flex}
#scrm .card{width:min(860px,100%);max-height:calc(100vh - 24px);overflow:auto;padding:16px;background:rgba(16,21,36,.97)}
#scrm h3{margin:0 0 4px;font-size:15px;display:flex;align-items:center;gap:8px;text-transform:none;letter-spacing:0;color:var(--txt)}
#scrm textarea{width:100%;min-height:110px;box-sizing:border-box;background:rgba(0,0,0,.25);border:1px solid var(--line);border-radius:10px;padding:8px 10px;color:var(--txt);font:12px var(--mono);outline:0;resize:vertical}
#scrm table{width:100%;border-collapse:collapse;margin-top:10px;font-size:12px}#scrm td,#scrm th{padding:7px 5px;border-top:1px solid var(--line);vertical-align:top;text-align:left}
#scrm th{color:var(--mut);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px}
.vpill{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:800;white-space:nowrap}
.vpill.sanctioned{background:#ff4d6d;color:#fff}.vpill.reported{background:rgba(255,159,67,.2);color:#ffb366;border:1px solid #ff9f43}.vpill.nomatch{background:rgba(46,229,157,.12);color:#2ee59d;border:1px solid #2ee59d55}.vpill.bad{background:rgba(255,255,255,.06);color:var(--mut)}
#scrsum{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;font-size:12px}
#cpp,#side .card{max-width:100%;overflow-x:auto}#side td{overflow-wrap:anywhere}@media(max-width:480px){#cpp .nm{max-width:84px}#cpp td{padding:5px 2px}}
@media(max-width:700px){#scrm .card{padding:12px}#scrm thead{display:none}#scrm tr{display:block;border-top:1px solid var(--line);padding:6px 0}#scrm td{display:block;border:0;padding:2px 0}#scrm td.c{display:inline-block;margin-right:8px}}`;
document.head.appendChild(css);
// ---------- graph styling ----------
cy.style().selector('node[?sanc]').style({'border-width':6,'border-color':'#ff4d6d','border-style':'double','underlay-color':'#ff4d6d','underlay-opacity':.45,'underlay-padding':9,'underlay-shape':'ellipse',
  label:e=>'⛔ SDN · '+(e.data('lbl')||''),color:'#ffd5dc','font-weight':700,'text-background-color':'#3a0a14','text-background-opacity':.9,'z-index':20})
 .selector('node[?rep][!sanc]').style({'border-width':4,'border-color':'#ff9f43','border-style':'dashed','underlay-color':'#ff9f43','underlay-opacity':.18,'underlay-padding':6,
  label:e=>'⚑ '+(e.data('lbl')||''),color:'#ffd9b0'})
 .selector('.unflag').style({display:'none'}).update();
const sancOf=i=>(i&&i.sanctions&&i.sanctions.length)?i.sanctions:null;
const repOf=i=>(i&&i.reports&&i.reports.count)?i.reports:null;
function mark(){let s=0,r=0;cy.batch(()=>cy.nodes().forEach(n=>{if(n.data('grp'))return;const i=n.data('info')||{};
  const a=!!sancOf(i),b=!!repOf(i);if(a!==!!n.data('sanc'))a?n.data('sanc',1):n.removeData('sanc');if(b!==!!n.data('rep'))b?n.data('rep',1):n.removeData('rep');if(a)s++;else if(b)r++}));
 SC.counts={sanctioned:s,reported:r};const b=$('scrflt');if(b)b.innerHTML='⛔'+(s?`<i>${s}</i>`:r?`<i class="a">${r}</i>`:'');applyFilter();return SC.counts}
window.ctScreenMark=mark;
function flagged(n){const i=n.data('info')||{};return n.data('sanc')||n.data('rep')||n.data('focus')||n.data('note')||HIGH.includes(i.kind||n.data('kind'))}
function applyFilter(){cy.batch(()=>{cy.nodes().forEach(n=>{if(n.data('grp'))return;n.toggleClass('unflag',SC.flagOnly&&!flagged(n))})});
 const b=$('scrflt');if(b)b.classList.toggle('on',SC.flagOnly)}
window.ctFlagOnly=on=>{SC.flagOnly=on==null?!SC.flagOnly:!!on;applyFilter();const c=SC.counts||{};
 toast(SC.flagOnly?`Flagged only: ${cy.nodes().not('.unflag').not('[?grp]').length} of ${cy.nodes().not('[?grp]').length} nodes (⛔ ${c.sanctioned||0} sanctioned · ⚑ ${c.reported||0} reported)`:'Showing all nodes')};
const gt=document.querySelector('.gtools');if(gt){const b=document.createElement('button');b.className='btn flt';b.id='scrflt';b.title='Show only flagged nodes (sanctions matches, community reports, high-risk labels)';b.textContent='⛔';b.onclick=()=>ctFlagOnly();gt.appendChild(b)}
const _add=window.add;window.add=function(d,f){const r=_add.apply(this,arguments);try{mark()}catch(e){console.warn(e)}return r};
// ---------- panels ----------
const d10=s=>s?String(s).slice(0,10):'?';
function sdnBox(hits,who){if(!hits||!hits.length)return'';
 return `<div class="sdnbox"><b class="h">⛔ Sanctions list match${hits.length>1?'es':''}</b>${hits.map(h=>`<div class="w">${esc(who||'Address')} ${esc(h.wording||('matches '+h.short+' entry '+h.entry))}</div>
  <div class="m">${esc(h.short)} entry: <b>${esc(h.entry||'?')}</b>${h.type?' · '+esc(h.type):''}${(h.programs||[]).length?' · programme '+esc(h.programs.join(', ')):''}${h.designated?' · designated '+esc(d10(h.designated)):''} · list as of ${esc(h.as_of||'?')}${h.asset?' · listed as '+esc(h.asset)+' address':''}<br>
  Source: ${h.url?`<a target="_blank" rel="noopener" href="${esc(h.url)}">${esc(h.list_name||h.short)} ↗</a>`:esc(h.list_name||h.short)}</div>`).join('')}
  <div class="m">Official list match on the exact address string. Confirm on the official list before any action.</div></div>`}
function repBox(rep,addr,chain){const ca=rep&&rep.chainabuse;const url=(rep&&rep.search_url)||('https://chainabuse.com/address/'+encodeURIComponent(addr||''));
 const ds=(rep&&rep.datasets)||[];const cr=(ca&&ca.reports)||[];
 const head=rep&&rep.count?`<b class="h">⚑ Community reports: unverified leads · ${rep.count}</b><div>${esc((rep.categories||[]).join(', '))}</div>`:'<b class="h">⚑ Community reports</b><div class="dim">None in ChainTrace\'s datasets.</div>';
 const st=SC.status&&SC.status.chainabuse;const btn=addr&&chain?(st&&st.configured?`<button class="btn sm" onclick="ctChainabuse('${esc(addr)}','${esc(chain)}',this)">Check Chainabuse (${st.left}/${st.limit} calls left this month)</button>`:''):'';
 return `<div class="repbox">${head}${ds.length?'<ul>'+ds.map(x=>`<li>${esc(x.source)}: “${esc(x.name||x.category)}” (${esc(x.category)})${x.url?` · <a target="_blank" rel="noopener" href="${esc(x.url)}">dataset ↗</a>`:''}</li>`).join('')+'</ul>':''}
 ${cr.length?'<ul>'+cr.slice(0,8).map(x=>`<li>Chainabuse ${esc(x.category)} · ${esc(d10(x.created))}${x.checked?' · checked by moderators':''} · <a target="_blank" rel="noopener" href="${esc(x.url)}">report ↗</a></li>`).join('')+'</ul>':''}
 <div style="font-size:11px;margin-top:5px">Reports are not verified by ChainTrace: treat as a lead, not evidence. <a target="_blank" rel="noopener" href="${esc(url)}">Search Chainabuse ↗</a></div>${btn}</div>`}
window.ctSdnBox=sdnBox;window.ctRepBox=repBox;
window.ctChainabuse=async(addr,chain,btn)=>{if(btn){btn.disabled=true;btn.textContent='Checking Chainabuse…'}
 try{const r=await fetch(`/api/screen?addr=${encodeURIComponent(addr)}&chain=${encodeURIComponent(chain)}&chainabuse=1`);const j=await r.json();
  const ca=j.chainabuse||{};const n=cy.getElementById(addr);if(n.length&&j.reports){const i=n.data('info')||{};i.reports=j.reports;n.data('info',i);mark()}
  if(btn){const box=btn.closest('.repbox');if(box)box.outerHTML=repBox(j.reports||{count:0,chainabuse:ca,search_url:ca.search_url},addr,chain);}
  toast(ca.status==='ok'||ca.status==='cached'?`Chainabuse: ${ca.count||0} report(s)`:(ca.note||ca.status));loadStatus()}catch(e){toast('Chainabuse check failed');if(btn)btn.disabled=false}};
function decorateFirstCard(html){const c=$('side').querySelector('.card');if(!c)return;const a=c.querySelector('.addr');const w=document.createElement('div');w.innerHTML=html;(a||c.firstChild).after(...w.childNodes)}
const _render=window.render;window.render=function(d){const r=_render.apply(this,arguments);try{
  const l=d.label||{};let h=sdnBox(l.sanctions);
  const others=(d.nodes||[]).filter(n=>n.id!==(d.address||'')&&sancOf(n));
  if(others.length)h+=`<div class="sdnbox"><b class="h">⛔ ${others.length} sanctioned counterpart${others.length>1?'ies':'y'} in view</b>${others.slice(0,6).map(n=>`<div class="w" style="margin-top:4px;cursor:pointer" onclick="ctFocusNode('${esc(n.id)}')">${esc(short(n.id))} ${esc(n.sanctions[0].wording)}</div>`).join('')}${others.length>6?`<div class="m">+${others.length-6} more: use ⛔ Flagged only</div>`:''}</div>`;
  if(d.kind==='address')h+=repBox(l.reports,d.address,d.chain);
  if(h)decorateFirstCard(h)}catch(e){console.warn(e)}return r};
function traceBox(j){const ns=(j.nodes||[]).filter(sancOf);let h=(j.warnings||[]).map(w=>`<div class="warnbox">${esc(w)}</div>`).join('');
 if(ns.length)h+=`<div class="sdnbox"><b class="h">⛔ ${ns.length} sanctioned address${ns.length>1?'es':''} in this ${j.type==='autotrace'?'AutoTrace':'trace'}</b>${ns.slice(0,6).map(n=>`<div class="w" style="margin-top:4px;cursor:pointer" onclick="ctFocusNode('${esc(n.id)}')">${esc(short(n.id))} ${esc(n.sanctions[0].wording)}</div>`).join('')}
  <div class="m">${j.type==='autotrace'?'AutoTrace stops each branch at a sanctioned address (treated as an endpoint). ':''}Confirm on the official list before any action.</div></div>`;
 const rp=(j.nodes||[]).filter(n=>!sancOf(n)&&repOf(n));if(rp.length)h+=`<div class="repbox"><b class="h">⚑ ${rp.length} address(es) with community reports: unverified leads</b>${rp.slice(0,5).map(n=>`<div style="cursor:pointer" onclick="ctFocusNode('${esc(n.id)}')">${esc(short(n.id))} · ${n.reports.count} · ${esc((n.reports.categories||[]).join(', '))}</div>`).join('')}</div>`;
 if(h)decorateFirstCard(h)}
window.ctFocusNode=id=>{const n=cy.getElementById(id);if(!n.length)return;cy.nodes().unselect();n.select();cy.animate({center:{eles:n},zoom:Math.max(cy.zoom(),1)},{duration:300});n.emit('tap')};
for(const f of ['renderTrace','renderAuto']){const o=window[f];if(typeof o==='function')window[f]=function(j){const r=o.apply(this,arguments);try{traceBox(j)}catch(e){console.warn(e)}return r}}
cy.on('tap','node',e=>{const i=e.target.data('info')||{};if(!i.id||String(i.id).startsWith('tx:')||e.target.data('grp'))return;
 const c=$('det').querySelector('.card');if(!c)return;const w=document.createElement('div');w.innerHTML=sdnBox(i.sanctions)+(repOf(i)?repBox(i.reports,i.id,i.chain):'');
 const a=c.querySelector('.addr');(a||c.firstChild).after(...w.childNodes)});
// ---------- batch screening modal ----------
const m=document.createElement('div');m.id='scrm';m.innerHTML=`<div class="card glass"><h3>🛡 Screen addresses<span class="sp" style="flex:1"></span><button class="btn sm" onclick="ctScreenClose()">✕</button></h3>
<div class="dim" style="font-size:12px">Paste addresses (BTC, ETH/EVM, SOL, TRON, XRP; other chains matched exactly against the lists), one per line or comma separated. Max 500.</div>
<textarea id="scrin" spellcheck="false" placeholder="0x…&#10;bc1…&#10;T…"></textarea>
<div class="row" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px"><button class="btn pri" id="scrgo" onclick="ctScreenRun()">Screen list</button><button class="btn" onclick="ctScreenFromGraph()">Use graph addresses</button><button class="btn" id="scrcsv" onclick="ctScreenCSV()" disabled>Download CSV</button></div>
<div id="scrmeta" class="dim" style="font-size:11.5px;margin-top:8px"></div><div id="scrsum"></div><div id="scrout"></div></div>`;document.body.appendChild(m);
m.addEventListener('click',e=>{if(e.target===m)ctScreenClose()});
window.ctScreenOpen=(text)=>{m.classList.add('on');if(text!=null)$('scrin').value=text;loadStatus();setTimeout(()=>$('scrin').focus(),50)};
window.ctScreenClose=()=>m.classList.remove('on');
window.ctScreenFromGraph=()=>{$('scrin').value=cy.nodes().filter(n=>!n.data('grp')&&!n.id().startsWith('tx:')).map(n=>n.id()).join('\n');toast('Graph addresses added')};
const vClass=v=>v==='sanctioned'?'sanctioned':v==='reported'?'reported':v==='no match'?'nomatch':'bad';
function metaLine(j){const L=j.lists||{};return Object.values(L).map(x=>`${esc(x.short)} as of ${esc(x.as_of||'?')} (${x.addresses} addresses)`).join(' · ')+(j.stale?' · <span style="color:#f6c945">list refresh due</span>':'')
 +(()=>{const cb=j.chainabuse_api||j.chainabuse;return ` · community reports: ChainTrace label datasets${cb&&cb.configured?` + Chainabuse (${cb.left}/${cb.limit} API calls left this month)`:' (Chainabuse: no API key set, use the search links)'}`})()}
async function loadStatus(){try{const r=await fetch('/api/screen/status');if(r.ok){SC.status=await r.json();$('scrmeta').innerHTML=metaLine({...SC.status,lists:SC.status.lists})}}catch(e){}}
window.ctScreenRun=async()=>{const t=$('scrin').value.trim();if(!t)return toast('Paste some addresses');const b=$('scrgo');b.disabled=true;b.textContent='Screening…';
 try{const r=await fetch('/api/screen/batch',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({text:t})});const j=await r.json();if(!r.ok){toast(j.detail||'Error');return}
  SC.last=j;$('scrcsv').disabled=false;$('scrmeta').innerHTML=metaLine(j);const s=j.summary||{};
  $('scrsum').innerHTML=`<span class="vpill sanctioned">⛔ ${s.sanctioned||0} sanctioned</span><span class="vpill reported">⚑ ${s.reported||0} reported</span><span class="vpill nomatch">✓ ${s['no match']||0} no match</span>${s['not an address']?`<span class="vpill bad">${s['not an address']} not recognised</span>`:''}`;
  $('scrout').innerHTML=`<table><thead><tr><th>Result</th><th>Address</th><th>Chain</th><th>Detail</th><th></th></tr></thead><tbody>${j.rows.map(x=>`<tr>
   <td class="c"><span class="vpill ${vClass(x.verdict)}">${x.verdict==='sanctioned'?'⛔ SANCTIONED':x.verdict==='reported'?'⚑ REPORTED':x.verdict==='no match'?'✓ no match':'?'}</span></td>
   <td><span class="mono">${esc(x.address)}</span><button class="copy" onclick="copy('${esc(x.address)}')">⧉</button></td><td class="c">${x.chain&&CH[x.chain]?chainTag(x.chain):esc((x.chain||'').toUpperCase())}</td>
   <td>${x.sanctions&&x.sanctions.length?x.sanctions.map(h=>`<div style="color:#ffd5dc"><b>${esc(h.wording)}</b><div class="dim" style="font-size:11px">${esc((h.programs||[]).join(', '))}${h.designated?' · designated '+esc(d10(h.designated)):''} · <a target="_blank" rel="noopener" href="${esc(h.url||'#')}">source ↗</a></div></div>`).join('')
     :x.reports&&x.reports.count?`<div style="color:#ffd9b0">${x.reports.count} community report(s): ${esc((x.reports.categories||[]).join(', '))}<div class="dim" style="font-size:11px">unverified leads, not evidence · ${esc((x.reports.datasets||[]).map(d=>d.source).join(', '))}</div></div>`
     :x.valid?`<span class="dim">${esc(x.name||'')}${x.unlisted_note?' · '+esc(x.unlisted_note):''}</span>`:'<span class="dim">not a recognised address</span>'}
     ${x.chainabuse_url?`<div style="font-size:11px"><a target="_blank" rel="noopener" href="${esc(x.chainabuse_url)}">Chainabuse ↗</a></div>`:''}</td>
   <td class="c">${x.valid&&x.chain&&CH[x.chain]?`<button class="btn sm" onclick="ctScreenClose();$('q').value='${esc(x.address)}';setBadge();go()">Open</button>`:''}</td></tr>`).join('')}</tbody></table>`;
 }catch(e){toast('Screening failed')}finally{b.disabled=false;b.textContent='Screen list'}};
window.ctScreenCSV=()=>{const j=SC.last;if(!j)return;const rows=[['address','chain','result','list','entry','entry_id','programmes','designated','list_as_of','source_url','community_reports','report_categories','wording']];
 for(const x of j.rows){const h=(x.sanctions||[])[0]||{};rows.push([x.address,x.chain||'',x.verdict,h.short||'',h.entry||'',h.uid||'',(h.programs||[]).join(' '),h.designated||'',h.as_of||'',h.url||'',(x.reports||{}).count||0,((x.reports||{}).categories||[]).join(' '),x.wording||''])}
 dl('chaintrace-screening-'+new Date().toISOString().slice(0,10)+'.csv',new Blob([rows.map(r=>r.map(v=>'"'+String(v).replace(/"/g,'""')+'"').join(',')).join('\n')],{type:'text/csv'}))};
const ctl=$('autobtn');if(ctl){const b=document.createElement('button');b.className='btn';b.id='scrbtn';b.title='Screen a list of addresses against sanctions lists and community reports';b.textContent='🛡 Screen';b.onclick=()=>ctScreenOpen();($('cancelbtn')||ctl).after(b)}
loadStatus();
const P=new URLSearchParams(location.search);if(P.get('screen')){const v=P.get('screen');ctScreenOpen(v==='1'?'':v.split(',').join('\n'));if(v!=='1')setTimeout(ctScreenRun,300)}
try{mark()}catch(e){}
})();

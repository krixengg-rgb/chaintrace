// ChainTrace v6: counterparties panel, direction colouring, entity grouping, noise filter.
// Loaded after the main script; wraps a few of its global functions (add, render, api, expand, snapshot, openCase, highlight, relayout).
(function(){
const V=Object.assign({dir:true,group:true,noise:true,min:1,unpriced:false},JSON.parse(localStorage.ct_v6||'{}'));
const save=()=>{localStorage.ct_v6=JSON.stringify(V)};
const NOISE=['spam','zero','approval'];
const day=t=>t?new Date(t*1000).toISOString().slice(0,10):'';
// ---------- noise ----------
function noisy(x){if(!V.noise||!x)return false;const f=x.flags||[];
 if(f.some(k=>NOISE.includes(k))||(V.unpriced&&f.includes('unpriced')))return true;
 return x.usd!=null&&x.usd>0&&x.usd<V.min}
window.ctNoisy=noisy;
function applyNoise(){let hid=0;
 cy.batch(()=>{cy.edges().forEach(e=>{if(e.data('meta'))return;const n=!e.hasClass('hot')&&!e.hasClass('hotx')&&noisy(e.data('info'));e.toggleClass('noise',n);if(n)hid++});
  cy.nodes().forEach(n=>{if(n.data('grp'))return;if(n.data('focus')||n.data('note')||n.hasClass('hot')){n.removeClass('noise');return}
   const es=n.connectedEdges().filter(e=>!e.data('meta'));n.toggleClass('noise',V.noise&&es.length>0&&es.every(e=>e.hasClass('noise')))})});
 const b=$('nhid');if(b)b.textContent=V.noise?hid+' hidden':'off';return hid}
// ---------- direction colouring ----------
function dirFocus(){const s=cy.nodes(':selected');return s.length?s[0]:cy.nodes('[?focus]')[0]}
function applyDir(){cy.batch(()=>{cy.edges().removeClass('din dout');if(!V.dir)return;const f=dirFocus();if(!f||!f.length)return;
 const ids=new Set([f.id()]);if(f.data('grp'))f.children().forEach(c=>ids.add(c.id()));
 cy.edges().forEach(e=>{if(e.hasClass('hot')||e.hasClass('hotx'))return;const s=ids.has(e.data('source')),t=ids.has(e.data('target'));if(t&&!s)e.addClass('din');else if(s&&!t)e.addClass('dout')})})}
// ---------- entity grouping ----------
function entName(s){s=String(s||'').split(/[:|(]/)[0].replace(/\b(hot|cold|deposit)\s*wallet\b/ig,'').replace(/[\s_#-]*\d+\s*$/,'').trim();return s.length>=2?s:null}
function gkey(n){const i=n.data('info')||{};if(!i.id||String(i.id).startsWith('tx:'))return null;
 const sg=i.suggested;if(sg){const ent=sg.entity||(sg.label||'').replace(/ deposit$/,'');if(ent)return['dep:'+ent.toLowerCase(),ent+' deposits (suggested)','exchange']}
 if(i.kind&&i.name){const ent=entName(i.name);if(ent)return['ent:'+ent.toLowerCase(),ent,i.kind]}
 if(cur&&cur.chain==='btc'&&(cur.cluster||[]).length>1&&cur.cluster.includes(i.id))return['clu:'+cur.address,'Cluster of '+short(cur.address),null];
 return null}
const kids=g=>cy.nodes().filter(n=>n.data('gof')===g.id()||n.data('parent')===g.id());
function regroup(){if(!V.group){ungroupAll();return}const B={};
 cy.nodes().forEach(n=>{if(n.data('grp'))return;const k=gkey(n);if(k)(B[k[0]]=B[k[0]]||{k,m:[]}).m.push(n)});
 cy.batch(()=>{for(const[key,b]of Object.entries(B)){if(b.m.length<2)continue;const gid='grp:'+key;let g=cy.getElementById(gid);
   if(!g.length)g=cy.add({group:'nodes',data:{id:gid,grp:1,gname:b.k[1],gkind:b.k[2]||undefined}});
   g.data('lbl',b.k[1]+' · '+b.m.length);const col=g.data('collapsed');
   for(const n of b.m){if(col){if(n.data('gof')!==gid){n.data('gof',gid);n.move({parent:null});n.addClass('gmem')}}else if(n.data('parent')!==gid)n.move({parent:gid})}}
  cy.nodes('[?grp]').forEach(g=>{if(!kids(g).length)g.remove()})})}
function ungroupAll(){cy.batch(()=>{cy.nodes('[?grp]').forEach(g=>{const k=kids(g);k.removeClass('gmem');k.forEach(n=>n.removeData('gof'));k.move({parent:null});g.remove()})})}
function rebuildMeta(){cy.remove(cy.edges('[?meta]'));const col=new Set(cy.nodes('[?grp][?collapsed]').map(g=>g.id()));if(!col.size)return;
 const rep=id=>{const g=cy.getElementById(id).data('gof');return g&&col.has(g)?g:id};const A={};
 cy.edges().forEach(e=>{if(e.hasClass('noise'))return;const s0=e.data('source'),t0=e.data('target'),s=rep(s0),t=rep(t0);if((s===s0&&t===t0)||s===t)return;
  const a=A[s+'»'+t]=A[s+'»'+t]||{source:s,target:t,usd:0,count:0,units:{},n:0};const i=e.data('info')||{};a.usd+=i.usd||0;a.count+=i.count||1;a.n++;if(i.unit)a.units[i.unit]=(a.units[i.unit]||0)+(i.amount||0)});
 cy.add(Object.values(A).map(a=>{const us=Object.entries(a.units);const one=us.length===1;
  return{group:'edges',data:{id:'meta:'+a.source+'»'+a.target,source:a.source,target:a.target,meta:1,usd:a.usd,
   lbl:'Σ '+(one?fmt(us[0][1],4)+' '+us[0][0]:us.length+' assets')+(a.usd?' · '+usd(a.usd):'')+' ×'+a.count,
   info:{source:a.source,target:a.target,amount:one?us[0][1]:null,unit:one?us[0][0]:'',usd:a.usd,count:a.count,meta:1,flows:a.n}}}}))}
function collapse(g){if(g.data('collapsed'))return;const k=g.children();const p={...g.position()};
 cy.batch(()=>{k.forEach(n=>n.data('gof',g.id()));k.move({parent:null});k.addClass('gmem');g.data('collapsed',1);g.position(p)});refresh(false)}
function split(g){if(!g.data('collapsed'))return;const k=kids(g);
 cy.batch(()=>{g.data('collapsed',0);k.removeClass('gmem');k.forEach(n=>n.removeData('gof'));k.move({parent:g.id()})});refresh(false)}
function toggleGroup(g){if(!g||!g.length)return;if(!g.data('grp')){const p=g.data('parent')||g.data('gof');if(!p)return toast('Not in a group');g=cy.getElementById(p)}
 g.data('collapsed')?split(g):collapse(g);toast((g.data('collapsed')?'Collapsed ':'Split ')+g.data('gname'))}
window.ctToggleGroup=id=>toggleGroup(cy.getElementById(id));
window.ctCollapseAll=on=>{cy.nodes('[?grp]').forEach(g=>on?collapse(g):split(g))};
function refresh(lay){regroup();applyNoise();rebuildMeta();applyDir();if(lay)relayout();autosave()}
window.ctRefresh=refresh;
// ---------- styles + toolbar ----------
cy.style().selector('node[?grp]').style({'background-image':'none','background-color':e=>(CAT[e.data('gkind')]||['#7c5cff'])[0],'background-opacity':.08,shape:'round-rectangle',
  'border-width':1.5,'border-style':'dashed','border-color':e=>(CAT[e.data('gkind')]||['#a08cff'])[0],label:'data(lbl)','text-valign':'top','text-margin-y':-3,'font-size':10,color:'#d9d2ff',padding:12})
 .selector('node[?grp][?collapsed]').style({width:48,height:48,'background-opacity':.85,'border-style':'double','border-width':5,'border-color':'#fff','text-valign':'bottom','text-margin-y':5,
  'background-image':e=>icon(e.data('gkind'))})
 .selector('edge[?meta]').style({'line-style':'solid',color:'#d9d2ff','font-size':8})
 .selector('edge.din').style({'line-color':'#2ee59d','target-arrow-color':'#2ee59d',color:'#9ff2cf','z-index':7})
 .selector('edge.dout').style({'line-color':'#ff6b81','target-arrow-color':'#ff6b81',color:'#ffc2cd','z-index':7})
 .selector('edge[?tmp]').style({opacity:0,label:'','target-arrow-shape':'none'}).selector('.glay').style({display:'none'}).selector('.noise').style({display:'none'}).selector('.gmem').style({display:'none'})
 .selector(':selected').style({'border-width':4,'border-color':'#f6c945'}).update();
const css=document.createElement('style');css.textContent=`
#vtools{position:absolute;left:10px;top:10px;z-index:5;display:flex;flex-wrap:wrap;gap:5px;align-items:center;padding:5px 6px;border-radius:12px;font-size:11.5px;max-width:calc(100% - 70px)}
#vtools .btn{padding:4px 8px;font-size:11.5px;border-radius:8px;background:rgba(14,19,32,.75)}#vtools .btn.on{border-color:#7c5cff;background:rgba(124,92,255,.28)}
#vtools input{width:44px;background:transparent;border:1px solid var(--line);color:inherit;border-radius:6px;padding:2px 4px;font-size:11.5px}
#vtools .lg{display:inline-flex;gap:6px;color:var(--mut)}#vtools .lg i{display:inline-block;width:14px;height:3px;border-radius:2px;vertical-align:middle;margin-right:3px}
#cpp .flt{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:8px}#cpp .flt select,#cpp .flt input{background:var(--panel2);border:1px solid var(--line);color:inherit;border-radius:8px;padding:4px 5px;font-size:12px;max-width:120px}
#cpp td{padding:6px 3px}#cpp .nm{max-width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}#cpp .in{color:#2ee59d}#cpp .out{color:#ff6b81}
#cpp .sg{color:#2ee6d6;border-color:#2ee6d655;background:#2ee6d618}#cpp svg{width:100%;height:74px;display:block;margin:4px 0 2px}
#cpp .plus{padding:3px 8px}#cpp .meta{font-size:11px;color:var(--mut)}
@media(max-width:900px){#vtools{font-size:11px;gap:4px}#vtools .lg{display:none}#cpp .nm{max-width:130px}#cpp .hide-s{display:none}}`;document.head.appendChild(css);
const tb=document.createElement('div');tb.id='vtools';tb.className='glass';$('gwrap').appendChild(tb);
function tools(){tb.innerHTML=`<button class="btn ${V.dir?'on':''}" title="Colour flows in (green) / out (red) of the selected node" onclick="ctSet('dir')">⇄ In/Out</button>
<button class="btn ${V.group?'on':''}" title="Group addresses by entity / suggested exchange / BTC cluster. Select a group and press E to collapse or split" onclick="ctSet('group')">▣ Group</button>
<button class="btn ${V.noise?'on':''}" title="Hide dust, spam/airdrop tokens, zero-value calls and approvals" onclick="ctSet('noise')">🧹 Noise <b id="nhid"></b></button>
<span title="Dust threshold (USD)">min $<input id="nmin" type="number" min="0" step="1" value="${V.min}" onchange="ctSet('min',this.value)"></span>
<label title="Also hide token flows with no market price" style="display:inline-flex;gap:3px;align-items:center"><input type="checkbox" style="width:auto" ${V.unpriced?'checked':''} onchange="ctSet('unpriced',this.checked)">unpriced</label>
<span class="lg">${V.dir?'<span><i style="background:#2ee59d"></i>in</span><span><i style="background:#ff6b81"></i>out</span>':''}</span>`}
window.ctSet=(k,v)=>{if(k==='min')V.min=Math.max(0,+v||0);else if(k==='unpriced')V.unpriced=!!v;else V[k]=!V[k];save();tools();refresh(k==='group');
 if(cur&&mode==='lookup'&&$('side').innerHTML)render(cur);else cpRender()};
tools();
// ---------- hooks ----------
const _relayout=relayout;window.relayout=function(){if(window._noLay)return;const gs=cy.nodes('[?grp]').filter(g=>!g.data('collapsed'));if(!gs.length)return _relayout();
 // cose handles compound nodes badly (groups drift far away): lay out flat with short invisible spring edges between members, then re-parent
 const mem=[];cy.batch(()=>{gs.forEach(g=>{const k=g.children();mem.push([g.id(),k]);k.move({parent:null})});gs.addClass('glay')});const tmp=[];
 for(const[,k]of mem)k.slice(1).forEach(b=>tmp.push({group:'edges',data:{id:'tmp:'+k[0].id()+'~'+b.id(),source:k[0].id(),target:b.id(),tmp:1}}));
 const T=cy.add(tmp);const L=cy.elements().not('[?grp]').not('.gmem').not('.noise').layout({...lay(),idealEdgeLength:e=>e.data('tmp')?30:120,edgeElasticity:e=>e.data('tmp')?400:80});
 L.one('layoutstop',()=>{cy.batch(()=>{cy.remove(T);mem.forEach(([g,k])=>k.move({parent:g}));cy.nodes('[?grp]').removeClass('glay')})});L.run()};
const _add=add;window.add=function(d,focus){const n0=cy.nodes().length;window._noLay=1;try{_add(d,focus)}finally{window._noLay=0}
 const grew=cy.nodes().length!==n0;refresh(false);if(grew)relayout()};
const _hl=highlight;window.highlight=function(j){_hl(j);applyNoise();applyDir()};
const _expand=expand;window.expand=function(id){if(String(id).startsWith('grp:'))return toggleGroup(cy.getElementById(id));return _expand(id)};
const _snap=snapshot;window.snapshot=function(){const s=_snap();s.graph.nodes=s.graph.nodes.filter(x=>!x.data.grp).map(x=>{const d={...x.data};delete d.parent;delete d.gof;return{data:d,position:x.position}});
 s.graph.edges=s.graph.edges.filter(d=>!d.meta);return s};
const _open=openCase;window.openCase=async function(id){await _open(id);restoring=true;try{refresh(false)}finally{restoring=false}};
const _render=render;window.render=function(d){let dd=d,hid=0;if(V.noise&&d&&d.txs){const k=d.txs.filter(t=>!noisy(t));hid=d.txs.length-k.length;dd=Object.assign({},d,{txs:k})}
 _render(dd);if(hid){const h=[...$('side').querySelectorAll('.card h3')].find(x=>x.textContent.startsWith('Activity'));if(h&&h.querySelector('.dim'))h.querySelector('.dim').textContent+=' · '+hid+' noise hidden'}
 if(d&&d.kind==='address'&&d.address){if(d.cp&&!CPS[d.address])cpFeed(d.address,d.chain,d.cp,d.next,true);CPV=d.address;cpRender()}};
const _api=api;window.api=async function(q,cursor){const j=await _api(q,cursor);try{if(j&&j.cp&&j.address)cpFeed(j.address,j.chain,j.cp,j.next,!cursor)}catch(e){console.warn(e)}return j};
// ---------- counterparties ----------
const CPS={};let CPV=null;const F={dir:'all',tok:'',min:0,from:'',to:'',n:10,all:false};
function mergeCp(a,b){const cl=x=>({...x,units:{...x.units},uusd:{...(x.uusd||{})},ucount:{...(x.ucount||{})}});const m=new Map();
 for(const x of a.counterparties||[])m.set(x.id+'|'+x.dir,cl(x));
 for(const x of b.counterparties||[]){const k=x.id+'|'+x.dir,y=m.get(k);if(!y){m.set(k,cl(x));continue}
  y.usd=Math.round((y.usd+x.usd)*100)/100;y.count+=x.count;for(const f of['units','uusd','ucount'])for(const[u,v]of Object.entries(x[f]||{}))y[f][u]=(y[f][u]||0)+v;
  y.first=Math.min(y.first||x.first,x.first||y.first);y.last=Math.max(y.last||0,x.last||0);y.flags=(y.flags||[]).filter(f=>(x.flags||[]).includes(f));if(!y.suggested&&x.suggested)y.suggested=x.suggested}
 return{counterparties:[...m.values()].sort((p,q)=>q.usd-p.usd||q.count-p.count),series:(a.series||[]).concat(b.series||[]).sort((p,q)=>p[0]-q[0]).slice(-3000)}}
function cpFeed(id,chain,cp,next,fresh){const o=CPS[id]&&!fresh?CPS[id]:{chain,data:{counterparties:[],series:[]},pages:0};o.data=mergeCp(o.data,cp);o.pages++;o.next=next;o.chain=chain;CPS[id]=o;if(CPV===id)cpRender()}
window.ctCpShow=id=>{CPV=id;cpRender();$('cpp').scrollIntoView({behavior:'smooth',block:'nearest'})};
window.ctCpLoad=async(id,more)=>{const o=CPS[id];const b=$('cpmore');if(b){b.disabled=true;b.textContent='Loading…'}
 if(more&&cur&&cur.address===id&&mode==='lookup'&&cur.next){await loadMore();return}
 try{const r=await fetch('/api/counterparties?q='+encodeURIComponent(id)+'&pages=2'+(more&&o?.next?'&cursor='+encodeURIComponent(o.next):'')+dts());const j=await r.json();
  if(!r.ok)throw new Error(j.detail||r.status);cpFeed(id,j.chain,j,j.next,!more);if(CPS[id])CPS[id].pages+=j.pages-1;if((j.warnings||[]).length)toast(j.warnings[0])}
 catch(e){toast('Counterparties: '+e.message);if(b){b.disabled=false;b.textContent='Retry'}}};
window.ctF=(k,v)=>{F[k]=k==='min'||k==='n'?+v||0:k==='all'?!F.all:v;cpRender()};
const inG=id=>cy.getElementById(id).length>0;
function cpRows(o){const fr=F.from?Date.parse(F.from)/1000:0,to=F.to?Date.parse(F.to)/1000+86399:1e12;let hid=0;
 const rows=o.data.counterparties.filter(x=>{if(F.dir!=='all'&&x.dir!==F.dir)return false;if(F.tok&&x.units[F.tok]==null)return false;
  if((x.last||1e12)<fr||(x.first||0)>to)return false;const u=F.tok?(x.uusd||{})[F.tok]:x.usd;if(F.min&&(u||0)<F.min)return false;
  if(noisy({flags:x.flags,usd:u})){hid++;return false}return true});
 if(F.tok)rows.sort((a,b)=>((b.uusd||{})[F.tok]||0)-((a.uusd||{})[F.tok]||0)||b.units[F.tok]-a.units[F.tok]);return[rows,hid]}
function hist(o){const fr=F.from?Date.parse(F.from)/1000:0,to=F.to?Date.parse(F.to)/1000+86399:1e12;
 const s=o.data.series.filter(r=>r[0]>=fr&&r[0]<=to&&(F.dir==='all'||r[2]===F.dir)&&(!F.tok||r[3]===F.tok)&&!(V.noise&&(r[4]||(r[1]>0&&r[1]<V.min))));
 if(s.length<2)return'<div class="meta">Not enough dated flows for a histogram.</div>';
 const t0=s[0][0],t1=s[s.length-1][0]||t0+1,N=32,w=(t1-t0)/N||1,useUsd=s.some(r=>r[1]>0),I=Array(N).fill(0),O=Array(N).fill(0);
 for(const r of s){const i=Math.min(N-1,Math.floor((r[0]-t0)/w));(r[2]==='in'?I:O)[i]+=useUsd?r[1]:1}
 const sq=Math.sqrt,mx=sq(Math.max(...I,...O)||1),bw=300/N,lab=t=>t1-t0<172800?tfmt(t).slice(5):day(t);let g='';
 for(let i=0;i<N;i++){const a=sq(I[i])/mx*33,b=sq(O[i])/mx*33,tt=lab(t0+i*w)+' → '+lab(t0+(i+1)*w);
  if(a)g+=`<rect x="${i*bw+.5}" y="${35-a}" width="${bw-1}" height="${a}" fill="#2ee59d"><title>${tt}: in ${useUsd?usd(I[i]):I[i]+' transfers'}</title></rect>`;
  if(b)g+=`<rect x="${i*bw+.5}" y="36" width="${bw-1}" height="${b}" fill="#ff6b81"><title>${tt}: out ${useUsd?usd(O[i]):O[i]+' transfers'}</title></rect>`}
 return`<svg viewBox="0 0 300 70" preserveAspectRatio="none"><line x1="0" y1="35.5" x2="300" y2="35.5" stroke="rgba(255,255,255,.15)"/>${g}</svg>
 <div class="meta" style="display:flex"><span>${lab(t0)}</span><span class="sp" style="flex:1;text-align:center">${useUsd?'USD (√ scale)':'transfers'} · <span class="in">▲ in</span> <span class="out">▼ out</span> · ${s.length} flows</span><span>${lab(t1)}</span></div>`}
function badge(x){return x.kind?tagH(x.kind):x.suggested?`<span class="tag sg" title="${esc(x.suggested.method||'')}">≈ ${esc(x.suggested.label)} ${Math.floor((x.suggested.confidence||0)*100)}%</span>`:''}
function cpRender(){let el=$('cpp');if(!el||!el.isConnected){el=el||document.createElement('div');el.id='cpp';const f=$('side').querySelector('.card');f?f.after(el):$('side').appendChild(el)}
 const o=CPS[CPV];if(!CPV){el.innerHTML='';return}
 const head=`<h3>⇆ Counterparties<span class="sp"></span><span class="dim" style="text-transform:none;letter-spacing:0">${esc(short(CPV))}${o?' · '+o.pages+' page(s)':''}</span></h3>`;
 if(!o){el.innerHTML=`<div class="card glass">${head}<div class="dim" style="font-size:12.5px">Not loaded yet for this address.</div><div class="row"><button class="btn sm pri" id="cpmore" onclick="ctCpLoad('${esc(CPV)}')">Load counterparties</button></div></div>`;return}
 const[rows,hid]=cpRows(o);const toks=[...new Set(o.data.counterparties.flatMap(x=>Object.keys(x.units)))].slice(0,40);const shown=rows.slice(0,F.all?150:25);
 el.innerHTML=`<div class="card glass">${head}
 <div class="flt"><select onchange="ctF('dir',this.value)"><option value="all">⇄ in + out</option><option value="in" ${F.dir==='in'?'selected':''}>↓ inflow</option><option value="out" ${F.dir==='out'?'selected':''}>↑ outflow</option></select>
 <select onchange="ctF('tok',this.value)"><option value="">all tokens</option>${toks.map(t=>`<option ${F.tok===t?'selected':''}>${esc(t)}</option>`).join('')}</select>
 <input type="number" min="0" step="10" placeholder="min $" value="${F.min||''}" style="width:64px" onchange="ctF('min',this.value)">
 <input type="date" value="${F.from}" onchange="ctF('from',this.value)" title="first seen from"><input type="date" value="${F.to}" onchange="ctF('to',this.value)" title="last seen to"></div>
 ${hist(o)}
 <div class="row" style="margin:6px 0"><select onchange="ctF('n',this.value)" style="background:var(--panel2);border:1px solid var(--line);color:inherit;border-radius:8px;padding:4px">${[5,10,20,50].map(n=>`<option ${F.n===n?'selected':''}>${n}</option>`).join('')}</select>
 <button class="btn sm pri" onclick="ctCpTop()">＋ Add top ${F.n}</button><span class="meta">${rows.length} shown${hid?' · '+hid+' noise hidden':''}</span></div>
 <table>${shown.map((x,i)=>{const u=F.tok?(x.uusd||{})[F.tok]:x.usd;const amt=F.tok?fmt(x.units[F.tok],4)+' '+esc(F.tok):Object.entries(x.units).sort((a,b)=>((x.uusd||{})[b[0]]||0)-((x.uusd||{})[a[0]]||0)).slice(0,2).map(([k,v])=>fmt(v,4)+' '+esc(k)).join(', ');
  return`<tr><td><div class="nm"><span class="${x.dir}">${x.dir==='in'?'↓':'↑'}</span> <a class="mono" href="#" onclick="ctCpPick(${i});return false">${esc(x.name||short(x.id))}</a></div><div>${badge(x)}</div>
   <div class="meta">${x.count} tx · ${day(x.first)}${x.last&&day(x.last)!==day(x.first)?' → '+day(x.last):''}</div></td>
   <td class="r"><b>${u?usd(u):'–'}</b><div class="meta">${amt}</div></td>
   <td class="r">${inG(x.id)?'<span class="dim" title="in graph">✓</span>':`<button class="btn sm plus" title="Add to graph" onclick="ctCpAdd(${i})">＋</button>`}</td></tr>`}).join('')}</table>
 ${rows.length>25?`<button class="btn sm" onclick="ctF('all')">${F.all?'Show fewer':'Show all '+Math.min(150,rows.length)}</button>`:''}
 <div class="row">${o.next?`<button class="btn sm" id="cpmore" onclick="ctCpLoad('${esc(CPV)}',1)">Load more pages</button>`:'<span class="meta">All fetched history (within date range) included.</span>'}</div>
 <div class="meta" style="margin-top:6px">Ranked by USD at transfer-time prices where known. Based on ${o.pages} history page(s); series ≤3000 most recent transfers.</div></div>`;
 el._rows=shown}
function cpAdd(xs){const o=CPS[CPV];if(!o||!xs.length)return 0;const nodes=[],edges=[];if(!inG(CPV))nodes.push({id:CPV,chain:o.chain});
 for(const x of xs){nodes.push({id:x.id,chain:o.chain,name:x.name||null,kind:x.kind||null,risk:x.risk||0,suggested:x.suggested||undefined});
  for(const[u,a]of Object.entries(x.units)){if(F.tok&&u!==F.tok)continue;const e={source:x.dir==='in'?x.id:CPV,target:x.dir==='in'?CPV:x.id,amount:a,unit:u,usd:(x.uusd||{})[u]||null,count:(x.ucount||{})[u]||x.count,first:x.first,last:x.last,flags:x.flags};
   if(e.usd==null&&Object.keys(x.units).length===1)e.usd=x.usd||null;edges.push(e)}}
 const before=cy.nodes().length;add({nodes,edges,unit:''},null);cpRender();return cy.nodes().length-before}
window.ctCpAdd=i=>{const x=$('cpp')._rows[i];cpAdd([x]);toast('Added '+short(x.id))};
window.ctCpPick=i=>{const x=$('cpp')._rows[i];const n=cy.getElementById(x.id);if(n.length){cy.nodes().unselect();n.select();cy.animate({center:{eles:n}},{duration:300})}else{cpAdd([x]);toast('Added '+short(x.id))}};
window.ctCpTop=()=>{const o=CPS[CPV];if(!o)return;const[rows]=cpRows(o);const n=cpAdd(rows.filter(x=>!inG(x.id)).slice(0,F.n));toast(n?'Added '+n+' counterparties':'Top '+F.n+' already in graph')};
// node tap: counterparties button + group card
cy.on('tap','node',e=>{const n=e.target;
 if(n.data('grp')){const k=kids(n);const ins=[];k.forEach(c=>ins.push(c.id()));const col=n.data('collapsed');
  $('det').innerHTML=`<div class="card glass"><h3>▣ ${esc(n.data('gname'))} ${tagH(n.data('gkind'))}</h3><div class="dim" style="font-size:12px">${ins.length} addresses grouped${n.id().startsWith('grp:dep:')?' · suggested (inferred) exchange deposits, not verified':n.id().startsWith('grp:clu:')?' · BTC common-input cluster':' · same verified entity'}</div>
  <div class="mono" style="margin-top:6px;font-size:11.5px;max-height:150px;overflow:auto">${ins.slice(0,60).map(a=>esc((cy.getElementById(a).data('info')||{}).name||a)+' <span class="dim">'+esc(short(a))+'</span>').join('<br>')}</div>
  <div class="row"><button class="btn sm pri" onclick="ctToggleGroup('${esc(n.id())}')">${col?'⤢ Split (E)':'▣ Collapse (E)'}</button></div></div>`;return}
 const id=n.id();if(id.startsWith('tx:'))return;const r=$('det').querySelector('.row');
 if(r)r.insertAdjacentHTML('beforeend',`<button class="btn sm" onclick="ctCpShow('${esc(id)}')">⇆ Counterparties</button>`);
 if(CPS[id]){CPV=id;cpRender()}});
cy.on('select unselect','node',()=>setTimeout(applyDir,0));
document.addEventListener('keydown',ev=>{if(ev.target.closest('input,textarea,select')||ev.ctrlKey||ev.metaKey||ev.altKey)return;
 if(ev.key==='e'||ev.key==='E'){const s=cy.nodes(':selected');if(s.length)toggleGroup(s[0])}});
})();

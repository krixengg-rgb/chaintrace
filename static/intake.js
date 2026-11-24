// ChainTrace v30: victim intake form. A guided form that builds a new case (victim payments, suspect addresses, 'victim' / 'suspect' labels,
// loss calculator prefilled) and a plain-English summary in a format suitable for reporting to Action Fraud / Report Fraud (copyable text + PDF made
// in this browser). Victim personal details (name, contact details, own-words account) never leave the browser: they are not sent to the server, not
// put into the case object (so not in case exports, reports, share links or evidence packs), and are kept only in this browser's localStorage for
// the case unless you clear them. Only public blockchain identifiers (tx hashes, addresses) are sent to the server, to validate and look them up.
(()=>{
const SCAMS=[['investment','Cryptocurrency investment / trading platform scam'],['romance','Romance scam / "pig butchering" (relationship + fake investment)'],['recovery','Fake fund-recovery service (scammed after an earlier loss)'],
 ['impersonation','Impersonation (bank, police, HMRC, exchange or company support)'],['phishing','Phishing / wallet drainer (seed phrase or approval stolen)'],['job','Job / task scam (paid to complete online "tasks")'],
 ['sextortion','Sextortion / blackmail'],['marketplace','Purchase / marketplace scam'],['other','Other']];
const CHANNELS=[['website','Website / platform'],['telegram','Telegram'],['whatsapp','WhatsApp'],['phone','Phone number'],['email','Email address'],['social','Social media profile'],['dating','Dating app profile'],['other','Other']];
const CHAINS=[['','Detect from the transaction ID'],['btc','Bitcoin'],['eth','Ethereum'],['tron','TRON'],['bsc','BNB Chain'],['sol','Solana'],['arb','Arbitrum'],['base','Base'],['polygon','Polygon'],['op','Optimism'],['xrp','XRP'],['ltc','Litecoin'],['doge','Dogecoin'],['bch','Bitcoin Cash']];
const css=document.createElement('style');css.textContent=`#inm{position:fixed;inset:0;z-index:80;display:none;background:rgba(5,8,18,.62);backdrop-filter:blur(3px);overflow:auto;padding:24px 10px}
#inm.on{display:block}#inm>.card{max-width:880px;margin:0 auto;padding:18px 18px 14px}#inm h4{margin:16px 0 6px;font-size:13px;letter-spacing:.02em;color:#cfd8ff}
#inm .g2{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px}#inm label{display:flex;flex-direction:column;gap:3px;font-size:11.5px;color:var(--mut);min-width:0}
#inm input,#inm select,#inm textarea{width:100%;box-sizing:border-box;min-width:0}#inm input:not([type=checkbox]):not([type=radio]),#inm select{background:rgba(0,0,0,.25);border:1px solid var(--line);border-radius:8px;padding:6px 8px;color:var(--txt);outline:0;color-scheme:dark}#inm select option{background:#141a2b;color:var(--txt)}#inm textarea{min-height:64px}
#inm .pd{border:1px solid rgba(123,216,143,.45);border-radius:12px;padding:10px 12px;background:rgba(123,216,143,.05)}
#inm .pay{border:1px solid var(--line);border-radius:12px;padding:10px;margin-top:8px;display:grid;grid-template-columns:120px 150px 1fr;gap:6px 10px;position:relative}
#inm .pay .wide{grid-column:1/-1}#inm .pay .x{position:absolute;right:8px;top:6px}#inm .ch{display:grid;grid-template-columns:170px 1fr 30px;gap:6px;margin-top:6px}
#inm .acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px;align-items:center}#inm .note{font-size:11.5px;color:#b8f0c4}#inm .warn{font-size:11.5px;color:#f6dd8a}
#inm #insum{min-height:260px;font-family:ui-monospace,Menlo,monospace;font-size:11.5px}#inm .res{margin-top:10px;font-size:12px}
@media (max-width:700px){#inm{padding:0}#inm>.card{border-radius:0;min-height:100%;padding:14px 12px}#inm .g2,#inm .pay{grid-template-columns:1fr}#inm .ch{grid-template-columns:1fr 30px}#inm .ch select{grid-column:1/-1}}`;
document.head.appendChild(css);
const opt=(a,v)=>a.map(([k,t])=>`<option value="${k}"${k===v?' selected':''}>${esc(t)}</option>`).join('');
const m=document.createElement('div');m.id='inm';m.innerHTML=`<div class="card glass" role="dialog" aria-modal="true" aria-labelledby="inh">
<h3 id="inh">🧾 Victim intake<span class="sp"></span><button class="btn sm" onclick="ctIntake(false)">✕</button></h3>
<div class="dim" style="font-size:12px">Answer what you can. This builds a new case from the payments and produces a plain-English summary in a format suitable for reporting to Action Fraud / Report Fraud.
It is not the official reporting form: report at <a href="https://www.reportfraud.police.uk/" target="_blank" rel="noopener">reportfraud.police.uk</a> or on 0300 123 2040 (England, Wales and Northern Ireland; in Scotland call Police Scotland on 101).</div>
<h4>1 · About the victim <span class="dim" style="font-weight:400">(stays in this browser)</span></h4>
<div class="pd"><div class="note">🔒 These details are never sent to the ChainTrace server and are not saved in the case, reports, share links or evidence packs. They appear only in the summary you copy or download.</div>
<div class="g2" style="margin-top:8px"><label>Full name<input id="in_name" autocomplete="off"></label><label>Phone<input id="in_phone" autocomplete="off"></label>
<label>Email<input id="in_email" autocomplete="off"></label><label>Postcode / address<input id="in_addr" autocomplete="off"></label></div>
<label style="margin-top:8px">What happened, in your own words<textarea id="in_story" placeholder="How you were contacted, what you were told, why you paid, when you realised…"></textarea></label>
<label style="flex-direction:row;align-items:center;gap:6px;margin-top:6px;color:var(--fg)"><input type="checkbox" id="in_incl" checked style="width:auto"> include these details in the summary</label></div>
<h4>2 · The incident</h4>
<div class="g2"><label>Type of scam<select id="in_type">${opt(SCAMS,'investment')}</select></label><label>Where did the contact start?<input id="in_where" placeholder="e.g. Instagram, a dating app, a cold call"></label>
<label>Date of first contact<input type="date" id="in_first"></label><label>Date you realised it was a scam<input type="date" id="in_found"></label></div>
<h4>3 · Payments you made</h4><div class="dim" style="font-size:11.5px">One row per crypto payment. With a transaction ID, ChainTrace fills in the amount, time and destination from the public blockchain.</div>
<div id="in_pays"></div><div class="acts" style="margin-top:6px"><button class="btn sm" onclick="ctInPay()">+ Add payment</button></div>
<h4>4 · The people or service you dealt with</h4>
<label>Suspect wallet addresses (one per line, e.g. addresses you were told to pay)<textarea id="in_sus" spellcheck="false"></textarea></label>
<div id="in_chs"></div><div class="acts" style="margin-top:6px"><button class="btn sm" onclick="ctInCh()">+ Add contact channel (website, Telegram, phone…)</button></div>
<div class="acts"><button class="btn pri" id="in_build" onclick="ctIntakeBuild()">📁 Build case &amp; summary</button><button class="btn" id="in_sumb" onclick="ctIntakeSummary()">📝 Summary only</button>
<span class="dim" id="in_msg" style="font-size:12px"></span></div>
<div id="in_out" style="display:none"><h4>Summary in a format suitable for reporting to Action Fraud / Report Fraud</h4>
<textarea id="insum" readonly></textarea><div class="acts"><button class="btn" onclick="ctIntakeCopy()">⧉ Copy text</button><button class="btn" id="in_pdf" onclick="ctIntakePDF()">⬇ PDF</button><button class="btn" onclick="ctIntakeTxt()">⬇ .txt</button>
<button class="btn" id="in_loss" onclick="ctIntake(false);ctLossOpen()" style="display:none">💷 Open loss calculator (prefilled)</button><button class="btn sm danger" onclick="ctIntakeForget()">Forget victim details</button></div>
<div class="warn" style="margin-top:6px">⚠ The PDF and text are made in this browser. Keep them safe: they contain personal details if you chose to include them.</div></div></div>`;
document.body.appendChild(m);m.addEventListener('click',e=>{if(e.target===m)ctIntake(false)});
const PDK=id=>'ct_intake_pd:'+id;const PDF_=['name','phone','email','addr','story'];
const today=()=>new Date().toISOString().slice(0,10);
window.ctInPay=(p={})=>{const d=document.createElement('div');d.className='pay';d.innerHTML=`<button class="btn sm x" title="Remove" onclick="this.parentElement.remove()">✕</button>
 <label>Date<input type="date" class="p_date" value="${esc(p.date||'')}"></label><label>Blockchain<select class="p_chain">${opt(CHAINS,p.chain||'')}</select></label><label>Paid from (your wallet address or exchange)<input class="p_from" value="${esc(p.from||'')}" placeholder="e.g. Coinbase account, or 0x…/bc1…"></label>
 <label class="wide">Transaction ID (hash)<input class="p_tx" spellcheck="false" value="${esc(p.tx||'')}" placeholder="0x… / 64 hex characters"></label>
 <label>Amount<input class="p_amt" inputmode="decimal" value="${esc(p.amount??'')}"></label><label>Asset<input class="p_asset" value="${esc(p.asset||'')}" placeholder="BTC, ETH, USDT…"></label><label>Sent to (if known)<input class="p_to" spellcheck="false" value="${esc(p.to||'')}"></label>`;
 $('in_pays').appendChild(d);return d};
window.ctInCh=(c={})=>{const d=document.createElement('div');d.className='ch';d.innerHTML=`<select class="c_type">${opt(CHANNELS,c.type||'website')}</select><input class="c_val" value="${esc(c.value||'')}" placeholder="URL, @handle, number or email used by the suspect"><button class="btn sm" title="Remove" onclick="this.parentElement.remove()">✕</button>`;$('in_chs').appendChild(d);return d};
function read(){const v=id=>($(id).value||'').trim();
 const pays=[...document.querySelectorAll('#in_pays .pay')].map(d=>({date:d.querySelector('.p_date').value,chain:d.querySelector('.p_chain').value,from:d.querySelector('.p_from').value.trim(),
  tx:d.querySelector('.p_tx').value.trim(),amount:d.querySelector('.p_amt').value.trim(),asset:d.querySelector('.p_asset').value.trim().toUpperCase(),to:d.querySelector('.p_to').value.trim()})).filter(p=>p.tx||p.amount||p.to);
 const chs=[...document.querySelectorAll('#in_chs .ch')].map(d=>({type:d.querySelector('.c_type').value,value:d.querySelector('.c_val').value.trim()})).filter(c=>c.value);
 return{pd:{name:v('in_name'),phone:v('in_phone'),email:v('in_email'),addr:v('in_addr'),story:v('in_story'),include:$('in_incl').checked},
  inc:{scam_type:$('in_type').value,where:v('in_where'),first_contact:$('in_first').value,discovered:$('in_found').value,payments:pays,suspects:v('in_sus').split(/[\s,;]+/).filter(Boolean),channels:chs}}}
function fill(inc,pd){if(pd){for(const k of PDF_)$('in_'+k).value=pd[k]||'';$('in_incl').checked=pd.include!==false}
 if(inc){$('in_type').value=inc.scam_type||'investment';$('in_where').value=inc.where||'';$('in_first').value=inc.first_contact||'';$('in_found').value=inc.discovered||'';
  $('in_pays').innerHTML='';(inc.payments||[]).forEach(p=>ctInPay(p));$('in_sus').value=(inc.suspects||[]).join('\n');$('in_chs').innerHTML='';(inc.channels||[]).forEach(c=>ctInCh(c))}
 if(!document.querySelector('#in_pays .pay'))ctInPay();}
window.ctIntake=on=>{on=on!==false;m.classList.toggle('on',on);if(on){let pd=null;try{pd=curCase?JSON.parse(localStorage.getItem(PDK(curCase.id))||'null'):null}catch(e){}
 fill(curCase&&curCase.intake?curCase.intake:null,pd);if(LASTSUM){$('insum').value=LASTSUM;$('in_out').style.display=''}}};
let LASTSUM='',VER={};
const n6=v=>(+v).toLocaleString('en-GB',{maximumFractionDigits:8});
const uk=t=>t?new Date(t*1000).toLocaleString('en-GB',{timeZone:'Europe/London',dateStyle:'long',timeStyle:'short'})+' (UK time)':'';
const utc=t=>t?new Date(t*1000).toISOString().replace('T',' ').slice(0,16)+' UTC':'';
const dlong=s=>s?new Date(s+'T12:00:00Z').toLocaleDateString('en-GB',{day:'numeric',month:'long',year:'numeric'}):'';
const cnm=c=>(CHAINS.find(x=>x[0]===c)||[0,c||'unknown blockchain'])[1];
const txurl=(c,h)=>c&&CH[c]&&CH[c].tx?CH[c].tx+h:'';
function summary(inc,pd){const L=[];const T=SCAMS.find(s=>s[0]===inc.scam_type)?.[1]||inc.scam_type;
 L.push('SUMMARY IN A FORMAT SUITABLE FOR REPORTING TO ACTION FRAUD / REPORT FRAUD');
 L.push(`Prepared on ${new Date().toLocaleDateString('en-GB',{day:'numeric',month:'long',year:'numeric'})} with ChainTrace (a blockchain tracing tool). This is not an official Action Fraud or Report Fraud form, and ChainTrace is not connected to either service. Action Fraud was replaced by Report Fraud on 4 December 2025: report online at reportfraud.police.uk or call 0300 123 2040 (England, Wales and Northern Ireland). In Scotland, call Police Scotland on 101.`);
 L.push('');
 if(pd.include&&(pd.name||pd.phone||pd.email||pd.addr)){L.push('1. ABOUT ME');if(pd.name)L.push('Name: '+pd.name);if(pd.phone)L.push('Phone: '+pd.phone);if(pd.email)L.push('Email: '+pd.email);if(pd.addr)L.push('Address / postcode: '+pd.addr);L.push('')}
 else{L.push('1. ABOUT ME');L.push('(Personal details left out of this copy. Add them when you report.)');L.push('')}
 L.push('2. WHAT HAPPENED');
 let s=`I was the victim of a ${T.charAt(0).toLowerCase()+T.slice(1)}.`;if(inc.first_contact)s+=` The first contact was on ${dlong(inc.first_contact)}${inc.where?` via ${inc.where}`:''}.`;else if(inc.where)s+=` The contact started via ${inc.where}.`;
 if(inc.discovered)s+=` I realised it was a scam on ${dlong(inc.discovered)}.`;L.push(s);
 if(pd.include&&pd.story){L.push('In my own words: '+pd.story)}L.push('');
 const pays=inc.payments||[];L.push(`3. PAYMENTS I MADE (${pays.length})`);const tot={};
 pays.forEach((p,i)=>{const v=VER[p.tx]||{};const amt=v.amount??(p.amount?+p.amount:null);const asset=v.unit||p.asset||'';const chain=v.chain||p.chain;const to=v.to||p.to;
  if(amt!=null&&asset)tot[asset]=(tot[asset]||0)+amt;
  let t=`Payment ${i+1}: `+(v.time?`On ${uk(v.time)} [${utc(v.time)}]`:(p.date?`On ${dlong(p.date)}`:'On a date not given'))+`, I sent ${amt!=null?n6(amt):'an amount not given'} ${asset} on ${cnm(chain)}`;
  if(p.from)t+=` from ${p.from}`;if(to)t+=` to the address ${to}`;t+='.';if(p.tx)t+=` Transaction ID: ${p.tx}.`;
  if(v.ok)t+=` Confirmed on the public blockchain${txurl(chain,p.tx)?' ('+txurl(chain,p.tx)+')':''}.`;else if(p.tx)t+=' (As entered; ChainTrace could not confirm it on the blockchain.)';else t+=' (No transaction ID given.)';
  if(v.note)t+=' Note: '+v.note;L.push(t)});
 if(Object.keys(tot).length)L.push('Total sent: '+Object.entries(tot).map(([a,v])=>n6(v)+' '+a).join(', ')+'.');
 const LL=window.CT_LOSS_LAST;if(LL&&LL.total_gbp_then!=null)L.push(`Value on the day of each payment: about £${(+LL.total_gbp_then).toLocaleString('en-GB',{maximumFractionDigits:2})} (ChainTrace loss calculator; daily prices, ECB GBP rate).`);
 L.push('');L.push('4. WHO I DEALT WITH');
 if((inc.suspects||[]).length)L.push('Wallet addresses I was told to pay or that received my money: '+inc.suspects.join(', ')+'.');
 (inc.channels||[]).forEach(c=>L.push(`${(CHANNELS.find(x=>x[0]===c.type)||[0,c.type])[1]}: ${c.value}`));
 if(!(inc.suspects||[]).length&&!(inc.channels||[]).length)L.push('No suspect details given.');
 L.push('');L.push('5. NOTES');
 L.push('Times from the blockchain are shown in UK time with UTC in brackets. Amounts with a transaction ID come from the public blockchain; other amounts are as I entered them.');
 L.push('A ChainTrace case has been created from these payments so that an investigator can trace where the money went. Any tracing results are leads for the police, not proof.');
 return L.join('\n')}
async function verify(inc){VER={};const txs=(inc.payments||[]).filter(p=>p.tx);
 for(const p of txs){try{const d=await api(p.tx);const c=d.chain;const tid='tx:'+d.tx;const ins=new Set(d.edges.filter(e=>e.target===tid).map(e=>e.source));
   const outs=d.edges.filter(e=>e.amount&&e.target!==tid&&!ins.has(e.target));
   const fromA=p.from&&/^(0x|bc1|[13]|T|r)/.test(p.from)?p.from:null;
   const leg=outs.find(e=>p.to&&(e.target||'').toLowerCase().endsWith(p.to.toLowerCase()))||outs.filter(e=>!fromA||(e.target||'').toLowerCase()!==fromA.toLowerCase()).sort((a,b)=>(b.usd||0)-(a.usd||0))[0];
   const t=typeof d.time==='number'?d.time:(d.time?Date.parse(d.time)/1000:null);
   VER[p.tx]={ok:true,chain:c,time:t,amount:leg?+leg.amount:null,unit:leg?String(leg.unit||'').replace('⇄',''):null,to:leg?bareId(leg.target):null,d,
    note:p.amount&&leg&&Math.abs(+p.amount-+leg.amount)>1e-9*Math.max(1,+leg.amount)?`the amount entered (${p.amount}) differs from the blockchain (${n6(leg.amount)})`:''}}
  catch(e){VER[p.tx]={ok:false,error:e.message}}}}
function persistPD(pd){if(!curCase)return;try{localStorage.setItem(PDK(curCase.id),JSON.stringify(pd))}catch(e){}}
window.ctIntakeSummary=async()=>{const{inc,pd}=read();$('in_msg').textContent='Checking transaction IDs on the blockchain…';await verify(inc);
 LASTSUM=summary(inc,pd);$('insum').value=LASTSUM;$('in_out').style.display='';$('in_msg').textContent='Summary ready.';window.CT_INTAKE_SUMMARY=LASTSUM;return LASTSUM};
window.ctIntakeBuild=async()=>{const{inc,pd}=read();if(!inc.payments.length&&!inc.suspects.length)return toast('Add at least one payment or suspect address');
 const b=$('in_build');b.disabled=true;$('in_msg').textContent='Creating the case…';
 try{const T=SCAMS.find(s=>s[0]===inc.scam_type)?.[1].split(/[ /(]/)[0]||'Scam';
  cy.elements().remove();$('side').innerHTML='';$('det').innerHTML='';$('empty').style.display='none';cur=null;lastTrace=null;mode='lookup';
  curCase=blankCase(`Intake · ${T} · ${inc.first_contact||today()}`);curCase.intake=inc;await Store.put(curCase);chip();caseCard();persistPD(pd);
  if(window.CT_LOSS)Object.assign(window.CT_LOSS,{victims:[],victim_txs:[],suspect:'',result:null});
  $('in_msg').textContent='Looking up the payments on the blockchain…';await verify(inc);let n=0;
  for(const p of inc.payments){const v=VER[p.tx];if(!v||!v.ok)continue;add(v.d,'tx:'+v.d.tx);n++;
   if(!window.CT_LOSS.victim_txs.includes(v.d.tx))ctLossMark(v.d.tx,'t');
   const tid='tx:'+v.d.tx;const ins=v.d.edges.filter(e=>e.target===tid).map(e=>e.source);const vic=(p.from&&cy.getElementById(p.from).length?[p.from]:ins);
   for(const a of vic){if(!curCase.labels[a])curCase.labels[a]={name:'victim',kind:null,at:Date.now(),source:'intake'};if(!window.CT_LOSS.victims.includes(a))ctLossMark(a,'v')}}
  const sus=[];for(const s of inc.suspects){let id=s;const hit=cy.nodes().filter(x=>x.id().toLowerCase()===s.toLowerCase()||x.id().toLowerCase().endsWith(':'+s.toLowerCase()));
   if(hit.length)id=hit[0].id();else{try{const d=await api(s);add(d,d.address);id=d.address}catch(e){continue}}sus.push(id);curCase.labels[id]={name:'suspect',kind:null,at:Date.now(),source:'intake'}}
  if(sus[0])ctLossMark(sus[0],'s');
  applyCaseDecor();relayout&&relayout();cy.fit(undefined,40);await persist();caseCard();
  if(typeof ctAudit==='function')try{ctAudit('intake.case_built',{payments:inc.payments.length,verified:n,suspects:sus.length,channels:inc.channels.length})}catch(e){}
  LASTSUM=summary(inc,pd);$('insum').value=LASTSUM;$('in_out').style.display='';$('in_loss').style.display='';window.CT_INTAKE_SUMMARY=LASTSUM;
  window.CT_INTAKE_DONE={verified:n,suspects:sus.length,payments:inc.payments.length,case:curCase.id};
  $('in_msg').textContent=`✓ Case “${curCase.name}” created: ${n} payment(s) confirmed on-chain, ${sus.length} suspect address(es) labelled; loss calculator prefilled.`;toast('Case created from the intake')}
 catch(e){$('in_msg').textContent='✗ '+e.message}finally{b.disabled=false}};
window.ctIntakeCopy=async()=>{try{await navigator.clipboard.writeText($('insum').value);toast('Summary copied')}catch(e){$('insum').select();document.execCommand('copy');toast('Summary copied')}};
const fname=ext=>'summary-for-report-fraud-'+today()+'.'+ext;
window.ctIntakeTxt=()=>dl(fname('txt'),new Blob([$('insum').value],{type:'text/plain'}));
window.ctIntakePDF=()=>{const txt=$('insum').value;if(!txt)return;const P=new MiniPDF({footer:'Prepared with ChainTrace - not an official Action Fraud / Report Fraud form',header:'Summary in a format suitable for reporting to Action Fraud / Report Fraud'});
 const lines=txt.split('\n');P.h(lines[0].charAt(0)+lines[0].slice(1).toLowerCase(),14);P.box(lines[1]);
 for(const l of lines.slice(2)){if(/^\d\. [A-Z ]+/.test(l)){P.rule();P.h(l.charAt(0)+l.slice(1).toLowerCase().replace(/^(\d\. )(.)/,(a,b,c)=>b+c.toUpperCase()),11.5)}
  else if(/^(Name|Phone|Email|Address \/ postcode): /.test(l)){const[k,...v]=l.split(': ');P.kv(k,v.join(': '))}
  else P.text(l,{sz:9.8})}
 const bl=P.blob();window.CT_INTAKE_PDF_SIZE=bl.size;dl(fname('pdf'),bl);if(typeof ctAudit==='function')try{ctAudit('intake.summary_pdf',{bytes:bl.size})}catch(e){}};
window.ctIntakeForget=()=>{if(curCase)localStorage.removeItem(PDK(curCase.id));for(const k of PDF_)$('in_'+k).value='';LASTSUM='';$('insum').value='';$('in_out').style.display='none';toast('Victim details removed from this browser')};
const anchor=$('lossbtn')||$('rptbtn')||$('savebtn');if(anchor){const b=document.createElement('button');b.className='btn';b.id='intakebtn';b.title='Victim intake form → new case + summary for Report Fraud';b.textContent='🧾 Intake';b.onclick=()=>ctIntake(true);anchor.before(b)}
const nav=(performance.getEntriesByType('navigation')[0]||{}).name||location.href;if(new URL(nav).searchParams.get('intake')==='1')setTimeout(()=>ctIntake(true),300);
})();

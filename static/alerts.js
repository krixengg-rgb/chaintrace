// ChainTrace: server-side email alerts panel (Watchlist drawer › ✉ Email). Status, send test email, per-address mute,
// and "copy watchlist for server" (sealed with the server's ALERTS_KEY, pasted into the Render env var ALERTS_WATCHLIST).
(()=>{
const css=document.createElement('style');css.textContent=`.alc{border:1px solid var(--line);border-radius:12px;padding:10px;margin:6px 0;font-size:12.5px;background:rgba(0,0,0,.15)}
.alc h4{margin:0 0 6px;font-size:13px}.alc .ok{color:#2ee59d}.alc .bad{color:#ff8a8a}.alc .ln{margin:4px 0;line-height:1.5}.alc .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:4px 0}
.alc .it{display:flex;gap:8px;align-items:center;padding:6px 0;border-top:1px solid var(--line)}.alc .it .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.alc textarea{width:100%;height:70px;font-family:var(--mono);font-size:11px;background:rgba(0,0,0,.3);color:var(--txt);border:1px solid var(--line);border-radius:8px}
.alc code{font-family:var(--mono);font-size:11px}`;document.head.appendChild(css);
let ON=false;
function inject(){const tabs=document.querySelector('#watchd .wtabs, .wtabs');if(!tabs||document.getElementById('wt-email'))return!!tabs;
 const b=document.createElement('button');b.id='wt-email';b.textContent='✉ Email';b.onclick=()=>{ON=true;paint()};tabs.appendChild(b);
 tabs.querySelectorAll('button:not(#wt-email)').forEach(x=>x.addEventListener('click',()=>{ON=false;b.classList.remove('on')}));return true}
const fmt=t=>t?new Date(t*1000).toLocaleString('en-GB',{timeZone:'Europe/London',dateStyle:'short',timeStyle:'short'})+' UK':'never';
async function paint(){if(!ON)return;const body=document.getElementById('wbody');if(!body)return;
 document.querySelectorAll('.wtabs button').forEach(x=>x.classList.toggle('on',x.id==='wt-email'));
 body.innerHTML='<div class="alc">Loading email-alert status…</div>';let j;
 try{const r=await fetch('/api/alerts/status');j=await r.json();if(!r.ok)throw new Error(j.detail||r.status)}catch(e){body.innerHTML=`<div class="alc bad">Status unavailable: ${esc(e.message)}</div>`;return}
 window.CT_ALERTS=j;const c=j.config;const ready=!c.missing.length;
 body.innerHTML=`<div class="alc" id="alc-status"><h4>✉ Server email alerts ${ready?'<span class="ok">● ready</span>':'<span class="bad">● setup incomplete</span>'}</h4>
  <div>Checked on a schedule by the server (no browser needed). New activity on watched addresses is emailed with amount, asset, counterparty, label, sanctions/risk flags, UK time + UTC and a link back here.</div>
  <div class="ln">Sender: <b>${esc(c.sender||'none')}</b> · to <b>${c.to.length?esc(c.to.join(', ')):'<span class="bad">not set</span>'}</b></div>${c.from?`<div class="ln dim" style="word-break:break-all">From: ${esc(c.from)}</div>`:''}
  <div class="ln">Last server run: <b>${fmt(j.last_run)}</b>${(j.runs||[]).length?`<br>${j.runs.at(-1).checked} checked, ${j.runs.at(-1).alerts} alert(s)${j.runs.at(-1).emailed?' emailed':''}`:''}</div>
  ${c.missing.length?`<div class="ln bad">Missing on the server: ${c.missing.map(esc).join(', ')}</div>`:''}${(c.notes||[]).map(n=>`<div class="ln" style="color:#f6dd8a">ⓘ ${esc(n)}</div>`).join('')}
  ${j.watchlist_error?`<div class="ln bad">${esc(j.watchlist_error)}</div>`:''}
  <div class="row"><button class="btn sm pri" id="al-test" onclick="ctAlertTest()" ${c.sender&&c.to.length?'':'disabled'}>Send test email</button><span id="al-msg" class="dim"></span></div></div>
 <div class="alc" id="alc-items"><h4>Server watchlist (${j.items.length})</h4>${j.items.length?j.items.map(it=>`<div class="it" data-id="${esc(it.id)}"><span class="nm" title="${esc(it.address)}">${esc(it.name||short(it.address))} <span class="dim">${esc((it.chain||'').toUpperCase())}${it.ref?' · '+esc(it.ref):''} · checked ${fmt(it.last_checked)}</span></span>
   <button class="btn sm al-mute" ${it.muted_in_env?'disabled title="muted in ALERTS_WATCHLIST"':''} onclick="ctAlertMute('${esc(it.id)}',${!it.muted})">${it.muted?'🔕 Muted':'🔔 Alerting'}</button></div>`).join(''):'<div class="dim">No addresses on the server yet: use “Copy watchlist for server” below.</div>'}</div>
 <div class="alc"><h4>Copy watchlist for server</h4><div>Seals this browser's ${typeof ctWItems==='function'?ctWItems().length:0} watched address(es) with the server key. Paste the value into the Render environment variable <code>ALERTS_WATCHLIST</code> (Dashboard › chaintrace › Environment), then save. Case data never goes into the code repository.</div>
  <div class="row"><button class="btn sm" onclick="ctAlertSeal()">Create sealed value</button><span id="al-smsg" class="dim"></span></div><textarea id="al-seal" readonly placeholder="enc:…" style="display:none"></textarea></div>`}
window.ctAlertTest=async()=>{const m=document.getElementById('al-msg');m.textContent='sending…';
 try{const r=await fetch('/api/alerts/test',{method:'POST'});const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);m.textContent=`✓ test email sent via ${j.sender} to ${j.to.join(', ')}`;window.CT_ALERT_TEST=j}
 catch(e){m.textContent='✗ '+e.message;window.CT_ALERT_TEST={error:e.message}}};
window.ctAlertMute=async(id,muted)=>{try{const r=await fetch('/api/alerts/mute',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,muted})});const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);toast(muted?'Muted: no emails for this address':'Alerts on for this address');paint()}catch(e){toast('Mute failed: '+e.message)}};
window.ctAlertSeal=async()=>{const m=document.getElementById('al-smsg'),t=document.getElementById('al-seal');const items=typeof ctWItems==='function'?ctWItems():[];if(!items.length)return toast('Watch some addresses first');
 try{const r=await fetch('/api/alerts/seal',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items})});const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);
  t.style.display='';t.value=j.value;t.select();try{await navigator.clipboard.writeText(j.value);m.textContent=`✓ ${j.items} address(es) sealed and copied`}catch(e){m.textContent=`✓ ${j.items} address(es) sealed: copy the value below`}}
 catch(e){m.textContent='✗ '+e.message}};
window.ctAlertsTab=()=>{if(inject()){ON=true;paint()}};
const iv=setInterval(()=>{if(inject())clearInterval(iv)},500);
})();

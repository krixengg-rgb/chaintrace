// ChainTrace v28: shareable read-only case links. The snapshot you choose is encrypted into the link itself (URL fragment);
// nothing is stored on the server. Case notes and private labels are left out unless you tick them.
(()=>{
const css=document.createElement('style');css.textContent=`#shm{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;align-items:center;justify-content:center;z-index:9999}#shm.on{display:flex}
#shm .box{width:min(560px,94vw);max-height:90vh;overflow:auto;padding:16px}#shm label{display:flex;gap:6px;align-items:center;font-size:13px;margin:6px 0}
#shm .pv{font-size:12px;border:1px solid var(--line);border-radius:9px;padding:8px;margin-top:8px}#shm .url{width:100%;font-family:monospace;font-size:11px;height:70px;margin-top:6px;background:#0d1220;color:inherit;border:1px solid var(--line);border-radius:8px}
#shm select{background:#161b2a;color:inherit;border:1px solid var(--line);border-radius:6px;padding:2px 6px}#shm .warn2{font-size:11.5px;color:#ffcf8a;margin-top:6px}`;document.head.appendChild(css);
document.body.insertAdjacentHTML('beforeend',`<div id="shm"><div class="card glass box"><h3>🔗 Share a read-only snapshot</h3>
 <div class="dim" style="font-size:12px">Creates a signed, expiring link to a snapshot of the current graph. The snapshot is encrypted inside the link (after the #), so the server keeps no copy. Anyone with the link can view it until it expires; they cannot edit or run lookups.</div>
 <label>Expires after <select id="shttl"><option value="1h">1 hour</option><option value="24h">24 hours</option><option value="7d" selected>7 days</option><option value="30d">30 days</option></select></label>
 <label><input type="checkbox" id="shnotes"> Include case notes (off by default)</label>
 <label><input type="checkbox" id="shlabels"> Include my private labels (off by default)</label>
 <div class="row" style="gap:6px;margin-top:6px"><button class="btn sm" id="shprev" onclick="ctSharePreview()">Preview</button><button class="btn sm primary" id="shgo" onclick="ctShareCreate()">Create link</button><span style="flex:1"></span><button class="btn sm" onclick="ctShareClose()">Close</button></div>
 <div id="shpv"></div><div id="shout"></div></div></div>`);
const body=()=>{const p=ctReportPayload({noise:false,img:false});return{nodes:p.nodes,edges:p.edges,case:p.case,meta:p.meta,log:p.log}};
const qs=pv=>`ttl=${$('shttl').value}&notes=${$('shnotes').checked}&labels=${$('shlabels').checked}${pv?'&preview=true':''}`;
const dt=t=>new Date(t*1000).toLocaleString('en-GB',{timeZone:'Europe/London'})+' UK · '+new Date(t*1000).toISOString().slice(0,16).replace('T',' ')+' UTC';
const pvH=j=>`<div class="pv" id="shpvbox"><b>Snapshot preview</b><div>${j.nodes} nodes · ${j.edges} edges · ${(j.bytes/1024).toFixed(1)} KB compressed</div>
 <div>Included: ${j.included.map(esc).join(', ')}</div><div>Left out: ${j.excluded.length?j.excluded.map(esc).join(', '):'nothing else'}</div>
 <div>Expires: ${dt(j.expires)}</div><div class="mono" style="font-size:10.5px;word-break:break-all">Audit SHA-256: ${esc(j.audit_sha256)}</div></div>`;
window.ctShareOpen=()=>{$('shpv').innerHTML='';$('shout').innerHTML='';$('shm').classList.add('on')};
window.ctShareClose=()=>$('shm').classList.remove('on');
async function call(pv){const r=await fetch('/api/share?'+qs(pv),{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body())});const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);return j}
window.ctSharePreview=async()=>{try{const j=await call(true);$('shpv').innerHTML=pvH(j)}catch(e){$('shpv').innerHTML=`<div class="warnbox">${esc(e.message)}</div>`}};
window.ctShareCreate=async()=>{const b=$('shgo');b.disabled=true;try{const j=await call(false);window.CT_LAST_SHARE=j;$('shpv').innerHTML=pvH(j);
  $('shout').innerHTML=`<textarea class="url" id="shurl" readonly>${esc(j.url)}</textarea><div class="row" style="gap:6px;margin-top:6px"><button class="btn sm" onclick="navigator.clipboard.writeText($('shurl').value).then(()=>toast('Link copied'))">Copy link</button><a class="btn sm" id="shopen" target="_blank" rel="noopener" href="${esc(j.url)}">Open viewer</a></div>
  <div class="warn2">Treat the link like the evidence itself: anyone holding it can read the snapshot until ${esc(dt(j.expires))}. Links cannot be revoked one by one; changing SHARE_KEY revokes all of them.</div>`;
  if(typeof ctAudit==='function')try{ctAudit('share.created',{audit_sha256:j.audit_sha256,expires:j.expires,nodes:j.nodes,edges:j.edges,notes:$('shnotes').checked,labels:$('shlabels').checked})}catch(e){}}
 catch(e){$('shout').innerHTML=`<div class="warnbox">${esc(e.message)}</div>`}finally{b.disabled=false}};
const rb=[...document.querySelectorAll('button')].find(x=>/Report/.test(x.textContent)&&x.closest('header,.top,.bar,div'));
if(rb&&!$('sharebtn'))rb.insertAdjacentHTML('beforebegin',`<button class="btn" id="sharebtn" title="Share a read-only snapshot" onclick="ctShareOpen()">🔗 Share</button> `);
})();

// ChainTrace mini PDF writer (v30): text-only A4 PDFs built entirely in the browser (Helvetica / Helvetica-Bold / Courier, WinAnsi).
// Used for documents that must never touch the server (victim intake summary). No dependencies.
(()=>{
const W={32:278,33:278,34:355,35:556,36:556,37:889,38:667,39:191,40:333,41:333,42:389,43:584,44:278,45:333,46:278,47:278,58:278,59:278,60:584,61:584,62:584,63:556,64:1015,
65:667,66:667,67:722,68:722,69:667,70:611,71:778,72:722,73:278,74:500,75:667,76:556,77:833,78:722,79:778,80:667,81:778,82:722,83:667,84:611,85:722,86:667,87:944,88:667,89:667,90:611,
91:278,92:278,93:278,94:469,95:556,96:333,97:556,98:556,99:500,100:556,101:556,102:278,103:556,104:556,105:222,106:222,107:500,108:222,109:833,110:556,111:556,112:556,113:556,
114:333,115:500,116:278,117:556,118:500,119:722,120:500,121:500,122:500,123:334,124:260,125:334,126:584,163:556,183:278};
for(let i=48;i<58;i++)W[i]=556;
const MAP={'\u2192':'->','\u2190':'<-','\u2013':'-','\u2014':'-','\u2018':"'",'\u2019':"'",'\u201c':'"','\u201d':'"','\u2022':'-','\u2026':'...','\u00a0':' ','\u2265':'>=','\u2264':'<=','\u2713':'v','\u26a0':'!','\u21c4':'<->'};
const clean=s=>String(s??'').replace(/[\u2192\u2190\u2013\u2014\u2018\u2019\u201c\u201d\u2022\u2026\u00a0\u2265\u2264\u2713\u26a0\u21c4]/g,c=>MAP[c]).replace(/[^\x09\x0a\x0d\x20-\x7e\xa0-\xff]/g,'?');
const wid=(s,f,sz)=>{if(f==='F3')return s.length*600*sz/1000;let w=0;for(const ch of s)w+=(W[ch.charCodeAt(0)]||556)*(f==='F2'?1.06:1);return w*sz/1000};
const esc=s=>s.replace(/\\/g,'\\\\').replace(/\(/g,'\\(').replace(/\)/g,'\\)');
function wrap(text,f,sz,maxw){const out=[];for(const para of clean(text).split('\n')){if(!para.trim()){out.push('');continue}
 let line='';for(const word of para.split(/ +/)){const cand=line?line+' '+word:word;if(wid(cand,f,sz)<=maxw){line=cand;continue}
  if(line)out.push(line);if(wid(word,f,sz)<=maxw){line=word;continue}
  let part='';for(const ch of word){if(wid(part+ch,f,sz)>maxw){out.push(part);part=''}part+=ch}line=part}
 out.push(line)}return out}
window.MiniPDF=class{constructor(o={}){this.pages=[];this.M=o.margin||48;this.PW=595.28;this.PH=841.89;this.footer=o.footer||'';this.header=o.header||'';this.newPage()}
 newPage(){this.cur=[];this.pages.push(this.cur);this.y=this.PH-this.M-(this.header?14:0)}
 need(h){if(this.y-h<this.M+18)this.newPage()}
 text(s,{f='F1',sz=10,color=[0,0,0],indent=0,gap=3,lh=1.32}={}){const lines=wrap(s,f,sz,this.PW-2*this.M-indent);
  for(const l of lines){this.need(sz*lh);this.y-=sz*lh;if(l)this.cur.push(`BT /${f} ${sz} Tf ${color.map(c=>(c/255).toFixed(3)).join(' ')} rg ${(this.M+indent).toFixed(2)} ${this.y.toFixed(2)} Td (${esc(l)}) Tj ET`)}
  this.y-=gap;return this}
 h(s,sz=13){this.need(sz*2.4);this.y-=6;return this.text(s,{f:'F2',sz,color:[22,38,74],gap:4})}
 rule(){this.need(8);this.y-=4;this.cur.push(`0.75 0.78 0.84 RG 0.6 w ${this.M} ${this.y.toFixed(2)} m ${(this.PW-this.M).toFixed(2)} ${this.y.toFixed(2)} l S`);this.y-=4;return this}
 box(s,{color=[165,90,0],sz=9.5}={}){const lines=wrap(s,'F2',sz,this.PW-2*this.M-16);const h=lines.length*sz*1.32+12;this.need(h+4);
  this.cur.push(`${color.map(c=>(c/255).toFixed(3)).join(' ')} RG 1.2 w ${this.M} ${(this.y-h).toFixed(2)} ${(this.PW-2*this.M).toFixed(2)} ${h.toFixed(2)} re S`);
  let y=this.y-6;for(const l of lines){y-=sz*1.32;this.cur.push(`BT /F2 ${sz} Tf ${color.map(c=>(c/255).toFixed(3)).join(' ')} rg ${this.M+8} ${y.toFixed(2)} Td (${esc(l)}) Tj ET`)}this.y-=h+6;return this}
 kv(k,v,{kw=150,sz=9.5,mono=false}={}){const lines=wrap(v,mono?'F3':'F1',mono?sz-1:sz,this.PW-2*this.M-kw);this.need(sz*1.32);
  this.y-=sz*1.32;this.cur.push(`BT /F2 ${sz} Tf 0.36 0.39 0.45 rg ${this.M} ${this.y.toFixed(2)} Td (${esc(clean(k))}) Tj ET`);
  lines.forEach((l,i)=>{if(i){this.need(sz*1.32);this.y-=sz*1.32}this.cur.push(`BT /${mono?'F3':'F1'} ${mono?sz-1:sz} Tf 0 0 0 rg ${this.M+kw} ${this.y.toFixed(2)} Td (${esc(l)}) Tj ET`)});this.y-=2;return this}
 bytes(){const objs=[];const add=s=>{objs.push(s);return objs.length};
  const cat=add(null),pages=add(null),f1=add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'),f2=add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>'),
   f3=add('<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>');const kids=[];const n=this.pages.length;
  this.pages.forEach((ops,i)=>{const extra=[];const ft=clean(this.footer+(this.footer?'  -  ':'')+`page ${i+1} of ${n}`);extra.push(`BT /F1 7.5 Tf 0.4 0.4 0.4 rg ${this.M} 24 Td (${esc(ft)}) Tj ET`);
   if(this.header)extra.push(`BT /F2 8 Tf 0.65 0.35 0 rg ${this.M} ${(this.PH-this.M+6).toFixed(2)} Td (${esc(clean(this.header))}) Tj ET`);
   const body=ops.concat(extra).join('\n');const c=add(`<< /Length ${body.length} >>\nstream\n${body}\nendstream`);
   kids.push(add(`<< /Type /Page /Parent ${pages} 0 R /MediaBox [0 0 ${this.PW} ${this.PH}] /Resources << /Font << /F1 ${f1} 0 R /F2 ${f2} 0 R /F3 ${f3} 0 R >> >> /Contents ${c} 0 R >>`))});
  objs[cat-1]=`<< /Type /Catalog /Pages ${pages} 0 R >>`;objs[pages-1]=`<< /Type /Pages /Kids [${kids.map(k=>k+' 0 R').join(' ')}] /Count ${kids.length} >>`;
  let out='%PDF-1.4\n%\xe2\xe3\xcf\xd3\n';const off=[];objs.forEach((o,i)=>{off.push(out.length);out+=`${i+1} 0 obj\n${o}\nendobj\n`});
  const x=out.length;out+=`xref\n0 ${objs.length+1}\n0000000000 65535 f \n`+off.map(o=>String(o).padStart(10,'0')+' 00000 n \n').join('')+`trailer\n<< /Size ${objs.length+1} /Root ${cat} 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  const b=new Uint8Array(out.length);for(let i=0;i<out.length;i++)b[i]=out.charCodeAt(i)&255;return b}
 blob(){return new Blob([this.bytes()],{type:'application/pdf'})}};
})();

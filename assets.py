"""ChainTrace v34 front-end delivery for slow free-tier hosts.
At import (a few ms): read static/index.html, join the app's own scripts (in page order) into one bundle (minify with rjsmin only if CHAINTRACE_MINIFY=1)
when installed, pre-compress index, bundle and the vendored cytoscape with brotli (if installed) and gzip, and name the bundles by
content hash so they can be cached for a year ('immutable'); index.html itself is always revalidated (no-cache).
CHAINTRACE_BUNDLE=0 serves the original files (debugging). Files under /static keep working unchanged (share viewer, tests)."""
import gzip, hashlib, os, re
H = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(H, "static")
try: import rjsmin
except Exception: rjsmin = None
try: import brotli
except Exception: brotli = None
ON = os.environ.get("CHAINTRACE_BUNDLE", "1") != "0"
import sys
BUILD = __name__ == "__main__"
TAG = re.compile(r'<script src="/static/([A-Za-z0-9_.-]+\.js)"></script>')
ASSETS = {}   # name -> {"raw", "gz", "br", "type", "etag"}
INDEX = {}
STATS = {}
CACHE = os.path.join(S, "b")   # build-time cache (gitignored): render.yaml runs `python3 assets.py` so a cold start only reads files
def _pack(name, data, ctype):
    h = hashlib.sha256(data).hexdigest()[:12]; gz = br = None
    fg, fb = os.path.join(CACHE, h + ".gz"), os.path.join(CACHE, h + ".br")
    try:
        gz = open(fg, "rb").read()
        if brotli and os.path.exists(fb): br = open(fb, "rb").read()
    except OSError: pass
    if gz is None or (brotli and br is None):
        gz = gzip.compress(data, 9 if BUILD else 6, mtime=0); br = brotli.compress(data, quality=11 if BUILD else 5) if brotli else None
        try:
            os.makedirs(CACHE, exist_ok=True); open(fg, "wb").write(gz)
            if br: open(fb, "wb").write(br)
        except OSError: pass
    a = {"raw": data, "gz": gz, "br": br, "type": ctype, "etag": f'"{h}"', "hash": h}
    ASSETS[name] = a; return a
def build():
    html = open(os.path.join(S, "index.html"), encoding="utf-8").read()
    if not ON:
        INDEX.update(_pack("index.html", html.encode(), "text/html; charset=utf-8")); return
    names = TAG.findall(html)
    vendor = [n for n in names if n == "cytoscape.min.js"]; app = [n for n in names if n not in vendor]
    src = "\n;\n".join(f"/* {n} */\n" + open(os.path.join(S, n), encoding="utf-8").read() for n in app)
    raw_len = len(src.encode())
    # Minifying is OFF by default: rjsmin does not understand template literals and dropped spaces after ${...}
    # ("3 error(s)" became "3error(s)"). Bundling + brotli gets nearly all of the gain (minify saved ~4% raw).
    js = rjsmin.jsmin(src) if (rjsmin and os.environ.get("CHAINTRACE_MINIFY") == "1") else src
    b = _pack("app", js.encode(), "application/javascript; charset=utf-8"); app_name = f"app.{b['hash']}.js"; ASSETS[app_name] = ASSETS.pop("app")
    out = html
    first = True
    def rep(m):
        nonlocal first
        n = m.group(1)
        if n in vendor:
            v = _pack("cy", open(os.path.join(S, n), "rb").read(), "application/javascript; charset=utf-8"); nm = f"cytoscape.{v['hash']}.js"; ASSETS[nm] = ASSETS.pop("cy")
            return f'<script src="/static/b/{nm}"></script>'
        if first: first = False; return f'<script src="/static/b/{app_name}"></script>'
        return ""
    out = TAG.sub(rep, out)
    INDEX.update(_pack("index.html", out.encode(), "text/html; charset=utf-8"))
    STATS.update({"scripts_bundled": len(app), "bundle_raw": raw_len, "bundle_min": len(js.encode()), "bundle_gz": len(ASSETS[app_name]["gz"]),
                  "bundle_br": len(ASSETS[app_name]["br"] or b""), "minifier": "rjsmin" if (rjsmin and os.environ.get("CHAINTRACE_MINIFY") == "1") else None, "brotli": bool(brotli), "app": app_name})
def respond(a, accept, cache):
    from fastapi.responses import Response
    enc = None; body = a["raw"]
    if a["br"] and "br" in accept: enc, body = "br", a["br"]
    elif "gzip" in accept: enc, body = "gzip", a["gz"]
    h = {"Cache-Control": cache, "ETag": a["etag"], "Vary": "Accept-Encoding"}
    if enc: h["Content-Encoding"] = enc
    return Response(body, media_type=a["type"], headers=h)
if BUILD:   # build step: best compression, written to static/b/ for the server to pick up
    import shutil; shutil.rmtree(CACHE, ignore_errors=True)
build()
if BUILD: print("assets:", STATS)

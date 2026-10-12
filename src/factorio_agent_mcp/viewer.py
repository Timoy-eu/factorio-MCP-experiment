"""Small live web viewer on 127.0.0.1 (for the human operator). Pure stdlib."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

from . import svgmap

PAGE = """<!doctype html><meta charset="utf-8"><title>Factorio Viewer</title>
<style>
body{margin:0;background:#111418;color:#d8dee6;font:13px Segoe UI,Arial,sans-serif}
#bar{display:flex;gap:10px;align-items:center;padding:8px 12px;background:#1b2027;position:sticky;top:0;flex-wrap:wrap}
input[type=number]{width:70px;background:#0d1014;color:#d8dee6;border:1px solid #394350;border-radius:4px;padding:3px}
button{background:#2a6fb0;color:#fff;border:0;border-radius:4px;padding:5px 10px;cursor:pointer}
#view{padding:8px;overflow:auto}
</style>
<div id="bar">
 <label><input type="checkbox" id="follow" checked> follow agent</label>
 <label>radius <input type="number" id="radius" value="30" min="5" max="80"></label>
 <label>zoom <input type="number" id="scale" value="16" min="6" max="40"></label>
 <label><input type="checkbox" id="auto" checked> refresh every <input type="number" id="every" value="3" min="1" max="60">s</label>
 <span>or area:</span>
 <input type="number" id="x1" placeholder="x1"><input type="number" id="y1" placeholder="y1">
 <input type="number" id="x2" placeholder="x2"><input type="number" id="y2" placeholder="y2">
 <button id="go">show</button><span id="msg"></span>
</div>
<div id="view"></div>
<script>
const $=id=>document.getElementById(id);
async function load(){
  const f=$('follow').checked;
  let q='scale='+$('scale').value;
  const a=['x1','y1','x2','y2'].map(i=>$(i).value);
  if(!f && a.every(v=>v!=='')) q+='&x1='+a[0]+'&y1='+a[1]+'&x2='+a[2]+'&y2='+a[3];
  else q+='&radius='+$('radius').value;
  try{
    const r=await fetch('/map.svg?'+q); const t=await r.text();
    if(r.ok){$('view').innerHTML=t;$('msg').textContent=new Date().toLocaleTimeString();}
    else $('msg').textContent=t;
  }catch(e){$('msg').textContent='no connection';}
}
$('go').onclick=()=>{ if(['x1','y1','x2','y2'].every(i=>$(i).value!=='')) $('follow').checked=false; load(); };
setInterval(()=>{ if($('auto').checked) load(); }, 1000);
let last=0; setInterval(()=>{ if($('auto').checked && Date.now()-last>=$('every').value*1000){last=Date.now();load();} },500);
load();
</script>"""


def make_handler(fetch: Callable[[dict], dict]):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence
            pass

        def _send(self, code: int, body: str, ctype: str) -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                return self._send(200, PAGE, "text/html")
            if url.path == "/map.svg":
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                try:
                    snap = fetch(q)
                    scale = int(q.get("scale", 16))
                    return self._send(200, svgmap.render(snap, scale=scale), "image/svg+xml")
                except Exception as err:  # show the problem in the page instead of failing silently
                    return self._send(500, str(err), "text/plain")
            self._send(404, "not found", "text/plain")

    return Handler


class Viewer:
    def __init__(self, fetch: Callable[[dict], dict], port: int = 8765, host: str = "127.0.0.1") -> None:
        self.httpd = ThreadingHTTPServer((host, port), make_handler(fetch))
        self.port = self.httpd.server_address[1]
        self.host = host
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

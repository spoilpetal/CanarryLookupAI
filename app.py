from __future__ import annotations
import base64, json, os, re, shlex, sqlite3, subprocess, time, uuid, hashlib, mimetypes, hmac, ipaddress, asyncio, secrets, urllib.parse, shutil, sys, socket, threading, zipfile, io, contextvars, tarfile, gzip, tempfile
from pathlib import Path
from typing import Any
import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse, PlainTextResponse, JSONResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parent

def _default_data_dir() -> Path:
    """Return a persistent per-user data directory on Windows, macOS and Linux."""
    override = os.environ.get("CANARRY_DATA") or os.environ.get("OLLAMA_STUDIO_DATA")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "CanarryLookupAI"

def _copy_missing_tree(source: Path, destination: Path) -> None:
    if not source.is_dir() or source.resolve() == destination.resolve():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            _copy_missing_tree(item, target)
        elif item.is_file() and not target.exists():
            try:
                shutil.copy2(item, target)
            except OSError:
                pass

def _migrate_legacy_data(destination: Path) -> None:
    """Copy legacy Ollama Studio user data once; never delete or overwrite originals."""
    legacy = Path.home() / ".local" / "share" / "ollama-studio"
    if legacy.exists() and legacy.resolve() != destination.resolve():
        destination.mkdir(parents=True, exist_ok=True)
        old_db = legacy / "studio.sqlite3"
        new_db = destination / "studio.sqlite3"
        if old_db.is_file() and not new_db.exists():
            try:
                source_db = sqlite3.connect(str(old_db))
                target_db = sqlite3.connect(str(new_db))
                with target_db:
                    source_db.backup(target_db)
                target_db.close()
                source_db.close()
            except sqlite3.Error:
                try:
                    if new_db.exists(): new_db.unlink()
                except OSError:
                    pass
        for folder in ("uploads", "generated"):
            _copy_missing_tree(legacy / folder, destination / folder)
    # Older releases stored project files beside the application. Move by copy,
    # preserving the original folder as a recoverable backup.
    old_workspace = ROOT / "workspace"
    new_workspace = destination / "workspace"
    _copy_missing_tree(old_workspace, new_workspace)

DATA_DIR = _default_data_dir().expanduser().resolve()
_migrate_legacy_data(DATA_DIR)
WORKSPACE = Path(os.environ.get("CANARRY_WORKSPACE", DATA_DIR / "workspace")).expanduser().resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
GENERATED_DIR = DATA_DIR / "generated"
DEVICE_WORKSPACES = DATA_DIR / "device-workspaces"
for d in (DATA_DIR, WORKSPACE, UPLOAD_DIR, GENERATED_DIR, DEVICE_WORKSPACES):
    d.mkdir(parents=True, exist_ok=True)
for d in (DATA_DIR, WORKSPACE, UPLOAD_DIR, GENERATED_DIR):
    try:
        if os.name != "nt":
            os.chmod(d, 0o700)
    except OSError:
        pass
DB_PATH = DATA_DIR / "studio.sqlite3"
KEY_PATH = DATA_DIR / ".canarry-device-secrets.key"
try:
    with KEY_PATH.open("xb") as key_file:
        key_file.write(Fernet.generate_key())
except FileExistsError:
    pass
try: os.chmod(KEY_PATH,0o600)
except OSError: pass
_SECRET_CIPHER = Fernet(KEY_PATH.read_bytes())
def _encrypt_device_value(value:str)->str:
    return "fernet:"+_SECRET_CIPHER.encrypt(value.encode("utf-8")).decode("ascii")
def _decrypt_device_value(value:str)->str:
    if not value.startswith("fernet:"): return value
    try:return _SECRET_CIPHER.decrypt(value[7:].encode("ascii")).decode("utf-8")
    except InvalidToken:raise RuntimeError("Device settings could not be decrypted. Preserve the CanarryLookup encryption key and data directory together.")
MAX_UPLOAD = 50 * 1024 * 1024
MAX_PROJECT_ARCHIVE = int(os.environ.get('CANARRY_MAX_PROJECT_ARCHIVE', str(2 * 1024 * 1024 * 1024)))
MAX_FILES_PER_TURN = 20
MAX_EXTRACT_CHARS = 120000
MAX_ATTACHMENT_CONTEXT_CHARS = 32000
MAX_CHAT_MESSAGES = 8
MAX_TOOL_ROUNDS = int(os.environ.get("MAX_TOOL_ROUNDS", "16"))
COMMAND_TIMEOUT = int(os.environ.get("COMMAND_TIMEOUT", "45"))

app = FastAPI(title="CanarryLookup AI", version="", docs_url=None, redoc_url=None, openapi_url=None)
CURRENT_DEVICE: contextvars.ContextVar[str] = contextvars.ContextVar("canarry_device_id", default="local-default")
CURRENT_DEVICE_OWNER: contextvars.ContextVar[bool] = contextvars.ContextVar("canarry_device_owner", default=False)
DEVICE_COOKIE = "canarry_device"
BIND_HOST = os.environ.get("CANARRY_HOST", "127.0.0.1")
ACCESS_PASSWORD = os.environ.get("CANARRY_ACCESS_PASSWORD", "")
ACCESS_USERNAME = os.environ.get("CANARRY_ACCESS_USERNAME", "canarry")
def is_loopback_bind(host: str) -> bool:
    if host.lower() in {"localhost", "127.0.0.1", "::1"}: return True
    try: return ipaddress.ip_address(host).is_loopback
    except ValueError: return False

_rate_buckets: dict[str, list[float]] = {}
@app.middleware("http")
async def protect_remote_access(request, call_next):
    raw_device=request.cookies.get(DEVICE_COOKIE, "")
    device_id=None; token_value=raw_device if re.fullmatch(r"[A-Fa-f0-9]{64}",raw_device or "") else ""
    if token_value:
        token_hash=hashlib.sha256(token_value.encode()).hexdigest()
        with db() as c: device=c.execute("SELECT id,is_owner,paired FROM devices WHERE token_hash=?",(token_hash,)).fetchone()
        if device: device_id=device["id"]
    set_cookie=False
    if not device_id:
        token_value=secrets.token_hex(32); token_hash=hashlib.sha256(token_value.encode()).hexdigest()
        with db() as c:
            owner=c.execute("SELECT id FROM devices WHERE is_owner=1 LIMIT 1").fetchone()
            device_id=uuid.uuid4().hex; is_owner=0 if owner else 1
            c.execute("INSERT INTO devices(id,token_hash,name,is_owner,paired,created) VALUES(?,?,?,?,?,?)",(device_id,token_hash,"Owner device" if is_owner else "Unpaired device",is_owner,1 if is_owner else 0,time.time()))
            if is_owner:
                legacy_settings=c.execute("SELECT key,value FROM settings WHERE key NOT IN ('network_auth_enabled','network_auth_username','network_auth_password')").fetchall()
                for legacy in legacy_settings:
                    c.execute("INSERT OR IGNORE INTO device_settings(device_id,key,value) VALUES(?,?,?)",(device_id,legacy["key"],_encrypt_device_value(legacy["value"])))
                    c.execute("DELETE FROM settings WHERE key=?",(legacy["key"],))
                for table in ("chats","projects","memories","uploads","mcp_servers"):
                    c.execute(f"UPDATE {table} SET device_id=? WHERE device_id IS NULL OR device_id=''",(device_id,))
                for secret_row in c.execute("SELECT id,config FROM mcp_servers WHERE device_id=?",(device_id,)).fetchall():
                    if not str(secret_row["config"]).startswith("fernet:"):
                        c.execute("UPDATE mcp_servers SET config=? WHERE id=?",(_encrypt_device_value(secret_row["config"]),secret_row["id"]))
                for auth_row in c.execute("SELECT key,value FROM settings WHERE key IN ('network_auth_enabled','network_auth_username','network_auth_password')").fetchall():
                    if not str(auth_row["value"]).startswith("fernet:"):
                        c.execute("UPDATE settings SET value=? WHERE key=?",(_encrypt_device_value(auth_row["value"]),auth_row["key"]))
                for old_image in GENERATED_DIR.glob("*"):
                    if old_image.is_file() and re.fullmatch(r"[a-f0-9]{32}\.[A-Za-z0-9]+",old_image.name):
                        image_id=old_image.name.split(".",1)[0]
                        c.execute("INSERT OR IGNORE INTO generated_images(id,path,device_id,created) VALUES(?,?,?,?)",(image_id,str(old_image),device_id,time.time()))
        set_cookie=True
    with db() as c: device=c.execute("SELECT id,is_owner,paired FROM devices WHERE id=?",(device_id,)).fetchone()
    tok=CURRENT_DEVICE.set(device_id); tok_owner=CURRENT_DEVICE_OWNER.set(bool(device and device["is_owner"]))
    try:
        path=request.url.path
        allowed_unpaired={"/", "/api/device/status", "/api/device/pair", "/static/app.js", "/static/style.css", "/static/canarry-mark.svg"}
        if device and not device["paired"] and path not in allowed_unpaired:
            response=JSONResponse({"detail":"This device must be paired by the owner before accessing the workspace."},status_code=403)
        else:
            response=await _protect_request_body(request,call_next)
        if set_cookie:
            response.set_cookie(DEVICE_COOKIE,token_value,httponly=True,samesite="strict",secure=bool(request.url.scheme=="https" or request.headers.get("x-forwarded-proto","").lower()=="https"),max_age=60*60*24*365)
        return response
    finally:
        CURRENT_DEVICE.reset(tok); CURRENT_DEVICE_OWNER.reset(tok_owner)

async def _protect_request_body(request, call_next):
    declared_size=request.headers.get("content-length")
    if declared_size:
        try:
            if int(declared_size)>60*1024*1024:
                return PlainTextResponse("Request body exceeds the 60 MB limit",status_code=413)
        except ValueError:
            return PlainTextResponse("Invalid Content-Length",status_code=400)
    # Optional Basic authentication. LAN use is password-free by default; public
    # tunnels are blocked unless the operator explicitly enables strong credentials.
    auth_enabled = bool(global_setting("network_auth_enabled", bool(ACCESS_PASSWORD)))
    auth_username = str(global_setting("network_auth_username", ACCESS_USERNAME) or ACCESS_USERNAME)
    auth_password = str(global_setting("network_auth_password", ACCESS_PASSWORD) or "")
    if auth_enabled:
        auth = request.headers.get("authorization", "")
        valid = False
        if auth.startswith("Basic "):
            try:
                raw = base64.b64decode(auth[6:], validate=True).decode("utf-8")
                username, password = raw.split(":", 1)
                valid = hmac.compare_digest(username, auth_username) and hmac.compare_digest(password, auth_password)
            except Exception: valid = False
        if not valid:
            return PlainTextResponse("Authentication required", status_code=401, headers={"WWW-Authenticate": 'Basic realm="CanarryLookup AI", charset="UTF-8"'})
    # Reject cross-origin browser mutations (non-browser clients without Origin remain supported).
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin:
            try:
                o = urllib.parse.urlsplit(origin)
                if o.netloc.lower() != request.headers.get("host", "").lower():
                    return PlainTextResponse("Cross-origin request blocked", status_code=403)
            except Exception:
                return PlainTextResponse("Invalid request origin", status_code=403)
        if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
            return PlainTextResponse("Cross-site request blocked", status_code=403)
    # Small in-process abuse guard. This is not a substitute for a reverse-proxy/WAF limit.
    if request.url.path.startswith("/api/"):
        ip = request.client.host if request.client else "unknown"
        bucket = "chat" if request.url.path == "/api/chat" else ("pair" if request.url.path == "/api/device/pair" else "general")
        key=ip+":"+bucket; now = time.time()
        hits = [t for t in _rate_buckets.get(key, []) if now-t < 60]
        limit = 18 if bucket=="chat" else (8 if bucket=="pair" else 180)
        if len(hits) >= limit:
            return PlainTextResponse("Rate limit exceeded; retry shortly.", status_code=429, headers={"Retry-After":"60"})
        hits.append(now); _rate_buckets[key] = hits
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
    return response



def _lan_addresses() -> list[str]:
    found=set()
    try:
        sock=socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("192.0.2.1", 80))
        found.add(sock.getsockname()[0]); sock.close()
    except OSError: pass
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip=item[4][0]
            if not ip.startswith(("127.","169.254.")): found.add(ip)
    except OSError: pass
    return sorted(found)

_tunnel_lock=threading.Lock()
_tunnel_process: subprocess.Popen | None=None
_tunnel_provider: str | None=None
_tunnel_url: str | None=None
_tunnel_error: str | None=None

def _tunnel_reader(proc: subprocess.Popen, provider: str) -> None:
    global _tunnel_url, _tunnel_error
    try:
        for line in iter(proc.stdout.readline, ""):
            line=line.strip()
            if not line: continue
            match=re.search(r"https://[a-zA-Z0-9.-]+(?:\.trycloudflare\.com|\.ngrok-free\.app|\.ngrok\.app|\.ts\.net)",line)
            if match:
                with _tunnel_lock: _tunnel_url=match.group(0)
                print(f"[CanarryLookup] Public URL: {_tunnel_url}",flush=True)
            else:
                try:
                    record=json.loads(line)
                    candidate=record.get("url") or record.get("msg","")
                    match=re.search(r"https://[a-zA-Z0-9.-]+(?:\.trycloudflare\.com|\.ngrok-free\.app|\.ngrok\.app)",str(candidate))
                    if match:
                        with _tunnel_lock: _tunnel_url=match.group(0)
                        print(f"[CanarryLookup] Public URL: {_tunnel_url}",flush=True)
                except Exception: pass
        code=proc.poll()
        if code not in (None,0):
            with _tunnel_lock:
                if not _tunnel_url: _tunnel_error=f"{provider} exited with code {code}. Check its CLI setup."
    except Exception as exc:
        with _tunnel_lock: _tunnel_error=str(exc)[:300]

def _start_tunnel(provider: str, port: int) -> dict:
    global _tunnel_process,_tunnel_provider,_tunnel_url,_tunnel_error
    provider=provider.lower().strip()
    if provider not in {"cloudflare","ngrok","tailscale"}:
        raise HTTPException(400,"Choose Cloudflare, ngrok, or Tailscale.")
    if not bool(global_setting("network_auth_enabled", bool(ACCESS_PASSWORD))):
        raise HTTPException(400,"Enable username and password before starting a public connection.")
    password=str(global_setting("network_auth_password",ACCESS_PASSWORD) or "")
    username=str(global_setting("network_auth_username",ACCESS_USERNAME) or "")
    if len(password)<16 or not username:
        raise HTTPException(400,"Public access requires a username and a password of at least 16 characters.")
    with _tunnel_lock:
        if _tunnel_process and _tunnel_process.poll() is None:
            return {"ok":True,"provider":_tunnel_provider,"url":_tunnel_url,"starting":not bool(_tunnel_url)}
        _tunnel_url=None; _tunnel_error=None
        if provider=="cloudflare":
            command=["cloudflared","tunnel","--url",f"http://127.0.0.1:{port}","--no-autoupdate"]
        elif provider=="ngrok":
            command=["ngrok","http",str(port),"--log","stdout","--log-format","json"]
        else:
            command=["tailscale","funnel",str(port)]
        try:
            env=os.environ.copy()
            if provider=="ngrok":
                credential=str(setting("tunnel_credential_ngrok",os.environ.get("CANARRY_NGROK_AUTHTOKEN","")) or os.environ.get("CANARRY_NGROK_AUTHTOKEN",""))
                if credential: env["NGROK_AUTHTOKEN"]=credential
            if provider=="cloudflare":
                credential=str(setting("tunnel_credential_cloudflare",os.environ.get("CANARRY_CLOUDFLARE_TUNNEL_TOKEN","")) or os.environ.get("CANARRY_CLOUDFLARE_TUNNEL_TOKEN",""))
                if credential:
                    # Cloudflare documents TUNNEL_TOKEN as the credential environment variable;
                    # avoid exposing the secret in the process command line.
                    env["TUNNEL_TOKEN"]=credential
                    command=["cloudflared","tunnel","run"]
                    hostname=str(setting("tunnel_hostname_cloudflare",os.environ.get("CANARRY_CLOUDFLARE_HOSTNAME","")) or os.environ.get("CANARRY_CLOUDFLARE_HOSTNAME",""))
                    if not hostname:raise HTTPException(400,"A named Cloudflare tunnel token requires its configured public hostname.")
                    _tunnel_url="https://"+hostname
            proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,env=env)
        except OSError as exc:
            raise HTTPException(400,f"Could not start {provider} CLI ({exc}). Install it and check its permissions.")
        _tunnel_process=proc; _tunnel_provider=provider
        threading.Thread(target=_tunnel_reader,args=(proc,provider),daemon=True).start()
        return {"ok":True,"provider":provider,"url":None,"starting":True}

def _stop_tunnel() -> dict:
    global _tunnel_process,_tunnel_provider,_tunnel_url,_tunnel_error
    with _tunnel_lock:
        provider=_tunnel_provider; proc=_tunnel_process
        if proc and proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill()
        if provider=="tailscale":
            try: subprocess.run(["tailscale","funnel","off"],capture_output=True,text=True,timeout=8)
            except Exception: pass
        _tunnel_process=None; _tunnel_provider=None; _tunnel_url=None; _tunnel_error=None
    return {"ok":True,"stopped":True}

@app.on_event("startup")
async def start_requested_tunnel():
    provider=os.environ.get("CANARRY_TUNNEL_PROVIDER")
    if provider:
        try: _start_tunnel(provider,int(os.environ.get("CANARRY_PORT","8080")))
        except Exception as exc: print(f"[CanarryLookup] Could not start {provider} tunnel: {exc}")

@app.on_event("shutdown")
async def stop_tunnel_on_shutdown():
    _stop_tunnel()

app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

def db():
    con=sqlite3.connect(DB_PATH); con.row_factory=sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS chats(id TEXT PRIMARY KEY,title TEXT NOT NULL,model TEXT NOT NULL DEFAULT '',messages TEXT NOT NULL DEFAULT '[]',created REAL NOT NULL,updated REAL NOT NULL,device_id TEXT);
        CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY,chat_id TEXT REFERENCES chats(id) ON DELETE SET NULL,name TEXT NOT NULL,path TEXT NOT NULL,mime TEXT NOT NULL,size INTEGER NOT NULL,extracted TEXT NOT NULL,created REAL NOT NULL,device_id TEXT);
        CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY,content TEXT NOT NULL,category TEXT NOT NULL DEFAULT 'general',created REAL NOT NULL,updated REAL NOT NULL,device_id TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,path TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,device_id TEXT);
        """)
        cols={r[1] for r in c.execute("PRAGMA table_info(chats)")}
        if "project_id" not in cols: c.execute("ALTER TABLE chats ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE SET NULL")
        if "pinned" not in cols: c.execute("ALTER TABLE chats ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        c.execute("CREATE TABLE IF NOT EXISTS mcp_servers(id TEXT PRIMARY KEY,name TEXT NOT NULL,transport TEXT NOT NULL,config TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,created REAL NOT NULL,updated REAL NOT NULL,device_id TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,name TEXT NOT NULL,is_owner INTEGER NOT NULL DEFAULT 0,paired INTEGER NOT NULL DEFAULT 0,harness_mode INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS device_pair_codes(code_hash TEXT PRIMARY KEY,created REAL NOT NULL,expires REAL NOT NULL,used INTEGER NOT NULL DEFAULT 0)")
        c.execute("CREATE TABLE IF NOT EXISTS device_settings(device_id TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(device_id,key))")
        c.execute("CREATE TABLE IF NOT EXISTS generated_images(id TEXT PRIMARY KEY,path TEXT NOT NULL,device_id TEXT NOT NULL,created REAL NOT NULL)")
        for table in ("chats","uploads","memories","projects","mcp_servers"):
            cols={r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            if "device_id" not in cols: c.execute(f"ALTER TABLE {table} ADD COLUMN device_id TEXT")
    try: os.chmod(DB_PATH,0o600)
    except OSError: pass
init_db()

class ChatRequest(BaseModel):
    messages:list[dict[str,Any]]=Field(max_length=100)
    model:str=Field(default="",max_length=200)
    temperature:float|None=Field(default=None,ge=0,le=2)
    agent:bool=True
    chat_id:str|None=None
    attachment_ids:list[str]=Field(default_factory=list,max_length=20)
    memory_enabled:bool=True

DEFAULT_PROVIDER={"type":"ollama","base_url":"http://127.0.0.1:11434","api_key":""}
def setting(key, default):
    did=CURRENT_DEVICE.get()
    with db() as c:
        r=c.execute("SELECT value FROM device_settings WHERE device_id=? AND key=?",(did,key)).fetchone()
    return json.loads(_decrypt_device_value(r["value"])) if r else default
def set_setting(key,value):
    did=CURRENT_DEVICE.get()
    with db() as c:c.execute("INSERT INTO device_settings(device_id,key,value) VALUES(?,?,?) ON CONFLICT(device_id,key) DO UPDATE SET value=excluded.value",(did,key,_encrypt_device_value(json.dumps(value))))
def global_setting(key, default):
    with db() as c:r=c.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
    return json.loads(_decrypt_device_value(r["value"])) if r else default
def set_global_setting(key,value):
    with db() as c:c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,_encrypt_device_value(json.dumps(value))))
def provider_config():
    p=setting("provider",DEFAULT_PROVIDER.copy()); p.update({k:v for k,v in DEFAULT_PROVIDER.items() if k not in p})
    p["base_url"]=(p.get("base_url") or DEFAULT_PROVIDER["base_url"]).rstrip("/")
    return p
def auth_headers(p):
    h={"Content-Type":"application/json"}
    if p.get("type")=="anthropic":
        h.update({"x-api-key":p.get("api_key", ""),"anthropic-version":"2023-06-01"})
    elif p.get("type")=="gemini":
        if p.get("api_key"): h["x-goog-api-key"]=p["api_key"]
    elif p.get("api_key"):
        h["Authorization"]="Bearer "+p["api_key"]
    return h

def provider_models_url(p):
    if p["type"]=="ollama": return f"{p['base_url']}/api/tags"
    if p["type"]=="anthropic": return f"{p['base_url']}/models"
    if p["type"]=="gemini": return f"{p['base_url']}/models"
    return f"{p['base_url']}/models"

def _mcp_servers():
    with db() as c: rows=c.execute("SELECT * FROM mcp_servers WHERE device_id=? ORDER BY created",(CURRENT_DEVICE.get(),)).fetchall()
    return [dict(r) for r in rows]

def _mcp_public(row):
    cfg=json.loads(_decrypt_device_value(row["config"]))
    return {"id":row["id"],"name":row["name"],"transport":row["transport"],"enabled":bool(row["enabled"]),"command":cfg.get("command",""),"args":cfg.get("args",[]),"url":cfg.get("url",""),"has_env":bool(cfg.get("env")),"has_headers":bool(cfg.get("headers"))}

async def _mcp_stdio_request(cfg, method, params=None, request_id=2):
    command=cfg.get("command",""); args=cfg.get("args",[])
    if not command or not isinstance(args,list) or len(args)>40: raise RuntimeError("MCP stdio command/arguments are invalid")
    env={k:os.environ[k] for k in ("PATH","HOME","USER","LOGNAME","LANG","TERM") if k in os.environ}
    extra=cfg.get("env",{})
    if isinstance(extra,dict): env.update({str(k):str(v) for k,v in extra.items() if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",str(k))})
    proc=await asyncio.create_subprocess_exec(command,*[str(a) for a in args],stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,env=env)
    async def send(obj):
        proc.stdin.write((json.dumps(obj,ensure_ascii=False)+"\n").encode()); await proc.stdin.drain()
    async def recv(want):
        while True:
            line=await asyncio.wait_for(proc.stdout.readline(),timeout=25)
            if not line: raise RuntimeError("MCP server closed its output")
            try: msg=json.loads(line)
            except Exception: continue
            if msg.get("id")==want:
                if "error" in msg: raise RuntimeError(str(msg["error"]))
                return msg.get("result",{})
    try:
        await send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"CanarryLookup AI","version":"1.6.0"}}})
        await recv(1); await send({"jsonrpc":"2.0","method":"notifications/initialized"})
        if method=="tools/list":
            await send({"jsonrpc":"2.0","id":request_id,"method":method,"params":params or {}}); result=await recv(request_id)
        else:
            await send({"jsonrpc":"2.0","id":request_id,"method":method,"params":params or {}}); result=await recv(request_id)
        return result
    finally:
        try: proc.terminate(); await asyncio.wait_for(proc.wait(),timeout=2)
        except Exception:
            try: proc.kill()
            except Exception: pass

async def _mcp_http_request(cfg, method, params=None, request_id=2):
    url=cfg.get("url","")
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment: raise RuntimeError("MCP HTTP URL must be a valid HTTP(S) URL without embedded credentials or fragments")
    headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream"}
    if isinstance(cfg.get("headers"),dict): headers.update({str(k):str(v) for k,v in cfg["headers"].items() if str(k).lower() not in {"host","content-length"}})
    async with httpx.AsyncClient(timeout=httpx.Timeout(35,connect=10),follow_redirects=False) as client:
        async def post(obj):
            nonlocal headers
            r=await client.post(url,json=obj,headers=headers); r.raise_for_status()
            sid=r.headers.get("mcp-session-id")
            if sid: headers["MCP-Session-Id"]=sid
            if "json" in r.headers.get("content-type",""):
                data=r.json()
                if data.get("error"): raise RuntimeError(str(data["error"]))
                return data.get("result",{})
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    try:
                        data=json.loads(line[5:].strip())
                        if data.get("id")==obj.get("id"):
                            if data.get("error"): raise RuntimeError(str(data["error"]))
                            return data.get("result",{})
                    except json.JSONDecodeError: pass
            return {}
        init_result=await post({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"CanarryLookup AI","version":"1.6.0"}}})
        headers["MCP-Protocol-Version"]=init_result.get("protocolVersion","2025-03-26")
        # Initialized is a notification; some servers return 202/empty body.
        try: await client.post(url,json={"jsonrpc":"2.0","method":"notifications/initialized"},headers=headers)
        except Exception: pass
        return await post({"jsonrpc":"2.0","id":request_id,"method":method,"params":params or {}})

async def mcp_request(row, method, params=None):
    cfg=json.loads(_decrypt_device_value(row["config"]))
    if row["transport"]=="stdio": return await _mcp_stdio_request(cfg,method,params)
    return await _mcp_http_request(cfg,method,params)

async def available_mcp_tools():
    out=[]
    for row in _mcp_servers():
        if not row["enabled"]: continue
        try:
            result=await mcp_request(row,"tools/list")
            for tool in result.get("tools",[]):
                raw_name=str(tool.get("name","")); safe=re.sub(r"[^A-Za-z0-9_-]","_",raw_name)[:80]
                if not safe: continue
                out.append({"type":"function","function":{"name":f"mcp__{row['id'][:8]}__{safe[:48]}","description":f"MCP server {row['name']}: {str(tool.get('description',''))[:700]}","parameters":tool.get("inputSchema") or {"type":"object","properties":{}}},"_mcp":{"server_id":row["id"],"tool":raw_name}})
        except Exception as e:
            out.append({"_notice":f"MCP server {row['name']} unavailable: {str(e)[:180]}"})
    return out

async def invoke_mcp_tool(tool,args):
    with db() as c: row=c.execute("SELECT * FROM mcp_servers WHERE id=? AND enabled=1 AND device_id=?",(tool["server_id"],CURRENT_DEVICE.get())).fetchone()
    if not row: return {"error":"MCP server is disabled or missing"}
    result=await mcp_request(dict(row),"tools/call",{"name":tool["tool"],"arguments":args})
    return {"content":[x.get("text",x) for x in result.get("content",[])],"isError":result.get("isError",False)}

def device_workspace()->Path:
    did=CURRENT_DEVICE.get()
    with db() as c:r=c.execute("SELECT is_owner FROM devices WHERE id=?",(did,)).fetchone()
    root=WORKSPACE if r and r["is_owner"] else DEVICE_WORKSPACES/did
    root.mkdir(parents=True,exist_ok=True)
    try:
        if os.name!="nt":os.chmod(root,0o700)
    except OSError:pass
    return root
def inside_workspace(rel:str)->Path:
    root=device_workspace()
    p=(root/rel).resolve()
    if p!=root and root not in p.parents: raise ValueError("Path is outside the configured workspace.")
    return p
def list_files(path:str=".")->dict:
    folder=inside_workspace(path)
    if not folder.exists() or not folder.is_dir():return {"error":"Directory not found"}
    rows=[]
    for p in sorted(folder.iterdir(),key=lambda x:(not x.is_dir(),x.name.lower()))[:250]:
        rows.append({"name":p.name,"path":str(p.relative_to(device_workspace())),"type":"directory" if p.is_dir() else "file","size":p.stat().st_size if p.is_file() else None})
    return {"path":path,"items":rows}
def read_file(path:str)->dict:
    p=inside_workspace(path)
    if not p.is_file():return {"error":"File not found"}
    if p.stat().st_size>1_000_000:return {"error":"File exceeds 1 MB read limit"}
    try:return {"path":path,"content":p.read_text(encoding="utf-8")}
    except UnicodeDecodeError:return {"error":"File is not UTF-8 text"}
def write_file(path:str,content:str)->dict:
    p=inside_workspace(path)
    if len(content.encode())>1_000_000:return {"error":"File exceeds 1 MB write limit"}
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content,encoding="utf-8")
    return {"path":path,"bytes_written":p.stat().st_size}
ALLOWED_EXECUTABLES={"python","python3","py","pytest","npm","node","git"}
def run_command(argv:list[str],timeout:int=COMMAND_TIMEOUT)->dict:
    if not argv or len(argv)>30 or any(not isinstance(x,str) or len(x)>2000 for x in argv):return {"error":"Invalid command arguments"}
    exe=Path(argv[0].replace("\\", "/")).name.lower()
    if exe.endswith((".exe", ".cmd", ".bat")): exe=exe.rsplit(".", 1)[0]
    if exe not in ALLOWED_EXECUTABLES:return {"error":f"Executable '{exe}' is not allowed."}
    try:
        r=subprocess.run(argv,cwd=device_workspace(),capture_output=True,text=True,timeout=min(max(int(timeout),1),COMMAND_TIMEOUT),shell=False,env={**os.environ,"PWD":str(device_workspace())})
        return {"returncode":r.returncode,"stdout":r.stdout[-12000:],"stderr":r.stderr[-12000:]}
    except subprocess.TimeoutExpired:return {"error":f"Command timed out after {timeout} seconds"}
TOOLS=[
 {"type":"function","function":{"name":"list_files","description":"List workspace files","parameters":{"type":"object","properties":{"path":{"type":"string"}}}}},
 {"type":"function","function":{"name":"read_file","description":"Read a UTF-8 text file in workspace, max 1 MB","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
 {"type":"function","function":{"name":"write_file","description":"Write a UTF-8 text file in workspace, max 1 MB","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}},
 {"type":"function","function":{"name":"run_command","description":"Run allowlisted executable in workspace, no shell","parameters":{"type":"object","properties":{"argv":{"type":"array","items":{"type":"string"}},"timeout":{"type":"integer"}},"required":["argv"]}}}
]
def invoke_tool(name,args):
    try:return {"list_files":list_files,"read_file":read_file,"write_file":write_file,"run_command":run_command}[name](**args)
    except Exception as e:return {"error":str(e)}
def get_chat(cid):
    with db() as c:r=c.execute("SELECT * FROM chats WHERE id=? AND device_id=?",(cid,CURRENT_DEVICE.get())).fetchone()
    return dict(r) if r else None
def save_chat(cid,messages,model="",project_id=None):
    if project_id:
        with db() as c:
            if not c.execute("SELECT 1 FROM projects WHERE id=? AND device_id=?",(project_id,CURRENT_DEVICE.get())).fetchone():project_id=None
    now=time.time();title=next((str(m.get("content"," ")).strip().replace("\n"," ")[:72] for m in messages if m.get("role")=="user"),"New conversation") or "New conversation"
    with db() as c:
        c.execute("""INSERT INTO chats(id,title,model,messages,created,updated,project_id,device_id) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET title=CASE WHEN chats.title='New conversation' THEN excluded.title ELSE chats.title END,model=excluded.model,messages=excluded.messages,updated=excluded.updated,project_id=COALESCE(excluded.project_id,chats.project_id) WHERE chats.device_id=excluded.device_id""",
        (cid,title,model,json.dumps(messages,ensure_ascii=False),now,now,project_id,CURRENT_DEVICE.get()))
def memory_rows():
    with db() as c:return [dict(x) for x in c.execute("SELECT * FROM memories WHERE device_id=? ORDER BY updated DESC",(CURRENT_DEVICE.get(),))]
def add_memory(content,category="general"):
    content=content.strip()
    if not content:return None
    mid=uuid.uuid4().hex
    with db() as c:c.execute("INSERT INTO memories(id,content,category,created,updated,device_id) VALUES(?,?,?,?,?,?)",(mid,content,category,time.time(),time.time(),CURRENT_DEVICE.get()))
    return mid
def relevant_memories(query,limit=8):
    words={w.lower() for w in re.findall(r"[a-zA-Z0-9_]{4,}",query)};scored=[]
    for m in memory_rows():
        mw=set(re.findall(r"[a-zA-Z0-9_]{4,}",m["content"].lower()));score=len(words & mw)
        if score:scored.append((score,m))
    return [m for _,m in sorted(scored,key=lambda x:x[0],reverse=True)[:limit]]
def extract_upload_text(path:Path,name:str)->str:
    ext=Path(name).suffix.lower();text_ext={".txt",".md",".py",".js",".ts",".tsx",".jsx",".json",".csv",".html",".css",".xml",".yaml",".yml",".toml",".rs",".go",".java",".c",".cpp",".h",".sh",".sql",".log",".ini",".conf"}
    if ext in text_ext:
        try:return path.read_text("utf-8")[:MAX_EXTRACT_CHARS]
        except UnicodeDecodeError:return "[File is not UTF-8 text; binary content retained locally.]"
    if ext==".pdf":
        try:
            from pypdf import PdfReader
            return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)[:MAX_EXTRACT_CHARS]
        except Exception as e:return f"[PDF extraction unavailable or failed: {e}]"
    if ext==".docx":
        try:
            from docx import Document
            return "\n".join(p.text for p in Document(str(path)).paragraphs)[:MAX_EXTRACT_CHARS]
        except Exception as e:return f"[DOCX extraction unavailable or failed: {e}]"
    return "[File stored locally. Binary content is not text-extracted.]"

def device_harness_enabled():
    with db() as c:r=c.execute("SELECT harness_mode FROM devices WHERE id=?",(CURRENT_DEVICE.get(),)).fetchone()
    return bool(r and r[0])

@app.get("/api/device/status")
async def device_status():
    with db() as c:
        d=c.execute("SELECT id,name,is_owner,paired,harness_mode FROM devices WHERE id=?",(CURRENT_DEVICE.get(),)).fetchone()
    return {"id":d["id"],"name":d["name"],"is_owner":bool(d["is_owner"]),"paired":bool(d["paired"]),"harness_mode":bool(d["harness_mode"])} if d else {"paired":False}

@app.post("/api/device/pair")
async def device_pair(payload:dict):
    code=str(payload.get("code","")).strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{12,40}",code):raise HTTPException(400,"Enter a valid one-time pairing code.")
    digest=hashlib.sha256(code.encode()).hexdigest()
    with db() as c:
        row=c.execute("SELECT * FROM device_pair_codes WHERE code_hash=? AND used=0 AND expires>?",(digest,time.time())).fetchone()
        if not row:raise HTTPException(403,"Pairing code is invalid, expired, or already used.")
        c.execute("UPDATE device_pair_codes SET used=1 WHERE code_hash=?",(digest,))
        c.execute("UPDATE devices SET paired=1,name=? WHERE id=?",(str(payload.get("name") or "Paired device")[:80],CURRENT_DEVICE.get()))
    return {"ok":True,"message":"Device paired. Its workspace and MCP connections are private to this device."}

@app.put("/api/device/mode")
async def device_mode(payload:dict):
    enabled=bool(payload.get("harness_mode",False))
    with db() as c:c.execute("UPDATE devices SET harness_mode=? WHERE id=?",(int(enabled),CURRENT_DEVICE.get()))
    return {"ok":True,"harness_mode":enabled}

@app.post("/api/device/pair-code")
async def device_pair_code():
    if not CURRENT_DEVICE_OWNER.get():raise HTTPException(403,"Only the owner device can create pairing codes.")
    code=secrets.token_urlsafe(15).replace("_","-")[:20]
    with db() as c:c.execute("INSERT INTO device_pair_codes(code_hash,created,expires,used) VALUES(?,?,?,0)",(hashlib.sha256(code.encode()).hexdigest(),time.time(),time.time()+600))
    return {"code":code,"expires_in_seconds":600}

@app.get("/api/device/list")
async def device_list():
    if not CURRENT_DEVICE_OWNER.get():raise HTTPException(403,"Only the owner device can manage paired devices.")
    with db() as c:rows=c.execute("SELECT id,name,is_owner,paired,harness_mode,created FROM devices ORDER BY created").fetchall()
    return [dict(r) for r in rows]

@app.delete("/api/device/{device_id}")
async def device_revoke(device_id:str):
    if not CURRENT_DEVICE_OWNER.get():raise HTTPException(403,"Only the owner device can revoke devices.")
    if device_id==CURRENT_DEVICE.get():raise HTTPException(400,"The owner device cannot revoke itself here.")
    with db() as c:c.execute("DELETE FROM devices WHERE id=? AND is_owner=0",(device_id,))
    return {"ok":True}

@app.get("/")
async def index():return FileResponse(ROOT/"static"/"index.html")
@app.get("/api/health")
async def health():
    p=provider_config()
    try:
        async with httpx.AsyncClient(timeout=8,headers=auth_headers(p)) as client:
            url=provider_models_url(p)
            r=await client.get(url);r.raise_for_status()
        return {"ok":True,"provider":p["type"],"base_url":p["base_url"],"workspace":str(device_workspace()),"database":"local SQLite"}
    except Exception as e:return {"ok":False,"provider":p["type"],"base_url":p["base_url"],"error":str(e),"workspace":str(device_workspace())}
@app.get("/api/models")
async def models():
    p=provider_config()
    try:
        async with httpx.AsyncClient(timeout=15,headers=auth_headers(p)) as client:
            url=provider_models_url(p)
            r=await client.get(url,headers=auth_headers(p));r.raise_for_status();data=r.json()
        if p["type"]=="ollama":return {"models":data.get("models",[]),"provider":"ollama"}
        rows=data.get("data",data.get("models",[]))
        if p["type"]=="gemini": rows=[m for m in rows if "generateContent" in m.get("supportedGenerationMethods",["generateContent"])]
        return {"models":[{"name":m.get("id",m.get("name","")).removeprefix("models/")} for m in rows],"provider":p["type"]}
    except Exception as e:raise HTTPException(502,f"Provider connection failed ({p['type']} at {p['base_url']}): {e}")

@app.get("/api/model-capabilities/{model:path}")
async def model_capabilities(model:str):
    p=provider_config()
    if p["type"]!="ollama":return {"known":False,"capabilities":[],"note":"Capabilities are provider/model dependent."}
    try:
        async with httpx.AsyncClient(timeout=15,headers=auth_headers(p)) as client:
            r=await client.post(f"{p['base_url']}/api/show",json={"model":model});r.raise_for_status();data=r.json()
        caps=data.get("capabilities") or []
        model_info=data.get("model_info") or {}
        thinking=("thinking" in caps) or any("thinking" in str(k).lower() for k in model_info)
        return {"known":bool(caps or model_info),"capabilities":caps,"vision":("vision" in caps),"tools":("tools" in caps),"thinking":thinking}
    except Exception as e:return {"known":False,"capabilities":[],"note":str(e)[:180]}

@app.post("/api/chats")
async def chat_create(payload:dict|None=None):
    cid=uuid.uuid4().hex;save_chat(cid,[],str((payload or {}).get("model","")),(payload or {}).get("project_id"));return {"id":cid}
@app.get("/api/chats")
async def chats():
    with db() as c:rows=c.execute("SELECT id,title,model,created,updated,project_id,pinned FROM chats WHERE device_id=? ORDER BY pinned DESC,updated DESC",(CURRENT_DEVICE.get(),)).fetchall()
    return [dict(x) for x in rows]
@app.get("/api/chats/export")
async def export_all_chats():
    buffer=io.BytesIO()
    with db() as c:
        rows=c.execute("SELECT id,title,model,messages,created,updated FROM chats WHERE device_id=? ORDER BY updated DESC",(CURRENT_DEVICE.get(),)).fetchall()
    with zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as archive:
        for row in rows:
            title=str(row["title"] or "conversation")
            safe=re.sub(r"[^A-Za-z0-9._-]+","-",title).strip(".-")[:60] or "conversation"
            try: messages=json.loads(row["messages"] or "[]")
            except Exception: messages=[]
            lines=[f"# {title}","","- Model: "+str(row["model"] or "Not recorded"),"- Exported: "+time.strftime("%Y-%m-%d %H:%M:%S",time.localtime()),""]
            for message in messages:
                content=message.get("content",message.get("text",""))
                if isinstance(content,list):
                    content="\\n".join(str(x.get("text",x.get("content",""))) if isinstance(x,dict) else str(x) for x in content)
                elif not isinstance(content,str): content=json.dumps(content,ensure_ascii=False,indent=2)
                lines.extend(["## "+str(message.get("role","assistant")).upper(),"",content,""])
            archive.writestr(f"{safe}-{str(row['id'])[:8]}.md","\\n".join(lines))
    buffer.seek(0)
    return StreamingResponse(buffer,media_type="application/zip",headers={"Content-Disposition":'attachment; filename="CanarryLookupAI-chats.zip"'})

@app.get("/api/chats/{cid}")
async def chat_detail(cid:str):
    r=get_chat(cid)
    if not r:raise HTTPException(404,"Conversation not found")
    r["messages"]=json.loads(r["messages"]);return r
@app.put("/api/chats/{cid}")
async def chat_update(cid:str,payload:dict):
    if not get_chat(cid):raise HTTPException(404,"Conversation not found")
    msgs=payload.get("messages",[])
    if not isinstance(msgs,list):raise HTTPException(400,"messages must be a list")
    save_chat(cid,msgs,str(payload.get("model","")),payload.get("project_id"));return {"ok":True,"id":cid}
@app.patch("/api/chats/{cid}")
async def chat_rename(cid:str,payload:dict):
    title=str(payload.get("title","")).strip()
    if not title or len(title)>100:raise HTTPException(400,"Title must contain 1–100 characters.")
    with db() as c:
        cur=c.execute("UPDATE chats SET title=?,updated=? WHERE id=? AND device_id=?",(title,time.time(),cid,CURRENT_DEVICE.get()))
        if not cur.rowcount:raise HTTPException(404,"Conversation not found")
    return {"ok":True}
@app.patch("/api/chats/{cid}/pin")
async def chat_pin(cid:str,payload:dict):
    with db() as c:
        cur=c.execute("UPDATE chats SET pinned=?,updated=? WHERE id=? AND device_id=?",(int(bool(payload.get("pinned"))),time.time(),cid,CURRENT_DEVICE.get()))
        if not cur.rowcount: raise HTTPException(404,"Conversation not found")
    return {"ok":True,"pinned":bool(payload.get("pinned"))}
@app.delete("/api/chats/{cid}")
async def chat_delete(cid:str):
    with db() as c:c.execute("DELETE FROM chats WHERE id=? AND device_id=?",(cid,CURRENT_DEVICE.get()))
    return {"ok":True}
@app.get("/api/projects")
async def projects():
    with db() as c:return [dict(x) for x in c.execute("SELECT * FROM projects WHERE device_id=? ORDER BY updated DESC",(CURRENT_DEVICE.get(),))]
@app.post("/api/projects")
async def project_create(payload:dict):
    name=str(payload.get("name","")).strip()
    if not name or len(name)>70:raise HTTPException(400,"Project name must contain 1–70 characters.")
    slug=re.sub(r"[^A-Za-z0-9._-]+","-",name).strip(".-")[:60] or "project";path=(device_workspace()/"projects"/slug)
    if path.exists():slug+= "-"+uuid.uuid4().hex[:6];path=(device_workspace()/"projects"/slug)
    path.mkdir(parents=True,exist_ok=False);pid=uuid.uuid4().hex
    with db() as c:c.execute("INSERT INTO projects(id,name,path,created,updated,device_id) VALUES(?,?,?,?,?,?)",(pid,name,str(path),time.time(),time.time(),CURRENT_DEVICE.get()))
    return {"id":pid,"name":name,"path":str(path)}
@app.patch("/api/chats/{cid}/project")
async def chat_project(cid:str,payload:dict):
    pid=payload.get("project_id")
    with db() as c:
        if pid and not c.execute("SELECT id FROM projects WHERE id=? AND device_id=?",(pid,CURRENT_DEVICE.get())).fetchone():raise HTTPException(404,"Project not found")
        cur=c.execute("UPDATE chats SET project_id=?,updated=? WHERE id=? AND device_id=?",(pid,time.time(),cid,CURRENT_DEVICE.get()))
        if not cur.rowcount:raise HTTPException(404,"Conversation not found")
    return {"ok":True}
@app.get("/api/network/status")
async def network_status():
    port=int(os.environ.get("CANARRY_PORT","8080"))
    auth_enabled=bool(global_setting("network_auth_enabled",bool(ACCESS_PASSWORD)))
    with _tunnel_lock:
        tunnel={"provider":_tunnel_provider,"url":_tunnel_url,"running":bool(_tunnel_process and _tunnel_process.poll() is None),"error":_tunnel_error}
    return {"host":BIND_HOST,"port":port,"device":{"id":CURRENT_DEVICE.get(),"owner":CURRENT_DEVICE_OWNER.get()},"lan_urls":[f"http://{ip}:{port}" for ip in _lan_addresses()],"auth_enabled":auth_enabled,"username":str(global_setting("network_auth_username",ACCESS_USERNAME) or ACCESS_USERNAME) if auth_enabled else None,"tunnel":tunnel,"providers":{"cloudflare":shutil.which("cloudflared") is not None,"ngrok":shutil.which("ngrok") is not None,"tailscale":shutil.which("tailscale") is not None},"owner_device":CURRENT_DEVICE_OWNER.get()}

@app.put("/api/network/auth")
async def update_network_auth(payload:dict):
    if not CURRENT_DEVICE_OWNER.get():raise HTTPException(403,"Only the owner device can change global network authentication.")
    enabled=bool(payload.get("enabled",False))
    username=str(payload.get("username","")).strip()
    password=str(payload.get("password",""))
    if enabled:
        if not username or len(username)>80 or ":" in username:
            raise HTTPException(400,"Choose a username (1–80 characters; colon is not allowed).")
        if password:
            if len(password)<16:
                raise HTTPException(400,"Use a password with at least 16 characters.")
            set_global_setting("network_auth_password",password)
        else:
            existing=str(global_setting("network_auth_password",ACCESS_PASSWORD) or "")
            if not existing:
                raise HTTPException(400,"Enter a password to enable sign-in.")
        set_global_setting("network_auth_username",username)
    set_global_setting("network_auth_enabled",enabled)
    return {"ok":True,"enabled":enabled,"username":username if enabled else None}

@app.put("/api/network/tunnel/credentials")
async def network_tunnel_credentials(payload:dict):
    if not CURRENT_DEVICE_OWNER.get():raise HTTPException(403,"Worldwide provider credentials can only be managed by the owner device.")
    provider=str(payload.get("provider","")).lower()
    if provider not in {"ngrok","cloudflare"}:raise HTTPException(400,"Enter a token for ngrok or Cloudflare. Tailscale uses its existing signed-in CLI session.")
    token=str(payload.get("token","")).strip()
    if len(token)>4096:raise HTTPException(400,"Credential is too long.")
    hostname=""
    if provider=="cloudflare":
        hostname=str(payload.get("hostname","")).strip()
        if hostname and (not re.fullmatch(r"[A-Za-z0-9.-]+",hostname) or "." not in hostname):raise HTTPException(400,"Enter a valid tunnel hostname.")
        if token and not hostname:raise HTTPException(400,"A named Cloudflare tunnel token requires its configured public hostname.")
    if token:set_setting("tunnel_credential_"+provider,token)
    elif payload.get("clear") is True:set_setting("tunnel_credential_"+provider,"")
    if provider=="cloudflare" and hostname:set_setting("tunnel_hostname_cloudflare",hostname)
    return {"ok":True,"provider":provider,"configured":bool(setting("tunnel_credential_"+provider,""))}

@app.post("/api/network/tunnel/start")
async def network_tunnel_start(payload:dict):
    if not CURRENT_DEVICE_OWNER.get():raise HTTPException(403,"Only the owner device can control worldwide access.")
    provider=str(payload.get("provider","cloudflare"))
    return _start_tunnel(provider,int(os.environ.get("CANARRY_PORT","8080")))

@app.post("/api/network/tunnel/stop")
async def network_tunnel_stop():
    if not CURRENT_DEVICE_OWNER.get():raise HTTPException(403,"Only the owner device can control worldwide access.")
    return _stop_tunnel()

@app.get("/api/settings")
async def get_settings():
    p=provider_config()
    return {"memory_enabled":setting("memory_enabled",True),"temperature":setting("temperature",0.2),"theme":setting("theme","midnight"),"provider":{"type":p["type"],"base_url":p["base_url"],"has_api_key":bool(p.get("api_key")),"preset":p.get("preset","custom")},"max_upload_mb":50,"max_files_per_turn":MAX_FILES_PER_TURN,"image_model":setting("image_model","dall-e-3"),"system_prompt":setting("system_prompt",""),"max_output_tokens":setting("max_output_tokens",512),"enter_to_send":setting("enter_to_send",True),"compact_mode":setting("compact_mode",False),"default_agent":setting("default_agent",True),"auto_scroll":setting("auto_scroll",True),"mcp_servers":[_mcp_public(x) for x in _mcp_servers()],"harness_mode":device_harness_enabled(),"device_id":CURRENT_DEVICE.get(),"is_owner_device":CURRENT_DEVICE_OWNER.get(),"network_auth_enabled":bool(global_setting("network_auth_enabled",bool(ACCESS_PASSWORD))),"network_auth_username":str(global_setting("network_auth_username",ACCESS_USERNAME) or ACCESS_USERNAME),"tunnel_credentials":{"ngrok":bool(setting("tunnel_credential_ngrok","")),"cloudflare":bool(setting("tunnel_credential_cloudflare",""))} if CURRENT_DEVICE_OWNER.get() else {}}
@app.put("/api/settings")
async def update_settings(payload:dict):
    if "memory_enabled" in payload:set_setting("memory_enabled",bool(payload["memory_enabled"]))
    if "temperature" in payload:set_setting("temperature",max(0,min(2,float(payload["temperature"]))))
    if payload.get("theme") in {"midnight","graphite","aurora","light","candlelight"}:set_setting("theme",payload["theme"])
    if "image_model" in payload:set_setting("image_model",str(payload["image_model"]).strip()[:100] or "dall-e-3")
    if "system_prompt" in payload:set_setting("system_prompt",str(payload["system_prompt"])[:6000])
    if "max_output_tokens" in payload:set_setting("max_output_tokens",max(128,min(32768,int(payload["max_output_tokens"]))))
    for key in ("enter_to_send","compact_mode","default_agent","auto_scroll"):
        if key in payload:set_setting(key,bool(payload[key]))
    if "provider" in payload:
        incoming=payload["provider"] or {};old=provider_config();typ=incoming.get("type","ollama")
        if typ not in {"ollama","openai-compatible","anthropic","gemini"}:raise HTTPException(400,"Unsupported provider type.")
        defaults={"ollama":"http://127.0.0.1:11434","openai-compatible":"https://api.openai.com/v1","anthropic":"https://api.anthropic.com/v1","gemini":"https://generativelanguage.googleapis.com/v1beta"}
        base=str(incoming.get("base_url") or defaults[typ]).strip().rstrip("/")
        parsed=urllib.parse.urlsplit(base)
        if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:raise HTTPException(400,"API endpoint must be a valid HTTP(S) URL without embedded credentials or fragments.")
        key=incoming.get("api_key","")
        if not key and typ==old.get("type"): key=old.get("api_key","")
        key=str(key).strip()
        if len(key)>4096: raise HTTPException(400,"API key is too long.")
        set_setting("provider",{"type":typ,"preset":str(incoming.get("preset","custom"))[:40],"base_url":base,"api_key":key})
    return await get_settings()

@app.get("/api/mcp/servers")
async def mcp_servers(): return [_mcp_public(x) for x in _mcp_servers()]
@app.post("/api/mcp/servers")
async def mcp_server_create(payload:dict):
    name=str(payload.get("name","")).strip()[:70]; transport=payload.get("transport","stdio")
    if not name or transport not in {"stdio","http"}: raise HTTPException(400,"Name and a supported MCP transport are required.")
    cfg=payload.get("config",{})
    if not isinstance(cfg,dict): raise HTTPException(400,"MCP config must be an object.")
    if transport=="stdio":
        command=str(cfg.get("command","")).strip()
        if not command or len(command)>300: raise HTTPException(400,"Enter the MCP server executable.")
        cfg={"command":command,"args":cfg.get("args",[]),"env":cfg.get("env",{})}
        if not isinstance(cfg["args"],list) or len(cfg["args"])>40 or not isinstance(cfg["env"],dict): raise HTTPException(400,"Invalid stdio args or environment.")
    else:
        url=str(cfg.get("url","")).strip()
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment: raise HTTPException(400,"MCP URL must be a valid HTTP(S) URL without embedded credentials or fragments.")
        cfg={"url":url,"headers":cfg.get("headers",{})}
        if not isinstance(cfg["headers"],dict): raise HTTPException(400,"MCP headers must be an object.")
    sid=uuid.uuid4().hex
    with db() as c:c.execute("INSERT INTO mcp_servers(id,name,transport,config,enabled,created,updated,device_id) VALUES(?,?,?,?,?,?,?,?)",(sid,name,transport,_encrypt_device_value(json.dumps(cfg)),1,time.time(),time.time(),CURRENT_DEVICE.get()))
    return {"ok":True,"server":_mcp_public(next(x for x in _mcp_servers() if x["id"]==sid))}
@app.patch("/api/mcp/servers/{sid}")
async def mcp_server_update(sid:str,payload:dict):
    with db() as c: row=c.execute("SELECT * FROM mcp_servers WHERE id=? AND device_id=?",(sid,CURRENT_DEVICE.get())).fetchone()
    if not row: raise HTTPException(404,"MCP server not found")
    cfg=json.loads(_decrypt_device_value(row["config"])); incoming=payload.get("config")
    if isinstance(incoming,dict):
        if row["transport"]=="stdio":
            cfg.update({k:incoming[k] for k in ("command","args") if k in incoming})
            if incoming.get("env"):cfg["env"]=incoming["env"]
        else:
            cfg.update({k:incoming[k] for k in ("url","headers") if k in incoming})
            parsed=urllib.parse.urlsplit(cfg.get("url",""))
            if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:raise HTTPException(400,"MCP URL must be a valid HTTP(S) URL without embedded credentials or fragments.")
    with db() as c:c.execute("UPDATE mcp_servers SET name=?,config=?,enabled=?,updated=? WHERE id=? AND device_id=?",(str(payload.get("name",row["name"]))[:70],_encrypt_device_value(json.dumps(cfg)),int(bool(payload.get("enabled",row["enabled"]))),time.time(),sid,CURRENT_DEVICE.get()))
    return {"ok":True}
@app.delete("/api/mcp/servers/{sid}")
async def mcp_server_delete(sid:str):
    with db() as c:c.execute("DELETE FROM mcp_servers WHERE id=? AND device_id=?",(sid,CURRENT_DEVICE.get()))
    return {"ok":True}
@app.post("/api/mcp/servers/{sid}/test")
async def mcp_server_test(sid:str):
    with db() as c: row=c.execute("SELECT * FROM mcp_servers WHERE id=? AND device_id=?",(sid,CURRENT_DEVICE.get())).fetchone()
    if not row: raise HTTPException(404,"MCP server not found")
    try:
        result=await mcp_request(dict(row),"tools/list")
        return {"ok":True,"tool_count":len(result.get("tools",[])),"tools":[x.get("name") for x in result.get("tools",[])][:30]}
    except Exception as e: raise HTTPException(502,f"MCP connection failed: {e}")

@app.get("/api/memories")
async def memories():return memory_rows()
@app.post("/api/memories")
async def memory_create(payload:dict):
    content=str(payload.get("content","")).strip()
    if not content or len(content)>4000:raise HTTPException(400,"Memory must contain 1–4000 characters.")
    mid=add_memory(content,str(payload.get("category","general"))[:40]);return {"id":mid,"content":content}
@app.put("/api/memories/{mid}")
async def memory_edit(mid:str,payload:dict):
    content=str(payload.get("content","")).strip()
    if not content or len(content)>4000:raise HTTPException(400,"Memory must contain 1–4000 characters.")
    with db() as c:
        cur=c.execute("UPDATE memories SET content=?,category=?,updated=? WHERE id=? AND device_id=?",(content,str(payload.get("category","general"))[:40],time.time(),mid,CURRENT_DEVICE.get()))
        if not cur.rowcount:raise HTTPException(404,"Memory not found")
    return {"ok":True}
@app.delete("/api/memories/{mid}")
async def memory_delete(mid:str):
    with db() as c:c.execute("DELETE FROM memories WHERE id=? AND device_id=?",(mid,CURRENT_DEVICE.get()))
    return {"ok":True}

@app.get("/api/uploads")
async def uploads(chat_id:str|None=None):
    with db() as c:
        rows=c.execute("SELECT id,chat_id,name,mime,size,created FROM uploads WHERE device_id=? AND chat_id IS ? ORDER BY created DESC",(CURRENT_DEVICE.get(),chat_id)).fetchall() if chat_id else c.execute("SELECT id,chat_id,name,mime,size,created FROM uploads WHERE device_id=? ORDER BY created DESC",(CURRENT_DEVICE.get(),)).fetchall()
    return [dict(x) for x in rows]
@app.post("/api/uploads")
async def upload_file(file:UploadFile=File(...),chat_id:str|None=Form(None)):
    if chat_id and not get_chat(chat_id):raise HTTPException(404,"Conversation not found on this device.")
    name=Path(file.filename or "attachment").name;data=await file.read(MAX_UPLOAD+1)
    if len(data)>MAX_UPLOAD:raise HTTPException(413,"Maximum file size is 50 MB per file.")
    uid=uuid.uuid4().hex;safe_name=re.sub(r"[^A-Za-z0-9._-]","_",name)[:120] or "attachment";path=UPLOAD_DIR/f"{uid}_{safe_name}";path.write_bytes(data)
    extracted=extract_upload_text(path,name)
    archive_ext = name.lower().endswith((".zip",".7z",".rar",".tar",".gz",".tgz",".tar.gz",".tar.xz",".tar.bz2"))
    archive_file_count = 0
    if archive_ext:
        try:
            archive_root = device_workspace() / "attachments" / uid
            source_root = archive_root / "source"
            # Reject archive bombs before extraction where the format exposes member sizes.
            lower_name = name.lower()
            if lower_name.endswith(".zip"):
                with zipfile.ZipFile(path) as zf:
                    infos = [i for i in zf.infolist() if not i.is_dir()]
                    total_unpacked = sum(i.file_size for i in infos)
                    if len(infos) > 20000 or total_unpacked > 512 * 1024 * 1024:
                        raise ValueError("Archive expands beyond the 20,000-file / 512 MB safety limit.")
            archive_result = _extract_project_archive(path, source_root, name)
            archive_file_count = int(archive_result.get("files", 0))
            entries = []
            snippets = []
            text_ext = {".txt",".md",".py",".js",".ts",".tsx",".jsx",".json",".csv",".html",".css",".xml",".yaml",".yml",".toml",".rs",".go",".java",".c",".cpp",".h",".sh",".sql",".log",".ini",".conf",".lock"}
            used = 0
            for item in sorted(source_root.rglob("*"), key=lambda x: str(x).lower()):
                if item.is_symlink(): continue
                rel = item.relative_to(source_root).as_posix()
                if item.is_dir():
                    entries.append(rel + "/")
                    continue
                entries.append(f"{rel} ({item.stat().st_size} bytes)")
                if item.suffix.lower() in text_ext and used < 26000:
                    try:
                        content = item.read_text("utf-8", errors="replace")
                        content = content[:max(0, min(5000, 26000-used))]
                        if content.strip():
                            block = f"\n--- {rel} ---\n{content}\n"
                            snippets.append(block); used += len(block)
                    except OSError:
                        pass
            extracted = (
                f"[ARCHIVE EXTRACTED SUCCESSFULLY]\n"
                f"Archive: {name}\n"
                f"Extracted workspace path: attachments/{uid}/source\n"
                f"Files extracted: {sum(1 for x in source_root.rglob('*') if x.is_file())}\n"
                "File tree (directories end with /):\n" + "\n".join(entries[:4000]) +
                "\n\nText-file previews (use workspace tools to read complete files):\n" + "".join(snippets)
            )[:MAX_EXTRACT_CHARS]
        except Exception as e:
            extracted = f"[ARCHIVE EXTRACTION FAILED: {type(e).__name__}: {e}] The original archive remains attached at {path}."
    mime=file.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    with db() as c:c.execute("INSERT INTO uploads(id,chat_id,name,path,mime,size,extracted,created,device_id) VALUES(?,?,?,?,?,?,?,?,?)",(uid,chat_id,name,str(path),mime,len(data),extracted,time.time(),CURRENT_DEVICE.get()))
    archive_status = None
    if archive_ext:
        archive_ok = extracted.startswith("[ARCHIVE EXTRACTED SUCCESSFULLY]")
        archive_status = {"extracted": archive_ok, "files": archive_file_count,
                          "error": None if archive_ok else extracted[:1800]}
    return {"id":uid,"name":name,"size":len(data),"mime":mime,"extracted_chars":len(extracted),"is_image":mime.startswith("image/"),"archive":archive_status}
@app.get("/api/generated/{image_id}")
async def generated_image(image_id:str):
    if not re.fullmatch(r"[a-f0-9]{32}",image_id): raise HTTPException(404,"Image not found")
    with db() as c:row=c.execute("SELECT path FROM generated_images WHERE id=? AND device_id=?",(image_id,CURRENT_DEVICE.get())).fetchone()
    if not row or not Path(row["path"]).is_file(): raise HTTPException(404,"Image not found")
    return FileResponse(row["path"])

@app.delete("/api/uploads/{uid}")
async def upload_delete(uid:str):
    with db() as c:r=c.execute("SELECT path FROM uploads WHERE id=? AND device_id=?",(uid,CURRENT_DEVICE.get())).fetchone();c.execute("DELETE FROM uploads WHERE id=? AND device_id=?",(uid,CURRENT_DEVICE.get()))
    if r:
        try:Path(r["path"]).unlink(missing_ok=True)
        except OSError:pass
    return {"ok":True}

def load_attachment_images(ids):
    if not ids:return []
    with db() as c:
        q=",".join("?" for _ in ids);rows=c.execute(f"SELECT path,mime FROM uploads WHERE device_id=? AND id IN ({q})",[CURRENT_DEVICE.get(),*ids]).fetchall()
    out=[];budget=16*1024*1024
    for r in rows:
        if r["mime"].startswith("image/") and budget>0:
            try:
                raw=Path(r["path"]).read_bytes()
                if len(raw)<=min(8*1024*1024,budget):
                    out.append({"mime":r["mime"],"data":base64.b64encode(raw).decode()});budget-=len(raw)
            except OSError:pass
    return out

def openai_messages(history, image_ids_by_message):
    result=[]
    for m in history:
        role=m.get("role")
        if role not in {"system","user","assistant","tool"}:continue
        content=m.get("content","")
        if role=="user":
            ids=image_ids_by_message.get(id(m),[])
            if ids:
                parts=[{"type":"text","text":str(content)}]
                for im in load_attachment_images(ids):parts.append({"type":"image_url","image_url":{"url":f"data:{im['mime']};base64,{im['data']}"}})
                content=parts
        item={"role":role,"content":content}
        for k in ("tool_calls","tool_call_id","name"):
            if k in m:item[k]=m[k]
        result.append(item)
    return result


# Project Engineer: isolated source trees, archive handling and model-driven tools.
PROJECT_ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".tar.gz", ".tar.xz", ".tar.bz2"}
def _project_root() -> Path:
    base = device_workspace() / "engine-projects"
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()

def _safe_project_name(name: str) -> str:
    stem = Path(name).name
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "-", stem).strip(" .-_")
    return (stem[:70] or "project")

def _safe_archive_target(root: Path, member: str) -> Path:
    raw = Path(member.replace("\\", "/"))
    if raw.is_absolute() or any(part in {"..", ""} for part in raw.parts):
        raise ValueError(f"Unsafe archive path: {member}")
    target = (root / raw).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Archive path escapes project: {member}")
    return target

def _extract_project_archive(archive: Path, destination: Path, filename: str) -> dict:
    lower = filename.lower()
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    if lower.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                if info.is_dir(): continue
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000: raise ValueError("Symbolic links in archives are not extracted.")
                target = _safe_archive_target(destination, info.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as source, target.open("wb") as out: shutil.copyfileobj(source, out)
                count += 1
    elif lower.endswith(".7z"):
        try: import py7zr
        except ImportError: raise ValueError("7z support needs py7zr. Install it with: pip install py7zr")
        with py7zr.SevenZipFile(archive, mode="r") as z:
            for item in z.list():
                if item.is_directory: continue
                link_check=getattr(item,"is_symlink",False)
                if link_check() if callable(link_check) else link_check:
                    raise ValueError("Symbolic links in 7Z archives are not extracted.")
                _safe_archive_target(destination, item.filename)
            z.extractall(path=destination)
            count = sum(1 for x in destination.rglob("*") if x.is_file())
    elif lower.endswith(".rar"):
        try: import rarfile
        except ImportError: raise ValueError("RAR support needs rarfile and an extraction backend (unrar, unar or bsdtar).")
        with rarfile.RarFile(archive) as r:
            for item in r.infolist():
                if item.isdir(): continue
                _safe_archive_target(destination, item.filename)
                if item.is_symlink(): raise ValueError("Symbolic links in RAR archives are not extracted.")
            r.extractall(destination)
            count = sum(1 for x in destination.rglob("*") if x.is_file())
    elif lower.endswith((".tar", ".tar.gz", ".tgz", ".tar.xz", ".tar.bz2")):
        with tarfile.open(archive, "r:*") as t:
            for item in t.getmembers():
                if item.isdir(): continue
                if not item.isfile(): raise ValueError("Links and special files in TAR archives are not extracted.")
                _safe_archive_target(destination, item.name)
            for item in t.getmembers():
                if not item.isfile(): continue
                target = _safe_archive_target(destination, item.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                source = t.extractfile(item)
                if source is None: continue
                with source, target.open("wb") as out: shutil.copyfileobj(source, out)
                count += 1
    elif lower.endswith(".gz"):
        # A standalone .gz is decompressed into a file without the .gz suffix.
        target_name = Path(filename).name[:-3] or "decompressed"
        target = _safe_archive_target(destination, target_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(archive, "rb") as inp, target.open("wb") as out: shutil.copyfileobj(inp, out)
        count = 1
    else:
        raise ValueError("Supported project archives: ZIP, 7Z, RAR, TAR, TAR.GZ, TGZ, TAR.XZ, TAR.BZ2 and GZ.")
    return {"files": count, "path": str(destination)}

def _project_path(project_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", project_id or ""):
        raise HTTPException(400, "Invalid project identifier.")
    root = (_project_root() / project_id).resolve()
    if _project_root() not in root.parents or not root.is_dir():
        raise HTTPException(404, "Project workspace not found on this device.")
    return root

def _project_file(project: Path, relative: str) -> Path:
    target = (project / relative).resolve()
    if target != project and project not in target.parents:
        raise HTTPException(400, "Path escapes the imported project.")
    return target

@app.post("/api/engine/import")
async def engine_import(file: UploadFile = File(...)):
    if not device_harness_enabled():
        raise HTTPException(403, "Enable Harness mode on this device before importing and modifying project source archives.")
    filename = Path(file.filename or "project.zip").name
    lower = filename.lower()
    if not any(lower.endswith(ext) for ext in PROJECT_ARCHIVE_EXTENSIONS):
        raise HTTPException(415, "Unsupported archive format. Supported: ZIP, 7Z, RAR, TAR, GZ and compressed TAR.")
    pid = uuid.uuid4().hex
    project = _project_root() / pid
    project.mkdir(parents=True, exist_ok=False)
    archive = project.parent / (pid + Path(filename).suffix.lower())
    size = 0
    try:
        with archive.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_PROJECT_ARCHIVE: raise HTTPException(413, f"Archive exceeds configured {MAX_PROJECT_ARCHIVE // (1024*1024)} MB import limit.")
                out.write(chunk)
        extracted = project / "source"
        result = _extract_project_archive(archive, extracted, filename)
        (project/"project.json").write_text(json.dumps({"name":_safe_project_name(filename),"original_filename":filename,"created":time.time()},ensure_ascii=False),encoding="utf-8")
        archive.unlink(missing_ok=True)
        files = [str(x.relative_to(extracted)) for x in extracted.rglob("*") if x.is_file()]
        return {"id":pid,"name":_safe_project_name(filename),"files":result["files"],"root":"source","file_list":files[:5000],"workspace":str(project)}
    except Exception:
        shutil.rmtree(project, ignore_errors=True)
        archive.unlink(missing_ok=True)
        raise

@app.get("/api/engine/projects")
async def engine_projects():
    result=[]
    for folder in sorted(_project_root().iterdir(), key=lambda p:p.stat().st_mtime, reverse=True):
        if folder.is_dir() and re.fullmatch(r"[a-f0-9]{32}",folder.name):
            source=folder/"source"
            try: meta=json.loads((folder/"project.json").read_text(encoding="utf-8"))
            except Exception: meta={}
            result.append({"id":folder.name,"name":meta.get("name",folder.name),"files":sum(1 for x in source.rglob("*") if x.is_file()) if source.exists() else 0})
    return result

@app.get("/api/engine/project/{project_id}/files")
async def engine_project_files(project_id:str, path:str=".", recursive:bool=False):
    project=_project_path(project_id)/"source"; target=_project_file(project,path)
    if not target.exists(): raise HTTPException(404,"Path not found.")
    if target.is_file(): return {"path":path,"files":[{"path":path,"size":target.stat().st_size}]}
    items=target.rglob("*") if recursive else target.iterdir()
    return {"path":path,"files":[{"path":str(x.relative_to(project)),"directory":x.is_dir(),"size":x.stat().st_size if x.is_file() else 0} for x in sorted(items,key=lambda x:(not x.is_dir(),str(x).lower()))]}

@app.get("/api/engine/project/{project_id}/read")
async def engine_project_read(project_id:str, path:str):
    project=_project_path(project_id)/"source"; target=_project_file(project,path)
    if not target.is_file(): raise HTTPException(404,"File not found.")
    if target.stat().st_size > 8*1024*1024: raise HTTPException(413,"File exceeds 8 MB read limit; inspect it in smaller sections.")
    try: return {"path":path,"content":target.read_text(encoding="utf-8")}
    except UnicodeDecodeError: raise HTTPException(415,"File is not UTF-8 text.")

@app.put("/api/engine/project/{project_id}/write")
async def engine_project_write(project_id:str, payload:dict):
    project=_project_path(project_id)/"source"
    if not device_harness_enabled(): raise HTTPException(403,"Harness mode is disabled.")
    path=str(payload.get("path","")); content=payload.get("content")
    if not path or not isinstance(content,str): raise HTTPException(400,"Provide path and text content.")
    target=_project_file(project,path); target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(content,encoding="utf-8")
    return {"ok":True,"path":path,"bytes":target.stat().st_size}

@app.post("/api/engine/project/{project_id}/command")
async def engine_project_command(project_id:str, payload:dict):
    if not device_harness_enabled(): raise HTTPException(403,"Harness mode is disabled.")
    project=_project_path(project_id)/"source"
    command=payload.get("command")
    if isinstance(command,str): argv=shlex.split(command)
    elif isinstance(command,list): argv=[str(x) for x in command]
    else: raise HTTPException(400,"Provide a command string or argument array.")
    if not argv: raise HTTPException(400,"Empty command.")
    cwd=_project_file(project,str(payload.get("cwd",".")))
    if not cwd.is_dir(): raise HTTPException(400,"Working directory does not exist.")
    timeout=max(1,min(int(payload.get("timeout",900)),3600))
    try:
        proc=await asyncio.create_subprocess_exec(*argv,cwd=str(cwd),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
        output,_=await asyncio.wait_for(proc.communicate(),timeout=timeout)
        return {"returncode":proc.returncode,"output":output.decode("utf-8",errors="replace")[-120000:],"cwd":str(cwd),"command":argv}
    except asyncio.TimeoutError:
        proc.kill(); await proc.wait()
        return {"returncode":124,"output":f"Command timed out after {timeout} seconds.","command":argv}

@app.post("/api/engine/search")
async def engine_web_search(payload:dict):
    query=str(payload.get("query","")).strip()
    if not query: raise HTTPException(400,"Enter a search query.")
    try:
        from ddgs import DDGS
        results=await asyncio.to_thread(lambda: list(DDGS().text(query,max_results=max(1,min(int(payload.get("limit",8)),12)))))
        return {"results":[{"title":x.get("title",""),"url":x.get("href",""),"snippet":x.get("body","")} for x in results]}
    except ImportError: raise HTTPException(503,"Web search dependency is missing. Install requirements.txt (ddgs).")
    except Exception as e: raise HTTPException(502,f"Web search failed: {e}")

def _parse_engine_tool_request(content: str, allowed_names=None):
    """Accept native-style JSON tool requests emitted as plain text by small models."""
    if not content:
        return None
    candidates = []
    for match in re.finditer(r"<canarry_tool>\s*(.*?)\s*</canarry_tool>", content, re.S | re.I):
        candidates.append(match.group(1).strip())
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", content, re.I):
        candidates.append(match.group(1).strip())
    candidates.append(content.strip())
    # Find balanced JSON objects, so nested arguments/content objects are preserved.
    decoder = json.JSONDecoder()
    for pos, char in enumerate(content):
        if char == "{":
            try:
                obj, consumed = decoder.raw_decode(content[pos:])
                if isinstance(obj, dict) and consumed > 0:
                    candidates.append(content[pos:pos + consumed])
            except Exception:
                pass
    aliases = {
        "list_files":"project_list_files", "read_file":"project_read_file",
        "write_file":"project_write_file", "run_command":"project_run_command",
        "search_web":"web_search", "search":"web_search",
        "project_list_files":"project_list_files", "project_read_file":"project_read_file",
        "project_write_file":"project_write_file", "project_run_command":"project_run_command",
        "web_search":"web_search"
    }
    allowed = set(allowed_names or [])
    seen = set()
    for raw in candidates:
        if raw in seen: continue
        seen.add(raw)
        try: obj = json.loads(raw)
        except Exception: continue
        if not isinstance(obj, dict): continue
        fn = obj.get("function") if isinstance(obj.get("function"), dict) else obj
        name = fn.get("name")
        args = fn.get("arguments", obj.get("arguments", {}))
        if isinstance(args, str):
            try: args = json.loads(args)
            except Exception: args = {}
        if isinstance(name, str) and (name in aliases or name in allowed) and isinstance(args, dict):
            return {"id":uuid.uuid4().hex,"type":"function","function":{"name":aliases.get(name,name),"arguments":json.dumps(args,ensure_ascii=False)}}
    return None

@app.post("/api/engine/project/{project_id}/agent")
async def engine_project_agent(project_id:str, payload:dict):
    if not device_harness_enabled(): raise HTTPException(403,"Enable Harness mode on this device to let the agent inspect and modify project files and run project commands.")
    project_container=_project_path(project_id)
    project=project_container/"source"
    try: project_meta=json.loads((project_container/"project.json").read_text(encoding="utf-8"))
    except Exception: project_meta={}
    original_archive=str(project_meta.get("original_filename") or project_meta.get("name") or "the imported archive")
    initial_tree=[]
    ignored_tree_dirs={".git","node_modules","target","dist","build",".venv","venv","__pycache__",".pytest_cache",".mypy_cache"}
    total_tree_entries=0
    if project.exists():
        for item in sorted(project.rglob("*"),key=lambda x:str(x.relative_to(project)).lower()):
            rel=item.relative_to(project)
            if any(part in ignored_tree_dirs for part in rel.parts):
                continue
            total_tree_entries += 1
            if len(initial_tree) < 1200:
                initial_tree.append(str(rel) + ("/" if item.is_dir() else f" ({item.stat().st_size} bytes)"))
    p=provider_config(); model=str(payload.get("model") or "")
    task=str(payload.get("task") or "").strip()
    if not model or not task: raise HTTPException(400,"Select a model and enter a development task.")
    think=bool(payload.get("think",False))
    tools=[
      {"type":"function","function":{"name":"project_list_files","description":"List files and directories inside the imported project. By default list recursively so you can see the complete source tree; use a narrower path when needed.","parameters":{"type":"object","properties":{"path":{"type":"string","description":"Relative directory path; default ."},"recursive":{"type":"boolean","description":"List nested files recursively; defaults true."},"limit":{"type":"integer","description":"Maximum entries to return; defaults 1500."}}}}},
      {"type":"function","function":{"name":"project_read_file","description":"Read a UTF-8 text file from the imported project.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
      {"type":"function","function":{"name":"project_write_file","description":"Create or replace a UTF-8 text file in the imported project. Use for complete implementation, not just suggestions.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}},
      {"type":"function","function":{"name":"project_run_command","description":"Run a command in the imported project directory (for example npm test, cargo check, python -m pytest). Commands execute as the CanarryLookup host user.","parameters":{"type":"object","properties":{"command":{"type":"string"},"cwd":{"type":"string"},"timeout":{"type":"integer"}},"required":["command"]}}},
      {"type":"function","function":{"name":"web_search","description":"Search the public web for current documentation, issues, APIs and technical references. Return titles, URLs and snippets.","parameters":{"type":"object","properties":{"query":{"type":"string"},"limit":{"type":"integer"}},"required":["query"]}}}
    ]
    if not bool(payload.get("web_search", True)):
        tools=[t for t in tools if t["function"]["name"]!="web_search"]
    system=("You are an autonomous software engineering agent working on the user's imported project. "
      "Inspect the actual repository before changing it. Understand architecture and follow existing conventions. "
      "Implement the requested work as completely as your capabilities allow; do not artificially restrict yourself to tiny changes. "
      "Use project tools to read and edit actual files, run builds/tests, diagnose failures, and iterate. "
      "Use web_search when current external documentation or technical facts are useful. "
      "Use project-relative paths. The uploaded archive has ALREADY been extracted; do not pass the archive filename as a directory. "
      f"Original uploaded archive: {original_archive}. The actual project root is the extracted source directory; start with project_list_files(path='.') and use paths relative to that root. "
      f"Extracted repository tree ({min(total_tree_entries, len(initial_tree))} shown of {total_tree_entries} entries): {json.dumps(initial_tree, ensure_ascii=False)}. "
      "The only valid tool names are project_list_files, project_read_file, project_write_file, project_run_command and web_search. "
      "For Ollama models, use the text tool protocol: do NOT use native function/tool calls. When a tool is needed, output one complete compact JSON object only, with no markdown fence or explanation, in this exact shape: {\"name\":\"project_list_files\",\"arguments\":{\"path\":\".\",\"recursive\":true}}. Wait for the tool result before deciding the next action. Never truncate JSON. "
      "Preserve unrelated user work and data. Never claim a command, edit, or test succeeded unless tool output confirms it. "
      "Do not create changelogs, build notes, version context, or release notes unless the user explicitly asks. "
      "Do not stop after planning: carry out the implementation. If a task is too large for one context, prioritize coherent end-to-end implementation and report exactly what remains.")
    if think: system += "\nReason carefully through the repository and task before acting; use a deliberate inspect-plan-implement-test-review loop."
    async def events():
        nonlocal think
        history=[{"role":"system","content":system},{"role":"user","content":task}]
        try:
            # Ollama may spend many minutes evaluating a large prompt on low-end CPUs.
            # None disables HTTPX read/write/pool deadlines for local model requests;
            # connect still has a finite deadline so a missing server fails promptly.
            provider_timeout = (httpx.Timeout(None, connect=20) if p["type"] == "ollama"
                                else httpx.Timeout(3600, connect=20))
            async with httpx.AsyncClient(timeout=provider_timeout) as client:
                while True:
                    if p["type"]=="ollama":
                        # Small local coder models frequently emit malformed native tool-call
                        # argument JSON. Use the explicit text protocol above and parse a complete
                        # JSON object ourselves; this avoids Ollama's internal tool-argument parser.
                        body={"model":model,"messages":history,"stream":True,"options":{"temperature":0.1,"num_predict":8192}}
                        if think: body["think"]=True
                        async with client.stream("POST",f"{p['base_url']}/api/chat",json=body,headers=auth_headers(p)) as r:
                            if r.status_code>=400:
                                raw=(await r.aread()).decode(errors="replace")
                                if think and "think" in raw.lower():
                                    think=False; yield f"data: {json.dumps({'type':'notice','message':'Model/provider rejected thinking mode; continuing without it.'})}\n\n"; continue
                                yield f"data: {json.dumps({'type':'error','message':raw})}\n\n"; return
                            final={}; content=""
                            async for line in r.aiter_lines():
                                if not line: continue
                                try: chunk=json.loads(line)
                                except Exception: continue
                                if chunk.get("error"):
                                    yield f"data: {json.dumps({'type':'error','message':str(chunk.get('error'))})}\n\n"
                                    return
                                msg=chunk.get("message",{})
                                if msg.get("content"):
                                    content+=msg["content"]; yield f"data: {json.dumps({'type':'token','text':msg['content']})}\n\n"
                                if msg.get("tool_calls"): final.setdefault("tool_calls",[]).extend(msg["tool_calls"])
                                if chunk.get("done"): break
                        calls=final.get("tool_calls",[])
                    elif p["type"]=="openai-compatible":
                        body={"model":model,"messages":history,"stream":True,"tools":tools,"tool_choice":"auto","temperature":0.15,"max_tokens":8192}
                        async with client.stream("POST",f"{p['base_url']}/chat/completions",json=body,headers=auth_headers(p)) as r:
                            if r.status_code>=400:
                                yield f"data: {json.dumps({'type':'error','message':(await r.aread()).decode(errors='replace')})}\n\n"; return
                            acc={}; content=""
                            async for line in r.aiter_lines():
                                if not line or not line.startswith("data:"): continue
                                raw=line[5:].strip()
                                if raw=="[DONE]": break
                                try: chunk=json.loads(raw)
                                except Exception: continue
                                for choice in chunk.get("choices",[]):
                                    delta=choice.get("delta",{})
                                    if delta.get("content"):
                                        content+=delta["content"]; yield f"data: {json.dumps({'type':'token','text':delta['content']})}\n\n"
                                    for tc in delta.get("tool_calls",[]):
                                        entry=acc.setdefault(tc.get("index",0),{"id":"","type":"function","function":{"name":"","arguments":""}})
                                        if tc.get("id"):entry["id"]=tc["id"]
                                        entry["function"]["name"]+=tc.get("function",{}).get("name","")
                                        entry["function"]["arguments"]+=tc.get("function",{}).get("arguments","")
                            calls=list(acc.values())
                    else:
                        yield f"data: {json.dumps({'type':'error','message':'Project Engineer currently supports Ollama and OpenAI-compatible providers for tool-driven coding.'})}\n\n"; return
                    text_protocol_call=False
                    if not calls and content:
                        fallback=_parse_engine_tool_request(content)
                        if fallback:
                            calls=[fallback]
                            text_protocol_call=True
                            yield f"data: {json.dumps({'type':'clear_response'})}\n\n"
                        elif (content.lstrip().startswith(("{", "```json", "<canarry_tool>")) or re.match(r'(?is)^\s*\{\s*["\']name["\']\s*:',content)):
                            yield f"data: {json.dumps({'type':'notice','message':'The model produced incomplete tool JSON. Asking it to retry with a complete JSON object.'})}\n\n"
                            history.append({"role":"assistant","content":content})
                            history.append({"role":"user","content":"Your previous tool request was incomplete or invalid JSON and was not executed. Re-emit exactly one complete compact JSON object with both name and arguments. Close every brace and quote. Do not use markdown."})
                            continue
                    if not calls:
                        yield f"data: {json.dumps({'type':'done'})}\n\n"; return
                    if text_protocol_call:
                        history.append({"role":"assistant","content":content})
                    else:
                        history.append({"role":"assistant","content":content or None,"tool_calls":calls})
                    for call in calls:
                        fn=call.get("function",{}); name=fn.get("name","")
                        name={"list_files":"project_list_files","read_file":"project_read_file","write_file":"project_write_file","run_command":"project_run_command","search_web":"web_search","search":"web_search"}.get(name,name)
                        try: args=json.loads(fn.get("arguments") or "{}")
                        except Exception: args={}
                        try:
                            if name=="project_list_files":
                                requested_path=str(args.get("path",".")).strip()
                                # Older/smaller models sometimes mistake the uploaded ZIP name for a directory.
                                if requested_path in {original_archive, Path(original_archive).name, str(Path(original_archive).stem)}:
                                    requested_path="."
                                target=_project_file(project,requested_path)
                                if not target.exists():
                                    result={"error":f"Directory not found: {requested_path}. Use path='.' to list the extracted project root."}
                                elif not target.is_dir():
                                    result={"error":f"Not a directory: {requested_path}"}
                                else:
                                    recursive=bool(args.get("recursive",True))
                                    limit=max(50,min(int(args.get("limit",1500)),3000))
                                    candidates=target.rglob("*") if recursive else target.iterdir()
                                    ignored={".git","node_modules","target","dist","build",".venv","venv","__pycache__",".pytest_cache",".mypy_cache"}
                                    entries=[]; total=0
                                    for x in sorted(candidates,key=lambda q:str(q.relative_to(project)).lower()):
                                        rel=x.relative_to(project)
                                        if any(part in ignored for part in rel.parts): continue
                                        if x.is_symlink(): continue
                                        total+=1
                                        if len(entries)<limit:
                                            entries.append({"path":str(rel),"directory":x.is_dir(),"size":x.stat().st_size if x.is_file() else 0})
                                    result={"root":requested_path,"recursive":recursive,"entries":entries,"total_entries":total,"truncated":total>len(entries),"note":"Paths are relative to the extracted project root."}
                            elif name=="project_read_file":
                                target=_project_file(project,str(args.get("path","")))
                                if not target.is_file(): result={"error":"File not found"}
                                elif target.stat().st_size>8*1024*1024: result={"error":"File exceeds 8 MB; read a smaller file"}
                                else:
                                    try: result={"path":args["path"],"content":target.read_text(encoding="utf-8")}
                                    except UnicodeDecodeError: result={"error":"Binary/non-UTF8 file"}
                            elif name=="project_write_file":
                                target=_project_file(project,str(args.get("path","")))
                                if not args.get("path") or not isinstance(args.get("content"),str): result={"error":"path and string content required"}
                                else:
                                    target.parent.mkdir(parents=True,exist_ok=True); target.write_text(args["content"],encoding="utf-8")
                                    result={"ok":True,"path":args["path"],"bytes":target.stat().st_size}
                            elif name=="project_run_command":
                                argv=shlex.split(str(args.get("command","")))
                                cwd=_project_file(project,str(args.get("cwd",".")))
                                if not argv or not cwd.is_dir(): result={"error":"Invalid command or working directory"}
                                else:
                                    timeout=max(1,min(int(args.get("timeout",900)),3600))
                                    proc=await asyncio.create_subprocess_exec(*argv,cwd=str(cwd),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
                                    try: out,_=await asyncio.wait_for(proc.communicate(),timeout=timeout); result={"returncode":proc.returncode,"output":out.decode(errors="replace")[-120000:]}
                                    except asyncio.TimeoutError: proc.kill(); await proc.wait(); result={"returncode":124,"output":f"Timed out after {timeout}s"}
                            elif name=="web_search":
                                from ddgs import DDGS
                                rows=await asyncio.to_thread(lambda:list(DDGS().text(str(args.get("query","")),max_results=max(1,min(int(args.get("limit",8)),12)))))
                                result={"results":[{"title":x.get("title",""),"url":x.get("href",""),"snippet":x.get("body","")} for x in rows]}
                            else: result={"error":"Unknown tool"}
                        except Exception as e: result={"error":str(e)}
                        yield f"data: {json.dumps({'type':'tool','name':name,'arguments':args,'result':result},ensure_ascii=False)}\n\n"
                        if p["type"]=="ollama" and text_protocol_call:
                            history.append({"role":"user","content":f"Tool result from {name}: {json.dumps(result,ensure_ascii=False)}\nContinue inspecting or implementing the task. If another tool is needed, emit one complete JSON tool request."})
                        elif p["type"]=="ollama":
                            history.append({"role":"tool","name":name,"content":json.dumps(result,ensure_ascii=False)})
                        else:
                            history.append({"role":"tool","tool_call_id":call.get("id",""),"name":name,"content":json.dumps(result,ensure_ascii=False)})
                yield f"data: {json.dumps({'type':'done'})}\n\n"
        except Exception as e:
            detail=str(e).strip() or f"{type(e).__name__}: provider request failed without an error message"
            yield f"data: {json.dumps({'type':'error','message':detail})}\n\n"
    return StreamingResponse(events(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

def _project_export_files(project:Path):
    base=project.resolve()
    for item in project.rglob("*"):
        if not item.is_file() or item.is_symlink(): continue
        resolved=item.resolve()
        if resolved==base or base not in resolved.parents: continue
        yield item, item.relative_to(project)

@app.get("/api/engine/project/{project_id}/export")
async def engine_project_export(project_id:str, format:str="zip"):
    project=_project_path(project_id)/"source"
    fmt=format.lower()
    if fmt not in {"zip","7z","tar.gz","tar","rar"}: raise HTTPException(400,"Export formats: zip, 7z, tar, tar.gz or rar (requires the RAR command-line encoder).")
    tmp=Path(tempfile.mkdtemp(prefix="canarry-export-"))
    try:
        base=tmp/"project"
        if fmt=="zip":
            dest=tmp/"project.zip"
            with zipfile.ZipFile(dest,"w",zipfile.ZIP_DEFLATED) as z:
                for f,relative in _project_export_files(project):
                    z.write(f,relative)
        elif fmt=="7z":
            try: import py7zr
            except ImportError: raise HTTPException(503,"Install py7zr to export 7z archives.")
            dest=tmp/"project.7z"
            with py7zr.SevenZipFile(dest,"w") as z:
                for f,relative in _project_export_files(project): z.write(f,arcname=str(relative))
        elif fmt=="rar":
            rar=shutil.which("rar")
            if not rar: raise HTTPException(503,"RAR export requires the official rar command-line encoder. RAR import remains available with unrar/unar/bsdtar.")
            dest=tmp/"project.rar"
            staging=tmp/"rar-source"; staging.mkdir()
            for f,relative in _project_export_files(project):
                target=staging/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,target)
            run=subprocess.run([rar,"a","-r",str(dest), "."],cwd=str(staging),capture_output=True,text=True,timeout=600)
            if run.returncode: raise HTTPException(500,"RAR export failed: "+(run.stderr or run.stdout)[-3000:])
        else:
            dest=tmp/("project.tar.gz" if fmt=="tar.gz" else "project.tar")
            with tarfile.open(dest,"w:gz" if fmt=="tar.gz" else "w") as t:
                for f,relative in _project_export_files(project): t.add(f,arcname=str(relative),recursive=False)
        return FileResponse(dest,filename=dest.name,background=BackgroundTask(shutil.rmtree,tmp,ignore_errors=True))
    finally:
        # FileResponse streams after return; temp directory cleanup is handled by a response background task below.
        pass

@app.post("/api/chat")
async def chat(req:ChatRequest):
    p=provider_config();model=req.model
    if not model:raise HTTPException(400,"Choose a model first.")
    temperature=req.temperature if req.temperature is not None else setting("temperature",0.2)
    if req.chat_id and not get_chat(req.chat_id):raise HTTPException(404,"Conversation not found on this device.")
    cid=req.chat_id or uuid.uuid4().hex;history=[dict(m) for m in req.messages if m.get("role") in {"user","assistant"}][-MAX_CHAT_MESSAGES:]
    if not history:raise HTTPException(400,"No messages supplied.")
    latest=next((m for m in reversed(history) if m.get("role")=="user"),{});user_text=str(latest.get("content",""))
    match=re.search(r"(?i)^(?:please\s+)?remember(?:\s+that|\s+this)?\s*[:,-]?\s*(.{8,4000})$",user_text.strip(),re.S)
    if match and setting("memory_enabled",True):add_memory(match.group(1).strip(),"user-approved")
    image_ids_by_message={}
    archive_workspace_paths={}
    for msg in history:
        ids=msg.get("attachment_ids",[]) if isinstance(msg.get("attachment_ids",[]),list) else []
        if msg is history[-1]:ids=list(dict.fromkeys(ids+req.attachment_ids))
        if ids and msg.get("role")=="user":
            image_ids_by_message[id(msg)]=ids
            with db() as c:
                q=",".join("?" for _ in ids);attached=c.execute(f"SELECT id,name,extracted FROM uploads WHERE device_id=? AND id IN ({q})",[CURRENT_DEVICE.get(),*ids]).fetchall()
            remaining=MAX_ATTACHMENT_CONTEXT_CHARS;pieces=[]
            for a in attached:
                if str(a["extracted"]).startswith("[ARCHIVE EXTRACTED SUCCESSFULLY]"):
                    archive_workspace_paths[str(a["name"])]=f"attachments/{a['id']}/source"
                if remaining<=0:break
                piece=f"--- Attached file: {a['name']} ---\n{a['extracted']}"[:remaining];pieces.append(piece);remaining-=len(piece)
            context="\n\n".join(pieces)
            if context:msg["content"]=str(msg.get("content",""))+"\n\n[Attached file contents; context-limited]\n"+context
    memories=relevant_memories(user_text) if req.memory_enabled and setting("memory_enabled",True) else []
    system=("You are CanarryLookup AI, a helpful assistant. In agent mode you may use the supplied workspace tools. Be precise and verify actions. "
      "If an uploaded archive is marked ARCHIVE EXTRACTED SUCCESSFULLY, it has already been unpacked into the listed workspace path. Inspect its file tree and read actual files from that extracted path. NEVER pass the original .zip filename to list_files or claim the archive is opaque. "
      "\n"+setting("system_prompt","")).strip()
    mcp_tools=await available_mcp_tools() if req.agent else []
    harness_enabled=bool(device_harness_enabled())
    system_tools=TOOLS if harness_enabled else []
    if not harness_enabled:
        system += "\n\nOperating mode: NORMAL. Do not claim to access or modify this device, its filesystem, shell, desktop, or applications. System tools are disabled. You may use only the separately configured MCP integrations. Archive file trees and text previews are already included in the user's message; inspect those directly. Do not output raw JSON tool-call requests."
    else:
        if p["type"] == "ollama" and req.agent:
            available_names=[x["function"]["name"] for x in system_tools+mcp_tools if "function" in x]
            system += "\n\nOperating mode: HARNESS. For Ollama, do not use native function calling. Use the text tool protocol: when a tool is needed, emit exactly one complete compact JSON object only, with no markdown or explanation, shaped like {\"name\":\"list_files\",\"arguments\":{\"path\":\".\"}}. Available tool names: " + ", ".join(available_names) + ". Wait for the tool result in the next user message. Never output incomplete JSON."
        else:
            system += "\n\nOperating mode: HARNESS. If native tool calling is unavailable and you need a workspace tool, emit exactly one compact JSON object with name and arguments; the application will execute it and suppress the raw request from the visible answer."
    history.insert(0,{"role":"system","content":system})
    mcp_lookup={x["function"]["name"]:x["_mcp"] for x in mcp_tools if "function" in x}
    tool_defs=[{"type":"function","function":x["function"]} for x in mcp_tools if "function" in x]
    active_archive_root: str | None = None

    def resolve_uploaded_archive_path(requested: str) -> tuple[str | None, str | None]:
        """Resolve an archive filename emitted by a model to its extracted workspace directory.

        Prefer attachment IDs from this request, then fall back to this device's persisted
        upload records. This handles tool retries and chat history that lost inline IDs.
        """
        raw = str(requested or ".").strip().replace("\\", "/").rstrip("/")
        if raw.startswith("./"):
            raw = raw[2:]
        if not raw or raw == ".":
            return ".", None
        for archive_name, extracted_root in archive_workspace_paths.items():
            name = Path(archive_name).name
            for candidate in (archive_name, name, Path(name).stem):
                if raw == candidate:
                    return extracted_root, None
                if raw.startswith(candidate + "/"):
                    return extracted_root + "/" + raw[len(candidate)+1:], None
        basename = Path(raw).name
        with db() as c:
            rows = c.execute(
                "SELECT id,name,extracted FROM uploads WHERE device_id=? ORDER BY created DESC LIMIT 200",
                (CURRENT_DEVICE.get(),),
            ).fetchall()
        for row in rows:
            stored_name = Path(str(row["name"])).name
            if not stored_name.lower().endswith((".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".tar.xz", ".tar.bz2")):
                continue
            if raw in {str(row["name"]), stored_name, Path(stored_name).stem} or raw.startswith(stored_name + "/"):
                if not str(row["extracted"] or "").startswith("[ARCHIVE EXTRACTED SUCCESSFULLY]"):
                    detail = str(row["extracted"] or "Archive extraction did not produce an index.")[:1200]
                    return None, f"The uploaded archive '{stored_name}' is present, but extraction failed: {detail}"
                rel = f"attachments/{row['id']}/source"
                if raw.startswith(stored_name + "/"):
                    rel += "/" + raw[len(stored_name)+1:]
                if inside_workspace(rel).is_dir():
                    return rel, None
                return None, f"The archive index exists, but its extracted folder is missing: {rel}. Re-upload the archive to rebuild it."
        return None, f"No extracted upload named '{basename}' was found for this device. Attach the ZIP to this chat again, or import it in Project Engineer."

    def resolve_active_archive_relative_path(requested: str) -> str:
        raw = str(requested or ".").strip()
        if active_archive_root and raw not in {"", "."}:
            normalized = raw.replace("\\", "/").lstrip("/")
            candidate = f"{active_archive_root}/{normalized}"
            try:
                if inside_workspace(candidate).exists():
                    return candidate
            except Exception:
                pass
        return raw or "."

    async def run_agent_tool(name,args):
        nonlocal active_archive_root
        aliases={"project_list_files":"list_files","project_read_file":"read_file","project_write_file":"write_file","project_run_command":"run_command"}
        name=aliases.get(name,name)
        args=dict(args or {})
        if name == "list_files":
            requested = str(args.get("path", ".")).strip()
            if requested != ".":
                resolved, diagnostic = resolve_uploaded_archive_path(requested)
                if resolved:
                    args["path"] = resolved
                    # Remember the root so subsequent src/foo.js paths are archive-relative.
                    if resolved.startswith("attachments/") and resolved.endswith("/source"):
                        active_archive_root = resolved
                elif diagnostic and requested.lower().endswith((".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".tar.xz", ".tar.bz2")):
                    return {"error": diagnostic}
                else:
                    args["path"] = resolve_active_archive_relative_path(requested)
            elif active_archive_root:
                args["path"] = active_archive_root
        elif name in {"read_file", "write_file"} and args.get("path"):
            requested = str(args["path"])
            resolved, diagnostic = resolve_uploaded_archive_path(requested)
            if resolved:
                args["path"] = resolved
                if resolved.startswith("attachments/") and resolved.endswith("/source"):
                    active_archive_root = resolved
            elif diagnostic and requested.lower().endswith((".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".tar.xz", ".tar.bz2")):
                return {"error": diagnostic}
            else:
                args["path"] = resolve_active_archive_relative_path(requested)
        if name in mcp_lookup: return await invoke_mcp_tool(mcp_lookup[name],args)
        return invoke_tool(name,args) if harness_enabled else {"error":"System tools are disabled in Normal mode. Enable Harness mode on this device to grant direct system access."}
    async def events():
        try:
            # Do not time out local Ollama inference: prompt evaluation can be very slow
            # on older CPUs. Keep connection establishment bounded, but wait indefinitely
            # for response bytes. Cloud providers retain the existing 5-minute read limit.
            provider_timeout = (httpx.Timeout(None, connect=15) if p["type"] == "ollama"
                                else httpx.Timeout(300, connect=15))
            async with httpx.AsyncClient(timeout=provider_timeout,headers=auth_headers(p)) as client:
                if p["type"]=="ollama":
                    for msg in history:
                        if msg.get("role")=="user":
                            ims=load_attachment_images(image_ids_by_message.get(id(msg),[]))
                            if ims:msg["images"]=[x["data"] for x in ims]
                    for round_no in range(MAX_TOOL_ROUNDS+1):
                        payload={"model":model,"messages":[{k:v for k,v in m.items() if k in {"role","content","images","tool_calls","name"}} for m in history],"stream":True,"options":{"temperature":temperature,"num_predict":setting("max_output_tokens",512)}}
                        use_ollama_text_tools=bool(req.agent and harness_enabled and p["type"]=="ollama")
                        if req.agent and not use_ollama_text_tools:payload["tools"]=system_tools+tool_defs
                        async with client.stream("POST",f"{p['base_url']}/api/chat",json=payload) as response:
                            if response.status_code>=400:
                                body=await response.aread();yield f"data: {json.dumps({'type':'error','message':body.decode(errors='replace')})}\n\n";return
                            final={}; streamed_content=""
                            async for line in response.aiter_lines():
                                if not line:continue
                                try:chunk=json.loads(line)
                                except json.JSONDecodeError:continue
                                if chunk.get("error"):
                                    yield f"data: {json.dumps({'type':'error','message':str(chunk.get('error'))})}\n\n"
                                    return
                                msg=chunk.get("message",{})
                                if msg.get("content"):
                                    streamed_content += msg["content"]
                                    yield f"data: {json.dumps({'type':'token','text':msg['content']})}\n\n"
                                if msg.get("tool_calls"):final.setdefault("tool_calls",[]).extend(msg["tool_calls"])
                                if chunk.get("done"):break
                        calls=final.get("tool_calls",[])
                        text_protocol_call=False
                        if not calls and use_ollama_text_tools and streamed_content:
                            allowed_names=[x["function"]["name"] for x in system_tools+tool_defs if "function" in x]
                            fallback=_parse_engine_tool_request(streamed_content,allowed_names)
                            if fallback:
                                calls=[fallback]
                                text_protocol_call=True
                                yield f"data: {json.dumps({'type':'clear_response'})}\n\n"
                            elif (streamed_content.lstrip().startswith(("{", "```json", "<canarry_tool>")) or re.match(r'(?is)^\s*\{\s*["\']name["\']\s*:',streamed_content)):
                                history.append({"role":"assistant","content":streamed_content})
                                history.append({"role":"user","content":"Your previous tool request was incomplete or invalid JSON and was not executed. Re-emit exactly one complete compact JSON object with a valid tool name and arguments. Close every brace and quote. Do not use markdown."})
                                yield f"data: {json.dumps({'type':'notice','message':'The model emitted incomplete tool JSON. Asked it to retry with a complete request.'})}\n\n"
                                continue
                        elif not calls and req.agent and harness_enabled and streamed_content:
                            fallback=_parse_engine_tool_request(streamed_content,[x["function"]["name"] for x in system_tools+tool_defs if "function" in x])
                            if fallback:
                                calls=[fallback]
                                text_protocol_call=True
                                yield f"data: {json.dumps({'type':'clear_response'})}\n\n"
                        if not calls:break
                        if text_protocol_call:
                            history.append({"role":"assistant","content":streamed_content or ""})
                        else:
                            history.append({"role":"assistant","content":streamed_content or "", "tool_calls":calls})
                        for call in calls:
                            fn=call.get("function",{});name=fn.get("name","");args=fn.get("arguments",{}) or {}
                            if isinstance(args,str):
                                try:args=json.loads(args)
                                except Exception:args={}
                            result=await run_agent_tool(name,args);yield f"data: {json.dumps({'type':'tool','name':name,'arguments':args,'result':result})}\n\n"
                            if p["type"]=="ollama" and text_protocol_call:
                                history.append({"role":"user","content":f"Tool result from {name}: {json.dumps(result,ensure_ascii=False)}\nContinue the task. If another tool is needed, emit one complete JSON tool request."})
                            else:
                                history.append({"role":"tool","content":json.dumps(result,ensure_ascii=False),"name":name})
                        if round_no==MAX_TOOL_ROUNDS:yield f"data: {json.dumps({'type':'notice','message':'Agent tool-round limit reached.'})}\n\n"
                elif p["type"]=="anthropic":
                    anth_history=[]
                    for m in history:
                        if m["role"]=="system": continue
                        role="assistant" if m["role"]=="assistant" else "user"
                        content=m.get("content","")
                        if role=="user" and m.get("tool_call_id"):
                            content=[{"type":"tool_result","tool_use_id":m["tool_call_id"],"content":str(content)}]
                        elif role=="assistant" and m.get("tool_calls"):
                            content=[{"type":"tool_use","id":tc.get("id","tool"),"name":tc.get("function",{}).get("name",""),"input":json.loads(tc.get("function",{}).get("arguments") or "{}")} for tc in m["tool_calls"]]
                        if role=="user":
                            image_blocks=[]
                            for im in load_attachment_images(image_ids_by_message.get(id(m),[])):
                                image_blocks.append({"type":"image","source":{"type":"base64","media_type":im["mime"],"data":im["data"]}})
                            if image_blocks:
                                if isinstance(content,str): content=[{"type":"text","text":content}]
                                content.extend(image_blocks)
                        anth_history.append({"role":role,"content":content})
                    for round_no in range(MAX_TOOL_ROUNDS+1):
                        payload={"model":model,"max_tokens":setting("max_output_tokens",512),"temperature":temperature,"system":system,"messages":anth_history,"stream":True}
                        if req.agent: payload["tools"]=[{"name":t["function"]["name"],"description":t["function"].get("description",""),"input_schema":t["function"].get("parameters",{"type":"object","properties":{}})} for t in system_tools]+[{"name":t["function"]["name"],"description":t["function"].get("description",""),"input_schema":t["function"].get("parameters",{"type":"object","properties":{}})} for t in mcp_tools if "function" in t]
                        async with client.stream("POST",f"{p['base_url']}/messages",json=payload,headers=auth_headers(p)) as response:
                            if response.status_code>=400:
                                body=await response.aread();yield f"data: {json.dumps({'type':'error','message':body.decode(errors='replace')})}\n\n";return
                            blocks={}; stop_reason=None
                            async for line in response.aiter_lines():
                                if not line.startswith("data:"): continue
                                try: ev=json.loads(line[5:].strip())
                                except Exception: continue
                                typ=ev.get("type")
                                if typ=="content_block_start":
                                    idx=ev.get("index",0); block=ev.get("content_block",{}); blocks[idx]=block
                                    if block.get("type")=="tool_use": blocks[idx]["input"]={}
                                elif typ=="content_block_delta":
                                    idx=ev.get("index",0); delta=ev.get("delta",{})
                                    if delta.get("type")=="text_delta": yield f"data: {json.dumps({'type':'token','text':delta.get('text','')})}\n\n"
                                    elif delta.get("type")=="input_json_delta": blocks.setdefault(idx,{"type":"tool_use","input_json":""}).setdefault("input_json","");blocks[idx]["input_json"]+=delta.get("partial_json","")
                                elif typ=="message_delta": stop_reason=ev.get("delta",{}).get("stop_reason")
                        calls=[]
                        for b in blocks.values():
                            if b.get("type")=="tool_use":
                                args=b.get("input",{})
                                if b.get("input_json"):
                                    try:args=json.loads(b["input_json"])
                                    except Exception:args={}
                                calls.append({"id":b.get("id",""),"name":b.get("name",""),"input":args})
                        if not calls or stop_reason!="tool_use": break
                        anth_history.append({"role":"assistant","content":[{"type":"tool_use","id":x["id"],"name":x["name"],"input":x["input"]} for x in calls]})
                        results=[]
                        for call in calls:
                            result=await run_agent_tool(call["name"],call["input"]);yield f"data: {json.dumps({'type':'tool','name':call['name'],'arguments':call['input'],'result':result})}\n\n"
                            results.append({"type":"tool_result","tool_use_id":call["id"],"content":json.dumps(result,ensure_ascii=False)})
                        anth_history.append({"role":"user","content":results})
                elif p["type"]=="gemini":
                    gem_history=[]
                    for m in history:
                        if m["role"]=="system": continue
                        role="model" if m["role"]=="assistant" else "user"
                        text_content=str(m.get("content") or "")
                        parts=[{"text":text_content}] if text_content else []
                        if role=="user":
                            for im in load_attachment_images(image_ids_by_message.get(id(m),[])):
                                parts.append({"inlineData":{"mimeType":im["mime"],"data":im["data"]}})
                        if m.get("tool_calls"):
                            parts=[{"functionCall":{"name":tc.get("function",{}).get("name",""),"args":json.loads(tc.get("function",{}).get("arguments") or "{}")}} for tc in m["tool_calls"]]
                        if m.get("tool_call_id"):
                            try:parts=[{"functionResponse":{"name":m.get("name","tool"),"response":{"result":json.loads(text_content)}}}]
                            except Exception:parts=[{"functionResponse":{"name":m.get("name","tool"),"response":{"result":text_content}}}]
                        gem_history.append({"role":role,"parts":parts})
                    for round_no in range(MAX_TOOL_ROUNDS+1):
                        payload={"systemInstruction":{"parts":[{"text":system}]},"contents":gem_history,"generationConfig":{"temperature":temperature,"maxOutputTokens":setting("max_output_tokens",512)},"tools":[{"functionDeclarations":[{"name":t["function"]["name"],"description":t["function"].get("description",""),"parameters":t["function"].get("parameters",{"type":"object","properties":{}})} for t in system_tools]+[{"name":t["function"]["name"],"description":t["function"].get("description",""),"parameters":t["function"].get("parameters",{"type":"object","properties":{}})} for t in mcp_tools if "function" in t]}] if req.agent else []}
                        url=f"{p['base_url']}/models/{urllib.parse.quote(model,safe='')}:streamGenerateContent?alt=sse"
                        async with client.stream("POST",url,json=payload,headers=auth_headers(p)) as response:
                            if response.status_code>=400:
                                body=await response.aread();yield f"data: {json.dumps({'type':'error','message':body.decode(errors='replace')})}\n\n";return
                            calls=[]
                            async for line in response.aiter_lines():
                                if not line.startswith("data:"):continue
                                try:chunk=json.loads(line[5:].strip())
                                except Exception:continue
                                for cand in chunk.get("candidates",[]):
                                    for part in cand.get("content",{}).get("parts",[]):
                                        if part.get("text"):yield f"data: {json.dumps({'type':'token','text':part['text']})}\n\n"
                                        if part.get("functionCall"):calls.append(part["functionCall"])
                        if not calls:break
                        gem_history.append({"role":"model","parts":[{"functionCall":x} for x in calls]})
                        responses=[]
                        for call in calls:
                            result=await run_agent_tool(call.get("name",""),call.get("args",{}));yield f"data: {json.dumps({'type':'tool','name':call.get('name'),'arguments':call.get('args',{}),'result':result})}\n\n"
                            responses.append({"functionResponse":{"name":call.get("name",""),"response":{"result":result}}})
                        gem_history.append({"role":"user","parts":responses})
                else:
                    for round_no in range(MAX_TOOL_ROUNDS+1):
                        payload={"model":model,"messages":openai_messages(history,image_ids_by_message),"stream":True,"temperature":temperature,"stream_options":{"include_usage":True},"max_tokens":setting("max_output_tokens",512)}
                        if req.agent:payload["tools"]=[{"type":"function","function":t["function"]} for t in system_tools]+tool_defs;payload["tool_choice"]="auto"
                        async with client.stream("POST",f"{p['base_url']}/chat/completions",json=payload) as response:
                            if response.status_code>=400:
                                body=await response.aread();yield f"data: {json.dumps({'type':'error','message':body.decode(errors='replace')})}\n\n";return
                            tool_acc={};finish=None
                            async for line in response.aiter_lines():
                                if not line or not line.startswith("data:"):continue
                                raw=line[5:].strip()
                                if raw=="[DONE]":break
                                try:chunk=json.loads(raw)
                                except json.JSONDecodeError:continue
                                if chunk.get("error"):
                                    err=chunk.get("error")
                                    yield f"data: {json.dumps({'type':'error','message':str(err.get('message') if isinstance(err,dict) else err)})}\n\n"
                                    return
                                for choice in chunk.get("choices",[]):
                                    delta=choice.get("delta",{});finish=choice.get("finish_reason") or finish
                                    if delta.get("content"):yield f"data: {json.dumps({'type':'token','text':delta['content']})}\n\n"
                                    for tc in delta.get("tool_calls",[]):
                                        idx=tc.get("index",0);entry=tool_acc.setdefault(idx,{"id":"","type":"function","function":{"name":"","arguments":""}})
                                        if tc.get("id"):entry["id"]=tc["id"]
                                        fn=tc.get("function",{});entry["function"]["name"]+=fn.get("name","");entry["function"]["arguments"]+=fn.get("arguments","")
                        calls=list(tool_acc.values())
                        if not calls:break
                        history.append({"role":"assistant","content":None,"tool_calls":calls})
                        for call in calls:
                            fn=call["function"];name=fn["name"]
                            try:args=json.loads(fn["arguments"] or "{}")
                            except Exception:args={}
                            result=await run_agent_tool(name,args);yield f"data: {json.dumps({'type':'tool','name':name,'arguments':args,'result':result})}\n\n"
                            history.append({"role":"tool","tool_call_id":call["id"],"name":name,"content":json.dumps(result,ensure_ascii=False)})
                        if round_no==MAX_TOOL_ROUNDS:yield f"data: {json.dumps({'type':'notice','message':'Agent tool-round limit reached.'})}\n\n"
            yield f"data: {json.dumps({'type':'chat_id','chat_id':cid})}\n\n";yield f"data: {json.dumps({'type':'done'})}\n\n"
        except httpx.ConnectError:yield f"data: {json.dumps({'type':'error','message':f'Cannot connect to {p["type"]} provider at {p["base_url"]}. Check the endpoint and provider service.'})}\n\n"
        except Exception as e:
            detail=str(e).strip() or f"{type(e).__name__}: provider request failed without an error message"
            yield f"data: {json.dumps({'type':'error','message':detail})}\n\n"
    return StreamingResponse(events(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.post("/api/images/generations")
async def image_generation(payload:dict):
    p=provider_config();prompt=str(payload.get("prompt","")).strip();model=str(payload.get("model") or ("gemini-2.5-flash-image" if p["type"]=="gemini" else setting("image_model","dall-e-3")))
    if not prompt:raise HTTPException(400,"Enter an image prompt.")
    async with httpx.AsyncClient(timeout=180,headers=auth_headers(p)) as client:
        try:
            if p["type"]=="gemini":
                url=f"{p['base_url']}/models/{urllib.parse.quote(model,safe='')}:generateContent"
                body={"contents":[{"role":"user","parts":[{"text":prompt}]}],"generationConfig":{"responseModalities":["TEXT","IMAGE"]}}
                r=await client.post(url,json=body);r.raise_for_status();data=r.json()
                for candidate in data.get("candidates",[]):
                    for part in candidate.get("content",{}).get("parts",[]):
                        inline=part.get("inlineData") or part.get("inline_data")
                        if inline and inline.get("data"):
                            mime=inline.get("mimeType",inline.get("mime_type","image/png"))
                            ext={"image/png":"png","image/jpeg":"jpg","image/webp":"webp"}.get(mime)
                            if not ext: raise HTTPException(502,"Gemini returned an unsupported image MIME type.")
                            image_id=uuid.uuid4().hex; target=GENERATED_DIR/f"{image_id}.{ext}"
                            raw=base64.b64decode(inline["data"],validate=True)
                            if len(raw)>25*1024*1024: raise HTTPException(502,"Generated image exceeded the 25 MB limit.")
                            target.write_bytes(raw)
                            with db() as c:c.execute("INSERT INTO generated_images(id,path,device_id,created) VALUES(?,?,?,?)",(image_id,str(target),CURRENT_DEVICE.get(),time.time()))
                            try: os.chmod(target,0o600)
                            except OSError: pass
                            return {"url":f"/api/generated/{image_id}","provider":"gemini"}
                raise HTTPException(502,"Gemini returned no image. Check that the selected model supports image generation.")
            if p["type"]!="openai-compatible":raise HTTPException(400,"Image generation is supported here by Gemini image models and compatible image-generation APIs.")
            r=await client.post(f"{p['base_url']}/images/generations",json={"model":model,"prompt":prompt,"n":1,"size":payload.get("size","1024x1024"),"response_format":"url"});r.raise_for_status();return r.json()
        except httpx.HTTPStatusError as e:raise HTTPException(e.response.status_code,e.response.text)
        except HTTPException:raise
        except Exception as e:raise HTTPException(502,str(e))


if __name__ == "__main__":
    import argparse, uvicorn
    parser=argparse.ArgumentParser(description="CanarryLookup AI local and remote web server")
    parser.add_argument("--host",default=BIND_HOST,help="Bind address (default: CANARRY_HOST or 127.0.0.1)")
    parser.add_argument("--port",type=int,default=int(os.environ.get("CANARRY_PORT","8080")))
    parser.add_argument("--username",default=os.environ.get("CANARRY_ACCESS_USERNAME",""),help="Optional HTTP Basic username")
    parser.add_argument("--password",default=os.environ.get("CANARRY_ACCESS_PASSWORD",""),help="Optional HTTP Basic password")
    parser.add_argument("--tunnel",choices=["cloudflare","ngrok","tailscale"],help="Start a public tunnel after the app starts; requires auth")
    parser.add_argument("--pair-code",action="store_true",help="Generate a one-time device pairing code")
    parser.add_argument("--firewall-setup",action="store_true",help="Print safe platform-specific firewall setup instructions")
    parser.add_argument("--devices",action="store_true",help="List paired devices")
    parser.add_argument("--revoke-device",default="",help="Revoke a non-owner device by ID")
    args=parser.parse_args()
    if args.pair_code:
        code=secrets.token_urlsafe(12).replace("_","-")[:20]
        with db() as c:c.execute("INSERT INTO device_pair_codes(code_hash,created,expires,used) VALUES(?,?,?,0)",(hashlib.sha256(code.encode()).hexdigest(),time.time(),time.time()+600))
        print("One-time pairing code (valid 10 minutes):",code);sys.exit(0)
    if args.firewall_setup:
        print("Firewall scripts are in scripts/firewall/. Run only the script for your OS; LAN access is restricted to your private subnet by default.")
        sys.exit(0)
    if args.devices or args.revoke_device:
        with db() as c:
            if args.revoke_device:
                cur=c.execute("DELETE FROM devices WHERE id=? AND is_owner=0",(args.revoke_device,))
                print("Revoked." if cur.rowcount else "No matching non-owner device.")
            else:
                for row in c.execute("SELECT id,name,is_owner,paired,harness_mode,created FROM devices ORDER BY created"):
                    print(f"{row['id']}  {row['name']}  {'OWNER' if row['is_owner'] else ('PAIRED' if row['paired'] else 'UNPAIRED')}  {'HARNESS' if row['harness_mode'] else 'NORMAL'}")
        sys.exit(0)
    os.environ["CANARRY_HOST"]=args.host; os.environ["CANARRY_PORT"]=str(args.port)
    if args.username: os.environ["CANARRY_ACCESS_USERNAME"]=args.username
    if args.password: os.environ["CANARRY_ACCESS_PASSWORD"]=args.password
    if args.tunnel: os.environ["CANARRY_TUNNEL_PROVIDER"]=args.tunnel
    if not is_loopback_bind(args.host):
        print("[CanarryLookup] Local network addresses:")
        for address in _lan_addresses():
            print(f"  http://{address}:{args.port}")
        if not _lan_addresses():
            print("  No LAN IPv4 address detected; open Settings → Network access to refresh.")
        if not args.password and not os.environ.get("CANARRY_ACCESS_PASSWORD"):
            print("[CanarryLookup] Sign-in is OFF. Only use this on a trusted private LAN.")
    uvicorn.run("app:app",host=args.host,port=args.port,reload=False)

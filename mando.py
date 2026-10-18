#!/usr/bin/env python3
"""Mando para una Samsung Smart TV en la misma Wi-Fi.

Abre http://127.0.0.1:8765. La tele, la IP y el permiso se guardan en
config.json, en esta carpeta, y no salen del ordenador.
"""

import asyncio
import base64
import json
import re
import socket
import ssl
import threading
import time
import urllib.parse
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parent
PORT = 8765
BRANDS = {"samsung": "Samsung"}
IP_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
MAC_RE = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")

KEYS = {
    "KEY_POWER",
    "KEY_SOURCE",
    "KEY_VOLUP",
    "KEY_VOLDOWN",
    "KEY_MUTE",
    "KEY_CHUP",
    "KEY_CHDOWN",
    "KEY_CH_LIST",
    "KEY_PRECH",
    "KEY_TTX_MIX",
    "KEY_UP",
    "KEY_DOWN",
    "KEY_LEFT",
    "KEY_RIGHT",
    "KEY_ENTER",
    "KEY_RETURN",
    "KEY_HOME",
    "KEY_EXIT",
    "KEY_MENU",
    "KEY_GUIDE",
    "KEY_INFO",
    "KEY_TOOLS",
    "KEY_PMODE",
    "KEY_RED",
    "KEY_GREEN",
    "KEY_YELLOW",
    "KEY_CYAN",
    "KEY_REWIND",
    "KEY_FF",
    "KEY_PLAY",
    "KEY_PAUSE",
    *[f"KEY_{n}" for n in range(10)],
}

# Ids públicos de apps Samsung. Las ocho primeras salen en el mando; el resto se elige.
CATALOG = [
    {"id": "11101200001", "name": "Netflix"},
    {"id": "111299001912", "name": "YouTube"},
    {"id": "3201512006785", "name": "Prime Video"},
    {"id": "3201901017640", "name": "Disney+"},
    {"id": "3202301029760", "name": "HBO Max"},
    {"id": "3201606009684", "name": "Spotify"},
    {"id": "3201807016597", "name": "Apple TV"},
    {"id": "org.tizen.browser", "name": "Internet"},
    {"id": "141199000051", "name": "Movistar Plus"},
    {"id": "111399002179", "name": "Orange TV"},
    {"id": "11101300901", "name": "Atresplayer"},
    {"id": "3201904018214", "name": "RTVE Play"},
    {"id": "3201511006428", "name": "Rakuten TV"},
    {"id": "3201806016390", "name": "DAZN"},
    {"id": "3202208028071", "name": "SkyShowtime"},
    {"id": "3201804016094", "name": "Filmin"},
    {"id": "3201908019041", "name": "Apple Music"},
    {"id": "3201601007250", "name": "Google Play"},
    {"id": "11091000000", "name": "Facebook Watch"},
    {"id": "20182100002", "name": "e-Manual"},
]
DEFAULT_APPS = CATALOG[:8]
APP_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/favicon.ico": ("favicon.ico", "image/x-icon"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
}


def ssl_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def remote_url(ip: str, token: str = "") -> str:
    name = urllib.parse.quote(base64.b64encode(b"Mando").decode())
    url = f"wss://{ip}:8002/api/v2/channels/samsung.remote.control?name={name}"
    if token:
        url += "&token=" + urllib.parse.quote(token)
    return url


class Samsung:
    def __init__(self, ip: str, token: str, on_token=None):
        self.ip = ip
        self.token = token
        self.on_token = on_token
        self.connected = False
        self.error = "Conectando…"
        self.stop_flag = threading.Event()
        self._apps_wait = None
        self.loop = asyncio.new_event_loop()
        self.queue: asyncio.Queue | None = None
        self._ready = threading.Event()
        self.thread = threading.Thread(target=self._thread, daemon=True)
        self.thread.start()
        self._ready.wait(5)

    def _thread(self):
        asyncio.set_event_loop(self.loop)
        self.queue = asyncio.Queue()
        self._ready.set()
        self.loop.run_until_complete(self._main())

    def close(self):
        self.stop_flag.set()
        self.thread.join(timeout=2)
        self.connected = False

    async def _main(self):
        while not self.stop_flag.is_set():
            try:
                async with websockets.connect(
                    remote_url(self.ip, self.token),
                    ssl=ssl_context(),
                    open_timeout=8,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    hello = json.loads(await asyncio.wait_for(ws.recv(), 8))
                    if hello.get("event") != "ms.channel.connect":
                        raise ConnectionError(hello.get("event") or "conexion rechazada")
                    token = (hello.get("data") or {}).get("token")
                    if token and token != self.token:
                        self.token = token
                        if self.on_token:
                            self.on_token(token)
                    self.connected = True
                    self.error = ""
                    while not self.stop_flag.is_set():
                        if not self._apps_wait:
                            try:
                                payload = await asyncio.wait_for(self.queue.get(), 0.5)
                            except asyncio.TimeoutError:
                                continue
                            await ws.send(json.dumps(payload))
                            continue
                        incoming = asyncio.create_task(ws.recv())
                        outgoing = asyncio.create_task(self.queue.get())
                        done, _pending = await asyncio.wait(
                            {incoming, outgoing},
                            timeout=0.5,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if not done:
                            incoming.cancel()
                            outgoing.cancel()
                            continue
                        if incoming in done:
                            self._take_apps(json.loads(incoming.result()))
                        else:
                            incoming.cancel()
                        if outgoing in done:
                            await ws.send(json.dumps(outgoing.result()))
                        else:
                            outgoing.cancel()
            except Exception as exc:
                self.connected = False
                self.error = "La tele no responde. ¿Está encendida?"
                if self.stop_flag.is_set():
                    return
                print(f"conexion: {exc}")
                await asyncio.sleep(2)

    def _take_apps(self, data: dict):
        wait = self._apps_wait
        if not wait:
            return
        payload = data.get("data")
        apps = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(apps, list):
            return
        if apps and not (isinstance(apps[0], dict) and apps[0].get("appId")):
            return
        found = []
        for app in apps:
            app_id = str(app.get("appId") or "")
            if APP_ID_RE.match(app_id):
                found.append({"id": app_id, "name": app.get("name") or app_id})
        wait[0]["apps"] = found
        wait[1].set()

    def list_installed(self) -> list:
        if not self.connected:
            raise ConnectionError(self.error or "Sin conexion")
        box: dict = {}
        done = threading.Event()
        self._apps_wait = (box, done)
        try:
            self.send(
                {
                    "method": "ms.channel.emit",
                    "params": {"event": "ed.installedApp.get", "to": "host"},
                }
            )
            if not done.wait(6):
                raise ConnectionError("La tele no envió la lista de apps")
            return box.get("apps", [])
        finally:
            self._apps_wait = None

    def send(self, payload: dict):
        if not self.connected or self.queue is None:
            raise ConnectionError(self.error or "Sin conexion")
        asyncio.run_coroutine_threadsafe(self.queue.put(payload), self.loop).result(3)

    def key(self, key: str):
        self.send(
            {
                "method": "ms.remote.control",
                "params": {
                    "Cmd": "Click",
                    "DataOfCmd": key,
                    "Option": "false",
                    "TypeOfRemote": "SendRemoteKey",
                },
            }
        )

    def app(self, app_id: str):
        self.send(
            {
                "method": "ms.channel.emit",
                "params": {
                    "event": "ed.apps.launch",
                    "to": "host",
                    "data": {"appId": app_id, "action_type": "DEEP_LINK", "metaTag": ""},
                },
            }
        )


async def pair_samsung(ip: str) -> str:
    """Abre el aviso en la tele y espera a que lo acepten."""
    deadline = time.monotonic() + 50
    async with websockets.connect(
        remote_url(ip),
        ssl=ssl_context(),
        open_timeout=8,
        ping_interval=None,
    ) as ws:
        while time.monotonic() < deadline:
            raw = await asyncio.wait_for(ws.recv(), deadline - time.monotonic())
            data = json.loads(raw)
            token = (data.get("data") or {}).get("token")
            if data.get("event") == "ms.channel.connect" and token:
                return token
    raise TimeoutError("La tele no aceptó el permiso")


def wake(mac: str, ip: str):
    raw = bytes.fromhex(mac.replace(":", ""))
    packet = b"\xff" * 6 + raw * 16
    parts = ip.split(".")
    broadcast = ".".join(parts[:3] + ["255"])
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, 9))


class Hub:
    def __init__(self):
        self.lock = threading.Lock()
        self.path = ROOT / "config.json"
        self.data = self._load()
        self.remote: Samsung | None = None
        self.start_active()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        data = {"active": "", "tvs": []}
        self.path.write_text(json.dumps(data, indent=2))
        return data

    def _write(self):
        self.path.write_text(json.dumps(self.data, indent=2))

    def active(self) -> dict | None:
        for tv in self.data["tvs"]:
            if tv["id"] == self.data.get("active"):
                return tv
        return self.data["tvs"][0] if self.data["tvs"] else None

    def public(self) -> dict:
        active = (self.active() or {}).get("id")
        return {
            "active": active,
            "brands": BRANDS,
            "tvs": [
                {
                    "id": tv["id"],
                    "name": tv["name"],
                    "brand": tv["brand"],
                    "ip": tv["ip"],
                    "mac": tv.get("mac", ""),
                    "paired": bool(tv.get("token")),
                }
                for tv in self.data["tvs"]
            ],
        }

    def start_active(self):
        if self.remote:
            self.remote.close()
            self.remote = None
        tv = self.active()
        if not tv or not tv.get("token"):
            return
        tv_id = tv["id"]

        def remember(token, saved_id=tv_id):
            self.remember_token(saved_id, token)

        self.remote = Samsung(tv["ip"], tv["token"], on_token=remember)

    def remember_token(self, tv_id: str, token: str):
        with self.lock:
            for tv in self.data["tvs"]:
                if tv["id"] == tv_id:
                    tv["token"] = token
            self._write()

    def status(self) -> dict:
        tv = self.active()
        if not tv:
            return {"connected": False, "error": "Añade una tele en Ajustes", "name": "Mando", "brand": ""}
        if not tv.get("token"):
            return {
                "connected": False,
                "error": "Falta aceptar el permiso en la tele",
                "name": tv["name"],
                "brand": tv["brand"],
            }
        remote = self.remote
        return {
            "connected": bool(remote and remote.connected),
            "error": remote.error if remote else "Sin conexion",
            "name": tv["name"],
            "brand": tv["brand"],
        }

    def add(self, body: dict) -> dict:
        brand = body.get("brand") or "samsung"
        if brand not in BRANDS:
            raise ValueError("De momento solo se puede configurar una Samsung")
        name = str(body.get("name", "")).strip()
        ip = str(body.get("ip", "")).strip()
        mac = str(body.get("mac", "")).strip()
        if not name:
            raise ValueError("Falta el nombre")
        if not IP_RE.match(ip) or any(int(part) > 255 for part in ip.split(".")):
            raise ValueError("IP no válida")
        if mac and not MAC_RE.match(mac):
            raise ValueError("MAC no válida")
        tv = {
            "id": uuid.uuid4().hex[:8],
            "name": name,
            "brand": brand,
            "ip": ip,
            "mac": mac,
            "token": "",
        }
        with self.lock:
            self.data["tvs"].append(tv)
            if not self.data.get("active"):
                self.data["active"] = tv["id"]
            self._write()
        return tv

    def remove(self, tv_id: str):
        with self.lock:
            self.data["tvs"] = [tv for tv in self.data["tvs"] if tv["id"] != tv_id]
            if self.data.get("active") == tv_id:
                self.data["active"] = self.data["tvs"][0]["id"] if self.data["tvs"] else ""
            self._write()
        self.start_active()

    def use(self, tv_id: str):
        with self.lock:
            if not any(tv["id"] == tv_id for tv in self.data["tvs"]):
                raise KeyError(tv_id)
            self.data["active"] = tv_id
            self._write()
        self.start_active()

    def pair(self, tv_id: str):
        with self.lock:
            tv = next((item for item in self.data["tvs"] if item["id"] == tv_id), None)
            if not tv:
                raise KeyError(tv_id)
            ip = tv["ip"]
        if self.remote:
            self.remote.close()
            self.remote = None
        token = asyncio.run(pair_samsung(ip))
        self.remember_token(tv_id, token)
        self.start_active()

    def key(self, key: str):
        if not self.remote:
            raise ConnectionError(self.status()["error"])
        self.remote.key(key)

    def app(self, app_id: str):
        if not self.remote:
            raise ConnectionError(self.status()["error"])
        self.remote.app(app_id)

    def wake_active(self):
        tv = self.active()
        if not tv or not tv.get("mac"):
            raise ValueError("Esa tele no tiene MAC. Añádela en Ajustes para poder encenderla.")
        wake(tv["mac"], tv["ip"])

    def apps_view(self) -> dict:
        selected = self.data.get("apps") or DEFAULT_APPS
        return {"selected": selected, "catalog": CATALOG}

    def save_apps(self, body: dict):
        items = body.get("apps")
        if not isinstance(items, list):
            raise ValueError("Lista de apps no válida")
        clean = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("App no válida")
            app_id = str(item.get("id", "")).strip()
            name = str(item.get("name", "")).strip() or app_id
            if not APP_ID_RE.match(app_id):
                raise ValueError("Id de app no válido")
            if len(name) > 40 or app_id in seen:
                continue
            seen.add(app_id)
            clean.append({"id": app_id, "name": name})
        with self.lock:
            self.data["apps"] = clean
            self._write()

    def installed(self) -> list:
        if not self.remote:
            raise ConnectionError(self.status()["error"])
        return self.remote.list_installed()


class Handler(BaseHTTPRequestHandler):
    hub: Hub

    def log_message(self, fmt, *args):
        print(f"[mando] {self.address_string()} {fmt % args}", flush=True)

    def _json(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/status":
            self._json(200, self.hub.status())
            return
        if path == "/api/tvs":
            self._json(200, self.hub.public())
            return
        if path == "/api/apps":
            self._json(200, self.hub.apps_view())
            return
        if path == "/api/installed":
            try:
                self._json(200, {"apps": self.hub.installed()})
            except ConnectionError as exc:
                self._json(503, {"error": str(exc)})
            return
        static = FILES.get(path)
        if not static:
            self._json(404, {"error": "no encontrado"})
            return
        name, mime = static
        body = (ROOT / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        parts = [part for part in path.split("/") if part]
        try:
            body = self._read()
            if path == "/api/key":
                key = body.get("key", "")
                if key not in KEYS:
                    self._json(400, {"error": "tecla no permitida"})
                    return
                self.hub.key(key)
            elif path == "/api/app":
                app_id = str(body.get("id", "")).strip()
                if not APP_ID_RE.match(app_id):
                    self._json(400, {"error": "app no válida"})
                    return
                self.hub.app(app_id)
            elif path == "/api/apps":
                self.hub.save_apps(body)
            elif path == "/api/wake":
                self.hub.wake_active()
            elif parts == ["api", "tvs"]:
                self.hub.add(body)
            elif len(parts) == 4 and parts[:2] == ["api", "tvs"] and parts[3] == "pair":
                self.hub.pair(parts[2])
            elif len(parts) == 4 and parts[:2] == ["api", "tvs"] and parts[3] == "active":
                self.hub.use(parts[2])
            else:
                self._json(404, {"error": "no encontrado"})
                return
            self._json(200, {"ok": True})
        except (ConnectionError, TimeoutError, ValueError) as exc:
            self._json(503 if isinstance(exc, ConnectionError) else 400, {"error": str(exc)})
        except KeyError:
            self._json(404, {"error": "tele no encontrada"})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def do_DELETE(self):
        parts = [part for part in urllib.parse.urlparse(self.path).path.split("/") if part]
        if len(parts) == 3 and parts[:2] == ["api", "tvs"]:
            self.hub.remove(parts[2])
            self._json(200, {"ok": True})
            return
        self._json(404, {"error": "no encontrado"})


def main():
    Handler.hub = Hub()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    webbrowser.open(url)
    print(f"Mando en {url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado")


if __name__ == "__main__":
    main()

"""WebSocket en el VPS: el agente de casa se conecta hacia aquí."""

import asyncio
import json
import os
import threading
import uuid

import websockets
from websockets.exceptions import ConnectionClosed


class AgentServer:
    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._waiters: dict[str, threading.Event] = {}
        self._results: dict[str, dict] = {}
        self._token_cb = None
        self._on_connect = None

    def set_token_callback(self, cb):
        self._token_cb = cb

    def set_on_connect(self, cb):
        self._on_connect = cb

    def start(self):
        if self._thread:
            return

        def run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._serve())

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    async def _serve(self):
        port = int(os.environ.get("AGENT_PORT", "8766"))

        async def handler(websocket):
            if not self._auth(websocket):
                await websocket.close(4401, "token invalido")
                return
            self._ws = websocket
            print("[agent] casa conectada", flush=True)
            if self._on_connect:
                try:
                    self._on_connect()
                except Exception as exc:
                    print(f"[agent] on_connect: {exc}", flush=True)
            try:
                async for raw in websocket:
                    msg = json.loads(raw)
                    if msg.get("type") == "event" and msg.get("event") == "token":
                        if self._token_cb:
                            self._token_cb(msg.get("token", ""))
                        continue
                    if msg.get("type") != "result":
                        continue
                    rid = msg.get("id")
                    if not rid:
                        continue
                    with self._lock:
                        self._results[rid] = msg
                        ev = self._waiters.get(rid)
                    if ev:
                        ev.set()
            except ConnectionClosed:
                pass
            finally:
                self._ws = None
                print("[agent] casa desconectada", flush=True)

        async with websockets.serve(handler, "0.0.0.0", port):
            print(f"[agent] escuchando en 0.0.0.0:{port}", flush=True)
            await asyncio.Future()

    def _auth(self, websocket) -> bool:
        expected = os.environ.get("AGENT_TOKEN", "")
        if not expected:
            return True
        query = websocket.request.path.split("?", 1)
        params = {}
        if len(query) > 1:
            for part in query[1].split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k] = v
        token = params.get("token") or websocket.request.headers.get("X-Agent-Token", "")
        return token == expected

    def is_connected(self) -> bool:
        return self._ws is not None

    def call(self, op: str, payload: dict | None = None, timeout: float = 60) -> dict:
        if not self._ws or not self._loop:
            raise ConnectionError(
                "Agente de casa desconectado. Arranca home_agent.py en un PC de tu Wi-Fi."
            )
        rid = uuid.uuid4().hex
        ev = threading.Event()
        with self._lock:
            self._waiters[rid] = ev
        msg = {"id": rid, "op": op, **(payload or {})}
        fut = asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(msg)), self._loop)
        fut.result(5)
        if not ev.wait(timeout):
            with self._lock:
                self._waiters.pop(rid, None)
            raise TimeoutError("La casa no respondió a tiempo")
        with self._lock:
            res = self._results.pop(rid, {})
            self._waiters.pop(rid, None)
        if not res.get("ok"):
            raise ConnectionError(res.get("error") or "Error del agente en casa")
        return res


registry = AgentServer()

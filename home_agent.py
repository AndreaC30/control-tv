#!/usr/bin/env python3
"""Agente en casa: conecta al VPS y manda las órdenes a la Samsung en la Wi-Fi local."""

import asyncio
import json
import os
import ssl
import sys
from urllib.parse import urlencode

import certifi
import websockets

from mando import Samsung, pair_samsung, wake


def tls_context() -> ssl.SSLContext:
    """CA de certifi: en macOS el Python de python.org suele no traer certificados."""
    return ssl.create_default_context(cafile=certifi.where())


class LocalSession:
    def __init__(self):
        self.remote: Samsung | None = None
        self.ip = ""
        self.token = ""

    def close(self):
        if self.remote:
            self.remote.close()
            self.remote = None

    def start(self, ip: str, token: str, on_token):
        self.close()
        self.ip = ip
        self.token = token or ""
        if not self.token:
            return {"connected": False, "error": "Falta permiso en la tele"}
        self.remote = Samsung(ip, self.token, on_token=on_token)
        for _ in range(20):
            if self.remote.connected:
                return {"connected": True, "error": ""}
            if self.remote.error and self.remote.error != "Conectando…":
                break
            import time

            time.sleep(0.25)
        return {
            "connected": bool(self.remote and self.remote.connected),
            "error": (self.remote.error if self.remote else "Sin conexion"),
        }

    def status(self) -> dict:
        if not self.remote:
            return {"connected": False, "error": "Sin sesion con la tele"}
        return {
            "connected": self.remote.connected,
            "error": self.remote.error or "",
        }


async def run():
    base = os.environ.get("MANDO_AGENT_URL", "wss://mandotv.kyadigital.es/agent/ws")
    token = os.environ.get("MANDO_AGENT_TOKEN", "")
    if not token:
        print("Falta MANDO_AGENT_TOKEN", file=sys.stderr)
        sys.exit(1)
    sep = "&" if "?" in base else "?"
    url = f"{base}{sep}{urlencode({'token': token})}"
    session = LocalSession()
    loop = asyncio.get_running_loop()

    while True:
        try:
            print(f"Conectando a {base}…", flush=True)
            async with websockets.connect(
                url,
                ssl=tls_context(),
                ping_interval=20,
                ping_timeout=20,
            ) as ws:
                print("Agente en linea. Deja este programa abierto.", flush=True)

                def on_token(t):
                    asyncio.run_coroutine_threadsafe(
                        ws.send(json.dumps({"type": "event", "event": "token", "token": t})),
                        loop,
                    )

                async for raw in ws:
                    req = json.loads(raw)
                    rid = req.get("id")
                    op = req.get("op")
                    try:
                        if op == "session_start":
                            data = session.start(req.get("ip", ""), req.get("token", ""), on_token)
                            await ws.send(json.dumps({"type": "result", "id": rid, "ok": True, **data}))
                        elif op == "session_stop":
                            session.close()
                            await ws.send(json.dumps({"type": "result", "id": rid, "ok": True}))
                        elif op == "status":
                            data = session.status()
                            await ws.send(json.dumps({"type": "result", "id": rid, "ok": True, **data}))
                        elif op == "pair":
                            tok = await pair_samsung(req.get("ip", ""))
                            await ws.send(
                                json.dumps({"type": "result", "id": rid, "ok": True, "token": tok})
                            )
                        elif op == "key":
                            if not session.remote:
                                raise ConnectionError("Sin conexion con la tele")
                            session.remote.key(req["key"])
                            await ws.send(json.dumps({"type": "result", "id": rid, "ok": True}))
                        elif op == "app":
                            if not session.remote:
                                raise ConnectionError("Sin conexion con la tele")
                            session.remote.app(req["app_id"])
                            await ws.send(json.dumps({"type": "result", "id": rid, "ok": True}))
                        elif op == "installed":
                            if not session.remote:
                                raise ConnectionError("Sin conexion con la tele")
                            apps = session.remote.list_installed()
                            await ws.send(
                                json.dumps({"type": "result", "id": rid, "ok": True, "apps": apps})
                            )
                        elif op == "wake":
                            wake(req.get("mac", ""), req.get("ip", ""))
                            await ws.send(json.dumps({"type": "result", "id": rid, "ok": True}))
                        else:
                            raise ValueError(f"op desconocida: {op}")
                    except Exception as exc:
                        await ws.send(
                            json.dumps(
                                {"type": "result", "id": rid, "ok": False, "error": str(exc)}
                            )
                        )
        except Exception as exc:
            print(f"Reconectando en 5s ({exc})", flush=True)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())

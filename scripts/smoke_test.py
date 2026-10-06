#!/usr/bin/env python3
"""Смоук-тест сервера: WebSocket-поток, ручной ордер, автоторговля. Запуск: python scripts/smoke_test.py (сервер на :8000)."""
import asyncio, json, time, urllib.request
import websockets

def post(path, body=None):
    req = urllib.request.Request("http://localhost:8000" + path, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()}

async def main(sym):
    async with websockets.connect(f"ws://localhost:8000/ws/{sym}") as ws:
        snap = json.loads(await ws.recv())
        print(sym, "snapshot:", snap["type"], "candles", len(snap["candles"]), "signal", snap["signal"] and {k: snap["signal"][k] for k in ("action","confidence","p_up")})
        counts = {}
        r = post(f"/api/{sym}/order", {"side": "buy", "qty": snap["default_qty"]})
        print("order:", r.get("ok"), r.get("position_id"), r.get("http_error"))
        t0 = time.time(); actions = []
        while time.time() - t0 < 4:
            m = json.loads(await ws.recv()); counts[m["type"]] = counts.get(m["type"], 0) + 1
            if m["type"] == "candle" and m["signal"]: actions.append(m["signal"]["action"])
        print("msgs:", counts, "actions:", actions[:12])
        print("close_all:", post(f"/api/{sym}/close_all")["closed"])
        print("mode auto:", post(f"/api/{sym}/mode", {"mode": "auto"}))
        t0 = time.time(); last = None
        while time.time() - t0 < 6:
            m = json.loads(await ws.recv())
            if m["type"] == "candle": last = m
        a = last["account"]
        print("after auto: equity %.2f trades %d positions %d stats %s" % (a["equity"], a["stats"]["trades"], len(a["positions"]), {k: round(v,3) for k,v in a["stats"].items()}))
        print("bot log:", [x["message"] for x in last["bot_log"][-3:]])
        print("mode manual:", post(f"/api/{sym}/mode", {"mode": "manual"}))
        print("bad order:", post(f"/api/{sym}/order", {"side": "buy", "qty": 1e9}))
if __name__ == "__main__":
    import sys
    for sym in (sys.argv[1:] or ["EURUSD", "NVDA", "SYNTH"]):
        asyncio.run(main(sym))

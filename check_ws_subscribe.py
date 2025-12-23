import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import websockets


DEFAULT_WS_URL = "wss://wbs.mexc.com/ws"
DEFAULT_ORIGIN = "https://www.mexc.com"
DEFAULT_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _now() -> float:
    return time.time()


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


async def _send_subscriptions(ws, symbol: str, depth_levels: int, trades: bool) -> None:
    await ws.send(
        _json_dumps(
            {
                "method": "SUBSCRIPTION",
                "params": [f"spot@public.limit.depth.v3.api@{symbol}@{depth_levels}"],
            }
        )
    )
    if trades:
        await ws.send(
            _json_dumps(
                {
                    "method": "SUBSCRIPTION",
                    "params": [f"spot@public.deals.v3.api@{symbol}"],
                }
            )
        )


def _maybe_parse_json(msg: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(msg, (str, bytes)):
        return None
    if isinstance(msg, bytes):
        try:
            msg = msg.decode("utf-8", errors="replace")
        except Exception:
            return None
    try:
        return json.loads(msg)
    except Exception:
        return None


@dataclass
class Stats:
    start_ts: float
    last_msg_ts: float
    msg_count: int = 0
    depth_count: int = 0
    trade_count: int = 0
    ping_count: int = 0
    pong_count: int = 0


async def run(url: str, symbol: str, origin: str, user_agent: str, duration_s: int, depth_levels: int, trades: bool) -> int:
    headers = {"User-Agent": user_agent, "Origin": origin}
    stats = Stats(start_ts=_now(), last_msg_ts=_now())

    print("MEXC WS long-connection subscribe test")
    print(f"- url: {url}")
    print(f"- symbol: {symbol}")
    print(f"- depth_levels: {depth_levels}")
    print(f"- trades: {trades}")
    print(f"- duration_s: {duration_s}")
    print("")

    try:
        connect_kwargs = dict(
            close_timeout=5,
            ping_interval=15,
            ping_timeout=10,
        )

        # websockets 版本的 header 参数名不同：优先 additional_headers，再回退 extra_headers
        try:
            ws_cm = websockets.connect(url, **connect_kwargs, additional_headers=headers)
        except TypeError:
            ws_cm = websockets.connect(url, **connect_kwargs, extra_headers=headers)

        async with ws_cm as ws:
            print(f"[{time.strftime('%H:%M:%S')}] ✅ connected")
            await _send_subscriptions(ws, symbol, depth_levels=depth_levels, trades=trades)
            print(f"[{time.strftime('%H:%M:%S')}] ✅ subscribed")

            end_ts = _now() + duration_s
            last_report = _now()

            while _now() < end_ts:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=20)
                except asyncio.TimeoutError:
                    # Keepalive / stall detection
                    print(f"[{time.strftime('%H:%M:%S')}] ⚠️ no message for 20s (still connected)")
                    continue

                stats.msg_count += 1
                stats.last_msg_ts = _now()

                # Heartbeat compatibility
                if msg == "ping":
                    stats.ping_count += 1
                    await ws.send("pong")
                    stats.pong_count += 1
                    continue

                data = _maybe_parse_json(msg)
                if isinstance(data, dict):
                    if data.get("msg") == "ping":
                        stats.ping_count += 1
                        await ws.send(_json_dumps({"msg": "pong"}))
                        stats.pong_count += 1
                        continue
                    if "ping" in data:
                        stats.ping_count += 1
                        await ws.send(_json_dumps({"pong": data.get("ping")}))
                        stats.pong_count += 1
                        continue

                    channel = data.get("c")
                    if isinstance(channel, str) and "limit.depth" in channel:
                        stats.depth_count += 1
                    if isinstance(channel, str) and "deals" in channel:
                        stats.trade_count += 1

                # periodic report
                if _now() - last_report >= 10:
                    up = _now() - stats.start_ts
                    rate = stats.msg_count / up if up > 0 else 0.0
                    print(
                        f"[{time.strftime('%H:%M:%S')}] msgs={stats.msg_count} rate={rate:.1f}/s depth={stats.depth_count} trades={stats.trade_count} ping={stats.ping_count}"
                    )
                    last_report = _now()

            print(f"[{time.strftime('%H:%M:%S')}] ✅ finished without disconnect")
            return 0

    except websockets.exceptions.ConnectionClosed as e:
        up = _now() - stats.start_ts
        print(f"[{time.strftime('%H:%M:%S')}] ❌ disconnected after {up:.1f}s: code={getattr(e, 'code', None)} reason={getattr(e, 'reason', None)}")
        return 2
    except Exception as e:
        up = _now() - stats.start_ts
        print(f"[{time.strftime('%H:%M:%S')}] ❌ error after {up:.1f}s: {e}")
        return 1
    finally:
        up = _now() - stats.start_ts
        idle = _now() - stats.last_msg_ts
        rate = stats.msg_count / up if up > 0 else 0.0
        print("")
        print("Summary")
        print(f"- uptime_s: {up:.1f}")
        print(f"- last_msg_idle_s: {idle:.1f}")
        print(f"- msg_count: {stats.msg_count} ({rate:.2f}/s)")
        print(f"- depth_count: {stats.depth_count}")
        print(f"- trade_count: {stats.trade_count}")
        print(f"- ping_count: {stats.ping_count}")


def main() -> int:
    p = argparse.ArgumentParser(description="Long-running MEXC WebSocket subscribe test to reproduce 1005/1006.")
    p.add_argument("--url", default=DEFAULT_WS_URL)
    p.add_argument("--symbol", default="BTCUSDT", help="MEXC symbol format, e.g. BTCUSDT")
    p.add_argument("--duration", type=int, default=600, help="Seconds to keep connection alive")
    p.add_argument("--depth-levels", type=int, default=5, choices=[5, 10, 20])
    p.add_argument("--trades", action="store_true", help="Also subscribe trades channel")
    p.add_argument("--origin", default=DEFAULT_ORIGIN)
    p.add_argument("--ua", default=DEFAULT_UA)
    args = p.parse_args()

    return asyncio.run(
        run(
            url=args.url,
            symbol=args.symbol,
            origin=args.origin,
            user_agent=args.ua,
            duration_s=args.duration,
            depth_levels=args.depth_levels,
            trades=args.trades,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""WebSocket receive loop (official gateway).

This is a dumb socket reader: identify, heartbeat, resume, normalize, spool.
It never retrieves wiki content, never composes text, and never sends a reply.
The only outbound frames are protocol frames (identify/resume/heartbeat).
"""
import asyncio
import contextlib
import json
import random
import signal
import time

try:
    import websockets
except ImportError:  # pragma: no cover - dependency is declared in pyproject
    websockets = None

from . import api, auth, config, normalize, store


class GatewayUnavailable(RuntimeError):
    pass


class _Stopped(Exception):
    """The listener was asked to stop while waiting for a frame."""


async def _heartbeat(ws, interval: float, last_seq):
    try:
        while True:
            await asyncio.sleep(interval)
            seq = last_seq[0] if last_seq else None
            await ws.send(json.dumps({"op": 1, "d": seq}))
    except (asyncio.CancelledError, Exception):
        return


def _identify(token: str, cfg: dict) -> dict:
    prefix = str(cfg.get("identify_prefix") or "QQBot")
    if prefix == "Bot":
        token_value = f"Bot {cfg.get('app_id', '')}.{token}"
    else:
        token_value = f"QQBot {token}"
    return {
        "op": 2,
        "d": {
            "token": token_value,
            "intents": api.INTENT_GROUP_AND_C2C,
            "shard": [0, 1],
            "properties": {"$os": "linux", "$browser": "qq-cli", "$device": "qq-cli"},
        },
    }


def _resume(token: str, cfg: dict, session_id: str, seq: int) -> dict:
    prefix = str(cfg.get("identify_prefix") or "QQBot")
    token_value = f"Bot {cfg.get('app_id', '')}.{token}" if prefix == "Bot" else f"QQBot {token}"
    return {"op": 6, "d": {"token": token_value, "session_id": session_id, "seq": seq}}


async def _recv_or_stop(ws, stop: asyncio.Event, timeout=None):
    """Await one frame, but wake immediately when the stop event is set.

    The signal handler only sets ``stop``; without this race the listener would
    stay blocked in ``ws.recv()`` and ignore SIGTERM while the gateway is quiet.
    """
    recv_task = asyncio.ensure_future(ws.recv())
    stop_task = asyncio.ensure_future(stop.wait())
    try:
        done, _ = await asyncio.wait(
            {recv_task, stop_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            raise asyncio.TimeoutError
        if stop_task in done and recv_task not in done:
            raise _Stopped
        return recv_task.result()
    finally:
        stop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stop_task
        if not recv_task.done():
            recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await recv_task


async def _session(cfg, deadline, max_events, stop):
    """One connection attempt. Returns the number of spooled events."""
    token = auth.get_token(cfg)
    url = api.get_gateway(token, cfg)
    cursor = store.load_cursor()
    session_id = cursor.get("session_id") or ""
    last_seq = [int(cursor.get("seq") or 0)]
    received = 0

    async with websockets.connect(url, ping_interval=None, close_timeout=5, max_size=2 ** 23) as ws:
        hb_task = None
        try:
            while True:
                remaining = None
                if deadline is not None:
                    remaining = max(0.0, deadline - time.monotonic())
                    if remaining <= 0:
                        return received
                raw = await _recv_or_stop(ws, stop, timeout=remaining)
                try:
                    frame = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                op = frame.get("op")
                d = frame.get("d") or {}

                if op == 10:  # hello
                    interval = float(d.get("heartbeat_interval") or 45000) / 1000.0
                    hb_task = asyncio.create_task(_heartbeat(ws, interval, last_seq))
                    if session_id:
                        await ws.send(json.dumps(_resume(token, cfg, session_id, last_seq[0])))
                    else:
                        await ws.send(json.dumps(_identify(token, cfg)))
                    continue

                if op == 11:  # heartbeat ack
                    continue
                if op == 7:  # reconnect requested
                    return received
                if op == 9:  # invalid session
                    store.clear_cursor()
                    session_id = ""
                    return received
                if op != 0:
                    continue

                seq = frame.get("s")
                if isinstance(seq, int):
                    last_seq[0] = seq
                t = frame.get("t") or ""

                if t == "READY":
                    session_id = str(d.get("session_id") or "")
                    store.update_cursor(session_id=session_id, seq=last_seq[0])
                    continue
                if t == "RESUMED":
                    store.update_cursor(session_id=session_id, seq=last_seq[0])
                    continue
                if t in (normalize.C2C_EVENT, normalize.GROUP_AT_EVENT):
                    try:
                        ev = normalize.normalize(frame, cfg)
                    except ValueError:
                        continue
                    store.append_event(ev, cfg)
                    store.update_cursor(session_id=session_id or None, seq=last_seq[0])
                    received += 1
                    if max_events and received >= max_events:
                        return received
                    continue
                # other dispatch events are intentionally ignored
        finally:
            if hb_task:
                hb_task.cancel()
                with contextlib.suppress(Exception):
                    await hb_task


async def run(cfg, *, once=False, timeout=None, max_events=None) -> dict:
    if websockets is None:
        raise GatewayUnavailable("websockets is not installed: pip install -r requirements.txt")
    deadline = time.monotonic() + float(timeout) if timeout else None
    total = 0
    backoff = 1.0
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass

    while not stop.is_set():
        if deadline is not None and time.monotonic() >= deadline:
            break
        try:
            got = await _session(cfg, deadline, max_events, stop)
            total += got
            backoff = 1.0
            if once and got:
                break
            if max_events and total >= max_events:
                break
            if deadline is not None and time.monotonic() >= deadline:
                break
        except _Stopped:
            break
        except asyncio.TimeoutError:
            break
        except api.TokenExpired:
            auth.get_token(cfg, force=True)
        except (api.ApiError, OSError, asyncio.IncompleteReadError):
            pass
        except Exception:
            pass
        if stop.is_set():
            break
        wait = min(60.0, backoff) * (0.7 + random.random() * 0.6)
        try:
            await asyncio.wait_for(stop.wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass
        backoff = min(60.0, backoff * 2)
    return {"received": total, "stopped": stop.is_set()}


def run_blocking(cfg, **kwargs) -> dict:
    return asyncio.run(run(cfg, **kwargs))

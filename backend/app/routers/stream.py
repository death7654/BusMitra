"""
Server-Sent Events: the server tells the client what changed.

Polling is the client guessing how often something might have changed.
It is wrong in both directions simultaneously - it burns requests when
nothing is happening and still arrives late when something does. For a
bus that is three minutes away, a fifteen-second poll means the figure
on screen is on average seven seconds stale, and there is no poll
interval short enough to fix that which is also cheap enough to run.

SSE rather than WebSockets, for three reasons that all point the same
way here:

  * The traffic is one-directional. The client already has perfectly
    good HTTP endpoints for everything it wants to *send*; it only
    needs a channel for what it receives.
  * It is plain HTTP. It goes through the same CORS, the same proxies
    and the same Tauri HTTP plumbing as every other call, with no
    upgrade handshake to get wrong.
  * EventSource reconnects on its own. A WebSocket client has to
    implement backoff and resumption by hand, and doing that badly is
    how a dropped connection becomes a reconnect storm.

The client keeps its polling loop as a fallback and simply lengthens
the interval while the stream is connected, so a stream that fails
degrades to exactly the previous behaviour rather than to a blank
screen.
"""

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..services import events


router = APIRouter(prefix="/api", tags=["Stream"])


# Sent when nothing has happened, to keep intermediaries from closing
# an idle connection. Comment frames are ignored by EventSource, which
# is exactly what a keepalive should be.
HEARTBEAT_SECONDS = 20


async def _event_source(request: Request):
    queue = await events.bus.subscribe()

    try:
        # An immediate frame so the client knows it's connected rather
        # than waiting up to HEARTBEAT_SECONDS to find out.
        yield _frame(
            "connected",
            {
                "at": datetime.utcnow().isoformat() + "Z",
                "heartbeat_seconds": HEARTBEAT_SECONDS,
            },
        )

        while True:
            # Disconnects are not always signalled by the socket
            # erroring, particularly behind a proxy, so the request's
            # own disconnect flag is checked on every pass.
            if await request.is_disconnected():
                break

            try:
                encoded = await asyncio.wait_for(
                    queue.get(), timeout=HEARTBEAT_SECONDS
                )
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue

            payload = json.loads(encoded)

            yield _frame(payload["event"], payload["data"], at=payload["at"])

    finally:
        # Must run on cancellation too, or a client that walks away
        # leaks a queue that the publisher keeps filling.
        await events.bus.unsubscribe(queue)


def _frame(event: str, data, at: str | None = None) -> str:
    body = {"data": data}

    if at:
        body["at"] = at

    return f"event: {event}\ndata: {json.dumps(body, default=str)}\n\n"


@router.get("/stream")
async def stream(request: Request):
    """
    Live updates for as long as the client stays connected.

    Each frame carries a complete state rather than a delta - see
    services/events.py for why that makes dropped frames safe.
    """

    return StreamingResponse(
        _event_source(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Nginx buffers streaming responses by default, which turns
            # a live stream into a batch delivered at disconnect.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/stream/info")
def stream_info():
    """
    Whether anyone is listening, and whether they're keeping up.

    A rising dropped count means subscribers are slower than the
    publish rate, which is the signal to look at either the payload
    size or the number of workers.
    """

    return {
        "subscribers": events.bus.subscriber_count,
        "published": events.bus.published,
        "dropped": events.bus.dropped,
        "heartbeat_seconds": HEARTBEAT_SECONDS,
    }

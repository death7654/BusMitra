"""
In-process event bus for the live stream.

Polling asks "has anything changed?" on a timer chosen by the client,
which is wrong in both directions at once: too often when nothing is
happening, too late when something is. The stream inverts that - the
server says what changed, when it changes.

This is deliberately the simplest thing that works for a single-process
deployment: an asyncio fan-out to whoever is currently listening. No
Redis, no broker, no persistence. Two consequences worth being explicit
about, because they decide whether this design is adequate:

  * It does not survive more than one worker. Run uvicorn with
    --workers 2 and a client connected to worker A never hears about an
    event published in worker B. For a campus-scale deployment that is
    fine; past that, the publish call is the seam where a real broker
    would go, and nothing else in the codebase would change.
  * Events are fire-and-forget. A subscriber whose queue has filled up
    is dropping updates, not buffering them - so the payloads are all
    complete states rather than deltas. A client that misses one and
    receives the next is fully correct again, which is the property
    that makes dropping safe.

The HTTP polling endpoints stay exactly as they are. The stream is an
optimisation on top, and the client falls back to polling whenever it
isn't connected.
"""

import asyncio
import json
from datetime import datetime
from typing import Any


# A subscriber that has fallen this far behind is not going to catch
# up, and holding its backlog costs the server memory it should be
# spending on clients that are keeping up.
MAX_QUEUED_EVENTS = 32


class EventBus:
    """Fan-out of JSON-serialisable events to active SSE subscribers."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

        # Counters, surfaced through /api/stream/info so the stream's
        # health is inspectable rather than guessed at.
        self.published = 0
        self.dropped = 0

    # -----------------------------------------------------
    # Subscription
    # -----------------------------------------------------

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUED_EVENTS)

        async with self._lock:
            self._subscribers.add(queue)

        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    # -----------------------------------------------------
    # Publishing
    # -----------------------------------------------------

    def publish(self, event: str, data: Any) -> None:
        """
        Send an event to every current subscriber.

        Synchronous on purpose: this is called from request handlers
        and from background threads doing ORM work, and making those
        paths await would mean threading async through code that has no
        other reason to be async. put_nowait never blocks, so the
        publisher is never slowed by a slow reader.
        """

        if not self._subscribers:
            return

        payload = {
            "event": event,
            "at": datetime.utcnow().isoformat() + "Z",
            "data": data,
        }

        encoded = json.dumps(payload, default=str)

        self.published += 1

        for queue in list(self._subscribers):
            try:
                queue.put_nowait(encoded)
            except asyncio.QueueFull:
                # See the module docstring: dropping is safe because
                # every payload is a complete state.
                self.dropped += 1


bus = EventBus()


# ---------------------------------------------------------
# Event names
# ---------------------------------------------------------
#
# Kept as constants so a typo in a publisher can't silently produce an
# event nobody is listening for.

BUS_STATUS = "bus_status"      # a bus's crowd figure or position moved
BUS_REMOVED = "bus_removed"    # a bus left the fleet
FLEET_CHANGED = "fleet_changed"
DEMO_CHANGED = "demo_changed"

import asyncio
import json
from typing import Dict, List, AsyncGenerator


class SSEManager:
    def __init__(self):
        self._queues: Dict[str, List[asyncio.Queue]] = {}

    async def subscribe(self, session_id: str) -> AsyncGenerator[dict, None]:
        queue: asyncio.Queue = asyncio.Queue()
        if session_id not in self._queues:
            self._queues[session_id] = []
        self._queues[session_id].append(queue)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            if session_id in self._queues:
                try:
                    self._queues[session_id].remove(queue)
                except ValueError:
                    pass
                if not self._queues[session_id]:
                    del self._queues[session_id]

    async def publish(self, session_id: str, event_type: str, data: dict) -> None:
        if session_id not in self._queues:
            return
        event = {"event": event_type, "data": json.dumps(data, ensure_ascii=False)}
        for queue in list(self._queues.get(session_id, [])):
            await queue.put(event)

    def publish_nowait(self, session_id: str, event_type: str, data: dict) -> None:
        if session_id not in self._queues:
            return
        event = {"event": event_type, "data": json.dumps(data, ensure_ascii=False)}
        for queue in list(self._queues.get(session_id, [])):
            queue.put_nowait(event)

    async def close_session(self, session_id: str) -> None:
        """Send sentinel to all subscribers to terminate their generators."""
        if session_id not in self._queues:
            return
        for queue in list(self._queues.get(session_id, [])):
            await queue.put(None)


sse_manager = SSEManager()

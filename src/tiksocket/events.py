from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

log = logging.getLogger("tiksocket")

Handler = Callable[..., Any]


class EventEmitter:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._waiters: dict[str, list[asyncio.Future]] = defaultdict(list)

    def on(self, event: str, handler: Handler | None = None):
        if handler is None:
            def wrap(func: Handler) -> Handler:
                self._handlers[event].append(func)
                return func
            return wrap
        self._handlers[event].append(handler)
        return handler

    def off(self, event: str, handler: Handler) -> None:
        if handler in self._handlers.get(event, []):
            self._handlers[event].remove(handler)

    def once(self, event: str, handler: Handler) -> Handler:
        def single(*args, **kwargs):
            self.off(event, single)
            return handler(*args, **kwargs)
        return self.on(event, single)

    async def wait_for(self, event: str, timeout: float | None = None) -> Any:
        future = asyncio.get_running_loop().create_future()
        self._waiters[event].append(future)
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            if future in self._waiters[event]:
                self._waiters[event].remove(future)

    def listeners(self, event: str) -> list[Handler]:
        return list(self._handlers.get(event, [])) + list(self._handlers.get("*", []))

    async def emit(self, event: str, payload: Any = None) -> None:
        for future in list(self._waiters.get(event, [])):
            if not future.done():
                future.set_result(payload)
        for handler in list(self._handlers.get(event, [])):
            await self._call(handler, payload)
        for handler in list(self._handlers.get("*", [])):
            await self._call(handler, event, payload)

    async def _call(self, handler: Handler, *args) -> None:
        try:
            result = handler(*args)
            if inspect.isawaitable(result):
                await result
        except Exception:
            log.exception("event handler failed")

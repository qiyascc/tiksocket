from __future__ import annotations

import asyncio
import math
import random
import time
import weakref
from dataclasses import dataclass

from playwright.async_api import Locator, Page

PUNCT = set(".,!?;:")
HIT_JS = """(e, [x, y]) => {
  const t = document.elementFromPoint(x, y);
  return !(t && (e === t || e.contains(t)));
}"""


@dataclass
class Style:
    enabled: bool = True
    speed: float = 1.0
    gap: tuple[float, float] = (6.0, 14.0)
    read: tuple[float, float] = (0.6, 1.8)


style = Style()
_where: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_last: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_locks: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def configure(enabled: bool | None = None, speed: float | None = None, gap: tuple[float, float] | None = None,
              read: tuple[float, float] | None = None) -> Style:
    if enabled is not None:
        style.enabled = enabled
    if speed is not None:
        style.speed = max(0.1, float(speed))
    if gap is not None:
        style.gap = (max(0.0, gap[0]), max(gap[0], gap[1]))
    if read is not None:
        style.read = (max(0.0, read[0]), max(read[0], read[1]))
    return style


def _ms(low: float, high: float) -> float:
    return random.uniform(low, high) / style.speed


async def pause(page: Page, low: float = 120, high: float = 400) -> None:
    if style.enabled:
        await page.wait_for_timeout(_ms(low, high))


async def read(page: Page) -> None:
    if style.enabled:
        await page.wait_for_timeout(_ms(style.read[0] * 1000, style.read[1] * 1000))


async def before_action(owner: object) -> None:
    if not style.enabled or style.gap[1] <= 0:
        return
    lock = _locks.setdefault(owner, asyncio.Lock())
    async with lock:
        wait = random.uniform(*style.gap) / style.speed - (time.monotonic() - _last.get(owner, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        _last[owner] = time.monotonic()


def _start(page: Page) -> tuple[float, float]:
    if page not in _where:
        size = page.viewport_size or {"width": 1280, "height": 800}
        _where[page] = (random.uniform(0.3, 0.7) * size["width"], random.uniform(0.3, 0.7) * size["height"])
    return _where[page]


def path(start: tuple[float, float], end: tuple[float, float], steps: int | None = None) -> list[tuple[float, float]]:
    (x0, y0), (x1, y1) = start, end
    distance = math.hypot(x1 - x0, y1 - y0)
    steps = steps or max(8, min(45, int(distance / 18)))
    bend = min(120.0, distance * 0.25)
    nx, ny = (-(y1 - y0) / distance, (x1 - x0) / distance) if distance else (0.0, 0.0)
    a = random.uniform(-bend, bend)
    b = random.uniform(-bend, bend)
    c1 = (x0 + (x1 - x0) * 0.3 + nx * a, y0 + (y1 - y0) * 0.3 + ny * a)
    c2 = (x0 + (x1 - x0) * 0.7 + nx * b, y0 + (y1 - y0) * 0.7 + ny * b)
    points = []
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)
        u = 1 - t
        x = u ** 3 * x0 + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * x1
        y = u ** 3 * y0 + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * y1
        jitter = 0.0 if i == steps else 0.8
        points.append((x + random.uniform(-jitter, jitter), y + random.uniform(-jitter, jitter)))
    return points


async def move(page: Page, x: float, y: float) -> None:
    if not style.enabled:
        await page.mouse.move(x, y)
        _where[page] = (x, y)
        return
    points = path(_start(page), (x, y))
    overshoot = len(points) > 20 and random.random() < 0.25
    if overshoot:
        dx, dy = points[-1][0] - points[-2][0], points[-1][1] - points[-2][1]
        points.append((x + dx * random.uniform(2, 5), y + dy * random.uniform(2, 5)))
        points.append((x, y))
    for px, py in points:
        await page.mouse.move(px, py)
        await asyncio.sleep(random.uniform(0.004, 0.018) / style.speed)
    _where[page] = (x, y)


def _target(box: dict) -> tuple[float, float]:
    spread_x = box["width"] * 0.18
    spread_y = box["height"] * 0.18
    x = box["x"] + box["width"] / 2 + max(-spread_x * 1.8, min(spread_x * 1.8, random.gauss(0, spread_x)))
    y = box["y"] + box["height"] / 2 + max(-spread_y * 1.8, min(spread_y * 1.8, random.gauss(0, spread_y)))
    return x, y


async def click(item: Locator, timeout: float = 4000, force: bool = False) -> None:
    if not style.enabled:
        await item.click(timeout=timeout, force=force)
        return
    page = item.page
    try:
        await item.scroll_into_view_if_needed(timeout=min(timeout, 3000))
        box = await item.bounding_box(timeout=min(timeout, 3000))
    except Exception:
        box = None
    size = page.viewport_size or {"width": 1280, "height": 800}
    if not box or box["width"] < 2 or box["height"] < 2 or box["y"] < 0 or box["y"] > size["height"]:
        await item.click(timeout=timeout, force=force)
        return
    x, y = _target(box)
    await move(page, x, y)
    await pause(page, 60, 220)
    if not force:
        try:
            covered = await item.evaluate(HIT_JS, [x, y])
        except Exception:
            covered = True
        if covered:
            await item.click(timeout=timeout, force=force)
            return
    await page.mouse.down()
    await page.wait_for_timeout(_ms(40, 130))
    await page.mouse.up()


async def type_text(page: Page, text: str) -> None:
    if not style.enabled:
        await page.keyboard.insert_text(text)
        return
    for char in text:
        if ord(char) > 0xFFFF or not char.isprintable():
            await page.keyboard.insert_text(char)
        else:
            await page.keyboard.type(char)
        await asyncio.sleep(random.uniform(0.045, 0.16) / style.speed)
        if char == " " and random.random() < 0.12:
            await asyncio.sleep(random.uniform(0.2, 0.6) / style.speed)
        elif char in PUNCT:
            await asyncio.sleep(random.uniform(0.15, 0.45) / style.speed)


async def scroll(page: Page, dy: float) -> None:
    if not style.enabled:
        await page.mouse.wheel(0, dy)
        return
    left = dy
    while abs(left) > 1:
        step = math.copysign(min(abs(left), random.uniform(80, 220)), left)
        await page.mouse.wheel(0, step)
        left -= step
        await asyncio.sleep(random.uniform(0.03, 0.12) / style.speed)
    await pause(page, 150, 500)

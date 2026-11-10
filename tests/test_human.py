from __future__ import annotations

import math
import time

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeout

from tiksocket import human

PAGE = """<html><body style="margin:0">
<button id="go" style="position:absolute;left:500px;top:300px;width:120px;height:40px">Follow</button>
<div id="cover" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.4)"></div>
<textarea id="box" style="position:absolute;left:40px;top:40px;width:300px;height:80px"></textarea>
<script>
window.moves = 0; window.hits = []; window.downs = [];
document.addEventListener('mousemove', () => { window.moves++; });
document.addEventListener('mousedown', () => { window.downs.push(performance.now()); });
document.addEventListener('mouseup', () => { window.downs.push(performance.now()); });
document.getElementById('go').addEventListener('click', e => { window.hits.push([e.clientX, e.clientY]); });
</script></body></html>"""


@pytest.fixture
async def page():
    playwright = pytest.importorskip("playwright.async_api")
    async with playwright.async_playwright() as pw:
        try:
            browser = await pw.chromium.launch()
        except Exception as exc:
            pytest.skip(f"chromium is not installed: {exc}")
        tab = await browser.new_page(viewport={"width": 900, "height": 600})
        await tab.set_content(PAGE)
        yield tab
        await browser.close()


@pytest.fixture
def person():
    human.configure(enabled=True, speed=4.0, gap=(0.2, 0.3), read=(0.0, 0.0))
    yield human.style
    human.configure(enabled=False, speed=1.0, gap=(6.0, 14.0), read=(0.6, 1.8))


def test_path_is_curved_and_lands_on_target():
    for _ in range(20):
        points = human.path((10, 10), (610, 410))
        assert points[-1] == pytest.approx((610, 410), abs=0.01)
        assert len(points) >= 8
        off = max(abs((p[0] - 10) * 400 - (p[1] - 10) * 600) / math.hypot(600, 400) for p in points)
        assert off < 200
    bends = [max(abs((p[0] - 10) * 400 - (p[1] - 10) * 600) / math.hypot(600, 400)
                 for p in human.path((10, 10), (610, 410))) for _ in range(20)]
    assert max(bends) > 5


def test_target_stays_inside_the_box():
    box = {"x": 100, "y": 50, "width": 80, "height": 30}
    spots = [human._target(box) for _ in range(500)]
    assert all(100 < x < 180 and 50 < y < 80 for x, y in spots)
    assert len({round(x) for x, _ in spots}) > 10


async def test_click_moves_the_mouse_and_hits_off_center(page, person):
    for _ in range(4):
        await human.click(page.locator("#go"))
    hits = await page.evaluate("window.hits")
    assert len(hits) == 4
    assert all(500 <= x <= 620 and 300 <= y <= 340 for x, y in hits)
    assert len({tuple(h) for h in hits}) > 1
    assert await page.evaluate("window.moves") > 20
    downs = await page.evaluate("window.downs")
    assert all(downs[i + 1] - downs[i] >= 9 for i in range(0, len(downs), 2))


async def test_covered_button_falls_back_to_playwright(page, person):
    await page.evaluate("document.getElementById('cover').style.display = 'block'")
    with pytest.raises(PlaywrightTimeout):
        await human.click(page.locator("#go"), timeout=800)
    assert await page.evaluate("window.hits") == []


async def test_robot_mode_clicks_instantly(page):
    await human.click(page.locator("#go"))
    assert len(await page.evaluate("window.hits")) == 1
    assert await page.evaluate("window.moves") <= 2


async def test_types_text_with_emoji(page, person):
    await human.click(page.locator("#box"))
    await human.type_text(page, "Salam, ev 3 otaq 🏡!")
    assert await page.input_value("#box") == "Salam, ev 3 otaq 🏡!"


async def test_gap_between_actions_is_per_account(person):
    class Account:
        pass

    first, second = Account(), Account()
    start = time.monotonic()
    await human.before_action(first)
    await human.before_action(second)
    assert time.monotonic() - start < 0.15
    await human.before_action(first)
    assert time.monotonic() - start >= 0.04


async def test_scroll_moves_the_page(page, person):
    await page.set_content("<div style='height:5000px'>tall</div>")
    await page.mouse.move(200, 200)
    await human.scroll(page, 900)
    assert await page.evaluate("window.scrollY") >= 850

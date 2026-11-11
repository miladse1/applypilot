"""Render ApplyPilot's app icons (PNG + .icns) from inline SVG with headless Chrome.

Usage: python make_icons.py OUT_DIR   (needs playwright; run once, outputs are committed)
"""
import asyncio
import base64
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.async_api import async_playwright

PLANE = '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z" fill="#fff"/><path d="m21.854 2.147-10.94 10.939" stroke="#4338ca" stroke-width="1.6" stroke-linecap="round"/>'
POWER = '<path d="M12 3v8" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/><path d="M6.6 6.9a7.5 7.5 0 1 0 10.8 0" stroke="#fff" stroke-width="2.4" stroke-linecap="round" fill="none"/>'


def svg(glyph: str, top: str, bottom: str, *, inset: bool) -> str:
    # macOS-style icons sit inside a 824px rounded square on a 1024px canvas; maskable icons fill the canvas.
    box, offset, radius, glyph_size = (824, 100, 186, 470) if inset else (1024, 0, 0, 520)
    gx = offset + (box - glyph_size) / 2
    shadow = '<filter id="s" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="10" stdDeviation="14" flood-opacity=".28"/></filter>' if inset else ""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>{shadow}</defs>
<rect x="{offset}" y="{offset}" width="{box}" height="{box}" rx="{radius}" fill="url(#g)" {'filter="url(#s)"' if inset else ''}/>
<svg x="{gx}" y="{gx + glyph_size * 0.02}" width="{glyph_size}" height="{glyph_size}" viewBox="0 0 24 24" fill="none">{glyph}</svg>
</svg>'''


async def render(page, markup: str, path: Path, size: int) -> None:
    data = base64.b64encode(markup.encode()).decode()
    await page.set_viewport_size({"width": size, "height": size})
    await page.set_content(f'<html><body style="margin:0;background:transparent"><img style="display:block" width="{size}" height="{size}" src="data:image/svg+xml;base64,{data}"></body></html>')
    await page.wait_for_function("document.images[0].complete")
    await page.screenshot(path=str(path), omit_background=True)


def scaled(master: Path, path: Path, size: int) -> None:
    # Headless Chrome renders reliably at 1024px; macOS `sips` makes the smaller sizes.
    subprocess.run(["sips", "-z", str(size), str(size), str(master), "--out", str(path)], check=True, capture_output=True)


async def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    designs = {
        "app": svg(PLANE, "#6366f1", "#4338ca", inset=True),
        "maskable": svg(PLANE, "#6366f1", "#4338ca", inset=False),
        "control": svg(POWER, "#475569", "#1e293b", inset=True),
    }
    masters = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page()
        for name, markup in designs.items():
            masters[name] = out / f".{name}-1024.png"
            await render(page, markup, masters[name], 1024)
        await browser.close()
    for size in (180, 192, 512):
        scaled(masters["app"], out / f"icon-{size}.png", size)
    scaled(masters["maskable"], out / "icon-maskable-512.png", 512)
    for name, key in (("ApplyPilot", "app"), ("ApplyPilotControl", "control")):
        iconset = out / f"{name}.iconset"
        iconset.mkdir(exist_ok=True)
        for base in (16, 32, 128, 256, 512):
            scaled(masters[key], iconset / f"icon_{base}x{base}.png", base)
            scaled(masters[key], iconset / f"icon_{base}x{base}@2x.png", base * 2)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out / f"{name}.icns")], check=True)
        shutil.rmtree(iconset)
    for master in masters.values():
        master.unlink()
    (out / "favicon.svg").write_text(designs["app"])


asyncio.run(main(Path(sys.argv[1])))

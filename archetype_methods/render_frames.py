"""Render the mixed-methods animation to still frames and a GIF for documents.

    uv run --with playwright --with pillow python -m archetype_methods.render_frames

Google Docs cannot run the HTML page and shows only a GIF's first frame, so a
Doc gets one PNG per step; Google Slides animates GIFs, so it gets the GIF.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
HTML = FIG / "mixed-methods-animation.html"
STEPS = 6
# the browser build already cached on this machine (see render notes in README)
CHROME = Path.home() / ".cache/ms-playwright/chromium-1228/chrome-linux64/chrome"
HIDE = ".controls,.legend,footer,header .eyebrow:last-child{display:none!important}"


def main():
    src = HTML.read_text()
    page_html = ("<!doctype html><html data-theme='light'><head><meta charset='utf-8'>"
                 f"<style>{HIDE} body{{background:#fff}} .wrap{{max-width:1000px}}</style></head><body>"
                 + src + "</body></html>")
    tmp = FIG / "_render.html"
    tmp.write_text(page_html)
    frames = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME) if CHROME.exists() else None)
        ctx = browser.new_context(viewport={"width": 1040, "height": 900}, device_scale_factor=2,
                                  reduced_motion="reduce", color_scheme="light")
        page = ctx.new_page()
        page.goto(tmp.as_uri())
        page.wait_for_timeout(1500)  # fonts
        for i in range(STEPS):
            page.evaluate(f"document.querySelectorAll('.dots button')[{i}].click()")
            page.wait_for_timeout(600)
            out = FIG / f"step_{i + 1}.png"
            page.locator(".wrap").screenshot(path=str(out))
            frames.append(Image.open(out).convert("RGB"))
            print("wrote", out)
        browser.close()
    tmp.unlink()
    w = min(f.width for f in frames)
    h = max(f.height for f in frames)
    canvas = []
    for f in frames:
        c = Image.new("RGB", (w, h), "white")
        c.paste(f.resize((w, int(f.height * w / f.width))), (0, 0))
        canvas.append(c.resize((w // 2, h // 2)))
    gif = FIG / "mixed-methods-pipeline.gif"
    canvas[0].save(gif, save_all=True, append_images=canvas[1:], duration=4000, loop=0, optimize=True)
    print("wrote", gif, gif.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()

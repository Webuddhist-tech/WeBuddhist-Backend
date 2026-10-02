"""HTML for the prayer-request PDF, and Chromium to print it.

The HTML is plain Jinja so it can be tested without a browser; only
`html_to_pdf` needs Playwright, and it imports it lazily so the rest of the
API starts on machines that never print a PDF. The page lays itself out in
JavaScript (`window.layout`, a masonry packer), so it has to be printed by a
real browser rather than an HTML-to-PDF converter."""

import asyncio
import base64
import html
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Sequence

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .prayer_pdf_content import Card

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# Chromium is a few hundred MB per instance; two at once is plenty for an
# admin-only export and keeps a burst of clicks from exhausting the box.
_RENDER_SLOTS = asyncio.Semaphore(2)
_LOAD_TIMEOUT_MS = 30_000

# Paper in mm, and the printable area inside the @page margins
# (16mm top, 18mm bottom, 15mm each side, plus 2mm of slack at the foot).
_PAGES_MM = {"A3": (297, 420), "A4": (210, 297)}


@dataclass
class RenderCard:
    card: Card
    avatar: Optional[str]  # data: URI of a real photo, or None for initials

    @property
    def span(self) -> int:
        return self.card.span

    @property
    def name_html(self) -> str:
        return self.card.name_html

    @property
    def message_html(self) -> str:
        return self.card.message_html

    @property
    def initials_html(self) -> str:
        return self.card.initials_html

    @property
    def initials_color(self) -> str:
        return self.card.initials_color


@dataclass
class PrayerPdfDocument:
    title_bo: Optional[str]
    title: Optional[str]
    title_zh: Optional[str]
    subtitle_bo: Optional[str]
    subtitle: Optional[str]
    subtitle_zh: Optional[str]
    date_label: str
    zh_date: str
    day_number: int
    day_number_bo: str
    closing_bo: Sequence[str]
    closing_mantra: Optional[str]
    closing_zh: Sequence[str]
    closing_en: Sequence[str]
    closing_emoji: Optional[str]
    page_size: str
    columns: int
    primary_color: str
    secondary_color: str
    cards: List[RenderCard] = field(default_factory=list)

    @property
    def has_closing(self) -> bool:
        return bool(
            self.closing_bo or self.closing_mantra or self.closing_zh or self.closing_en or self.closing_emoji
        )


@lru_cache(maxsize=1)
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )


@lru_cache(maxsize=None)
def _font_data_uri(relative_path: str) -> str:
    """Fonts go in as data URIs: a page made with set_content has no origin
    to load file:// URLs from."""
    path = _FONTS_DIR / relative_path
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        logger.warning("Prayer PDF font %s is missing; falling back to system fonts", path)
        return ""
    return f"data:font/ttf;base64,{encoded}"


def content_size_mm(page_size: str) -> tuple:
    width, height = _PAGES_MM.get(page_size, _PAGES_MM["A3"])
    return width - 30, height - 36


def render_html(document: PrayerPdfDocument) -> str:
    content_w, content_h = content_size_mm(document.page_size)
    template = _environment().get_template("prayer_requests.html.j2")
    return template.render(
        fonts={
            # EB Garamond (SIL OFL) stands in for the action's Microsoft
            # Garamond, which may not be redistributed; Monlam Uni OuChan2 is
            # the Tibetan face both use.
            "garamond": _font_data_uri("prayer_pdf/EBGaramond.ttf"),
            "garamond_italic": _font_data_uri("prayer_pdf/EBGaramond-Italic.ttf"),
            "tibetan": _font_data_uri("bo.ttf"),
        },
        page_size=document.page_size if document.page_size in _PAGES_MM else "A3",
        content_w_mm=content_w,
        content_h_mm=content_h,
        primary_color=document.primary_color,
        secondary_color=document.secondary_color,
        title_bo=document.title_bo,
        title=document.title,
        title_zh=document.title_zh,
        subtitle_bo=document.subtitle_bo,
        subtitle=document.subtitle,
        subtitle_zh=document.subtitle_zh,
        day_number=document.day_number,
        day_number_bo=document.day_number_bo,
        date_label=document.date_label,
        zh_date=document.zh_date,
        count=len(document.cards),
        cards=document.cards,
        has_closing=document.has_closing,
        closing_bo=document.closing_bo,
        closing_mantra=document.closing_mantra,
        closing_zh=document.closing_zh,
        closing_en=document.closing_en,
        closing_emoji=document.closing_emoji,
        layout_json=json.dumps(
            {"columns": document.columns, "contentW": content_w, "contentH": content_h}
        ),
    )


def footer_template(date_label: str, color: str) -> str:
    """Date and page number, bottom right of every page."""
    return (
        '<div style="width:100%;margin:0 15mm;display:flex;justify-content:flex-end;align-items:center;'
        f'font-size:9pt;color:{html.escape(color)};font-family:serif;-webkit-print-color-adjust:exact">'
        f'<span>{html.escape(date_label)} &nbsp;·&nbsp; <span class="pageNumber"></span> / '
        '<span class="totalPages"></span></span></div>'
    )


async def html_to_pdf(html_content: str, *, date_label: str, color: str) -> bytes:
    from playwright.async_api import async_playwright

    async with _RENDER_SLOTS:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                page = await browser.new_page()
                # Fonts and photos are inlined as data: URIs, so the page has
                # nothing to fetch; refuse anything it tries.
                await page.route("**/*", lambda route: route.abort())
                await page.set_content(html_content, wait_until="load", timeout=_LOAD_TIMEOUT_MS)
                await page.evaluate("document.fonts.ready.then(() => true)")
                await page.wait_for_timeout(300)
                pages = await page.evaluate("window.layout()")
                logger.info("Prayer PDF laid out on %s page(s)", pages)
                return await page.pdf(
                    prefer_css_page_size=True,
                    print_background=True,
                    display_header_footer=True,
                    header_template="<div></div>",
                    footer_template=footer_template(date_label, color),
                )
            finally:
                await browser.close()

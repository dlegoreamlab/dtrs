from __future__ import annotations

import os
from typing import Tuple

from PIL import Image
from reportlab.lib.pagesizes import portrait
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from .models import DocumentModel, PageModel, TextSpan


class PDFRenderer:
    def __init__(self) -> None:
        self._register_fonts()

    def _register_fonts(self) -> None:
        for name in ["HYSMyeongJo-Medium", "HYGothic-Medium"]:
            try:
                pdfmetrics.registerFont(UnicodeCIDFont(name))
            except Exception:
                pass

    def _pick_font(self, span: TextSpan) -> str:
        if any("가" <= ch <= "힣" for ch in (span.translated_text or span.text)):
            return "HYGothic-Medium"
        return "Helvetica"

    def render(self, doc: DocumentModel, output_pdf: str) -> str:
        if not doc.pages:
            raise ValueError("document has no pages")
        first_page = doc.pages[0]
        c = canvas.Canvas(output_pdf, pagesize=portrait((first_page.width, first_page.height)))
        for idx, page in enumerate(doc.pages):
            if idx > 0:
                c.setPageSize((page.width, page.height))
            self._render_page(c, page)
            c.showPage()
        c.save()
        return output_pdf

    def _render_page(self, c: canvas.Canvas, page: PageModel) -> None:
        bg_path = page.background_path or page.image_path
        if os.path.exists(bg_path):
            c.drawImage(bg_path, 0, 0, width=page.width, height=page.height, mask='auto')
        for table in page.tables:
            x1, y1, x2, y2 = table.bbox
            self._stroke_rect(c, page, x1, y1, x2, y2)
            if table.rows > 1:
                row_h = (y2 - y1) / table.rows
                for r in range(1, table.rows):
                    self._stroke_line(c, page, x1, y1 + row_h * r, x2, y1 + row_h * r)
            if table.cols > 1:
                col_w = (x2 - x1) / table.cols
                for col in range(1, table.cols):
                    self._stroke_line(c, page, x1 + col_w * col, y1, x1 + col_w * col, y2)
        for span in sorted(page.text_spans, key=lambda s: (s.bbox[1], s.bbox[0])):
            self._draw_span(c, page, span)
        for eq in page.equations:
            label = f"${eq.latex}$" if eq.latex else "[equation]"
            x1, y1, _, y2 = eq.bbox
            self._draw_text(c, page, x1, y2, label, 10, "Helvetica-Oblique")

    def _draw_span(self, c: canvas.Canvas, page: PageModel, span: TextSpan) -> None:
        x1, y1, _, y2 = span.bbox
        text = span.translated_text or span.text
        font_name = self._pick_font(span)
        font_size = max(8, float(span.font_size))
        self._draw_text(c, page, x1, y2, text, font_size, font_name, span.char_spacing)

    def _draw_text(self, c: canvas.Canvas, page: PageModel, x: float, bottom_y: float, text: str, font_size: float, font_name: str, char_space: float = 0.0) -> None:
        text_obj = c.beginText()
        text_obj.setTextOrigin(x, page.height - bottom_y)
        text_obj.setFont(font_name, font_size)
        if hasattr(text_obj, 'setCharSpace'):
            text_obj.setCharSpace(char_space)
        text_obj.textLine(text)
        c.drawText(text_obj)

    def _stroke_rect(self, c: canvas.Canvas, page: PageModel, x1: float, y1: float, x2: float, y2: float) -> None:
        c.rect(x1, page.height - y2, x2 - x1, y2 - y1, stroke=1, fill=0)

    def _stroke_line(self, c: canvas.Canvas, page: PageModel, x1: float, y1: float, x2: float, y2: float) -> None:
        c.line(x1, page.height - y1, x2, page.height - y2)

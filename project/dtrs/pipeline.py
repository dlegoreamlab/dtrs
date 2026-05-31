from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List, Optional

import fitz  # PyMuPDF

from .models import DocumentModel, PageModel, TextSpan
from .modules import (
    BackgroundRestorer,
    EquationDetector,
    FontEstimator,
    LayoutAnalyzer,
    TableDetector,
    Translator,
    build_ocr_backend,
)
from .render import PDFRenderer


@dataclass
class PipelineConfig:
    source_lang: str = "auto"
    target_lang: str = "en"
    ocr_backend: str = "tesseract"
    tesseract_lang: str = "eng+kor"
    dpi: int = 200


class DTRSPipeline:
    def __init__(self, config: Optional[PipelineConfig] = None) -> None:
        self.config = config or PipelineConfig()
        self.ocr = build_ocr_backend(self.config.ocr_backend, self.config.tesseract_lang)
        self.layout = LayoutAnalyzer()
        self.font_estimator = FontEstimator()
        self.table_detector = TableDetector()
        self.equation_detector = EquationDetector()
        self.bg_restorer = BackgroundRestorer()
        self.translator = Translator(self.config.source_lang, self.config.target_lang)
        self.renderer = PDFRenderer()

    def run(self, source_pdf: str, workdir: str, output_pdf: str) -> DocumentModel:
        os.makedirs(workdir, exist_ok=True)
        doc = self._extract_pages(source_pdf, workdir)
        for page in doc.pages:
            page.text_spans = self._extract_text(page)
            page.tables = self.table_detector.detect(page.image_path, page.page_no)
            for table in page.tables:
                self.table_detector.attach_cells(table, page.text_spans)
            page.equations = self.equation_detector.detect(page.text_spans)
            self._estimate_fonts(page)
            page.background_path = self.bg_restorer.restore(
                page.image_path,
                page.text_spans,
                os.path.join(workdir, f"page_{page.page_no:03d}_background.png"),
            )
            self.translator.batch_translate(page.text_spans)
            self._adapt_layout(page)
        self.renderer.render(doc, output_pdf)
        self._write_sidecars(doc, workdir, output_pdf)
        return doc

    def _extract_pages(self, source_pdf: str, workdir: str) -> DocumentModel:
        src = fitz.open(source_pdf)
        out = DocumentModel(source_pdf=source_pdf, metadata={"page_count": src.page_count})
        scale = self.config.dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        for i, page in enumerate(src, start=1):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image_path = os.path.join(workdir, f"page_{i:03d}.png")
            pix.save(image_path)
            out.pages.append(PageModel(page_no=i, width=pix.width, height=pix.height, image_path=image_path))
        src.close()
        return out

    def _extract_text(self, page: PageModel) -> List[TextSpan]:
        raw_spans = self.ocr.extract_words(page.image_path, page.page_no)
        lines = self.layout.group_lines(raw_spans, y_tol=12.0)
        merged: List[TextSpan] = []
        for line in lines:
            merged.append(self.layout.merge_line_spans(line))
        return merged

    def _estimate_fonts(self, page: PageModel) -> None:
        for span in page.text_spans:
            span.font_size = self.font_estimator.estimate_pixel_font_size(page.image_path, span.bbox)
            span.font_name = self.font_estimator.choose_font_name(span.text)
            span.line_height = round(span.font_size * 1.2, 2)
        self.font_estimator.estimate_char_spacing(page.text_spans)

    def _adapt_layout(self, page: PageModel) -> None:
        for span in page.text_spans:
            target = span.translated_text or span.text
            x1, y1, x2, y2 = span.bbox
            box_w = max(1.0, x2 - x1)
            est_text_w = max(1.0, len(target)) * (span.font_size * 0.56 + span.char_spacing)
            if est_text_w > box_w:
                scale = max(0.6, box_w / est_text_w)
                span.font_size = max(8.0, round(span.font_size * scale, 2))
                if len(target) > 5 and scale < 0.85:
                    wrap_at = max(5, int(len(target) * scale))
                    span.translated_text = self._soft_wrap(target, wrap_at)
            if (span.translated_text or span.text).count("\n") > 0:
                lines = (span.translated_text or span.text).splitlines()
                span.bbox = (x1, y1, x2, y1 + max(y2 - y1, span.font_size * 1.25 * len(lines)))

    def _soft_wrap(self, text: str, width: int) -> str:
        words = text.split()
        if len(words) <= 1:
            return text
        lines: List[str] = []
        buf = ""
        for word in words:
            candidate = f"{buf} {word}".strip()
            if len(candidate) <= width or not buf:
                buf = candidate
            else:
                lines.append(buf)
                buf = word
        if buf:
            lines.append(buf)
        return "\n".join(lines)

    def _write_sidecars(self, doc: DocumentModel, workdir: str, output_pdf: str) -> None:
        with open(os.path.join(workdir, "document_model.json"), "w", encoding="utf-8") as f:
            json.dump(doc.to_dict(), f, ensure_ascii=False, indent=2)
        with open(os.path.join(workdir, "run_info.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "output_pdf": output_pdf,
                    "source_pdf": doc.source_pdf,
                    "target_lang": self.config.target_lang,
                    "ocr_backend": self.config.ocr_backend,
                    "page_count": len(doc.pages),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

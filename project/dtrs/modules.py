from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image

from .models import EquationObject, TableCell, TableObject, TextSpan


EQUATION_HINT_RE = re.compile(r"[=+\-×÷∑∫√π∞≤≥^_\\]|\\b(?:sin|cos|tan|lim|log)\\b")
DEFAULT_FONT_CANDIDATES = [
    "Helvetica",
    "Times-Roman",
    "Courier",
    "NotoSansCJKkr-Regular",
]


@dataclass
class OCRWord:
    text: str
    bbox: Tuple[float, float, float, float]
    confidence: float = 1.0


class OCRBackend:
    def extract_words(self, image_path: str, page_no: int) -> List[TextSpan]:
        raise NotImplementedError


class TesseractOCRBackend(OCRBackend):
    def __init__(self, lang: str = "eng+kor"):
        self.lang = lang
        import pytesseract  # type: ignore

        self.pytesseract = pytesseract

    def extract_words(self, image_path: str, page_no: int) -> List[TextSpan]:
        img = cv2.imread(image_path)
        data = self.pytesseract.image_to_data(
            img,
            lang=self.lang,
            output_type=self.pytesseract.Output.DICT,
        )
        spans: List[TextSpan] = []
        for i, text in enumerate(data["text"]):
            text = (text or "").strip()
            if not text:
                continue
            x, y, w, h = (data["left"][i], data["top"][i], data["width"][i], data["height"][i])
            conf = float(data["conf"][i]) / 100.0 if str(data["conf"][i]).strip() not in {"-1", ""} else 0.0
            spans.append(
                TextSpan(
                    text=text,
                    bbox=(float(x), float(y), float(x + w), float(y + h)),
                    page_no=page_no,
                    confidence=max(0.0, conf),
                )
            )
        return spans


class PaddleOCRBackend(OCRBackend):
    def __init__(self, lang: str = "korean"):
        from paddleocr import PaddleOCR  # type: ignore

        self.ocr = PaddleOCR(use_angle_cls=True, lang=lang)

    def extract_words(self, image_path: str, page_no: int) -> List[TextSpan]:
        result = self.ocr.ocr(image_path, cls=True)
        spans: List[TextSpan] = []
        for line in result[0] if result and result[0] else []:
            quad = line[0]
            text, conf = line[1]
            xs = [p[0] for p in quad]
            ys = [p[1] for p in quad]
            spans.append(
                TextSpan(
                    text=text,
                    bbox=(float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))),
                    page_no=page_no,
                    confidence=float(conf),
                )
            )
        return spans


class MockOCRBackend(OCRBackend):
    def extract_words(self, image_path: str, page_no: int) -> List[TextSpan]:
        return []


def build_ocr_backend(preferred: str = "tesseract", lang: str = "eng+kor") -> OCRBackend:
    if preferred == "paddle":
        try:
            return PaddleOCRBackend(lang="korean")
        except Exception:
            pass
    try:
        return TesseractOCRBackend(lang=lang)
    except Exception:
        return MockOCRBackend()


class FontEstimator:
    def estimate_pixel_font_size(self, image_path: str, bbox: Tuple[float, float, float, float]) -> float:
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return 12.0
        x1, y1, x2, y2 = [max(0, int(v)) for v in bbox]
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            return max(8.0, y2 - y1)
        _, binary = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        ys, _ = np.where(binary > 0)
        if len(ys) == 0:
            return max(8.0, y2 - y1)
        top, bottom = int(np.min(ys)), int(np.max(ys))
        measured = float(max(1, bottom - top))
        return max(8.0, measured * 1.15)

    def estimate_char_spacing(self, spans: Sequence[TextSpan]) -> None:
        ordered = sorted(spans, key=lambda s: (s.bbox[1], s.bbox[0]))
        for prev, cur in zip(ordered, ordered[1:]):
            if abs(prev.bbox[1] - cur.bbox[1]) > max(prev.font_size, cur.font_size):
                continue
            gap = cur.bbox[0] - prev.bbox[2]
            if gap > 0:
                cur.char_spacing = round(gap / max(1, len(cur.text)), 2)

    def choose_font_name(self, text: str) -> str:
        if any("가" <= ch <= "힣" for ch in text):
            return "NotoSansCJKkr-Regular"
        if re.search(r"[0-9]", text):
            return "Helvetica"
        return DEFAULT_FONT_CANDIDATES[0]


class LayoutAnalyzer:
    def group_lines(self, spans: Sequence[TextSpan], y_tol: float = 12.0) -> List[List[TextSpan]]:
        ordered = sorted(spans, key=lambda s: (s.bbox[1], s.bbox[0]))
        lines: List[List[TextSpan]] = []
        for span in ordered:
            placed = False
            for line in lines:
                baseline = np.mean([s.bbox[1] for s in line])
                if abs(span.bbox[1] - baseline) <= y_tol:
                    line.append(span)
                    placed = True
                    break
            if not placed:
                lines.append([span])
        for line in lines:
            line.sort(key=lambda s: s.bbox[0])
        return lines

    def merge_line_spans(self, line: Sequence[TextSpan]) -> TextSpan:
        text = " ".join([s.text for s in line]).strip()
        x1 = min(s.bbox[0] for s in line)
        y1 = min(s.bbox[1] for s in line)
        x2 = max(s.bbox[2] for s in line)
        y2 = max(s.bbox[3] for s in line)
        confidence = sum(s.confidence for s in line) / max(1, len(line))
        merged = TextSpan(text=text, bbox=(x1, y1, x2, y2), page_no=line[0].page_no, confidence=confidence)
        return merged


class TableDetector:
    def detect(self, image_path: str, page_no: int) -> List[TableObject]:
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return []
        _, bin_img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        vert_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
        horizontal = cv2.morphologyEx(bin_img, cv2.MORPH_OPEN, horiz_kernel, iterations=1)
        vertical = cv2.morphologyEx(bin_img, cv2.MORPH_OPEN, vert_kernel, iterations=1)
        table_mask = cv2.add(horizontal, vertical)
        contours, _ = cv2.findContours(table_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        tables: List[TableObject] = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if w < 100 or h < 60:
                continue
            row_count = max(1, self._estimate_lines(horizontal[y : y + h, x : x + w], axis=0))
            col_count = max(1, self._estimate_lines(vertical[y : y + h, x : x + w], axis=1))
            tables.append(TableObject(bbox=(x, y, x + w, y + h), page_no=page_no, rows=row_count, cols=col_count))
        return sorted(tables, key=lambda t: (t.bbox[1], t.bbox[0]))

    def attach_cells(self, table: TableObject, spans: Sequence[TextSpan]) -> TableObject:
        x1, y1, x2, y2 = table.bbox
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        cell_w = width / max(1, table.cols)
        cell_h = height / max(1, table.rows)
        cells: List[TableCell] = []
        for span in spans:
            sx1, sy1, sx2, sy2 = span.bbox
            cx = (sx1 + sx2) / 2
            cy = (sy1 + sy2) / 2
            if not (x1 <= cx <= x2 and y1 <= cy <= y2):
                continue
            row = min(table.rows - 1, int((cy - y1) / cell_h))
            col = min(table.cols - 1, int((cx - x1) / cell_w))
            cells.append(TableCell(row=row, col=col, bbox=span.bbox, text=span.text))
        table.cells = cells
        return table

    @staticmethod
    def _estimate_lines(mask: np.ndarray, axis: int) -> int:
        projection = np.sum(mask > 0, axis=axis)
        active = projection > max(5, projection.max() * 0.2 if projection.size else 0)
        count = 0
        in_run = False
        for flag in active:
            if flag and not in_run:
                count += 1
                in_run = True
            elif not flag:
                in_run = False
        return count - 1 if count > 1 else count


class EquationDetector:
    def detect(self, spans: Sequence[TextSpan]) -> List[EquationObject]:
        equations: List[EquationObject] = []
        for span in spans:
            if EQUATION_HINT_RE.search(span.text):
                equations.append(
                    EquationObject(
                        bbox=span.bbox,
                        page_no=span.page_no,
                        latex=self.to_latex(span.text),
                        confidence=span.confidence,
                    )
                )
        return equations

    def to_latex(self, text: str) -> str:
        latex = text
        replacements = {
            "∑": r"\\sum",
            "∫": r"\\int",
            "√": r"\\sqrt",
            "≤": r"\\leq",
            "≥": r"\\geq",
            "π": r"\\pi",
            "∞": r"\\infty",
            "×": r"\\times",
            "÷": r"\\div",
        }
        for src, tgt in replacements.items():
            latex = latex.replace(src, tgt)
        if "=" in latex and "^" not in latex and re.search(r"[0-9][²³]", text):
            latex = latex.replace("²", "^2").replace("³", "^3")
        return latex


class BackgroundRestorer:
    def restore(self, image_path: str, spans: Sequence[TextSpan], output_path: str) -> str:
        image = cv2.imread(image_path)
        if image is None:
            return image_path
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        for span in spans:
            x1, y1, x2, y2 = [max(0, int(v)) for v in span.bbox]
            pad = 2
            cv2.rectangle(mask, (max(0, x1 - pad), max(0, y1 - pad)), (min(mask.shape[1] - 1, x2 + pad), min(mask.shape[0] - 1, y2 + pad)), 255, -1)
        restored = cv2.inpaint(image, mask, 3, cv2.INPAINT_TELEA)
        cv2.imwrite(output_path, restored)
        return output_path


class Translator:
    def __init__(self, source_lang: str = "auto", target_lang: str = "en"):
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.backend = None
        try:
            from deep_translator import GoogleTranslator  # type: ignore

            self.backend = GoogleTranslator(source=source_lang, target=target_lang)
        except Exception:
            self.backend = None

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        if self.backend is None:
            return text
        try:
            return self.backend.translate(text)
        except Exception:
            return text

    def batch_translate(self, spans: Sequence[TextSpan]) -> None:
        for span in spans:
            span.translated_text = self.translate(span.text)

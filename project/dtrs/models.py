from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

BBox = Tuple[float, float, float, float]


@dataclass
class TextSpan:
    text: str
    bbox: BBox
    page_no: int
    confidence: float = 1.0
    rotation: float = 0.0
    color: Tuple[int, int, int] = (0, 0, 0)
    font_name: str = "Helvetica"
    font_size: float = 12.0
    char_spacing: float = 0.0
    line_height: Optional[float] = None
    translated_text: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TableCell:
    row: int
    col: int
    bbox: BBox
    text: str = ""


@dataclass
class TableObject:
    bbox: BBox
    page_no: int
    rows: int
    cols: int
    cells: List[TableCell] = field(default_factory=list)


@dataclass
class EquationObject:
    bbox: BBox
    page_no: int
    latex: str = ""
    confidence: float = 0.0


@dataclass
class GraphicObject:
    bbox: BBox
    page_no: int
    kind: str = "image"
    source_path: Optional[str] = None


@dataclass
class PageModel:
    page_no: int
    width: int
    height: int
    image_path: str
    text_spans: List[TextSpan] = field(default_factory=list)
    tables: List[TableObject] = field(default_factory=list)
    equations: List[EquationObject] = field(default_factory=list)
    graphics: List[GraphicObject] = field(default_factory=list)
    background_path: Optional[str] = None


@dataclass
class DocumentModel:
    source_pdf: str
    pages: List[PageModel] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

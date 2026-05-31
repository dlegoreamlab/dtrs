from __future__ import annotations

import argparse
import os

from .pipeline import DTRSPipeline, PipelineConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DTRS prototype: document translation and reconstruction")
    parser.add_argument("source_pdf", help="input PDF path")
    parser.add_argument("--workdir", default="./workdir", help="working directory")
    parser.add_argument("--output", default="./translated_reconstructed.pdf", help="output PDF path")
    parser.add_argument("--source-lang", default="auto", help="translation source language")
    parser.add_argument("--target-lang", default="en", help="translation target language")
    parser.add_argument("--ocr-backend", default="tesseract", choices=["tesseract", "paddle"], help="ocr backend")
    parser.add_argument("--tesseract-lang", default="eng+kor", help="tesseract language pack string")
    parser.add_argument("--dpi", default=200, type=int, help="render DPI")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    os.makedirs(args.workdir, exist_ok=True)
    config = PipelineConfig(
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        ocr_backend=args.ocr_backend,
        tesseract_lang=args.tesseract_lang,
        dpi=args.dpi,
    )
    pipeline = DTRSPipeline(config)
    pipeline.run(args.source_pdf, args.workdir, args.output)
    print(f"done: {args.output}")


if __name__ == "__main__":
    main()

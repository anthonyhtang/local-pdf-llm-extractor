from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pdf_extractor.utils import normalize_extracted_text


class ConversionError(RuntimeError):
    pass


class MineruUnavailableError(ConversionError):
    pass


ConversionResult = tuple[str, str, list[str]]


def convert_pdf(
    pdf_path: Path,
    engine: Literal["mineru", "pymupdf", "fast", "fast-first"] = "mineru",
    fast_fallback: bool = False,
) -> ConversionResult:
    warnings: list[str] = []
    should_try_fast_first = engine in {"fast", "fast-first"}
    should_fallback_after_fast = fast_fallback or engine == "fast-first"

    if should_try_fast_first:
        try:
            return extract_text_fast(pdf_path), "fast", warnings
        except Exception as exc:
            if not should_fallback_after_fast:
                raise ConversionError(f"fast text extraction failed for {pdf_path.name}: {exc}") from exc
            warnings.append(f"fast text extraction failed for {pdf_path.name}: {exc}")
            warnings.append("Falling back to Markdown conversion engines.")

    if engine == "pymupdf":
        return convert_with_pymupdf(pdf_path), "pymupdf", warnings

    warnings.extend(_describe_mineru_runtime())

    try:
        return convert_with_mineru(pdf_path), "mineru", warnings
    except Exception as exc:  # pragma: no cover - defensive branch around third-party code
        warnings.append(f"MinerU failed for {pdf_path.name}: {exc}")

    warnings.append("Falling back to pymupdf4llm.")
    return convert_with_pymupdf(pdf_path), "pymupdf", warnings


def convert_pdfs(
    pdf_paths: list[Path],
    engine: Literal["mineru", "pymupdf", "fast", "fast-first"] = "mineru",
    fast_fallback: bool = False,
    batch_convert: bool = True,
) -> tuple[dict[Path, ConversionResult], dict[Path, str]]:
    if not pdf_paths:
        return {}, {}

    if not batch_convert or engine != "mineru" or len(pdf_paths) <= 1:
        return _convert_pdfs_individually(pdf_paths, engine, fast_fallback)

    results: dict[Path, ConversionResult] = {}
    failures: dict[Path, str] = {}
    shared_warnings = _describe_mineru_runtime()

    try:
        mineru_results = convert_with_mineru_batch(pdf_paths)
    except Exception:
        return _convert_pdfs_individually(pdf_paths, engine, fast_fallback)

    for pdf_path in pdf_paths:
        if pdf_path in mineru_results:
            results[pdf_path] = (mineru_results[pdf_path], "mineru", shared_warnings.copy())
            continue

        warnings = shared_warnings.copy()
        warnings.append(f"MinerU batch conversion did not produce a Markdown file for {pdf_path.name}.")
        warnings.append("Falling back to pymupdf4llm.")
        try:
            results[pdf_path] = (convert_with_pymupdf(pdf_path), "pymupdf", warnings)
        except Exception as exc:
            failures[pdf_path] = str(exc)

    return results, failures


def _convert_pdfs_individually(
    pdf_paths: list[Path],
    engine: Literal["mineru", "pymupdf", "fast", "fast-first"],
    fast_fallback: bool,
) -> tuple[dict[Path, ConversionResult], dict[Path, str]]:
    results: dict[Path, ConversionResult] = {}
    failures: dict[Path, str] = {}

    for pdf_path in pdf_paths:
        try:
            results[pdf_path] = convert_pdf(pdf_path, engine=engine, fast_fallback=fast_fallback)
        except Exception as exc:
            failures[pdf_path] = str(exc)

    return results, failures


def convert_with_mineru(pdf_path: Path) -> str:
    try:
        from mineru.cli.common import do_parse
        from mineru.cli.common import read_fn
    except ImportError as exc:  # pragma: no cover - depends on optional native packages
        raise MineruUnavailableError(f"MinerU is unavailable: {exc}") from exc

    with TemporaryDirectory() as tmp_dir:
        output_dir = Path(tmp_dir)
        do_parse(
            output_dir=str(output_dir),
            pdf_file_names=[pdf_path.stem],
            pdf_bytes_list=[read_fn(pdf_path)],
            p_lang_list=["en"],
            backend="pipeline",
            parse_method="auto",
            formula_enable=True,
            table_enable=True,
            f_draw_layout_bbox=False,
            f_draw_span_bbox=False,
            f_dump_md=True,
            f_dump_middle_json=False,
            f_dump_model_output=False,
            f_dump_orig_pdf=False,
            f_dump_content_list=False,
        )

        markdown_files = sorted(output_dir.rglob(f"{pdf_path.stem}.md"))
        if not markdown_files:
            raise ConversionError(f"MinerU did not produce a Markdown file for {pdf_path.name}")
        text = markdown_files[0].read_text(encoding="utf-8")

    if not text or not text.strip():
        raise ConversionError(f"MinerU produced no text for {pdf_path.name}")
    return text.strip()


def convert_with_mineru_batch(pdf_paths: list[Path]) -> dict[Path, str]:
    try:
        from mineru.cli.common import do_parse
        from mineru.cli.common import read_fn
    except ImportError as exc:  # pragma: no cover - depends on optional native packages
        raise MineruUnavailableError(f"MinerU is unavailable: {exc}") from exc

    alias_map = {pdf_path: f"pdf_{index:04d}" for index, pdf_path in enumerate(pdf_paths, start=1)}

    with TemporaryDirectory() as tmp_dir:
        output_dir = Path(tmp_dir)
        do_parse(
            output_dir=str(output_dir),
            pdf_file_names=[alias_map[pdf_path] for pdf_path in pdf_paths],
            pdf_bytes_list=[read_fn(pdf_path) for pdf_path in pdf_paths],
            p_lang_list=["en"] * len(pdf_paths),
            backend="pipeline",
            parse_method="auto",
            formula_enable=True,
            table_enable=True,
            f_draw_layout_bbox=False,
            f_draw_span_bbox=False,
            f_dump_md=True,
            f_dump_middle_json=False,
            f_dump_model_output=False,
            f_dump_orig_pdf=False,
            f_dump_content_list=False,
        )

        results: dict[Path, str] = {}
        for pdf_path, alias in alias_map.items():
            markdown_files = sorted(output_dir.rglob(f"{alias}.md"))
            if not markdown_files:
                continue

            text = markdown_files[0].read_text(encoding="utf-8").strip()
            if text:
                results[pdf_path] = text

    return results


def convert_with_pymupdf(pdf_path: Path) -> str:
    try:
        import pymupdf4llm
    except ImportError as exc:  # pragma: no cover - depends on optional native packages
        raise ConversionError(f"pymupdf4llm is unavailable: {exc}") from exc

    text = pymupdf4llm.to_markdown(str(pdf_path))
    if not text or not text.strip():
        raise ConversionError(f"pymupdf4llm produced no text for {pdf_path.name}")
    return text.strip()


def extract_text_fast(pdf_path: Path) -> str:
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - depends on optional native packages
        raise ConversionError(f"PyMuPDF is unavailable for fast extraction: {exc}") from exc

    text_parts: list[str] = []

    with pymupdf.open(pdf_path) as document:
        for page in document:
            page_text = page.get_text("text", sort=True)
            if page_text and page_text.strip():
                text_parts.append(page_text)

    normalized_text = normalize_extracted_text("\n\n".join(text_parts))
    if len(normalized_text) < 100:
        raise ConversionError("no usable embedded text layer was found")
    return normalized_text


def _describe_mineru_runtime() -> list[str]:
    warnings: list[str] = []

    try:
        import torch
    except ImportError:
        warnings.append("PyTorch is unavailable, so MinerU GPU detection could not be confirmed ahead of time.")
        return warnings

    if not torch.cuda.is_available():
        warnings.append("CUDA is not available in the current Python environment. MinerU will run on CPU in this environment.")
        return warnings

    try:
        device_name = torch.cuda.get_device_name(torch.cuda.current_device())
    except Exception:  # pragma: no cover - hardware and driver dependent
        device_name = "unknown GPU"

    warnings.append(f"CUDA is available. MinerU will run with GPU acceleration on {device_name}.")
    return warnings

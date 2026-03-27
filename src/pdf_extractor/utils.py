from __future__ import annotations

import re
from pathlib import Path
from math import ceil
from typing import Iterable


def discover_pdf_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() == ".pdf" else []

    if not input_path.is_dir():
        return []

    return sorted(
        pdf_path
        for pdf_path in input_path.rglob("*")
        if pdf_path.is_file() and pdf_path.suffix.lower() == ".pdf"
    )


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def truncate_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."


def build_output_path(pdf_path: Path, output_dir: Path | None) -> Path:
    target_dir = output_dir if output_dir is not None else pdf_path.parent
    return target_dir / f"{pdf_path.stem}.md"


def resolve_chunk_size(text_length: int, engine: str, requested_chunk_size: int | None) -> int:
    if requested_chunk_size is not None:
        return requested_chunk_size

    if text_length <= 0:
        return 6000

    if engine == "fast":
        base_size = 12000
        target_chunks = 6
        max_size = 16000
    else:
        base_size = 7000
        target_chunks = 10
        max_size = 10000

    adaptive_size = max(base_size, ceil(text_length / target_chunks))
    return min(adaptive_size, max_size)


def normalize_extracted_text(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    paragraphs: list[str] = []
    current_lines: list[str] = []

    for raw_line in lines:
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            if current_lines:
                paragraphs.append(_merge_wrapped_lines(current_lines))
                current_lines = []
            continue
        current_lines.append(line)

    if current_lines:
        paragraphs.append(_merge_wrapped_lines(current_lines))

    cleaned = "\n\n".join(paragraph for paragraph in paragraphs if paragraph)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def split_markdown_into_chunks(markdown: str, chunk_size: int) -> list[str]:
    markdown = markdown.strip()
    if not markdown:
        return []

    if len(markdown) <= chunk_size:
        return [markdown]

    sections = _split_into_sections(markdown)
    chunks: list[str] = []
    current_parts: list[str] = []
    current_length = 0

    for section in sections:
        if len(section) > chunk_size:
            oversized_sections = _split_large_section(section, chunk_size)
        else:
            oversized_sections = [section]

        for part in oversized_sections:
            part_length = len(part)
            if current_parts and current_length + 2 + part_length > chunk_size:
                chunks.append("\n\n".join(current_parts).strip())
                current_parts = [part]
                current_length = part_length
                continue

            current_parts.append(part)
            current_length = part_length if current_length == 0 else current_length + 2 + part_length

    if current_parts:
        chunks.append("\n\n".join(current_parts).strip())

    return [chunk for chunk in chunks if chunk]


def _split_into_sections(markdown: str) -> list[str]:
    sections: list[str] = []
    current_lines: list[str] = []

    for line in markdown.splitlines():
        if line.startswith("#") and current_lines:
            sections.append("\n".join(current_lines).strip())
            current_lines = [line]
            continue
        current_lines.append(line)

    if current_lines:
        sections.append("\n".join(current_lines).strip())

    return [section for section in sections if section]


def _split_large_section(section: str, chunk_size: int) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in section.split("\n\n") if paragraph.strip()]
    if len(paragraphs) <= 1:
        return _split_by_length(section, chunk_size)

    chunks: list[str] = []
    current_parts: list[str] = []
    current_length = 0

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            if current_parts:
                chunks.append("\n\n".join(current_parts).strip())
                current_parts = []
                current_length = 0
            chunks.extend(_split_by_length(paragraph, chunk_size))
            continue

        if current_parts and current_length + 2 + len(paragraph) > chunk_size:
            chunks.append("\n\n".join(current_parts).strip())
            current_parts = [paragraph]
            current_length = len(paragraph)
            continue

        current_parts.append(paragraph)
        current_length = len(paragraph) if current_length == 0 else current_length + 2 + len(paragraph)

    if current_parts:
        chunks.append("\n\n".join(current_parts).strip())

    return chunks


def _split_by_length(text: str, chunk_size: int) -> list[str]:
    return [text[index : index + chunk_size].strip() for index in range(0, len(text), chunk_size) if text[index : index + chunk_size].strip()]


def format_chunked_output(chunk_results: Iterable[str]) -> str:
    results = [result.strip() for result in chunk_results if result.strip()]
    if len(results) <= 1:
        return results[0] if results else ""

    return "\n\n".join(
        f"## Chunk {index}\n\n{result}"
        for index, result in enumerate(results, start=1)
    )


def _merge_wrapped_lines(lines: list[str]) -> str:
    merged = lines[0]

    for line in lines[1:]:
        if merged.endswith("-") and not line.startswith(("-", "*", "•")):
            merged = merged[:-1] + line
            continue

        merged = f"{merged} {line}"

    return merged.strip()

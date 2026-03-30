from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from time import perf_counter
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from pdf_extractor.converter import ConversionError, convert_pdf, convert_pdfs
from pdf_extractor.extractor import LiteModelClient, ModelProviderError
from pdf_extractor.utils import (
    build_output_path,
    discover_pdf_files,
    format_chunked_output,
    read_text_file,
    resolve_chunk_size,
    split_markdown_into_chunks,
    write_text_file,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Run local PDF retrieval/extraction and produce concise consolidation output for downstream LLM processing.",
)
console = Console()


@dataclass(slots=True)
class FileProcessingMetrics:
    pdf_name: str
    resolved_engine: str = ""
    chunk_model: str = ""
    aggregate_model: str = ""
    chunk_size: int = 0
    chunk_count: int = 0
    convert_seconds: float = 0.0
    chunk_seconds: float = 0.0
    extract_seconds: float = 0.0
    merge_seconds: float = 0.0
    write_seconds: float = 0.0
    total_seconds: float = 0.0


@app.command()
def main(
    input: Annotated[Path, typer.Option("--input", exists=True, file_okay=True, dir_okay=True, readable=True, path_type=Path, help="PDF file or directory containing PDFs.")],
    prompt: Annotated[str | None, typer.Option("--prompt", help="Retrieval/extraction instruction text.")] = None,
    prompt_file: Annotated[Path | None, typer.Option("--prompt-file", exists=True, file_okay=True, dir_okay=False, readable=True, path_type=Path, help="Path to a text file containing the extraction prompt.")] = None,
    output_dir: Annotated[Path | None, typer.Option("--output-dir", file_okay=False, dir_okay=True, writable=True, path_type=Path, help="Directory to write outputs to. Defaults to each PDF directory.")] = None,
    engine: Annotated[Literal["mineru", "pymupdf", "fast", "fast-first"], typer.Option("--engine", case_sensitive=False, help="Extraction engine to use.")] = "mineru",
    fast_fallback: Annotated[bool, typer.Option("--fast-fallback", help="When --engine fast fails, fall back to the slower Markdown conversion pipeline. This is implied by --engine fast-first.")] = False,
    provider: Annotated[Literal["local", "openrouter"], typer.Option("--provider", case_sensitive=False, help="Lite model provider to use.")] = "local",
    local_url: Annotated[str, typer.Option("--local-url", "--ollama-url", help="Base URL for the local model API (Ollama-compatible).")]= "http://localhost:11434",
    openrouter_url: Annotated[str, typer.Option("--openrouter-url", help="Base URL for OpenRouter API.")] = "https://openrouter.ai/api/v1",
    openrouter_api_key_env: Annotated[str, typer.Option("--openrouter-api-key-env", help="Environment variable name that stores the OpenRouter API key.")] = "OPENROUTER_API_KEY_Test",
    model: Annotated[str, typer.Option("--model", help="Model name for chunk extraction and document-level consolidation.")] = "qwen3.5:9b",
    chunk_model: Annotated[str | None, typer.Option("--chunk-model", help="Optional model override for chunk-level extraction. Defaults to --model.")] = None,
    chunk_size: Annotated[int | None, typer.Option("--chunk-size", min=500, help="Maximum characters per chunk sent to the model provider. Leave unset to use adaptive defaults.")] = None,
    parallelism: Annotated[int, typer.Option("--parallelism", min=1, help="Maximum number of concurrent chunk requests.")] = 2,
    min_request_interval: Annotated[float | None, typer.Option("--min-request-interval", min=0.0, help="Minimum seconds between outbound model API requests. Defaults: local=0.0, openrouter=1.0.")] = None,
    max_retries: Annotated[int, typer.Option("--max-retries", min=0, help="Maximum retry attempts for model API timeouts and throttling responses.")] = 4,
    batch_convert: Annotated[bool, typer.Option("--batch-convert/--no-batch-convert", help="Batch PDF conversion across multiple files when the selected engine supports it.")] = True,
    include_chunk_details: Annotated[bool, typer.Option("--include-chunk-details", help="Append per-chunk candidate answers for debugging; main output remains concise consolidation text.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Show detailed execution status and timing information.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Write extracted content to disk and skip model API extraction.")] = False,
) -> None:
    try:
        _run(
            input_path=input,
            prompt=prompt,
            prompt_file=prompt_file,
            output_dir=output_dir,
            engine=engine,
            fast_fallback=fast_fallback,
            provider=provider,
            local_url=local_url,
            openrouter_url=openrouter_url,
            openrouter_api_key_env=openrouter_api_key_env,
            model=model,
            chunk_model=chunk_model,
            chunk_size=chunk_size,
            parallelism=parallelism,
            min_request_interval=min_request_interval,
            max_retries=max_retries,
            batch_convert=batch_convert,
            include_chunk_details=include_chunk_details,
            verbose=verbose,
            dry_run=dry_run,
        )
    except typer.Exit:
        raise
    except Exception as exc:  # pragma: no cover - top-level safety net
        console.print(f"[red]Unexpected error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


def _run(
    input_path: Path,
    prompt: str | None,
    prompt_file: Path | None,
    output_dir: Path | None,
    engine: Literal["mineru", "pymupdf", "fast", "fast-first"],
    fast_fallback: bool,
    provider: Literal["local", "openrouter"],
    local_url: str,
    openrouter_url: str,
    openrouter_api_key_env: str,
    model: str,
    chunk_model: str | None,
    chunk_size: int | None,
    parallelism: int,
    min_request_interval: float | None,
    max_retries: int,
    batch_convert: bool,
    include_chunk_details: bool,
    verbose: bool,
    dry_run: bool,
) -> None:
    if prompt and prompt_file:
        console.print("[red]Use either --prompt or --prompt-file, not both.[/red]")
        raise typer.Exit(code=2)

    resolved_prompt = _resolve_prompt(prompt, prompt_file)
    pdf_files = discover_pdf_files(input_path)
    if not pdf_files:
        console.print(f"[red]No PDF files found at {input_path}.[/red]")
        raise typer.Exit(code=1)

    if provider == "openrouter" and parallelism > 2:
        console.print("[yellow]OpenRouter mode caps parallelism at 2 by default to avoid API throttling.[/yellow]")
        parallelism = 2

    resolved_chunk_model = chunk_model or model

    model_client: LiteModelClient | None = None
    startup_seconds = 0.0
    if not dry_run:
        startup_started = perf_counter()
        api_key: str | None = None
        base_url = local_url
        if provider == "openrouter":
            base_url = openrouter_url
            api_key = os.environ.get(openrouter_api_key_env, "").strip() or None
            if not api_key:
                console.print(
                    f"[red]Missing OpenRouter API key. Set env var {openrouter_api_key_env} before running.[/red]"
                )
                raise typer.Exit(code=2)

        effective_min_interval = min_request_interval
        if effective_min_interval is None:
            effective_min_interval = 1.0 if provider == "openrouter" else 0.0

        model_client = LiteModelClient(
            provider=provider,
            base_url=base_url,
            model=model,
            api_key=api_key,
            min_request_interval_seconds=effective_min_interval,
            max_retries=max_retries,
        )
        startup_check_warning: str | None = None
        try:
            available_models = model_client.ensure_model_available([model, resolved_chunk_model])
        except ModelProviderError as exc:
            message = str(exc)
            is_transient_openrouter_startup = (
                provider == "openrouter"
                and message.startswith("Unable to reach OpenRouter")
            )
            if is_transient_openrouter_startup:
                startup_check_warning = message
                available_models = [model, resolved_chunk_model]
            else:
                console.print(f"[red]{exc}[/red]")
                model_client.close()
                raise typer.Exit(code=1) from exc
        startup_seconds = perf_counter() - startup_started
        console.print(
            f"[green]Model provider ready.[/green] Provider: [bold]{provider}[/bold] | Primary: [bold]{model}[/bold] | Chunk: [bold]{resolved_chunk_model}[/bold] | Available: {', '.join(available_models)}"
        )
        if startup_check_warning:
            console.print(
                "[yellow]Startup model-list probe failed transiently; continuing with runtime requests.[/yellow] "
                f"{startup_check_warning}"
            )
        if verbose:
            console.print(
                f"[blue]Provider startup check:[/blue] {startup_seconds:.3f}s | min_interval={effective_min_interval:.2f}s | retries={max_retries}"
            )

    failures: list[tuple[Path, str]] = []
    success_count = 0
    metrics: list[FileProcessingMetrics] = []
    use_batch_progress = len(pdf_files) > 1

    try:
        if use_batch_progress:
            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task_id = progress.add_task("Preparing PDFs", total=len(pdf_files))
                success_count, failures, metrics = _process_pdfs(
                    pdf_files=pdf_files,
                    progress=progress,
                    task_id=task_id,
                    output_dir=output_dir,
                    engine=engine,
                    fast_fallback=fast_fallback,
                    chunk_size=chunk_size,
                    parallelism=parallelism,
                    batch_convert=batch_convert,
                    include_chunk_details=include_chunk_details,
                    verbose=verbose,
                    dry_run=dry_run,
                    model=model,
                    chunk_model=resolved_chunk_model,
                    resolved_prompt=resolved_prompt,
                    model_client=model_client,
                )
        else:
            success_count, failures, metrics = _process_pdfs(
                pdf_files=pdf_files,
                progress=None,
                task_id=None,
                output_dir=output_dir,
                engine=engine,
                fast_fallback=fast_fallback,
                chunk_size=chunk_size,
                parallelism=parallelism,
                batch_convert=batch_convert,
                include_chunk_details=include_chunk_details,
                verbose=verbose,
                dry_run=dry_run,
                model=model,
                chunk_model=resolved_chunk_model,
                resolved_prompt=resolved_prompt,
                model_client=model_client,
            )
    finally:
        if model_client is not None:
            model_client.close()

    console.rule("Run Report")
    console.print(f"Processed successfully: [bold]{success_count}[/bold]")
    console.print(f"Failed: [bold]{len(failures)}[/bold]")
    if metrics and verbose:
        _print_timing_summary(metrics)
    for failed_path, message in failures:
        console.print(f"[red]- {failed_path.name}:[/red] {message}")

    if failures:
        raise typer.Exit(code=1)


def _process_pdfs(
    pdf_files: list[Path],
    progress: Progress | None,
    task_id: int | None,
    output_dir: Path | None,
    engine: Literal["mineru", "pymupdf", "fast", "fast-first"],
    fast_fallback: bool,
    chunk_size: int | None,
    parallelism: int,
    batch_convert: bool,
    include_chunk_details: bool,
    verbose: bool,
    dry_run: bool,
    model: str,
    chunk_model: str,
    resolved_prompt: str,
    model_client: LiteModelClient | None,
) -> tuple[int, list[tuple[Path, str]], list[FileProcessingMetrics]]:
    failures: list[tuple[Path, str]] = []
    success_count = 0
    metrics_list: list[FileProcessingMetrics] = []
    prefetched_results: dict[Path, tuple[str, str, list[str]]] = {}
    prefetched_failures: dict[Path, str] = {}
    shared_convert_seconds = 0.0

    if batch_convert and engine == "mineru" and len(pdf_files) > 1:
        if progress is not None and task_id is not None:
            progress.update(task_id, description=f"Batch converting {len(pdf_files)} PDFs")
        if verbose:
            console.print(f"[blue]Batch conversion:[/blue] enabled for {len(pdf_files)} PDFs with MinerU")
        batch_started = perf_counter()
        prefetched_results, prefetched_failures = convert_pdfs(
            pdf_files,
            engine=engine,
            fast_fallback=fast_fallback,
            batch_convert=True,
        )
        batch_seconds = perf_counter() - batch_started
        shared_convert_seconds = batch_seconds / len(pdf_files)
        if verbose:
            console.print(f"[blue]Batch conversion timing:[/blue] total={batch_seconds:.3f}s | amortized={shared_convert_seconds:.3f}s/file")

    for pdf_path in pdf_files:
        started = perf_counter()
        metrics = FileProcessingMetrics(pdf_name=pdf_path.name)
        amortized_convert_seconds = 0.0
        stage_label = "Extracting text" if engine in {"fast", "fast-first"} else "Converting"
        if progress is not None and task_id is not None:
            progress.update(task_id, description=f"{stage_label} {pdf_path.name}")

        console.print(f"[cyan]{pdf_path.name}[/cyan] [white]{stage_label.lower()}[/white]")

        try:
            if pdf_path in prefetched_failures:
                amortized_convert_seconds = shared_convert_seconds
                raise ConversionError(prefetched_failures[pdf_path])

            if pdf_path in prefetched_results:
                extracted_text, resolved_engine, warnings = prefetched_results[pdf_path]
                metrics.convert_seconds = shared_convert_seconds
                amortized_convert_seconds = shared_convert_seconds
            else:
                convert_started = perf_counter()
                extracted_text, resolved_engine, warnings = convert_pdf(
                    pdf_path,
                    engine=engine,
                    fast_fallback=fast_fallback,
                )
                metrics.convert_seconds = perf_counter() - convert_started
            metrics.resolved_engine = resolved_engine
            metrics.chunk_model = chunk_model
            metrics.aggregate_model = "-"
            for warning in warnings:
                console.print(f"[yellow]Warning:[/yellow] {warning}")

            if dry_run:
                output_path = build_output_path(pdf_path, output_dir)
                write_started = perf_counter()
                _write_output(output_path, extracted_text)
                metrics.write_seconds = perf_counter() - write_started
                metrics.total_seconds = amortized_convert_seconds + (perf_counter() - started)
                metrics_list.append(metrics)
                console.print(f"[green]{pdf_path.name}[/green] [white]done[/white] -> {output_path}")
                if verbose:
                    _print_file_timing(metrics)
                success_count += 1
                continue

            if progress is not None and task_id is not None:
                progress.update(task_id, description=f"Extracting {pdf_path.name}")

            console.print(f"[cyan]{pdf_path.name}[/cyan] [white]extracting[/white]")

            chunk_started = perf_counter()
            selected_chunk_size = resolve_chunk_size(len(extracted_text), resolved_engine, chunk_size)
            chunks = split_markdown_into_chunks(extracted_text, selected_chunk_size)
            metrics.chunk_seconds = perf_counter() - chunk_started
            if not chunks:
                raise ConversionError(f"No extractable content was produced for {pdf_path.name}")
            metrics.chunk_size = selected_chunk_size
            metrics.chunk_count = len(chunks)
            if verbose:
                console.print(
                    f"[blue]Chunk plan:[/blue] size={metrics.chunk_size} chars | chunks={metrics.chunk_count} | parallelism={parallelism} | chunk_model={chunk_model}"
                )

            assert model_client is not None
            extract_started = perf_counter()
            chunk_outputs = model_client.extract_chunks_parallel(chunks, resolved_prompt, parallelism, model=chunk_model)
            metrics.extract_seconds = perf_counter() - extract_started

            merge_started = perf_counter()
            output_body = model_client.merge_chunk_evidence(chunk_outputs, resolved_prompt, model=model)
            metrics.merge_seconds = perf_counter() - merge_started
            if include_chunk_details:
                chunk_details = format_chunked_output(chunk_outputs)
                if chunk_details:
                    output_body = "\n\n".join(
                        [
                            output_body.strip(),
                            "---",
                            "## Chunk Candidates",
                            "",
                            chunk_details,
                        ]
                    ).strip()
            output_content = _build_extraction_document(output_body)
            output_path = build_output_path(pdf_path, output_dir)
            write_started = perf_counter()
            _write_output(output_path, output_content)
            metrics.write_seconds = perf_counter() - write_started
            metrics.total_seconds = amortized_convert_seconds + (perf_counter() - started)
            metrics_list.append(metrics)
            console.print(f"[green]{pdf_path.name}[/green] [white]done[/white] -> {output_path}")
            if verbose:
                _print_file_timing(metrics)
            success_count += 1
        except (ConversionError, ModelProviderError, OSError) as exc:
            metrics.total_seconds = amortized_convert_seconds + (perf_counter() - started)
            metrics_list.append(metrics)
            failures.append((pdf_path, str(exc)))
            console.print(f"[red]{pdf_path.name}[/red] [white]error[/white] {exc}")
        finally:
            if progress is not None and task_id is not None:
                progress.advance(task_id)

    return success_count, failures, metrics_list


def _resolve_prompt(prompt: str | None, prompt_file: Path | None) -> str:
    if prompt is not None:
        resolved = prompt.strip()
        if resolved:
            return resolved
        console.print("[red]--prompt cannot be empty.[/red]")
        raise typer.Exit(code=2)
    if prompt_file is not None:
        resolved = read_text_file(prompt_file).strip()
        if resolved:
            return resolved
        console.print("[red]--prompt-file is empty.[/red]")
        raise typer.Exit(code=2)

    console.print("[red]A prompt is required. Use --prompt or --prompt-file.[/red]")
    raise typer.Exit(code=2)


def _write_output(output_path: Path, content: str) -> None:
    if output_path.exists():
        console.print(f"[yellow]Warning:[/yellow] Overwriting existing file {output_path}")
    write_text_file(output_path, content.rstrip() + "\n")


def _build_extraction_document(body: str) -> str:
    return body.strip()


def _print_file_timing(metrics: FileProcessingMetrics) -> None:
    console.print(
        "[blue]Timing:[/blue] "
        f"convert={metrics.convert_seconds:.3f}s | "
        f"chunk={metrics.chunk_seconds:.3f}s | "
        f"extract={metrics.extract_seconds:.3f}s | "
        f"merge={metrics.merge_seconds:.3f}s | "
        f"write={metrics.write_seconds:.3f}s | "
        f"total={metrics.total_seconds:.3f}s"
    )


def _print_timing_summary(metrics_list: list[FileProcessingMetrics]) -> None:
    table = Table(title="Timing Summary")
    table.add_column("File")
    table.add_column("Engine")
    table.add_column("Chunk Model")
    table.add_column("Stage2")
    table.add_column("Chunks", justify="right")
    table.add_column("Chunk Size", justify="right")
    table.add_column("Convert", justify="right")
    table.add_column("Chunk", justify="right")
    table.add_column("Extract", justify="right")
    table.add_column("Merge", justify="right")
    table.add_column("Write", justify="right")
    table.add_column("Total", justify="right")

    for metrics in metrics_list:
        table.add_row(
            metrics.pdf_name,
            metrics.resolved_engine or "-",
            metrics.chunk_model or "-",
            metrics.aggregate_model or "-",
            str(metrics.chunk_count),
            str(metrics.chunk_size or 0),
            f"{metrics.convert_seconds:.3f}s",
            f"{metrics.chunk_seconds:.3f}s",
            f"{metrics.extract_seconds:.3f}s",
            f"{metrics.merge_seconds:.3f}s",
            f"{metrics.write_seconds:.3f}s",
            f"{metrics.total_seconds:.3f}s",
        )

    console.print(table)


if __name__ == "__main__":
    app()

# Semantic PDF Retriever

中文说明: [README.zh-CN.md](README.zh-CN.md)

```text
 /\_/\\   Semantic PDF Retriever
( o.o )   Parse PDFs, ask semantically
 > ^ <    Chunk, ask, merge
```

Semantic PDF Retriever is a cross-platform Python CLI that extracts information from PDF documents on your own machine.

## Why This Project

This project is not built for polished summarization. It is built for semantic retrieval and evidence extraction across large PDF collections.

The core use case is high-recall screening: quickly locate relevant documents and passages for a user-defined information need, then output structured evidence for downstream analysis.

The practical need is simple: you often need to search many long PDFs for nuanced semantic signals, but existing approaches force trade-offs that are not acceptable for this workflow.

Why not standard RAG as the primary decision layer:

- RAG scales well for large corpora, but retrieval quality in nuanced semantic tasks (methodology, identification logic, causal claims) is often not precise enough for this workflow.

Why not full online premium models (ChatGPT/Claude/Gemini/etc.) on full corpora:

- Cost grows quickly with batch size and repeated querying.
- At scale, cost is multiplicative: total spend roughly tracks number of PDFs × number of query rounds × average tokens per round, which becomes expensive very quickly in screening workflows.
- Context windows are still a bottleneck when screening large document sets end-to-end.

What this project does instead:

- Uses robust parsing plus lite-model extraction as a controllable middle layer.
- Prioritizes semantic screening precision over polished narrative output.
- Produces intermediate evidence artifacts that can be sent later to stronger and more expensive models.

Output intent:

- The document-level result is intentionally concise and retrieval-oriented.
- It is a screening intermediate artifact for downstream LLM processing, not a final narrative summary.

In short, the model layer's job here is retrieval and extraction, not final writing.

## Problem Context

Many useful research questions are semantic rather than keyword-based. For example:

- In a folder of hundreds of papers, which PDFs use event-study specifications?
- Across a large report set, which documents clearly rely on natural experiments?
- In a batch screening run, which files explicitly describe identification strategy assumptions?

For a small one-off document check, sending a full PDF to a premium model can be acceptable.

The bottleneck appears when you need screening across large PDF collections: repeated querying, repeated context loading, and cross-document screening quickly become expensive and operationally hard to scale.

This project makes that workflow practical: parse consistently, chunk consistently, and run semantic extraction through configurable lite models so you avoid repeatedly sending raw full documents to expensive remote contexts.

It combines three stages:

1. PDF parsing into Markdown or normalized plain text.
2. Chunking the extracted content into LLM-friendly segments.
3. Lite-model-based information extraction through either a local provider or OpenRouter.

The project is designed for users who want a controllable workflow for research papers, reports, and internal documents, with flexible provider choices.

## What This Project Does

- Converts PDFs into Markdown or normalized text.
- Uses lite models from either local runtime (Ollama-compatible) or OpenRouter low-cost/free models.
- Supports both high-fidelity parsing and faster text-first parsing.
- Works on Windows and Linux, including WSL-style paths.
- Supports multi-file directory processing.
- Supports batched MinerU conversion to reduce repeated parser initialization overhead.
- Supports split-model inference for chunk-level extraction and evidence screening.

## Who This Is For

- Researchers extracting evidence or study design details from papers.
- Analysts reviewing reports and long-form PDFs with reproducible pipelines.
- Developers who want a reproducible CLI pipeline built with `uv`.
- Teams that need a transparent workflow instead of a cloud-only document pipeline.

## Core Features

- `mineru` engine for high-fidelity Markdown reconstruction with GPU acceleration when available.
- `fast` engine for direct PDF text extraction when a text layer exists.
- `fast-first` engine to try direct text extraction first and fall back automatically when the PDF has no usable text layer.
- `pymupdf` fallback engine for a lighter-weight Markdown path.
- Batch conversion mode for multi-file MinerU runs.
- Adaptive chunk sizing.
- Concurrent chunk extraction requests to the configured model provider.
- Two-stage extraction: chunk candidates first, evidence merge second.
- Detailed verbose timing output.

## Project Status

This repository packages the application code and dependency metadata only.

It does not vend third-party model weights, downloaded parser assets, Python virtual environments, or benchmark scratch outputs. Those assets are either generated locally or downloaded from upstream projects during installation and first use.

## Architecture Overview

The application has four main parts:

- `src/pdf_extractor/cli.py`: Typer-based CLI entry point and orchestration.
- `src/pdf_extractor/converter.py`: PDF parsing engines and batch conversion logic.
- `src/pdf_extractor/extractor.py`: provider client, chunk extraction, and evidence merging.
- `src/pdf_extractor/utils.py`: chunking, file helpers, normalization, and output helpers.

High-level flow:

```text
PDF(s)
  -> parse with fast / fast-first / mineru / pymupdf
  -> normalize or reconstruct Markdown
  -> split into chunks
  -> send chunk prompts to configured lite model provider
  -> merge chunk evidence into one document output
  -> write Markdown result files
```

## Retrieval and Consolidation Logic

The retrieval and consolidation stage is intentionally simple.

Chunk-level retrieval:

- Each chunk is checked for whether it contains evidence relevant to the user query.
- Non-relevant chunks are dropped.

Document-level consolidation:

- Consolidation is task-general and follows the user query.
- For existence-style queries, it returns EXISTS or NOT EXISTS based on whether any sufficiently supported hit is present.
- For non-existence queries, it does not force existence labels and instead follows the requested output format.
- If multiple distinct supported hits are present, it combines them in one coherent result instead of treating this as a conflict.

Output format intent:

- Return one compact paragraph for downstream processing.
- Keep it concise and retrieval-oriented.
- This is an intermediate artifact for stronger downstream LLMs, not the final narrative report.

## Prompt Templates (Core Tuning Point)

The chunk and consolidation prompts are defined in files, not hardcoded in Python logic:

- `prompts/chunk_prompt.txt`: controls per-chunk retrieval behavior.
- `prompts/consolidation_prompt.txt`: controls document-level consolidation behavior.

These templates are a primary tuning surface for quality and style. You can adjust strictness, detail level, output format constraints, and decision behavior without changing application code.

## Dependencies and Credit

This project depends on upstream open-source software and should not be treated as a replacement for those projects.

Primary upstream dependencies:

- `MinerU` for high-fidelity PDF parsing and layout reconstruction.
- `PyMuPDF` and `pymupdf4llm` for direct text extraction and lightweight Markdown conversion.
- `Ollama` for local LLM serving.
- `OpenRouter` for hosted low-cost/free lite models.
- `PyTorch` and `torchvision` for GPU-enabled runtime support used by MinerU.
- `Typer` for the CLI.
- `httpx` for provider HTTP communication.
- `rich` for terminal formatting and timing tables.

Credit belongs to the maintainers of those upstream projects for the core parsing, model-serving, and runtime capabilities this tool builds on top of.

## Requirements

Runtime requirements:

- Python 3.11 or newer.
- `uv` for environment and dependency management.
- One configured model provider:
  - local provider at `http://localhost:11434` (Ollama-compatible), or
  - OpenRouter API access key via environment variable.

Optional but recommended:

- NVIDIA GPU and CUDA-capable drivers for faster MinerU parsing.

This repository includes both `pyproject.toml` and `requirements.txt`.

- `pyproject.toml` is the source of truth.
- `requirements.txt` is included for compatibility with tooling that expects a pip-style dependency file.

## Installation

### Preferred: uv

```bash
uv sync
```

Run the CLI with:

```bash
uv run pdf-extract --help
```

### Alternative: pip

If you need a conventional installation path for automation or CI, you can use `requirements.txt`, although the main development workflow is based on `uv`.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

On Windows PowerShell, activation is typically:

```powershell
.venv\Scripts\Activate.ps1
```

## Lite Model Provider Setup

You can run with either a local provider (`--provider local`) or OpenRouter (`--provider openrouter`).

### Local Provider (Ollama-compatible)

Start Ollama locally and make sure the model you want to use has been pulled.

Example:

```bash
ollama serve
ollama pull qwen3.5:2b
ollama pull qwen3.5:9b
ollama pull gemma3:4b
```

### OpenRouter Provider

Set your key in an environment variable (default variable name is `OPENROUTER_API_KEY_Test`):

```powershell
$env:OPENROUTER_API_KEY_Test = "<your-key>"
```

Windows persistent user environment variable:

```powershell
setx OPENROUTER_API_KEY_Test "<your-key>"
```

Available free-model presets:

- `minimax/minimax-m2.5:free`
- `openai/gpt-oss-120b:free`
- `google/gemini-2.5-flash-lite`
- `z-ai/glm-4.5-air:free`

Recommended robust preset (validated in this project):

```bash
uv run pdf-extract \
  --input path/to/file.pdf \
  --provider openrouter \
  --model minimax/minimax-m2.5:free \
  --engine fast-first \
  --parallelism 2 \
  --min-request-interval 1.0 \
  --max-retries 4 \
  --prompt-file prompts/your_prompt.txt
```

If this model keeps failing due to upstream provider instability, switch only the model:

```bash
--model openai/gpt-oss-120b:free
```

The default extraction model in the CLI remains `qwen3.5:9b` for local mode.

Recommended local models for this workflow:

- `qwen3.5:2b`: more conservative and cheaper to run. Better when you prefer fewer fabricated details, even if it may miss weak evidence.
- `gemma3:4b`: more aggressive and often better at surfacing candidate answers. Better when you prefer recall and are willing to manually screen noisier outputs.

## Quick Start

### 1. Dry-run a single PDF

This converts the PDF to Markdown or text and writes the intermediate output without calling any model API.

```bash
uv run pdf-extract --input path/to/file.pdf --dry-run
```

### 2. Extract information from a single PDF

```bash
uv run pdf-extract \
  --input path/to/file.pdf \
  --prompt "Extract evidence about the policy shock, including date, location, and affected population" \
  --model qwen3.5:9b
```

Use OpenRouter free model:

```bash
uv run pdf-extract \
  --input path/to/file.pdf \
  --provider openrouter \
  --model minimax/minimax-m2.5:free \
  --engine fast-first \
  --parallelism 2 \
  --min-request-interval 1.0 \
  --max-retries 4 \
  --prompt "Extract evidence about the policy shock, including date, location, and affected population"
```

Official structured prompt template:

```text
Task: <what to extract from the document>

Requirements:
- <format or length requirement>
- <what to include>
- <what to exclude>

If the document does not clearly contain the requested information, write exactly: <fallback text>
```

The extractor recognizes the final line above as a whole-document fallback rule.
At chunk level it will use `NOT_RELEVANT` internally instead of letting a partial chunk emit the final fallback text, then merge relevant chunk evidence without running a local summary stage.

Example: exogenous shock extraction

```text
Identify the main exogenous shock or natural experiment used in this document, if there is one.

Requirements:
- Answer in no more than 120 words.
- Describe only the event itself: what happened, when and where it occurred, and why it is treated as plausibly exogenous.
- Do not describe the paper, research design, identification strategy, treatment or control groups, methods, data, sample period, results, mechanisms, moderators, or robustness checks.

If the document does not clearly contain the requested information, write exactly: No clear exogenous shock identified.
```

### 3. Process a folder of PDFs

```bash
uv run pdf-extract \
  --input path/to/folder \
  --prompt-file prompts/your_prompt.txt \
  --output-dir output
```

## Usage

### Basic Help

```bash
uv run pdf-extract --help
```

### Single-File Workflows

Convert a single PDF without LLM extraction:

```bash
uv run pdf-extract --input fulltext/testing.pdf --dry-run
```

Use the fast embedded-text engine:

```bash
uv run pdf-extract --input fulltext/testing.pdf --engine fast --dry-run
```

Use the recommended automatic text-first mode:

```bash
uv run pdf-extract \
  --input fulltext/testing.pdf \
  --engine fast-first \
  --prompt "Extract all findings"
```

Use the high-fidelity MinerU engine:

```bash
uv run pdf-extract \
  --input fulltext/testing.pdf \
  --engine mineru \
  --prompt "Extract all findings"
```

### Directory Workflows

Process all PDFs in a folder recursively:

```bash
uv run pdf-extract \
  --input fulltext \
  --prompt-file prompts/your_prompt.txt \
  --output-dir output
```

Force batched MinerU conversion across multiple files:

```bash
uv run pdf-extract \
  --input fulltext \
  --engine mineru \
  --batch-convert \
  --prompt-file prompts/your_prompt.txt \
  --output-dir output
```

Disable batched conversion for comparison or debugging:

```bash
uv run pdf-extract \
  --input fulltext \
  --engine mineru \
  --no-batch-convert \
  --prompt-file prompts/your_prompt.txt \
  --output-dir output
```

### Model Selection

Use one model for chunk extraction:

```bash
uv run pdf-extract \
  --input fulltext/testing.pdf \
  --prompt "Extract all findings" \
  --model qwen3.5:9b
```

Use a smaller chunk model for faster chunk-level retrieval:

```bash
uv run pdf-extract \
  --input fulltext/testing.pdf \
  --engine fast \
  --chunk-model gemma3:4b \
  --model qwen3.5:9b \
  --parallelism 3 \
  --verbose \
  --prompt "Extract all findings"
```

### Debugging and Timing

Show detailed timing data:

```bash
uv run pdf-extract \
  --input fulltext/testing.pdf \
  --engine fast-first \
  --verbose \
  --prompt "Extract all findings"
```

Include per-chunk candidate answers in the output file:

```bash
uv run pdf-extract \
  --input fulltext/testing.pdf \
  --engine fast \
  --include-chunk-details \
  --prompt "Extract all findings"
```

## CLI Reference

```text
pdf-extract \
  --input PATH \
  --prompt TEXT \
  --prompt-file PATH \
  --output-dir PATH \
  --engine [mineru|pymupdf|fast|fast-first] \
  --fast-fallback \
  --provider [local|openrouter] \
  --local-url TEXT \
  --openrouter-url TEXT \
  --openrouter-api-key-env TEXT \
  --model TEXT \
  --chunk-model TEXT \
  --chunk-size INT \
  --parallelism INT \
  --min-request-interval FLOAT \
  --max-retries INT \
  --batch-convert / --no-batch-convert \
  --include-chunk-details \
  --verbose \
  --dry-run
```

Important options:

- `--input`: single PDF or directory of PDFs.
- `--prompt`: inline extraction instruction.
- `--prompt-file`: read the extraction instruction from a file.
- `--output-dir`: write outputs to a dedicated directory instead of each source directory.
- `--engine`: choose the parsing strategy.
- `--provider`: `local` (default) or `openrouter`.
- `--local-url`: local provider base URL (Ollama-compatible).
- `--openrouter-api-key-env`: env var name for OpenRouter API key (default `OPENROUTER_API_KEY_Test`).
- `--model`: default model for chunk-level extraction.
- `--chunk-model`: optional override model for chunk-level extraction.
- `--parallelism`: number of concurrent chunk requests sent to provider. Default is `2`.
- `--min-request-interval`: minimum delay between outbound requests. Defaults to `1.0s` in OpenRouter mode.
- `--max-retries`: retry count for timeouts/429/5xx.
- `--verbose`: print startup, plan, and timing details.
- `--dry-run`: skip provider calls and only write converted text or Markdown.

## Remote API Rate-Limit Defaults

When `--provider openrouter` is used, the CLI applies conservative defaults to reduce ban/throttle risk:

- Parallelism is capped at `2`.
- Minimum request interval defaults to `1.0` second.
- `429`, `408`, `5xx` responses are retried with exponential backoff and jitter.
- If the provider returns `Retry-After`, that server hint is honored before retrying.
- If OpenRouter `/models` startup probing fails transiently, runtime requests still proceed with warning mode.

These defaults are intentionally conservative for long-running multi-PDF jobs.

## Engine Comparison

| Engine         | What it does                                  | Strengths                                                    | Tradeoffs                                                | Recommended use                                           |
| -------------- | --------------------------------------------- | ------------------------------------------------------------ | -------------------------------------------------------- | --------------------------------------------------------- |
| `fast`       | Reads the embedded PDF text layer directly    | Fastest path for text-based PDFs                             | Fails on image-only PDFs and does not reconstruct layout | Use when you know the PDF already has a usable text layer |
| `fast-first` | Tries `fast`, then falls back automatically | Best convenience-to-speed balance                            | Fallback path is slower than direct extraction           | Recommended default when document quality is unknown      |
| `mineru`     | Performs higher-fidelity PDF reconstruction   | Best layout recovery, tables, formulas, and GPU acceleration | Heavier runtime and dependency footprint                 | Use when output fidelity matters more than raw speed      |
| `pymupdf`    | Uses a lighter Markdown conversion path       | Simpler and lighter fallback                                 | Lower fidelity on complex layouts                        | Use when MinerU is unavailable or intentionally avoided   |

## Output Files

The tool writes Markdown outputs next to the input file by default, or into `--output-dir` if specified.

Output conventions:

- All modes write to `{pdf_stem}.md` by default.
- Running a different mode later for the same PDF will overwrite that Markdown file unless you change `--output-dir`.
- This naming policy is intentional so the default output stays simple and predictable for batch processing and downstream tooling.

Full extraction outputs include:

- PDF file name
- model metadata
- engine metadata
- prompt preview
- date
- merged evidence extracted from relevant chunks

By design, this output is a compact retrieval result for downstream processing (for example, by a stronger hosted LLM), rather than a polished end-user report.

If `--include-chunk-details` is enabled, the output also appends chunk-level candidate answers.

## Performance Notes

- `fast` and `fast-first` are usually the fastest choices when the PDF contains a usable text layer.
- Once PDF parsing becomes fast enough, model inference usually becomes the dominant cost.
- Chunk-level model choice strongly affects throughput and recall quality for local retrieval.
- Batch conversion helps most when multiple PDFs are processed with `mineru` and initialization overhead would otherwise repeat.

## Windows and Linux Path Support

All file handling uses `pathlib.Path`.

Examples:

- Windows: `C:\Users\name\docs\paper.pdf`
- Linux: `/home/name/docs/paper.pdf`
- WSL-mounted Windows path: `/mnt/c/Users/name/docs/paper.pdf`

## Limitations

- Scanned PDFs without a usable text layer may require the heavier Markdown path and still produce imperfect output.
- Complex tables and visual layouts remain dependent on upstream parser quality.
- Very long documents may still produce imperfect chunk boundaries if the reconstructed structure is weak.
- Local LLM quality depends heavily on the prompt and model choice.

## Repository Contents

This repository is intended to store source code and configuration, not generated runtime artifacts.

The public repository is meant to be a lightweight, reproducible project checkout. Users are expected to install dependencies and download upstream model assets through the documented setup flow rather than retrieving them from this repository.

Ignored from version control:

- local virtual environments
- benchmark logs
- temporary validation folders
- generated output folders
- local sample PDFs and derived outputs

## Development Notes

- The project is developed with `uv`.
- `uv.lock` is checked in for reproducible installs.
- `requirements.txt` is provided for compatibility, but `pyproject.toml` remains canonical.

## Verification Checklist

1. `uv sync` completes successfully.
2. `uv run pdf-extract --help` shows the CLI options.
3. `uv run pdf-extract --input path/to/file.pdf --dry-run` writes a conversion artifact without calling any provider.
4. `uv run pdf-extract --input path/to/file.pdf --prompt "..."` calls the configured provider and writes an extraction artifact.
5. `uv run pdf-extract --input path/to/folder --batch-convert --dry-run` processes multiple PDFs successfully.

## License and Upstream Notice

This repository contains the orchestration code for a local PDF extraction workflow.

This project is released under the MIT License. See the `LICENSE` file for the full text.

It depends on third-party open-source projects for PDF parsing, model runtime support, and local LLM serving. Please review and comply with the licenses and attribution requirements of those upstream dependencies when redistributing or deploying this project.

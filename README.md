# Local PDF LLM Extractor

Chinese version: [README.zh-CN.md](README.zh-CN.md)

```text
    _                    _   ____  ____  _____   _      _      __  __
   | |    ___   ___ __ _| | |  _ \|  _ \|  ___| | |    | |    |  \/  |
   | |   / _ \ / __/ _` | | | |_) | | | | |_    | |    | |    | |\/| |
   | |__| (_) | (_| (_| | | |  __/| |_| |  _|   | |___ | |___ | |  | |
   |_____\___/ \___\__,_|_| |_|   |____/|_|     |_____||_____||_|  |_|

    _____         _                  _
   | ____|__  __ | |_ _ __ __ _  ___| |_ ___  _ __
   |  _|  \ \/ / | __| '__/ _` |/ __| __/ _ \| '__|
   | |___  >  <  | |_| | | (_| | (__| || (_) | |
   |_____/_/\_\  \__|_|  \__,_|\___|\__\___/|_|

                .-"""-.
               / .===. \
               \/ 6 6 \/
               ( \___/ )
___ooo__________\_____/_______________________________
/                                                     /
|  > ask_semantic_question("what statistical tool?") |
|  > parse locally                                    |
|  > chunk smartly                                    |
|  > query ollama                                     |
|  > write answer.md                                  |
\____________________________ooo______________________\
               |  |  |
               |_ | _|
               |  |  |
               |__|__|
               /-'Y'-\\
              (__/ \__)
```

Local PDF LLM Extractor is a cross-platform Python CLI that extracts information from PDF documents on your own machine.

## Why This Project

Many useful research questions are semantic rather than keyword-based. For example:

- What statistical tool does this research use?
- Does this paper rely on a natural experiment?
- What identification strategy does the author claim?

You can ask those questions directly to an AI model, but uploading an entire PDF into an agent context is expensive and token-intensive, especially for long papers and batch workflows.

This project exists to make that workflow practical: parse the PDF locally, reduce it into a structured text pipeline, and let a local LLM answer semantic questions without paying the repeated token cost of sending the raw document to a remote agent each time.

It combines three stages:

1. PDF parsing into Markdown or normalized plain text.
2. Chunking the extracted content into LLM-friendly segments.
3. Local LLM-based information extraction through Ollama.

The project is designed for users who want a local-first workflow for research papers, reports, and internal documents without sending content to a hosted API.

## What This Project Does

- Converts PDFs into Markdown or normalized text.
- Uses local Ollama models to answer structured extraction prompts.
- Supports both high-fidelity parsing and faster text-first parsing.
- Works on Windows and Linux, including WSL-style paths.
- Supports multi-file directory processing.
- Supports batched MinerU conversion to reduce repeated parser initialization overhead.
- Supports split-model inference, where one model handles chunk extraction and another handles final aggregation.

## Who This Is For

- Researchers extracting evidence or study design details from papers.
- Analysts reviewing reports and long-form PDFs locally.
- Developers who want a reproducible CLI pipeline built with `uv`.
- Teams that need a transparent local workflow instead of a cloud-only document pipeline.

## Core Features

- `mineru` engine for high-fidelity Markdown reconstruction with GPU acceleration when available.
- `fast` engine for direct PDF text extraction when a text layer exists.
- `fast-first` engine to try direct text extraction first and fall back automatically when the PDF has no usable text layer.
- `pymupdf` fallback engine for a lighter-weight Markdown path.
- Batch conversion mode for multi-file MinerU runs.
- Adaptive chunk sizing.
- Concurrent chunk extraction requests to Ollama.
- Two-stage extraction: chunk candidates first, final answer aggregation second.
- Detailed verbose timing output.

## Project Status

This repository packages the application code and dependency metadata only.

It does not vend third-party model weights, downloaded parser assets, Python virtual environments, or benchmark scratch outputs. Those assets are either generated locally or downloaded from upstream projects during installation and first use.

## Architecture Overview

The application has four main parts:

- `src/pdf_extractor/cli.py`: Typer-based CLI entry point and orchestration.
- `src/pdf_extractor/converter.py`: PDF parsing engines and batch conversion logic.
- `src/pdf_extractor/extractor.py`: Ollama client, chunk extraction, and final aggregation.
- `src/pdf_extractor/utils.py`: chunking, file helpers, normalization, and output helpers.

High-level flow:

```text
PDF(s)
  -> parse with fast / fast-first / mineru / pymupdf
  -> normalize or reconstruct Markdown
  -> split into chunks
  -> send chunk prompts to Ollama
  -> merge chunk answers into one final output
  -> write Markdown result files
```

## Dependencies and Credit

This project depends on upstream open-source software and should not be treated as a replacement for those projects.

Primary upstream dependencies:

- `MinerU` for high-fidelity PDF parsing and layout reconstruction.
- `PyMuPDF` and `pymupdf4llm` for direct text extraction and lightweight Markdown conversion.
- `Ollama` for local LLM serving.
- `PyTorch` and `torchvision` for GPU-enabled runtime support used by MinerU.
- `Typer` for the CLI.
- `httpx` for local Ollama HTTP communication.
- `rich` for terminal formatting and timing tables.

Credit belongs to the maintainers of those upstream projects for the core parsing, model-serving, and runtime capabilities this tool builds on top of.

## Requirements

Runtime requirements:

- Python 3.11 or newer.
- `uv` for environment and dependency management.
- A running Ollama instance, by default at `http://localhost:11434`.
- At least one installed Ollama generation model.

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

## Ollama Setup

Start Ollama locally and make sure the model you want to use has been pulled.

Example:

```bash
ollama serve
ollama pull qwen3.5:9b
ollama pull gemma3:4b
```

The default aggregation model in the CLI is `qwen3.5:9b`.

## Quick Start

### 1. Dry-run a single PDF

This converts the PDF to Markdown or text and writes the intermediate output without calling Ollama.

```bash
uv run pdf-extract --input path/to/file.pdf --dry-run
```

### 2. Extract information from a single PDF

```bash
uv run pdf-extract \
  --input path/to/file.pdf \
  --prompt "Summarize the key findings in English" \
  --model qwen3.5:9b
```

### 3. Process a folder of PDFs

```bash
uv run pdf-extract \
  --input path/to/folder \
  --prompt-file prompts/default.txt \
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
  --prompt-file prompts/default.txt \
  --output-dir output
```

Force batched MinerU conversion across multiple files:

```bash
uv run pdf-extract \
  --input fulltext \
  --engine mineru \
  --batch-convert \
  --prompt-file prompts/default.txt \
  --output-dir output
```

Disable batched conversion for comparison or debugging:

```bash
uv run pdf-extract \
  --input fulltext \
  --engine mineru \
  --no-batch-convert \
  --prompt-file prompts/default.txt \
  --output-dir output
```

### Model Selection

Use one model for both chunk extraction and final aggregation:

```bash
uv run pdf-extract \
  --input fulltext/testing.pdf \
  --prompt "Extract all findings" \
  --model qwen3.5:9b
```

Use a smaller chunk model and a stronger aggregation model:

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
  --ollama-url TEXT \
  --model TEXT \
  --chunk-model TEXT \
  --chunk-size INT \
  --parallelism INT \
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
- `--model`: final aggregation model.
- `--chunk-model`: optional faster model for chunk-level extraction.
- `--parallelism`: number of concurrent chunk requests sent to Ollama.
- `--verbose`: print startup, plan, and timing details.
- `--dry-run`: skip Ollama and only write converted text or Markdown.

## Engine Comparison

| Engine | What it does | Strengths | Tradeoffs | Recommended use |
| --- | --- | --- | --- | --- |
| `fast` | Reads the embedded PDF text layer directly | Fastest path for text-based PDFs | Fails on image-only PDFs and does not reconstruct layout | Use when you know the PDF already has a usable text layer |
| `fast-first` | Tries `fast`, then falls back automatically | Best convenience-to-speed balance | Fallback path is slower than direct extraction | Recommended default when document quality is unknown |
| `mineru` | Performs higher-fidelity PDF reconstruction | Best layout recovery, tables, formulas, and GPU acceleration | Heavier runtime and dependency footprint | Use when output fidelity matters more than raw speed |
| `pymupdf` | Uses a lighter Markdown conversion path | Simpler and lighter fallback | Lower fidelity on complex layouts | Use when MinerU is unavailable or intentionally avoided |

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
- final extracted answer

If `--include-chunk-details` is enabled, the output also appends chunk-level candidate answers.

## Performance Notes

- `fast` and `fast-first` are usually the fastest choices when the PDF contains a usable text layer.
- Once PDF parsing becomes fast enough, Ollama inference usually becomes the dominant cost.
- Split-model inference can reduce runtime significantly by using a small chunk model and a stronger final aggregation model.
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
3. `uv run pdf-extract --input path/to/file.pdf --dry-run` writes a conversion artifact without calling Ollama.
4. `uv run pdf-extract --input path/to/file.pdf --prompt "..."` calls Ollama and writes an extraction artifact.
5. `uv run pdf-extract --input path/to/folder --batch-convert --dry-run` processes multiple PDFs successfully.

## License and Upstream Notice

This repository contains the orchestration code for a local PDF extraction workflow.

This project is released under the MIT License. See the `LICENSE` file for the full text.

It depends on third-party open-source projects for PDF parsing, model runtime support, and local LLM serving. Please review and comply with the licenses and attribution requirements of those upstream dependencies when redistributing or deploying this project.

#!/usr/bin/env bash
set -uo pipefail

cd /mnt/c/wsl_shared/prj_pdf-local-extract
export PYTHONPATH=src
OLLAMA_URL=${OLLAMA_URL:-http://localhost:11434}

PROMPT_FILE=/tmp/shock_prompt.txt
cat >"$PROMPT_FILE" <<'EOF'
Identify the main exogenous shock or natural experiment used in this document, if there is one.

Requirements:
- Answer in no more than 120 words.
- Describe only the event itself: what happened, when and where it occurred, and why it is treated as plausibly exogenous.
- Do not describe the paper, research design, identification strategy, treatment or control groups, methods, data, sample period, results, mechanisms, moderators, or robustness checks.

If the document does not clearly contain the requested information, write exactly: No clear exogenous shock identified.
EOF

INPUT_DIR=/mnt/c/wsl_shared/prj_shock_crawler/fulltext
OUTPUT_DIR=/mnt/c/wsl_shared/prj_shock_crawler/test_output_all
mkdir -p "$OUTPUT_DIR"

count_total=$(find "$INPUT_DIR" -maxdepth 1 -type f -iname '*.pdf' | wc -l)
count_done=$(find "$OUTPUT_DIR" -maxdepth 1 -type f -iname '*.md' | wc -l)
echo "[info] total_pdfs=$count_total existing_outputs=$count_done ollama_url=$OLLAMA_URL"

find "$INPUT_DIR" -maxdepth 1 -type f -iname '*.pdf' -print0 |
while IFS= read -r -d '' pdf; do
  base="$(basename "$pdf" .pdf)"
  out="$OUTPUT_DIR/${base}.md"

  if [ -f "$out" ]; then
    echo "[skip] $(basename "$pdf")"
    continue
  fi

  echo "[run]  $(basename "$pdf")"
  ./.venv/bin/python -m pdf_extractor.cli \
    --input "$pdf" \
    --prompt-file "$PROMPT_FILE" \
    --ollama-url "$OLLAMA_URL" \
    --model qwen3.5:2b \
    --engine fast-first \
    --output-dir "$OUTPUT_DIR" \
    --parallelism 1 \
    --verbose || echo "[fail] $(basename "$pdf")"
done

echo "[done] batch loop finished"

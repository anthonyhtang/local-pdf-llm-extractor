# Semantic PDF Retriever 中文说明

English version: [README.md](README.md)

```text
 /\_/\\   Semantic PDF Retriever
( o.o )  解析 PDF，语义检索与抽取
 > ^ <   chunk, ask, merge
```

Semantic PDF Retriever 是一个跨平台的 Python 命令行工具，用来从 PDF 中抽取信息，并通过可配置的 lite model 进行语义问答与信息提取。

## 为什么会有这个项目

这个项目不是为了写“漂亮摘要”，而是为了解决大量 PDF 的语义检索与证据抽取问题。

核心目标是高召回筛查：根据用户给定的信息需求，快速定位相关文档与证据片段，并输出结构化结果，供后续分析使用。

现实约束很明确：你需要在大量长文档里找细粒度语义信息，但常见路径都存在明显短板。

为什么不把标准 RAG 作为主要决策层：

- RAG 在大规模文档检索上很有价值，但在细粒度语义任务（方法识别、因果主张、识别策略）上，检索精度通常还不够稳定。

为什么不直接把全量文档交给云端大模型：

- 成本会随着文档规模和重复查询快速上升。
- 在大规模筛查场景下，成本是乘法放大的：总开销大致随 PDF 数量 × 查询轮次 × 每轮平均 token 量增长，很快就会变得不可持续。
- 上下文窗口仍然难以承载大规模、多文档端到端筛查。

这个项目的做法：

- 用稳定解析 + lite model 抽取作为可控中间层。
- 优先保证语义筛查与证据抽取，而不是叙事摘要。
- 产出中间证据结果，后续再交给更强、更昂贵的模型做深度推理或写作。

输出意图：

- 文档级结果会刻意保持简洁、偏检索导向。
- 它是给下游大模型继续处理的筛查中间结果，不是最终面向读者的叙事摘要。

简而言之，模型层在这里负责“找证据”，不是“写终稿”。

## 问题场景

很多研究问题并不是简单的关键词搜索，而是语义层面的提问，例如：

- 在上百篇论文的目录里，哪些 PDF 使用了事件研究（event-study）规格？
- 在大规模报告集合里，哪些文档明确依赖自然实验？
- 在一轮批量筛查里，哪些文件明确描述了识别策略假设？

如果只是小规模、一次性的单文档检查，直接交给商用大模型通常也可行。

真正的瓶颈出现在“大量 PDF 的批量筛查任务”上：需要反复查询、反复装载上下文、跨文档筛查，成本会快速上升，工程上也很难扩展。

这个项目的目标是把流程工程化：先把 PDF 解析成结构化文本，再按稳定 chunk 方式送给可配置 lite model 做语义抽取，避免每次都把整篇原始文档塞进昂贵远程上下文。

整个流程大致分成三步：

1. 把 PDF 解析成 Markdown 或规范化文本。
2. 把文本切分成适合 LLM 处理的块。
3. 通过 lite model 完成 chunk 级抽取与证据合并（可选本地 provider 或 OpenRouter）。

这个项目适合做研究论文、报告、内部文档分析的人，尤其适合希望控制成本、减少 token 消耗、并保留可重复工作流的场景。

## 项目功能

- 支持将 PDF 转成 Markdown 或规范化纯文本。
- 支持通过 lite model 进行语义提问与信息抽取（本地 provider + OpenRouter 低成本模型）。
- 同时支持高保真解析路径和更快的文本优先解析路径。
- 支持 Windows、Linux，以及 WSL 风格路径。
- 支持目录批处理。
- 支持 MinerU 批量转换，减少重复初始化开销。
- 支持 split-model 推理，用于 chunk 级抽取与证据筛查。

## 核心特性

- `mineru` 引擎：更高保真的 Markdown 重建，在有 GPU 时可加速。
- `fast` 引擎：直接提取 PDF 内嵌文本层，速度最快。
- `fast-first` 引擎：优先尝试直接文本提取，失败后自动回退。
- `pymupdf` 引擎：更轻量的 Markdown 路径。
- 多文件批量转换。
- 自适应 chunk 大小。
- 并发发送 chunk 到所选模型 provider。
- 两阶段抽取：先抽 chunk 候选，再进行证据去重与合并。
- 详细 verbose 计时输出。

## 项目状态

这个仓库只包含应用代码和依赖元数据。

它不包含第三方模型权重、解析器下载的模型资产、本地虚拟环境、或者测试与 benchmark 过程中产生的大文件。这些内容应当由用户在本地安装或由上游项目按需下载。

## 架构概览

主要模块如下：

- `src/pdf_extractor/cli.py`：Typer 命令行入口与流程编排。
- `src/pdf_extractor/converter.py`：PDF 解析引擎与批量转换逻辑。
- `src/pdf_extractor/extractor.py`：provider 客户端、chunk 抽取与证据合并。
- `src/pdf_extractor/utils.py`：切块、文件工具、文本规范化与输出辅助函数。

高层流程：

```text
PDF
  -> 使用 fast / fast-first / mineru / pymupdf 解析
  -> 生成纯文本或 Markdown
  -> 切分为多个 chunk
  -> 将 chunk 发送给所选 lite model provider
  -> 合并为证据结果
  -> 写出 Markdown 文件
```

## 检索与 Consolidation 逻辑

检索与 consolidation 的规则刻意保持简单。

Chunk 级检索：

- 对每个 chunk 判断是否包含与用户问题相关的证据。
- 不相关的 chunk 直接丢弃。

文档级 consolidation：

- consolidation 是任务无关的，会跟随用户 query 的目标与格式。
- 对“是否存在”这类 query，输出 EXISTS 或 NOT EXISTS；只要有足够支持的命中即判定 EXISTS。
- 对非存在性 query，不会强行输出 EXISTS 标签，而是按用户要求的格式组织结果。
- 如果存在多个不同但都被支持的命中，会合并在同一结果里输出，而不是因为多目标而判定不明确。

输出意图：

- 只输出一个紧凑段落，便于下游处理。
- 保持简洁、检索导向。
- 这是给更强下游大模型使用的中间结果，不是最终叙事报告。

## Prompt 模板（核心可调点）

chunk 与 consolidation 的提示词已经放在文件中维护，不再硬编码在 Python 逻辑里：

- `prompts/chunk_prompt.txt`：控制 chunk 级检索行为。
- `prompts/consolidation_prompt.txt`：控制文档级 consolidation 行为。

这些模板是质量和风格调优的核心入口。你可以在不改应用代码的情况下，直接调节严格度、细节密度、输出格式约束和判定策略。

## 依赖与致谢

这个项目建立在多个开源项目之上，不应该被理解为对这些上游项目的替代。

主要依赖包括：

- `MinerU`：高保真 PDF 解析与版面重建。
- `PyMuPDF` 与 `pymupdf4llm`：直接文本提取与轻量 Markdown 转换。
- `Ollama`：本地大模型服务。
- `OpenRouter`：在线 low-cost/free lite models。
- `PyTorch` 与 `torchvision`：MinerU 所依赖的 GPU 运行时支持。
- `Typer`：命令行框架。
- `httpx`：模型 provider HTTP 通信。
- `rich`：终端格式化与计时表格。

这些能力的核心 credit 应归属于各上游项目的维护者，本项目主要提供的是本地 PDF 语义抽取工作流的编排与整合。

## 环境要求

- Python 3.11 或以上。
- `uv`，用于环境与依赖管理。
- 至少配置一个模型 provider：
  - 本地 provider（Ollama 兼容接口，默认 `http://localhost:11434`），或
  - OpenRouter API key（从环境变量读取）。

可选但推荐：

- NVIDIA GPU 与可用的 CUDA 驱动，以提升 MinerU 路径的性能。

仓库中同时提供：

- `pyproject.toml`：项目依赖的权威定义。
- `requirements.txt`：兼容部分需要 pip 风格依赖文件的工具链。

## 安装

### 推荐方式：uv

```bash
uv sync
```

查看 CLI 帮助：

```bash
uv run pdf-extract --help
```

### 兼容方式：pip

如果你需要传统的安装方式，也可以使用 `requirements.txt`，但项目主要还是以 `uv` 为主。

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Windows PowerShell 下常见激活方式：

```powershell
.venv\Scripts\Activate.ps1
```

## Lite Model Provider 设置

你可以二选一：`--provider local` 或 `--provider openrouter`。

### 本地 Provider（Ollama 兼容）

先在本地启动 Ollama，并确保拉取了要使用的模型。

例如：

```bash
ollama serve
ollama pull qwen3.5:2b
ollama pull qwen3.5:9b
ollama pull gemma3:4b
```

### OpenRouter Provider

把 key 放在环境变量中（默认变量名 `OPENROUTER_API_KEY_Test`）：

```powershell
$env:OPENROUTER_API_KEY_Test = "<your-key>"
```

Windows 持久化（用户级）环境变量：

```powershell
setx OPENROUTER_API_KEY_Test "<your-key>"
```

可用的 free model 预设：

- `minimax/minimax-m2.5:free`
- `openai/gpt-oss-120b:free`
- `google/gemini-2.5-flash-lite`
- `z-ai/glm-4.5-air:free`

local 模式下 CLI 默认抽取模型仍是 `qwen3.5:9b`。

推荐的本地模型组合：

- `qwen3.5:2b`：更保守、运行成本更低。适合你更在意少编造、哪怕会漏掉一部分边缘信息的场景。
- `gemma3:4b`：更激进，通常更容易给出候选答案。适合你更在意召回率，并愿意人工筛掉部分噪声的场景。

## 快速开始

### 1. 先做一次单文件 dry-run

这一步只做 PDF 转换，不调用任何模型 API。

```bash
uv run pdf-extract --input path/to/file.pdf --dry-run
```

### 2. 对单个 PDF 进行语义抽取

```bash
uv run pdf-extract \
  --input path/to/file.pdf \
  --prompt "提取与外生冲击相关的证据，包括时间、地点和受影响对象" \
  --model qwen3.5:9b
```

使用 OpenRouter free model：

```bash
uv run pdf-extract \
  --input path/to/file.pdf \
  --provider openrouter \
  --model minimax/minimax-m2.5:free \
  --prompt "提取与外生冲击相关的证据，包括时间、地点和受影响对象"
```

官方结构化 prompt 模板：

```text
Task: <你想从文档中抽取什么>

Requirements:
- <格式或长度要求>
- <需要包含什么>
- <需要排除什么>

If the document does not clearly contain the requested information, write exactly: <fallback text>
```

程序会把最后这一行识别为“整篇文档级别”的 fallback 规则。
在 chunk 阶段，如果局部证据不足，程序会内部使用 `NOT_RELEVANT`，而不会让单个 chunk 直接输出最终 fallback 文本，随后仅对相关 chunk 证据做去重合并。

例子：识别外生冲击

```text
Identify the main exogenous shock or natural experiment used in this document, if there is one.

Requirements:
- Answer in no more than 120 words.
- Describe only the event itself: what happened, when and where it occurred, and why it is treated as plausibly exogenous.
- Do not describe the paper, research design, identification strategy, treatment or control groups, methods, data, sample period, results, mechanisms, moderators, or robustness checks.

If the document does not clearly contain the requested information, write exactly: No clear exogenous shock identified.
```

### 3. 批量处理一个目录中的 PDF

```bash
uv run pdf-extract \
  --input path/to/folder \
  --prompt-file prompts/your_prompt.txt \
  --output-dir output
```

## 用法

### 基本帮助

```bash
uv run pdf-extract --help
```

### 单文件工作流

不调用 LLM，只生成中间 Markdown 或文本：

```bash
uv run pdf-extract --input fulltext/testing.pdf --dry-run
```

使用最快的文本层提取路径：

```bash
uv run pdf-extract --input fulltext/testing.pdf --engine fast --dry-run
```

使用推荐的自动文本优先模式：

```bash
uv run pdf-extract \
  --input fulltext/testing.pdf \
  --engine fast-first \
  --prompt "Extract all findings"
```

使用高保真的 MinerU 路径：

```bash
uv run pdf-extract \
  --input fulltext/testing.pdf \
  --engine mineru \
  --prompt "Extract all findings"
```

### 目录工作流

递归处理目录中的所有 PDF：

```bash
uv run pdf-extract \
  --input fulltext \
  --prompt-file prompts/your_prompt.txt \
  --output-dir output
```

强制启用 MinerU 批量转换：

```bash
uv run pdf-extract \
  --input fulltext \
  --engine mineru \
  --batch-convert \
  --prompt-file prompts/your_prompt.txt \
  --output-dir output
```

关闭批量转换以便比较或调试：

```bash
uv run pdf-extract \
  --input fulltext \
  --engine mineru \
  --no-batch-convert \
  --prompt-file prompts/your_prompt.txt \
  --output-dir output
```

### 模型选择

同一个模型用于 chunk 抽取：

```bash
uv run pdf-extract \
  --input fulltext/testing.pdf \
  --prompt "Extract all findings" \
  --model qwen3.5:9b
```

使用较小模型做 chunk 抽取以提升速度：

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

### 调试与计时

显示详细计时信息：

```bash
uv run pdf-extract \
  --input fulltext/testing.pdf \
  --engine fast-first \
  --verbose \
  --prompt "Extract all findings"
```

在输出文件中附带每个 chunk 的候选答案：

```bash
uv run pdf-extract \
  --input fulltext/testing.pdf \
  --engine fast \
  --include-chunk-details \
  --prompt "Extract all findings"
```

## CLI 参数参考

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

常用参数说明：

- `--input`：单个 PDF 或 PDF 目录。
- `--prompt`：直接在命令行中提供抽取指令。
- `--prompt-file`：从文件中读取抽取指令。
- `--output-dir`：输出到指定目录，而不是写回输入 PDF 所在目录。
- `--engine`：选择 PDF 解析策略。
- `--provider`：`local`（默认）或 `openrouter`。
- `--local-url`：本地 provider 地址（Ollama 兼容）。
- `--openrouter-api-key-env`：OpenRouter API key 的环境变量名（默认 `OPENROUTER_API_KEY_Test`）。
- `--model`：默认的 chunk 抽取模型。
- `--chunk-model`：可选的 chunk 抽取覆盖模型。
- `--parallelism`：并发发送的 chunk 数量，默认 `2`。
- `--min-request-interval`：请求之间最小间隔，OpenRouter 默认 `1.0s`。
- `--max-retries`：超时/429/5xx 重试次数。
- `--verbose`：打印启动、规划与计时细节。
- `--dry-run`：跳过模型调用，只写中间转换结果。

## 远程 API 限流默认策略

当使用 `--provider openrouter` 时，CLI 默认采用保守策略，降低封禁/限流风险：

- 并发上限自动限制为 `2`。
- 请求最小间隔默认 `1.0` 秒。
- 对 `429`、`408`、`5xx` 自动指数退避重试，并加随机抖动。
- 如果服务端返回 `Retry-After`，会优先按该等待时间重试。
- 如果 OpenRouter 的 `/models` 启动探测出现瞬时失败，CLI 会告警后继续执行运行期请求。

这些默认值是为了长时间批跑的稳定性。

## 引擎比较

| 引擎           | 作用                            | 优点                                 | 缺点                                 | 建议使用场景                    |
| -------------- | ------------------------------- | ------------------------------------ | ------------------------------------ | ------------------------------- |
| `fast`       | 直接读取 PDF 文本层             | 对于文本型 PDF 速度最快              | 无法处理纯图像 PDF，也不重建复杂版面 | 明确知道 PDF 有可用文本层时使用 |
| `fast-first` | 先尝试 `fast`，失败后自动回退 | 兼顾易用性与速度                     | 回退后速度会下降                     | 文档质量未知时的推荐默认选项    |
| `mineru`     | 更高保真的 PDF 重建             | 版面、表格、公式恢复更好，可利用 GPU | 运行更重，依赖也更复杂               | 输出质量优先时使用              |
| `pymupdf`    | 轻量 Markdown 转换路径          | 更简单、更轻量                       | 对复杂版面的恢复较弱                 | 无法使用 MinerU 或不想使用时    |

## 输出文件

默认情况下，工具会把 Markdown 输出写在输入文件旁边；如果指定了 `--output-dir`，则写入指定目录。

输出规则：

- 所有模式默认都写为 `{pdf_stem}.md`
- 如果对同一个 PDF 用不同模式重复运行，会覆盖同名 Markdown 文件，除非使用不同的 `--output-dir`
- 这样做是为了让默认输出更简单、稳定、适合批处理和后续工具接入

完整抽取输出通常包含：

- PDF 文件名
- 模型信息
- 引擎信息
- 提示词预览
- 日期
- 从相关 chunk 合并得到的证据

这个输出默认就是“紧凑的检索中间结果”，便于后续交给更强的下游模型继续处理，而不是直接当作最终报告。

如果开启 `--include-chunk-details`，输出还会追加每个 chunk 的候选答案。

## 性能说明

- 对于带有文本层的 PDF，`fast` 和 `fast-first` 通常是最快的。
- 当 PDF 解析足够快之后，主要瓶颈通常会转移到模型推理。
- chunk 模型选择会显著影响本地检索吞吐与召回质量。
- 批量转换在多个 PDF 使用 `mineru` 时更有价值，因为它可以摊薄初始化开销。

## Windows 与 Linux 路径支持

所有文件路径都使用 `pathlib.Path` 处理。

示例：

- Windows：`C:\Users\name\docs\paper.pdf`
- Linux：`/home/name/docs/paper.pdf`
- WSL 挂载 Windows 路径：`/mnt/c/Users/name/docs/paper.pdf`

## 限制

- 没有可用文本层的扫描版 PDF 可能需要走较重的 Markdown 路径，而且结果仍可能不完美。
- 复杂表格与版面恢复质量仍然依赖上游解析器。
- 超长文档如果原始结构很弱，chunk 边界仍可能不够理想。
- 本地 LLM 的最终质量很大程度上依赖模型本身与提示词设计。

## 仓库内容说明

本仓库用于保存源码与配置，不用于保存运行时生成的大文件。

公共仓库目标是保持轻量、可复现。依赖安装和上游模型资产下载应通过文档中说明的安装步骤完成，而不是直接从仓库分发。

版本控制中忽略的内容包括：

- 本地虚拟环境
- benchmark 日志
- 临时验证目录
- 生成的输出目录
- 本地样例 PDF 与其派生输出

## 开发说明

- 项目使用 `uv` 进行开发与依赖管理。
- `uv.lock` 已纳入版本控制，以确保可复现安装。
- `requirements.txt` 仅为兼容性提供，`pyproject.toml` 才是权威定义。

## 验证清单

1. `uv sync` 可以成功完成。
2. `uv run pdf-extract --help` 可以显示 CLI 帮助。
3. `uv run pdf-extract --input path/to/file.pdf --dry-run` 可以在不调用任何 provider 的情况下写出转换结果。
4. `uv run pdf-extract --input path/to/file.pdf --prompt "..."` 可以调用所选 provider 并写出抽取结果。
5. `uv run pdf-extract --input path/to/folder --batch-convert --dry-run` 可以成功处理多个 PDF。

## 许可证与上游说明

本仓库包含的是一个本地 PDF 语义抽取工作流的编排代码。

本项目采用 MIT License，完整文本见 `LICENSE` 文件。

本项目依赖多个第三方开源项目来完成 PDF 解析、模型运行时支持和本地 LLM 服务。若你要再分发或部署本项目，请同时遵守这些上游依赖各自的许可证与署名要求。

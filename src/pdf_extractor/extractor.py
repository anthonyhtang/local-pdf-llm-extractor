from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
from functools import lru_cache
from pathlib import Path
import random
import re
import threading
import time
from email.utils import parsedate_to_datetime
from typing import Literal

import httpx

NOT_RELEVANT_SENTINEL = "NOT_RELEVANT"
PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
CHUNK_PROMPT_TEMPLATE = PROMPTS_DIR / "chunk_prompt.txt"
CONSOLIDATION_PROMPT_TEMPLATE = PROMPTS_DIR / "consolidation_prompt.txt"


class ModelProviderError(RuntimeError):
    pass


@dataclass(slots=True)
class LiteModelClient:
    provider: Literal["local", "openrouter"]
    base_url: str
    model: str
    api_key: str | None = None
    timeout_seconds: float = 120.0
    min_request_interval_seconds: float = 0.0
    max_retries: int = 4
    backoff_base_seconds: float = 1.5
    _client: httpx.Client = field(init=False, repr=False)
    _sync_throttle_lock: threading.Lock = field(init=False, repr=False)
    _last_request_monotonic: float = field(init=False, default=0.0, repr=False)
    _async_throttle_lock: asyncio.Lock | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.provider = self.provider.lower().strip()  # type: ignore[assignment]
        if self.provider not in {"local", "openrouter"}:
            raise ModelProviderError(f"Unsupported model provider: {self.provider}")
        self.base_url = self.base_url.rstrip("/")
        self._sync_throttle_lock = threading.Lock()
        self._client = httpx.Client(base_url=self.base_url, headers=self._build_headers())

    def close(self) -> None:
        self._client.close()

    def _build_headers(self) -> dict[str, str]:
        if self.provider == "openrouter":
            if not self.api_key:
                raise ModelProviderError("OpenRouter API key is missing.")
            return {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/anthonyhtang/semantic-pdf-retriever",
                "X-Title": "Semantic PDF Retriever",
            }
        return {}

    def ensure_model_available(self, models: list[str] | None = None) -> list[str]:
        timeout_seconds = 15.0 if self.provider == "local" else 20.0
        available_models: list[str] = []

        for attempt in range(self.max_retries + 1):
            try:
                self._enforce_min_interval_sync()
                path = "/api/tags" if self.provider == "local" else "/models"
                response = self._client.get(path, timeout=timeout_seconds)
                if self._retryable_status(response.status_code) and attempt < self.max_retries:
                    retry_after = self._retry_after_delay_seconds(response)
                    time.sleep(retry_after if retry_after is not None else self._retry_delay_seconds(attempt))
                    continue
                response.raise_for_status()
                payload = response.json()
                if self.provider == "local":
                    available_models = [
                        item.get("name", "")
                        for item in payload.get("models", [])
                        if item.get("name")
                    ]
                else:
                    available_models = [
                        item.get("id", "")
                        for item in payload.get("data", [])
                        if item.get("id")
                    ]
                break
            except httpx.TimeoutException as exc:
                if attempt >= self.max_retries:
                    endpoint_name = "local provider" if self.provider == "local" else "OpenRouter"
                    raise ModelProviderError(
                        f"Unable to reach {endpoint_name} at {self.base_url}: {exc}"
                    ) from exc
                time.sleep(self._retry_delay_seconds(attempt))
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if self._retryable_status(status_code) and attempt < self.max_retries:
                    retry_after = self._retry_after_delay_seconds(exc.response)
                    time.sleep(retry_after if retry_after is not None else self._retry_delay_seconds(attempt))
                    continue
                endpoint_name = "local provider" if self.provider == "local" else "OpenRouter"
                detail = self._extract_error_detail(exc.response)
                detail_suffix = f" | detail: {detail}" if detail else ""
                raise ModelProviderError(
                    f"Unable to reach {endpoint_name} at {self.base_url}: {exc}{detail_suffix}"
                ) from exc
            except httpx.HTTPError as exc:
                if attempt >= self.max_retries:
                    endpoint_name = "local provider" if self.provider == "local" else "OpenRouter"
                    raise ModelProviderError(f"Unable to reach {endpoint_name} at {self.base_url}: {exc}") from exc
                time.sleep(self._retry_delay_seconds(attempt))

        requested_models = models or [self.model]
        missing_models = [model for model in requested_models if model not in available_models]
        if missing_models:
            raise ModelProviderError(
                "Requested model is not available. Missing: "
                + ", ".join(missing_models)
                + ". Installed models: "
                + ", ".join(available_models or ["<none>"])
            )
        return available_models

    def _build_payload(self, markdown: str, prompt: str, model: str | None = None) -> dict[str, object]:
        model_name = model or self.model
        combined_prompt = f"{prompt}\n\n---\n\n{markdown}"
        if self.provider == "local":
            return {
                "model": model_name,
                "prompt": combined_prompt,
                "stream": False,
            }
        return {
            "model": model_name,
            "messages": [{"role": "user", "content": combined_prompt}],
            "temperature": 0,
        }

    def _endpoint_path(self) -> str:
        return "/api/generate" if self.provider == "local" else "/chat/completions"

    def _extract_text_from_response(self, data: dict[str, object]) -> str:
        if self.provider == "local":
            result = data.get("response", "")
            if isinstance(result, str) and result.strip():
                return result.strip()
            raise ModelProviderError("Local provider returned an empty response.")

        error_block = data.get("error")
        if isinstance(error_block, dict):
            message = error_block.get("message")
            if isinstance(message, str) and message.strip():
                code = error_block.get("code")
                code_suffix = f" (code: {code})" if isinstance(code, (str, int)) else ""
                raise ModelProviderError(f"OpenRouter returned an error payload: {message.strip()}{code_suffix}")

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content", "")
                    if isinstance(content, str) and content.strip():
                        return content.strip()
                    if isinstance(content, list):
                        joined = "\n".join(
                            part.get("text", "")
                            for part in content
                            if isinstance(part, dict) and isinstance(part.get("text"), str)
                        ).strip()
                        if joined:
                            return joined

        # Fallback for response-style payloads returned by some routed providers.
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        output = data.get("output")
        if isinstance(output, list):
            collected: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    text = part.get("text")
                    if isinstance(text, str) and text.strip():
                        collected.append(text.strip())
            if collected:
                return "\n".join(collected)

        legacy_response = data.get("response")
        if isinstance(legacy_response, str) and legacy_response.strip():
            return legacy_response.strip()

        keys_preview = ", ".join(sorted(str(key) for key in data.keys())[:12])
        raise ModelProviderError(f"OpenRouter response does not contain usable text. Top-level keys: {keys_preview}")

    def _retryable_status(self, status_code: int) -> bool:
        return status_code in {408, 409, 425, 429, 500, 502, 503, 504}

    def _is_retryable_payload_error(self, exc: ModelProviderError) -> bool:
        message = str(exc).lower()
        return (
            self.provider == "openrouter"
            and (
                "provider returned error" in message
                or "overloaded" in message
                or "temporarily unavailable" in message
                or "timeout" in message
            )
        )

    def _extract_error_detail(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            return text[:300] if text else ""

        if isinstance(payload, dict):
            error_block = payload.get("error")
            if isinstance(error_block, dict):
                message = error_block.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        return ""

    def _retry_delay_seconds(self, attempt: int) -> float:
        base = self.backoff_base_seconds * (2 ** attempt)
        jitter = random.uniform(0.0, 0.25)
        return base + jitter

    def _retry_after_delay_seconds(self, response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After", "").strip()
        if not value:
            return None
        if value.isdigit():
            return max(0.0, float(value))
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, retry_at.timestamp() - time.time())

    def _enforce_min_interval_sync(self) -> None:
        if self.min_request_interval_seconds <= 0:
            return
        with self._sync_throttle_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_monotonic
            wait_seconds = self.min_request_interval_seconds - elapsed
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._last_request_monotonic = time.monotonic()

    async def _enforce_min_interval_async(self) -> None:
        if self.min_request_interval_seconds <= 0:
            return
        if self._async_throttle_lock is None:
            self._async_throttle_lock = asyncio.Lock()
        async with self._async_throttle_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_monotonic
            wait_seconds = self.min_request_interval_seconds - elapsed
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            self._last_request_monotonic = time.monotonic()

    def call_model(self, markdown: str, prompt: str, model: str | None = None) -> str:
        payload = self._build_payload(markdown, prompt, model=model)
        endpoint = self._endpoint_path()
        timeout_seconds = self.timeout_seconds

        for attempt in range(self.max_retries + 1):
            try:
                self._enforce_min_interval_sync()
                response = self._client.post(endpoint, json=payload, timeout=timeout_seconds)
                if self._retryable_status(response.status_code) and attempt < self.max_retries:
                    retry_after = self._retry_after_delay_seconds(response)
                    time.sleep(retry_after if retry_after is not None else self._retry_delay_seconds(attempt))
                    continue
                response.raise_for_status()
                data = response.json()
                try:
                    return self._extract_text_from_response(data)
                except ModelProviderError as payload_exc:
                    if self._is_retryable_payload_error(payload_exc) and attempt < self.max_retries:
                        time.sleep(self._retry_delay_seconds(attempt))
                        continue
                    raise
            except httpx.TimeoutException as exc:
                if attempt >= self.max_retries:
                    raise ModelProviderError(f"Request timed out after retries: {exc}") from exc
                time.sleep(self._retry_delay_seconds(attempt))
                timeout_seconds = min(timeout_seconds * 1.5, self.timeout_seconds * 3)
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if self._retryable_status(status_code) and attempt < self.max_retries:
                    retry_after = self._retry_after_delay_seconds(exc.response)
                    time.sleep(retry_after if retry_after is not None else self._retry_delay_seconds(attempt))
                    continue
                detail = self._extract_error_detail(exc.response)
                detail_suffix = f" | detail: {detail}" if detail else ""
                raise ModelProviderError(
                    f"Provider request failed with status {status_code}: {exc}{detail_suffix}"
                ) from exc
            except httpx.HTTPError as exc:
                if attempt >= self.max_retries:
                    raise ModelProviderError(f"Provider request failed: {exc}") from exc
                time.sleep(self._retry_delay_seconds(attempt))

        raise ModelProviderError("Provider request failed after retries.")

    def extract_from_chunk(self, content: str, prompt: str, model: str | None = None) -> str:
        chunk_prompt = _build_chunk_prompt(prompt)
        return self.call_model(content, chunk_prompt, model=model)

    def merge_chunk_evidence(self, chunk_results: list[str], prompt: str, model: str | None = None) -> str:
        document_fallback = _extract_document_fallback(prompt)
        normalized_fallback = _normalize_for_matching(document_fallback) if document_fallback else None
        relevant_results = [
            result.strip()
            for result in chunk_results
            if result.strip()
            and _normalize_for_matching(result) != _normalize_for_matching(NOT_RELEVANT_SENTINEL)
            and (normalized_fallback is None or _normalize_for_matching(result) != normalized_fallback)
        ]
        relevant_results = _deduplicate_candidates(relevant_results)

        if not relevant_results:
            if document_fallback:
                return document_fallback
            return "No relevant evidence found in the document."

        limited_results = relevant_results[:10]
        combined_candidates = "\n\n".join(
            f"Candidate {index}:\n{result}"
            for index, result in enumerate(limited_results, start=1)
        )

        consolidation_prompt = _build_consolidation_prompt(prompt, document_fallback)
        return self.call_model(combined_candidates, consolidation_prompt, model=model)

    def extract_chunks_parallel(
        self,
        chunks: list[str],
        prompt: str,
        parallelism: int,
        model: str | None = None,
    ) -> list[str]:
        if not chunks:
            return []
        if parallelism <= 1 or len(chunks) == 1:
            return [self.extract_from_chunk(chunk, prompt, model=model) for chunk in chunks]
        return asyncio.run(self._extract_chunks_parallel_async(chunks, prompt, parallelism, model))

    async def _extract_chunks_parallel_async(
        self,
        chunks: list[str],
        prompt: str,
        parallelism: int,
        model: str | None,
    ) -> list[str]:
        semaphore = asyncio.Semaphore(max(1, parallelism))
        timeout = httpx.Timeout(self.timeout_seconds)

        async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout, headers=self._build_headers()) as client:
            tasks = [
                self._extract_single_chunk_async(client, semaphore, chunk, prompt, model)
                for chunk in chunks
            ]
            return list(await asyncio.gather(*tasks))

    async def _extract_single_chunk_async(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        chunk: str,
        prompt: str,
        model: str | None,
    ) -> str:
        chunk_prompt = _build_chunk_prompt(prompt)
        payload = self._build_payload(chunk, chunk_prompt, model=model)

        async with semaphore:
            return await self._post_generate_async(client, payload)

    async def _post_generate_async(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, object],
    ) -> str:
        endpoint = self._endpoint_path()
        timeout_seconds = self.timeout_seconds

        for attempt in range(self.max_retries + 1):
            try:
                await self._enforce_min_interval_async()
                response = await client.post(endpoint, json=payload, timeout=timeout_seconds)
                if self._retryable_status(response.status_code) and attempt < self.max_retries:
                    retry_after = self._retry_after_delay_seconds(response)
                    await asyncio.sleep(retry_after if retry_after is not None else self._retry_delay_seconds(attempt))
                    continue
                response.raise_for_status()
                data = response.json()
                try:
                    return self._extract_text_from_response(data)
                except ModelProviderError as payload_exc:
                    if self._is_retryable_payload_error(payload_exc) and attempt < self.max_retries:
                        await asyncio.sleep(self._retry_delay_seconds(attempt))
                        continue
                    raise
            except httpx.TimeoutException as exc:
                if attempt >= self.max_retries:
                    raise ModelProviderError(f"Request timed out after retries: {exc}") from exc
                await asyncio.sleep(self._retry_delay_seconds(attempt))
                timeout_seconds = min(timeout_seconds * 1.5, self.timeout_seconds * 3)
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if self._retryable_status(status_code) and attempt < self.max_retries:
                    retry_after = self._retry_after_delay_seconds(exc.response)
                    await asyncio.sleep(retry_after if retry_after is not None else self._retry_delay_seconds(attempt))
                    continue
                detail = self._extract_error_detail(exc.response)
                detail_suffix = f" | detail: {detail}" if detail else ""
                raise ModelProviderError(
                    f"Provider request failed with status {status_code}: {exc}{detail_suffix}"
                ) from exc
            except httpx.HTTPError as exc:
                if attempt >= self.max_retries:
                    raise ModelProviderError(f"Provider request failed: {exc}") from exc
                await asyncio.sleep(self._retry_delay_seconds(attempt))

        raise ModelProviderError("Provider request failed after retries.")


# Backward compatibility for existing imports.
OllamaError = ModelProviderError
OllamaClient = LiteModelClient


def _deduplicate_candidates(chunk_results: list[str]) -> list[str]:
    deduplicated: list[str] = []
    seen: set[str] = set()

    for result in chunk_results:
        normalized = " ".join(result.lower().split())
        if normalized in seen:
            continue
        seen.add(normalized)
        deduplicated.append(result)

    return deduplicated


def _build_chunk_prompt(prompt: str) -> str:
    document_fallback = _extract_document_fallback(prompt)
    fallback_rules = ""
    if document_fallback:
        fallback_rules = "\n".join(
            [
                f"Never reply with the whole-document fallback string at chunk level: {document_fallback}",
                f"If the chunk lacks enough evidence, reply exactly {NOT_RELEVANT_SENTINEL} instead.",
            ]
        )

    template = _load_prompt_template(CHUNK_PROMPT_TEMPLATE)
    return template.format(
        not_relevant_sentinel=NOT_RELEVANT_SENTINEL,
        document_fallback_rules=fallback_rules,
        user_instruction=prompt,
    ).strip()


def _build_consolidation_prompt(prompt: str, document_fallback: str | None) -> str:
    fallback_rule = ""
    if document_fallback:
        fallback_rule = f"If the document does not clearly support an answer, reply exactly: {document_fallback}"

    template = _load_prompt_template(CONSOLIDATION_PROMPT_TEMPLATE)
    return template.format(
        document_fallback_rule=fallback_rule,
        user_instruction=prompt,
    ).strip()


@lru_cache(maxsize=8)
def _load_prompt_template(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ModelProviderError(f"Unable to read prompt template file: {path} ({exc})") from exc
    if not content:
        raise ModelProviderError(f"Prompt template file is empty: {path}")
    return content


def _extract_document_fallback(prompt: str) -> str | None:
    for line in prompt.splitlines():
        match = re.search(r"(?:write|return)\s+exactly:\s*(.+)$", line.strip(), flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip()
        if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {'"', "'", '`'}:
            candidate = candidate[1:-1].strip()
        if candidate:
            return candidate
    return None


def _normalize_for_matching(text: str) -> str:
    return " ".join(text.strip().lower().split())

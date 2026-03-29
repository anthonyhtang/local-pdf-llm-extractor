from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
import re

import httpx

NOT_RELEVANT_SENTINEL = "NOT_RELEVANT"


class OllamaError(RuntimeError):
    pass


@dataclass(slots=True)
class OllamaClient:
    base_url: str
    model: str
    timeout_seconds: float = 120.0
    _client: httpx.Client = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url)

    def close(self) -> None:
        self._client.close()

    def ensure_model_available(self, models: list[str] | None = None) -> list[str]:
        try:
            response = self._client.get("/api/tags", timeout=15.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(f"Unable to reach Ollama at {self.base_url}: {exc}") from exc

        payload = response.json()
        available_models = [item.get("name", "") for item in payload.get("models", []) if item.get("name")]
        requested_models = models or [self.model]
        missing_models = [model for model in requested_models if model not in available_models]
        if missing_models:
            raise OllamaError(
                "Requested model is not available. Missing: "
                + ", ".join(missing_models)
                + ". Installed models: "
                + ", ".join(available_models or ["<none>"])
            )
        return available_models

    def call_ollama(self, markdown: str, prompt: str, model: str | None = None) -> str:
        payload = {
            "model": model or self.model,
            "prompt": f"{prompt}\n\n---\n\n{markdown}",
            "stream": False,
        }

        try:
            return self._post_generate(payload, self.timeout_seconds)
        except httpx.TimeoutException:
            return self._post_generate(payload, self.timeout_seconds * 2)

    def _post_generate(self, payload: dict[str, object], timeout_seconds: float) -> str:
        try:
            response = self._client.post("/api/generate", json=payload, timeout=timeout_seconds)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc

        data = response.json()
        result = data.get("response", "")
        if not isinstance(result, str) or not result.strip():
            raise OllamaError("Ollama returned an empty response.")
        return result.strip()

    def extract_from_chunk(self, content: str, prompt: str, model: str | None = None) -> str:
        chunk_prompt = _build_chunk_prompt(prompt)
        return self.call_ollama(content, chunk_prompt, model=model)

    def merge_chunk_evidence(self, chunk_results: list[str], prompt: str) -> str:
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
        lines = ["## Retrieved Evidence"]
        for index, result in enumerate(relevant_results, start=1):
            lines.append(f"\n### Evidence {index}\n{result}")
        return "\n".join(lines).strip()

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

        async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
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
        payload = {
            "model": model or self.model,
            "prompt": f"{chunk_prompt}\n\n---\n\n{chunk}",
            "stream": False,
        }

        async with semaphore:
            try:
                return await self._post_generate_async(client, payload, self.timeout_seconds)
            except httpx.TimeoutException:
                return await self._post_generate_async(client, payload, self.timeout_seconds * 2)

    async def _post_generate_async(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> str:
        try:
            response = await client.post("/api/generate", json=payload, timeout=timeout_seconds)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc

        data = response.json()
        result = data.get("response", "")
        if not isinstance(result, str) or not result.strip():
            raise OllamaError("Ollama returned an empty response.")
        return result.strip()


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
    instructions = [
        "You are reviewing one chunk from a larger document.",
        "Answer only with information supported by this chunk.",
        f"If the chunk does not contain material relevant to the user instruction, reply exactly {NOT_RELEVANT_SENTINEL}.",
        "Otherwise return only evidence grounded in this chunk.",
        "Prefer a short bullet list with direct facts, entities, dates, and numbers from the chunk.",
        "Do not summarize the whole document.",
        "This is a chunk-level task, not a whole-document task.",
        "Do not repeat the user instruction. Do not add caveats unless the chunk itself requires them.",
    ]
    if document_fallback:
        instructions.append(f"Never reply with the whole-document fallback string at chunk level: {document_fallback}")
        instructions.append(f"If the chunk lacks enough evidence, reply exactly {NOT_RELEVANT_SENTINEL} instead.")
    instructions.extend(["", "User instruction:", prompt])
    return "\n".join(instructions)


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

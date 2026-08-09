import hashlib
import math
import re
from dataclasses import asdict, dataclass
from typing import Any

from app.config import Settings
from app.models import WikiChunk, WikiDocument, new_id
from app.security.tenant import tenant_filter

VECTOR_SIZE = 256
TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_.:/-]+|[\u4e00-\u9fff]")


@dataclass(slots=True)
class MemoryHit:
    document_id: str
    title: str
    heading: str | None
    excerpt: str
    score: float
    version: int

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


class WikiMemory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def reindex(self, document: WikiDocument) -> None:
        chunks = _split_markdown(document.content, self.settings.rag_chunk_chars)
        await WikiChunk.filter(document_id=document.id).delete()
        for ordinal, (heading, content) in enumerate(chunks):
            tokens = _tokens(f"{document.title} {heading or ''} {content}")
            await WikiChunk.create(
                id=new_id("wch"),
                tenant_id=document.tenant_id,
                document_id=document.id,
                ordinal=ordinal,
                heading=heading,
                content=content,
                token_count=max(1, len(content.encode("utf-8")) // 3),
                embedding=_embedding(tokens),
                keywords=_keywords(tokens),
            )
        document.chunk_count = len(chunks)
        await document.save(update_fields=["chunk_count", "updated_at"])

    async def retrieve(self, query: str, *, limit: int | None = None) -> list[MemoryHit]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        query_embedding = _embedding(query_tokens)
        query_terms = set(query_tokens)
        chunks = (
            await WikiChunk.filter(
                document__status="published",
                **tenant_filter(),
            )
            .select_related("document")
            .limit(2000)
        )
        ranked: list[tuple[float, WikiChunk]] = []
        for chunk in chunks:
            semantic = _dot(query_embedding, _float_vector(chunk.embedding))
            keyword_terms = set(str(value) for value in chunk.keywords)
            lexical = len(query_terms & keyword_terms) / max(1, len(query_terms))
            score = semantic * 0.7 + lexical * 0.3
            if score > 0.04:
                ranked.append((score, chunk))
        ranked.sort(key=lambda item: item[0], reverse=True)
        selected = ranked[: (limit or self.settings.rag_max_chunks)]
        return [
            MemoryHit(
                document_id=chunk.document_id,
                title=chunk.document.title,
                heading=chunk.heading,
                excerpt=chunk.content[:1800],
                score=round(score, 4),
                version=chunk.document.version,
            )
            for score, chunk in selected
        ]


def _split_markdown(content: str, target_chars: int) -> list[tuple[str | None, str]]:
    blocks = re.split(r"\n\s*\n", content.strip())
    chunks: list[tuple[str | None, str]] = []
    current: list[str] = []
    current_heading: str | None = None
    current_size = 0
    for raw in blocks:
        block = raw.strip()
        if not block:
            continue
        heading_match = re.match(r"^#{1,6}\s+(.+)$", block.splitlines()[0])
        if heading_match:
            if current:
                chunks.append((current_heading, "\n\n".join(current)))
                current = []
                current_size = 0
            current_heading = heading_match.group(1).strip()[:500]
        if current and current_size + len(block) > target_chars:
            chunks.append((current_heading, "\n\n".join(current)))
            overlap = current[-1][-200:] if current else ""
            current = [overlap] if overlap else []
            current_size = len(overlap)
        if len(block) > target_chars:
            for start in range(0, len(block), target_chars - 200):
                part = block[start : start + target_chars]
                if part:
                    chunks.append((current_heading, part))
            current = []
            current_size = 0
            continue
        current.append(block)
        current_size += len(block)
    if current:
        chunks.append((current_heading, "\n\n".join(current)))
    return chunks or [(None, content[:target_chars])]


def _tokens(text: str) -> list[str]:
    raw = [value.lower() for value in TOKEN_PATTERN.findall(text)]
    chinese = [value for value in raw if "\u4e00" <= value <= "\u9fff"]
    bigrams = [f"{left}{right}" for left, right in zip(chinese, chinese[1:], strict=False)]
    return raw + bigrams


def _embedding(tokens: list[str]) -> list[float]:
    vector = [0.0] * VECTOR_SIZE
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        index = value % VECTOR_SIZE
        vector[index] += -1.0 if value & 1 else 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / norm, 6) for value in vector]


def _keywords(tokens: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    for token in tokens:
        if len(token) > 1:
            counts[token] = counts.get(token, 0) + 1
    return [key for key, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:80]]


def _float_vector(value: object) -> list[float]:
    if not isinstance(value, list):
        return []
    return [float(item) for item in value[:VECTOR_SIZE] if isinstance(item, (int, float))]


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))

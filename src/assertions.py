"""Canary helpers. (Named assertions.py because `assert` is a reserved word in Python.)"""

from __future__ import annotations

import uuid

from .adapter import SearchHit


def canary(category: str) -> str:
    """Unique per test per run so runs never contaminate each other. Format: ZQ-<CATEGORY>-<12 hex>."""
    return f"ZQ-{category.upper()}-{uuid.uuid4().hex[:12]}"


def scope_id(prefix: str) -> str:
    """Namespace-safe unique scope name (letters, digits, underscore, hyphen, colon only)."""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def contains_canary(hits: list[SearchHit], c: str) -> bool:
    return any(c in h.text for h in hits)


def not_contains_canary(hits: list[SearchHit], c: str) -> bool:
    return not contains_canary(hits, c)


def hits_with_canary(hits: list[SearchHit], c: str) -> list[SearchHit]:
    return [h for h in hits if c in h.text]

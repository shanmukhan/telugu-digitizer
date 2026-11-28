"""Process-local monotonic cache invalidation epochs for read-mostly NLP models."""

from __future__ import annotations

import threading

_LOCK = threading.Lock()
_SENTENCE_CONTEXT_EPOCH = 0


def current_sentence_context_epoch() -> int:
    with _LOCK:
        return _SENTENCE_CONTEXT_EPOCH


def bump_sentence_context_epoch() -> int:
    global _SENTENCE_CONTEXT_EPOCH
    with _LOCK:
        _SENTENCE_CONTEXT_EPOCH += 1
        return _SENTENCE_CONTEXT_EPOCH

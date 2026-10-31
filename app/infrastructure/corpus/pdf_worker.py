"""
PDF text extraction in a child process — ``readers._pdf_text`` runs this file as a script.

A 30 KB PDF can hold a flate stream that inflates to megabytes of drawing operators, and every
page may point at the same stream, so parsing an untrusted PDF inside the server could take
minutes and gigabytes while holding the GIL. Here it runs in a separate process that the parent
kills after a timeout. The child imports only the standard library and ``pypdf`` (the parent
starts it with ``python -I``, so not even the repository is on its path), limits its own address
space where the OS enforces that (Linux), and reads at most ``max_pages`` pages and
``max_chars`` characters.

Usage: ``python -I pdf_worker.py MAX_PAGES MAX_CHARS MEMORY_BYTES < file.pdf``. The answer is
one JSON object on stdout, ``{"text": str, "warnings": [str]}`` or ``{"error": str}``.
"""

from __future__ import annotations

import io
import json
import logging
import sys
from typing import Any, Dict, List


def _limit_memory(limit_bytes: int) -> None:
    """Cap the address space (RLIMIT_AS) on Linux; macOS does not enforce it, Windows lacks it."""
    if not sys.platform.startswith("linux"):
        return
    import resource

    try:
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
    except (ValueError, OSError):
        pass  # a lower hard limit is already in place


def extract(data: bytes, max_pages: int, max_chars: int) -> Dict[str, Any]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    warnings: List[str] = []
    n_pages = len(reader.pages)
    if n_pages > max_pages:
        warnings.append(f"PDF has {n_pages:,} pages — only the first {max_pages:,} were read")
    parts: List[str] = []
    length = 0
    for index in range(min(n_pages, max_pages)):
        parts.append(reader.pages[index].extract_text() or "")
        length += len(parts[-1]) + 1
        if length > max_chars:
            warnings.append(f"PDF text cut at {max_chars:,} characters")
            break
    return {"text": "\n".join(parts)[:max_chars], "warnings": warnings}


def main() -> None:
    max_pages, max_chars, memory_bytes = (int(arg) for arg in sys.argv[1:4])
    _limit_memory(memory_bytes)
    logging.disable(logging.CRITICAL)  # pypdf logs every oddity of a malformed file
    try:
        result = extract(sys.stdin.buffer.read(), max_pages, max_chars)
    except Exception as exc:  # anything pypdf raises on a hostile file, MemoryError included
        result = {"error": (str(exc) or type(exc).__name__)[:200]}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()

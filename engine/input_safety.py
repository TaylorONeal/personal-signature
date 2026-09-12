"""Bound export input without executing it or exposing record contents in errors."""
import json
import os
from pathlib import Path
import stat

MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024


def read_text(path, encoding="utf-8", errors="strict"):
    """Whole-document parsers have a hard limit, including if a file grows mid-read."""
    with open(path, "rb") as stream:
        data = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("Export document exceeds 64 MiB; split it into smaller valid files")
    return data.decode(encoding, errors)


def json_document(path):
    try:
        return json.loads(read_text(path, encoding="utf-8-sig"))
    except RecursionError:
        raise ValueError("Export JSON nesting is too deep") from None


def text_lines(path):
    """Bound individual UTF-8 lines while allowing large streamed CSV/JSONL exports."""
    with open(path, "rb") as stream:
        first = True
        while True:
            data = stream.readline(MAX_LINE_BYTES + 1)
            if not data:
                return
            if len(data) > MAX_LINE_BYTES:
                raise ValueError("Export line exceeds 1 MiB")
            yield data.decode("utf-8-sig" if first else "utf-8")
            first = False


def inspect_input(path, max_bytes=1024 * 1024 * 1024, max_files=10000):
    """Reject special files, symlinks, and excessive input trees.

    Run before ingest. Local concurrent edits remain outside the trust boundary.
    """
    path = Path(path)
    total = count = 0
    pending = [path]
    while pending:
        current = pending.pop()
        mode = current.lstat().st_mode
        if stat.S_ISDIR(mode):
            with os.scandir(current) as entries:
                for entry in entries:
                    count += 1
                    if count > max_files:
                        raise ValueError("Export tree exceeds 10000 entries; select a smaller source directory")
                    pending.append(Path(entry.path))
        elif stat.S_ISREG(mode):
            total += current.stat().st_size
            if total > max_bytes:
                raise ValueError("Export input exceeds byte budget; select a smaller source or increase --max-input-mb")
        else:
            raise ValueError("Export inputs must contain only regular files and directories, not symlinks or devices")
    return total

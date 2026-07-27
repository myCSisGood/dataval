"""Validation provenance helpers.

The report and promotion flow use the same canonical manifest so a compliant
report cannot be reused after any governed input or validator implementation
changes.
"""
from __future__ import annotations

import hashlib
import os
from typing import Iterable

from .precheck import locate_pieces


def sha256_file(path: str, *, length: int | None = None) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    return value[:length] if length else value


def sha256_paths(paths: Iterable[str], root: str) -> dict[str, str]:
    """Hash existing files with stable, POSIX-style labels."""
    out: dict[str, str] = {}
    for path in sorted(set(os.path.abspath(p) for p in paths)):
        if not os.path.isfile(path):
            continue
        label = os.path.relpath(path, root).replace(os.sep, "/")
        out[label] = sha256_file(path)
    return out


def input_hashes(ddl_path: str) -> dict[str, str]:
    """Return hashes for the four-piece subject input using logical names."""
    pieces = locate_pieces(ddl_path)
    hashes: dict[str, str] = {}
    if os.path.isfile(ddl_path):
        hashes["ddl"] = sha256_file(ddl_path)
    for key in ("relations", "context"):
        path = pieces[key]
        if os.path.isfile(path):
            hashes[key] = sha256_file(path)
    samples = pieces["samples"]
    if os.path.isdir(samples):
        for filename in sorted(os.listdir(samples)):
            if filename.lower().endswith(".csv"):
                hashes[f"samples/{filename}"] = sha256_file(
                    os.path.join(samples, filename))
    return hashes


def validation_manifest(ddl_path: str, compiled_path: str) -> dict:
    """Build the canonical provenance record embedded in every report."""
    return {
        "format": "dataval.validation_manifest.v1",
        "validation_bundle_code": sha256_file(compiled_path, length=16),
        "input_hashes": input_hashes(ddl_path),
    }


def manifest_mismatches(expected: dict, actual: dict) -> list[str]:
    """Return human-readable differences between two validation manifests."""
    problems: list[str] = []
    if not isinstance(expected, dict):
        return ["報告缺 validation_manifest"]
    if expected.get("format") != actual.get("format"):
        problems.append(
            f"manifest 格式不同：報告 {expected.get('format')}／目前 {actual.get('format')}")
    if expected.get("validation_bundle_code") != actual.get("validation_bundle_code"):
        problems.append(
            "驗證 bundle 已變更：報告 "
            f"{expected.get('validation_bundle_code')}／目前 "
            f"{actual.get('validation_bundle_code')}")
    before = expected.get("input_hashes") or {}
    after = actual.get("input_hashes") or {}
    for name in sorted(set(before) | set(after)):
        if before.get(name) != after.get(name):
            problems.append(
                f"輸入 {name} 已變更：報告 {before.get(name, '（無）')}／"
                f"目前 {after.get(name, '（無）')}")
    return problems

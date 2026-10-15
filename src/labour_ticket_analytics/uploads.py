"""Importing a workbook chosen in the browser (ticket #41).

The upload is streamed into `uploads/` in the local data directory under its
content's SHA-256, never beside the source code, and refused beyond
MAX_UPLOAD_BYTES or when it is not an .xlsx package. It is then imported
exactly as a launch import is (`workbook.import_workbook`: read-only, formulas
kept as text, external links not loaded, macros never run) and previewed
before anything changes: the sheet, row and field counts, the column mapping
and the import issues. Only activating it adds the Snapshot and makes it
active; a workbook that would be refused at launch is refused here with the
same message, and its file is removed.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, AsyncIterator
from urllib.parse import unquote

from labour_ticket_analytics.schema import (
    OPTIONAL_COLUMNS, REQUIRED_COLUMNS, missing_optional_columns, missing_required_columns,
)
from labour_ticket_analytics.workbook import Snapshot

UPLOAD_DIR_NAME = "uploads"
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_NAME = 200
# Every .xlsx file is a zip package, which starts with a local file header.
ZIP_MAGIC = b"PK\x03\x04"
# Issues listed in the preview; the counts by kind cover them all.
PREVIEW_ISSUES = 50

REFUSED_NEXT_STEP = (
    "Nothing was imported and the active Snapshot is unchanged. Correct the workbook, or export it again from the "
    "company system, then choose it again."
)


class UploadError(Exception):
    def __init__(self, code: str, field_name: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.field = field_name
        self.status = status

    def payload(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "message": str(self), "next_step": REFUSED_NEXT_STEP}


def upload_dir(data_dir: Path) -> Path:
    return data_dir / UPLOAD_DIR_NAME


def clean_name(value: str | None) -> str:
    """The workbook's file name as chosen (percent-encoded, as a header must be ASCII), without any folder; it must
    end in .xlsx."""
    if not value or not value.strip():
        raise UploadError("missing_name", "name", "say the workbook's file name")
    name = PureWindowsPath(PurePosixPath(unquote(value.strip())).name).name
    if len(name) > MAX_NAME:
        raise UploadError("too_long", "name", f"the file name is longer than {MAX_NAME} characters")
    if not name.lower().endswith(".xlsx"):
        raise UploadError(
            "not_xlsx", "name",
            f"{name} is not an .xlsx workbook; save the export as an Excel workbook (.xlsx) and choose it again",
        )
    return name


async def receive(chunks: AsyncIterator[bytes], data_dir: Path, declared_length: str | None) -> tuple[Path, str, int]:
    """Stream the body into the data directory; returns the stored path, its SHA-256 and its size in bytes."""
    if declared_length is not None and declared_length.isdigit() and int(declared_length) > MAX_UPLOAD_BYTES:
        raise _too_large()
    folder = upload_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    handle, temporary = tempfile.mkstemp(dir=folder, prefix="receiving-", suffix=".part")
    try:
        with os.fdopen(handle, "wb") as out:
            async for chunk in chunks:
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise _too_large()
                digest.update(chunk)
                out.write(chunk)
        with open(temporary, "rb") as written:
            if written.read(len(ZIP_MAGIC)) != ZIP_MAGIC:
                raise UploadError(
                    "not_xlsx", "file",
                    "the file is not an .xlsx workbook (it is not an Excel package); save the export as an Excel "
                    "workbook (.xlsx) and choose it again",
                )
        fingerprint = digest.hexdigest()
        stored = folder / f"{fingerprint}.xlsx"
        os.replace(temporary, stored)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return stored, fingerprint, size


def _too_large() -> UploadError:
    return UploadError(
        "too_large", "file", f"the workbook is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB, the upload limit",
        status=413,
    )


def preview(snapshot: Snapshot, size: int, same_as: str | None, stored: Path) -> dict[str, Any]:
    """What activating the workbook would add: its sheet, counts, column mapping and import issues."""
    fields = snapshot.fields
    known = set(REQUIRED_COLUMNS) | set(OPTIONAL_COLUMNS)
    issues = list(snapshot.import_issues)
    return {
        "id": snapshot.fingerprint,
        "workbook_name": snapshot.workbook_name,
        "size_bytes": size,
        # Where the file is kept; launching with this path starts from the same Snapshot.
        "stored_as": str(stored.resolve()),
        "fingerprint": snapshot.fingerprint,
        "fingerprint_algorithm": snapshot.fingerprint_algorithm,
        "sheet": snapshot.sheet,
        "row_count": snapshot.row_count,
        "field_count": snapshot.field_count,
        "mapping": [
            {
                "column": column,
                "kind": "required" if column in REQUIRED_COLUMNS else "optional",
                "position": fields.index(column) + 1 if column in fields else None,
                "present": column in fields,
            }
            for column in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS)
        ],
        "missing_required_columns": missing_required_columns(fields),
        "missing_optional_columns": missing_optional_columns(fields),
        "other_columns": [column for column in fields if column not in known],
        "disabled_features": snapshot.disabled_features,
        "import_issue_count": len(issues),
        "import_issue_counts": [{"code": code, "count": count} for code, count in sorted(Counter(i["code"] for i in issues).items())],
        "import_issues": issues[:PREVIEW_ISSUES],
        # "active" or "loaded" when this content is already a Snapshot: activating it then adds nothing.
        "same_as": same_as,
    }

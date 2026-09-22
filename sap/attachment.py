"""
DICON "Files" attachment access (Phase 3).

Clicking the DICON hotspot cell in the AP Open Item grid opens a
"[T-DMS] Document Management System" popup (screen include with program
SAPLZ_TS_DMS_COMMON, screen 2160) scoped to that item's B/L reference
(confirmed live 2026-09-15: the popup shows Document type / Reference no
fields matching the row's BL_Number). It contains an inner ALV grid
(GuiShell/GridView) listing attached files with technical columns
DAPPL / DKTXT / FILEP / DTTRG / CNAM / CDAT / CTME.

READ-ONLY. The popup's "Document Attach" (F8) and "Document Delete" (F9)
toolbar buttons are NEVER pressed - only "Document Display" (F2) / a
double-click on a file row, which asks SAP to render the document
locally (a display action, not a write action).

Confirmed live 2026-09-15 against real attachments across 8 files / 5
vendors:
  - SAP saves EVERY opened attachment to C:\\temp\\_<seq>.xls first
    (observed _<user-id>01.xls, _<user-id>02.xls, _<user-id>03.xls, ...
    where <user-id> is the logged-in SAP user's numeric ID),
    regardless of its real type or original filename, and regardless of
    whether anything then successfully displays it. Polling that folder
    for a newly-created file is far more reliable than trying to detect
    whatever app SAP shells out to afterward (browsers in particular
    often reuse an existing process instead of spawning a new PID, which
    made process-based detection silently fail for some files).
  - IMPORTANT: the saved file's extension does not reliably reflect its
    real format - an .xlsx sample was saved locally as ".xls" (content
    sniffed via signature 'PK\\x03\\x04'). Never trust the extension.
  - A single attachment can bundle several document types as separate
    sheets (e.g. one workbook containing "INVOICE", "SHIPPING PACKING
    LIST", "PACKING LIST", "BL" sheets together) - classification must
    inspect sheet/page content, not assume one file equals one document
    type.
  - CRITICAL SAFETY FINDING: opening a PDF-type attachment (DAPPL="PDF")
    - via double-click OR the "Document Display" (F2) button - did not
    open any viewer and, when tried via the toolbar button, reset the
    ENTIRE SAP session back to the SAP Easy Access screen (losing
    the AP Open Item transaction and any in-progress work). This looks like a missing/
    misconfigured ArchiveLink viewer setup for this document type on
    this SAP system (not something scripting can fix), so this module
    refuses to open anything except confirmed-safe types (XLS/XLSX) and
    raises UnsupportedAttachmentType instead - never attempts the
    double-click for other types.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Optional

from .ap_open_item import TCODE

GRID_ID = "wnd[0]/usr/shell"
POPUP_TITLE_SUBSTR = "Document Management System"
INNER_GRID_ID = "wnd[1]/usr/cntlSCR2160_CONTAINER/shellcont/shell"
CLOSE_BUTTON_ID = "wnd[1]/tbar[0]/btn[12]"  # "Close   (F12)" - safe, always OK to press

# NEVER press these on the DMS popup - they are write actions:
#   wnd[1]/tbar[0]/btn[8]  "Document Attach...   (F8)"
#   wnd[1]/tbar[0]/btn[9]  "Document Delete...   (F9)"

ATTACHMENT_COLUMNS = ["DAPPL", "DKTXT", "FILEP", "DTTRG", "CNAM", "CDAT", "CTME"]

# Attachment types (DAPPL) confirmed safe to open via double-click.
# PDF is confirmed UNSAFE (resets the whole SAP session - see module
# docstring); other types (e.g. "LIM"/image) are simply unconfirmed, so
# they are excluded too until specifically validated live.
SUPPORTED_ATTACHMENT_TYPES = {"XLS", "XLSX"}

# SAP consistently spools every opened attachment here first, regardless
# of what (if anything) then displays it - confirmed live 2026-09-15.
SAP_DOWNLOAD_TEMP_DIR = Path(r"C:\temp")


class AttachmentError(RuntimeError):
    pass


class UnsupportedAttachmentType(AttachmentError):
    """Raised instead of ever attempting to open a file type that hasn't
    been confirmed safe (see SUPPORTED_ATTACHMENT_TYPES)."""


def open_attachment_list(session, row_index: int) -> None:
    """Open the DMS attachment popup for an AP Open Item grid row (0-based)."""
    try:
        grid = session.findById(GRID_ID)
        grid.SetCurrentCell(row_index, "DICON")
        time.sleep(0.05)
        grid.ClickCurrentCell()
    except Exception as exc:  # noqa: BLE001
        raise AttachmentError(f"Failed to open attachment list for row {row_index}: {exc}") from exc

    if session.Children.Count < 2:
        raise AttachmentError(f"Expected a DMS popup to open for row {row_index}, but no popup appeared.")

    title = session.findById("wnd[1]").Text
    if POPUP_TITLE_SUBSTR not in title:
        raise AttachmentError(f"Expected a DMS popup for row {row_index}, got window titled: '{title}'")


def read_attachment_list(session) -> list[dict[str, Any]]:
    """Read attachment metadata rows (filename, type, creator, date) from
    the currently open DMS popup. Read-only - GetCellValue only."""
    try:
        grid = session.findById(INNER_GRID_ID)
        row_count = grid.RowCount
    except Exception as exc:  # noqa: BLE001
        raise AttachmentError(f"Could not read attachment list grid: {exc}") from exc

    rows: list[dict[str, Any]] = []
    for r in range(row_count):
        row: dict[str, Any] = {}
        for col in ATTACHMENT_COLUMNS:
            try:
                row[col] = grid.GetCellValue(r, col)
            except Exception as exc:  # noqa: BLE001
                row[col] = None
                row[f"{col}_error"] = str(exc)
        rows.append(row)
    return rows


def close_attachment_list(session) -> None:
    """Close the DMS popup via the safe Close (F12) button."""
    try:
        session.findById(CLOSE_BUTTON_ID).press()
    except Exception as exc:  # noqa: BLE001
        raise AttachmentError(f"Failed to close attachment popup: {exc}") from exc


def _wait_for_new_temp_file(before_files: set[str], timeout: float = 15.0) -> Optional[Path]:
    """Poll SAP_DOWNLOAD_TEMP_DIR for a file that wasn't in `before_files`.

    Confirmed live 2026-09-15: SAP always writes the opened attachment
    here first, whether or not anything ends up successfully displaying
    it, and whether that display app spawns a new process (Excel did) or
    reuses/streams elsewhere (some setups don't spawn a detectable new
    PID at all) - so watching the folder is more reliable than watching
    processes.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if SAP_DOWNLOAD_TEMP_DIR.is_dir():
            current = {f.name for f in SAP_DOWNLOAD_TEMP_DIR.iterdir() if f.is_file()}
            new_names = current - before_files
            if new_names:
                newest = max(
                    (SAP_DOWNLOAD_TEMP_DIR / n for n in new_names),
                    key=lambda p: p.stat().st_mtime,
                )
                return newest
        time.sleep(0.2)
    return None


def open_and_copy_attachment_file(
    session,
    file_row_index: int,
    dest_dir: str | Path,
    dest_filename: Optional[str] = None,
    timeout: float = 15.0,
) -> Path:
    """Double-click a file row in the currently open DMS popup, wait for
    SAP to spool it to its local temp folder, and COPY it into dest_dir.

    Refuses to open anything whose DAPPL type isn't in
    SUPPORTED_ATTACHMENT_TYPES (raises UnsupportedAttachmentType without
    touching the row at all) - confirmed live that opening a PDF-type
    attachment can reset the entire SAP session, so unconfirmed types are
    never attempted.

    Does not close whatever viewer app SAP may shell out to afterward -
    the user's Excel instance may be hosting other work, so we never
    force-close or kill processes here. The copy lets Phase 4 read the
    file content directly without touching any live viewer.

    Raises AttachmentError if no new file appears in the temp folder
    within `timeout` seconds (never silently returns an empty/wrong result).
    """
    grid = session.findById(INNER_GRID_ID)
    try:
        dappl = (grid.GetCellValue(file_row_index, "DAPPL") or "").strip().upper()
        original_name = grid.GetCellValue(file_row_index, "FILEP")
    except Exception as exc:  # noqa: BLE001
        raise AttachmentError(f"Failed to read attachment row {file_row_index} metadata: {exc}") from exc

    if dappl not in SUPPORTED_ATTACHMENT_TYPES:
        raise UnsupportedAttachmentType(
            f"Attachment row {file_row_index} ({original_name!r}) has type '{dappl}', which is not "
            f"in the confirmed-safe list {sorted(SUPPORTED_ATTACHMENT_TYPES)}. Refusing to open it "
            f"(a PDF-type attachment was confirmed live to reset the whole SAP session)."
        )

    before_files: set[str] = set()
    if SAP_DOWNLOAD_TEMP_DIR.is_dir():
        before_files = {f.name for f in SAP_DOWNLOAD_TEMP_DIR.iterdir() if f.is_file()}

    try:
        grid.SelectedRows = str(file_row_index)
        grid.SetCurrentCell(file_row_index, "FILEP")
        time.sleep(0.1)
        grid.DoubleClickCurrentCell()
    except Exception as exc:  # noqa: BLE001
        raise AttachmentError(f"Failed to trigger open on attachment row {file_row_index}: {exc}") from exc

    src_path = _wait_for_new_temp_file(before_files, timeout=timeout)
    if src_path is None:
        raise AttachmentError(
            f"No new file appeared in {SAP_DOWNLOAD_TEMP_DIR} within {timeout}s after opening "
            f"attachment row {file_row_index} ({original_name!r})."
        )

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_name = dest_filename or original_name or src_path.name
    dest_path = dest_dir / dest_name
    shutil.copy2(src_path, dest_path)
    return dest_path


def process_attachments(
    session,
    rows: list[dict[str, Any]],
    dest_root: str | Path,
    logger=None,
    download_files: bool = True,
    recover_fn=None,
) -> list[dict[str, Any]]:
    """For each ITEM row, check the DICON "Files" indicator. If blank, skip
    without opening anything (fast - matches project rule: only inspect
    what's actually there). If non-blank, open the attachment list, read
    metadata for every file, and (if download_files) copy each file into
    dest_root/Source_Row_<n>/ for Phase 4 parsing.

    IMPORTANT (confirmed live 2026-09-15): if a file fails to actually
    download (observed with a Korean-filename .xls - repeatedly timed
    out with no crash while the popup stayed open), pressing the DMS
    popup's "Close" button afterward does not return to the AP
    Open Item list - it resets the WHOLE session back to the SAP Easy Access
    screen (this looks like the transaction's own error-recovery
    fallback, not a scripting crash - F3/Escape are disabled on that
    popup, Close is the only way out). Without recovery, every
    subsequent row would then fail with a cryptic "control not found"
    error since we're no longer even in the AP Open Item transaction.

    `recover_fn`, if given, is called with no arguments to re-navigate
    back into the AP Open Item transaction and re-run the search (e.g.
    `lambda: (open_transaction(session, TCODE), open_and_search(session, criteria, sap_date_format))`)
    whenever this function notices we've fallen out of the transaction. Without
    it, this function still detects the situation and stops early rather
    than silently failing every remaining row.

    Preserves Source_Row. Continues past per-row failures (logs + moves on).
    """
    results: list[dict[str, Any]] = []
    item_rows = [r for r in rows if r.get("Row_Type") == "ITEM"]
    total = len(item_rows)

    for idx, row in enumerate(item_rows, start=1):
        source_row = row["Source_Row"]
        row_index = source_row - 1
        has_indicator = bool((row.get("Files") or "").strip())

        result: dict[str, Any] = {"Source_Row": source_row, "Has_Files_Indicator": has_indicator}

        if not has_indicator:
            result["Attachment_Status"] = "NONE"
            result["Attachment_Count"] = 0
            results.append(result)
            continue

        if logger:
            logger.info("Row %d/%d (Source_Row=%s): Files indicator present, opening...", idx, total, source_row)

        try:
            open_attachment_list(session, row_index)
            files = read_attachment_list(session)
            result["Attachment_Count"] = len(files)
            result["Files"] = files

            if download_files and files:
                dest_dir = Path(dest_root) / f"Source_Row_{source_row}"
                copied_paths = []
                for file_idx in range(len(files)):
                    try:
                        dest = open_and_copy_attachment_file(session, file_idx, dest_dir)
                        copied_paths.append(str(dest))
                    except AttachmentError as exc:
                        if logger:
                            logger.error("Row %s file %d: download failed: %s", source_row, file_idx, exc)
                result["Downloaded_Paths"] = copied_paths

            close_attachment_list(session)
            result["Attachment_Status"] = "OK"

        except Exception as exc:  # noqa: BLE001
            result["Attachment_Status"] = "ERROR"
            result["Attachment_Error"] = str(exc)
            if logger:
                logger.error("Row %s: attachment processing failed: %s", source_row, exc)
            try:
                if session.Children.Count > 1:
                    close_attachment_list(session)
            except Exception:  # noqa: BLE001
                pass

        results.append(result)

        # Confirmed real failure mode: closing the popup after a failed
        # download can silently drop us out of the AP Open Item transaction entirely. Check
        # after every item (not just on error - the crash showed up here,
        # not at the exception site) and self-heal if a recovery function
        # was provided.
        try:
            current_transaction = session.Info.Transaction
        except Exception:  # noqa: BLE001
            current_transaction = None

        if current_transaction != TCODE:
            if logger:
                logger.error(
                    "Row %s: session fell out of %s (now on %s) after attachment handling.",
                    source_row, TCODE, current_transaction,
                )
            if recover_fn is not None:
                try:
                    recover_fn()
                    if logger:
                        logger.info("Recovered: re-navigated back into %s and re-ran the search.", TCODE)
                except Exception as recovery_exc:  # noqa: BLE001
                    if logger:
                        logger.error("Recovery failed (%s) - stopping attachment processing early.", recovery_exc)
                    break
            else:
                if logger:
                    logger.error("No recover_fn provided - stopping attachment processing early.")
                break

    return results

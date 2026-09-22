"""
Standard SAP GOS (Generic Object Services) attachment access via FB03.

CONFIRMED LIVE 2026-09-15 (from the user's own screen recording of how
they actually check attachments): the REAL attachment mechanism this
business uses is NOT the AP Open Item transaction's own "Files" (DICON) popup - that
mechanism (see sap/attachment.py) is scoped to a B/L reference, rarely
populated, and confirmed to crash the whole session on PDF attachments.
The mechanism actually used is the standard SAP GOS "Attachment list" on
the FI accounting document, opened via FB03. This is far more reliable:
PDF, JPEG, a mislabeled-extension XLSX, and a genuinely legacy OLE .xls
were ALL confirmed to open correctly here.

Path: AP Open Item grid row -> Accounting_Doc (BELNR_I) + Posting_Date (for
fiscal year) + Company Code -> FB03 -> GOS attachment list -> Display ->
file lands in the user's local SAP GUI frontend download folder
(~/Documents/SAP/SAP GUI/ by default - NOT C:\\temp, which is specific to
the other, custom DMS mechanism in sap/attachment.py).

Mechanics discovered live (none guessed):
  - The GOS toolbar is a control most scripts never look at:
    wnd[0]/titl/shellcont/shell (GuiShell, SubType "Toolbar") - part of
    the window TITLE bar, not the usual tbar[0]/tbar[1]/usr areas.
  - Its button has NO static tooltip/children via the normal GuiMenu
    tree; the real submenu only appears via PressContextButton
    ('%GOS_TOOLBOX') - NOT PressButton - after which
    GetMenuItemIdFromPosition(i) enumerates real function codes:
    %GOS_PCATTA_CREA / %GOS_NOTE_CREA / %GOS_URL_CREA (Create ... - WRITE,
    never select), %GOS_VIEW_ATTA (View Attachment List - what we use),
    %GOS_SO_SENDOBJ / %GOS_SRELATIONS / %GOS_WF_* (unrelated).
  - SelectMenuItem('%GOS_VIEW_ATTA') opens the "Service: Attachment list"
    popup (wnd[1]). Its grid
    (wnd[1]/usr/cntlCONTAINER_0100/shellcont/shell) has columns
    BITM_ICON / BITM_DESCR / CREATOR / CREADATE. BITM_ICON reliably
    reports the REAL file type (e.g. "@J0\\QJPEG Image@",
    "@J2\\QMS Excel Worksheet@") - trust this over the filename/extension.
  - That grid has its OWN embedded toolbar (GetToolbarButtonId):
    %ATTA_CREATE / %ATTA_EDIT / %ATTA_DELETE (WRITE - never press),
    %ATTA_DISPLAY (opens the selected attachment - confirmed working),
    %ATTA_EXPORT (untested - might save without opening a viewer, worth
    trying in a future session), %ATTA_REFRESH.
  - Neither double-clicking a row nor the popup's own "Continue" (Enter)
    button actually opened anything in testing - only
    SelectedRows + PressToolbarButton('%ATTA_DISPLAY') reliably worked.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Optional

import win32com.client

from .navigation import check_not_write_screen, open_transaction

# Apps SAP shells out to when displaying a downloaded attachment.
# EXCEL/WINWORD/PHOTOS were confirmed to spawn a brand-new process per
# file (safe to close individually right after we've copied the file).
# ACROBAT/ACRORD32 were confirmed to REUSE one existing process across
# many PDFs opened over a run (closing it mid-batch could drop a tab a
# later item still needs) - those are only closed once, at the very end
# of process_gos_attachments, and only if they weren't already running
# before this batch started.
PER_FILE_CLOSE_PROCESS_NAMES = {"EXCEL.EXE", "WINWORD.EXE", "PHOTOS.EXE", "PHOTOSAPP.EXE"}
BATCH_END_CLOSE_PROCESS_NAMES = {"ACRORD32.EXE", "ACROBAT.EXE"}
ALL_VIEWER_PROCESS_NAMES = PER_FILE_CLOSE_PROCESS_NAMES | BATCH_END_CLOSE_PROCESS_NAMES


def _snapshot_pids(process_names: set[str]) -> dict[int, str]:
    """Read-only WMI snapshot of {pid: name} for the given process names."""
    wmi = win32com.client.GetObject("winmgmts:")
    pids: dict[int, str] = {}
    for proc in wmi.ExecQuery("SELECT ProcessId, Name FROM Win32_Process"):
        name = (proc.Name or "").upper()
        if name in process_names:
            pids[proc.ProcessId] = name
    return pids


def _close_pids(pids: set[int], logger=None) -> None:
    """Force-close specific processes by PID via taskkill. Only ever
    called on PIDs we positively identified as spawned by our own
    automation to display a disposable copy of a downloaded attachment -
    never the user's own documents (see PER_FILE_CLOSE_PROCESS_NAMES /
    BATCH_END_CLOSE_PROCESS_NAMES docstring above for the safety
    reasoning)."""
    import subprocess

    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, timeout=10, check=False,
            )
            if logger:
                logger.info("Closed leftover viewer process (PID %s).", pid)
        except Exception as exc:  # noqa: BLE001
            if logger:
                logger.warning("Could not close viewer process PID %s: %s", pid, exc)

def _close_download_dir_documents(logger=None) -> int:
    """Close only the Excel workbooks / Word documents that live in SAP
    GUI's download folder, inside an Excel/Word that is ALREADY running.

    _close_pids() can only kill a viewer PROCESS that is new since before
    the file was opened. If the user already has Excel (or Word) running,
    SAP opens each attachment as another window inside that existing
    process - no new PID appears, so nothing was closed and the windows
    piled up (confirmed live 2026-09-21). Closing by file location is
    safe: it touches ONLY files under DEFAULT_SAP_GUI_DOWNLOAD_DIR (our
    own disposable downloaded copies), never the user's other workbooks,
    and never quits the application itself. Saving is always declined."""
    download_dir = str(DEFAULT_SAP_GUI_DOWNLOAD_DIR).lower().rstrip("\\/") + "\\"
    closed = 0
    for prog_id, collection in (("Excel.Application", "Workbooks"), ("Word.Application", "Documents")):
        try:
            app = win32com.client.GetActiveObject(prog_id)
        except Exception:  # noqa: BLE001 - not running: nothing to close
            continue
        try:
            items = list(getattr(app, collection))
        except Exception:  # noqa: BLE001
            continue
        for item in items:
            try:
                if str(item.FullName).lower().startswith(download_dir):
                    item.Close(False)
                    closed += 1
            except Exception as exc:  # noqa: BLE001
                if logger:
                    logger.warning("Could not close %s document: %s", prog_id, exc)
        if prog_id == "Excel.Application":
            try:
                for pvw in list(app.ProtectedViewWindows):
                    try:
                        if str(pvw.SourcePath).lower().rstrip("\\/") + "\\" == download_dir:
                            pvw.Close()
                            closed += 1
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass
    if closed and logger:
        logger.info("Closed %d downloaded document(s) inside an already-running Excel/Word.", closed)
    return closed


GOS_TOOLBAR_ID = "wnd[0]/titl/shellcont/shell"
GOS_BUTTON_ID = "%GOS_TOOLBOX"
GOS_MENU_VIEW_ATTACHMENTS = "%GOS_VIEW_ATTA"

ATTACHMENT_LIST_TITLE_SUBSTR = "attachment list"
ATTACHMENT_GRID_ID = "wnd[1]/usr/cntlCONTAINER_0100/shellcont/shell"
ATTACHMENT_LIST_COLUMNS = ["BITM_ICON", "BITM_DESCR", "CREATOR", "CREADATE"]

ATTA_DISPLAY_BUTTON = "%ATTA_DISPLAY"
# NEVER press/select these - they are write actions:
#   grid toolbar: %ATTA_CREATE, %ATTA_EDIT, %ATTA_DELETE
#   GOS menu: %GOS_PCATTA_CREA, %GOS_NOTE_CREA, %GOS_URL_CREA

DEFAULT_SAP_GUI_DOWNLOAD_DIR = Path.home() / "Documents" / "SAP" / "SAP GUI"


class GosAttachmentError(RuntimeError):
    pass


def open_fb03(session, doc_number: str, company_code: str, fiscal_year: str) -> None:
    """Navigate to FB03 and display a document (read-only)."""
    open_transaction(session, "FB03")
    try:
        session.findById("wnd[0]/usr/txtRF05L-BELNR").text = doc_number
        session.findById("wnd[0]/usr/ctxtRF05L-BUKRS").text = company_code
        session.findById("wnd[0]/usr/txtRF05L-GJAHR").text = fiscal_year
    except Exception as exc:  # noqa: BLE001
        raise GosAttachmentError(f"Failed to fill FB03 selection screen: {exc}") from exc

    check_not_write_screen(session)
    session.findById("wnd[0]").sendVKey(0)
    check_not_write_screen(session)

    sbar = session.findById("wnd[0]/sbar")
    if sbar.MessageType == "E":
        raise GosAttachmentError(f"FB03 could not display document {doc_number}: {sbar.Text}")


def open_attachment_list(session) -> None:
    """Open the GOS 'Attachment list' popup for the currently displayed FB03 document."""
    try:
        toolbar = session.findById(GOS_TOOLBAR_ID)
        toolbar.PressContextButton(GOS_BUTTON_ID)
        time.sleep(0.2)
        toolbar.SelectMenuItem(GOS_MENU_VIEW_ATTACHMENTS)
    except Exception as exc:  # noqa: BLE001
        raise GosAttachmentError(f"Failed to open GOS attachment list: {exc}") from exc

    time.sleep(0.5)
    if session.Children.Count < 2:
        raise GosAttachmentError("Expected the GOS attachment list popup to open, but no popup appeared.")

    title = session.findById("wnd[1]").Text
    if ATTACHMENT_LIST_TITLE_SUBSTR not in title.lower():
        raise GosAttachmentError(f"Expected the GOS attachment list popup, got window titled: '{title}'")


def read_attachment_list(session) -> list[dict[str, Any]]:
    """Read attachment metadata (title, real file type via icon, creator, date).
    Read-only - GetCellValue only."""
    try:
        grid = session.findById(ATTACHMENT_GRID_ID)
        row_count = grid.RowCount
    except Exception as exc:  # noqa: BLE001
        raise GosAttachmentError(f"Could not read GOS attachment list grid: {exc}") from exc

    rows: list[dict[str, Any]] = []
    for r in range(row_count):
        row: dict[str, Any] = {}
        for col in ATTACHMENT_LIST_COLUMNS:
            try:
                row[col] = grid.GetCellValue(r, col)
            except Exception as exc:  # noqa: BLE001
                row[col] = None
                row[f"{col}_error"] = str(exc)
        rows.append(row)
    return rows


def close_attachment_list(session) -> None:
    """Close the GOS attachment list popup via Cancel (F12) - safe, read-only."""
    try:
        session.findById("wnd[1]/tbar[0]/btn[12]").press()
    except Exception as exc:  # noqa: BLE001
        raise GosAttachmentError(f"Failed to close GOS attachment list: {exc}") from exc


def _wait_for_new_download(before_files: set[str], download_dir: Path, timeout: float = 15.0) -> Optional[Path]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if download_dir.is_dir():
            current = {f.name for f in download_dir.iterdir() if f.is_file()}
            new_names = current - before_files
            if new_names:
                newest = max((download_dir / n for n in new_names), key=lambda p: p.stat().st_mtime)
                return newest
        time.sleep(0.2)
    return None


def open_and_copy_attachment(
    session,
    row_index: int,
    dest_dir: str | Path,
    dest_filename: Optional[str] = None,
    download_dir: Path = DEFAULT_SAP_GUI_DOWNLOAD_DIR,
    timeout: float = 15.0,
    close_viewer: bool = True,
    logger=None,
) -> Path:
    """Select a row in the currently open GOS attachment list and press
    Display (%ATTA_DISPLAY) - the only trigger confirmed to actually open
    the file. Waits for it to appear in the user's SAP GUI download
    folder and copies it into dest_dir.

    If `close_viewer` is True (default), immediately closes whatever
    per-file viewer app (Excel/Word/Photos - confirmed to spawn a fresh
    process per file) opened as a result, once the file is safely copied.
    Acrobat/Reader is excluded here (it reuses one shared process across
    many PDFs in a run - see BATCH_END_CLOSE_PROCESS_NAMES) and is instead
    cleaned up once at the end of process_gos_attachments.
    """
    grid = session.findById(ATTACHMENT_GRID_ID)
    try:
        original_name = grid.GetCellValue(row_index, "BITM_DESCR")
        icon = grid.GetCellValue(row_index, "BITM_ICON")
    except Exception as exc:  # noqa: BLE001
        raise GosAttachmentError(f"Failed to read attachment row {row_index}: {exc}") from exc

    before_files: set[str] = set()
    if download_dir.is_dir():
        before_files = {f.name for f in download_dir.iterdir() if f.is_file()}

    before_pids = _snapshot_pids(PER_FILE_CLOSE_PROCESS_NAMES) if close_viewer else {}

    try:
        grid.SetCurrentCell(row_index, "BITM_DESCR")
        grid.SelectedRows = str(row_index)
        time.sleep(0.1)
        grid.PressToolbarButton(ATTA_DISPLAY_BUTTON)
    except Exception as exc:  # noqa: BLE001
        raise GosAttachmentError(f"Failed to trigger Display on attachment row {row_index}: {exc}") from exc

    src_path = _wait_for_new_download(before_files, download_dir, timeout=timeout)
    if src_path is None:
        raise GosAttachmentError(
            f"No new file appeared in {download_dir} within {timeout}s after displaying "
            f"attachment row {row_index} ({original_name!r}, icon={icon!r})."
        )

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_name = dest_filename or src_path.name
    dest_path = dest_dir / dest_name
    shutil.copy2(src_path, dest_path)

    if close_viewer:
        after_pids = _snapshot_pids(PER_FILE_CLOSE_PROCESS_NAMES)
        new_pids = set(after_pids) - set(before_pids)
        if new_pids:
            _close_pids(new_pids, logger=logger)
        _close_download_dir_documents(logger=logger)

    return dest_path


def process_gos_attachments(
    session,
    rows: list[dict[str, Any]],
    dest_root: str | Path,
    company_code: str,
    logger=None,
    download_files: bool = True,
    close_shared_viewer_every: int = 5,
) -> list[dict[str, Any]]:
    """For each ITEM row, use its Accounting_Doc (from the AP Open Item grid)
    to open FB03 and check the standard GOS attachment list. Preserves
    Source_Row. Continues past per-row failures (logs + moves on),
    self-healing back onto the AP Open Item result screen is the caller's
    responsibility only if this function is interleaved with further
    AP Open Item grid reads (it always leaves the session on FB03/Easy
    Access, never touches that transaction itself).
    """
    results: list[dict[str, Any]] = []
    item_rows = [r for r in rows if r.get("Row_Type") == "ITEM"]
    total = len(item_rows)

    # Acrobat/Reader reuses one shared process across many PDFs opened
    # during a run (confirmed live) rather than one-per-file, so it can't
    # be closed after every single item the way Excel/Photos are. Instead
    # it's swept every `close_shared_viewer_every` items (default 5, per
    # user request 2026-09-15 - a full-batch-only sweep let one instance
    # grow to ~2GB RAM over 127 items and bogged down the machine) - each
    # sweep only closes instance(s) that weren't already running at the
    # start of that window, so a pre-existing session of the user's own
    # (open before this function was ever called) is never touched.
    pre_existing_acrobat_pids = set(_snapshot_pids(BATCH_END_CLOSE_PROCESS_NAMES)) if download_files else set()

    def _sweep_shared_viewers():
        nonlocal pre_existing_acrobat_pids
        current = set(_snapshot_pids(BATCH_END_CLOSE_PROCESS_NAMES))
        new_pids = current - pre_existing_acrobat_pids
        if new_pids:
            if logger:
                logger.info("Closing %d Acrobat/Reader instance(s) opened so far.", len(new_pids))
            _close_pids(new_pids, logger=logger)
        # Whatever remains (pre-existing, or a close that failed) becomes
        # the new baseline so we never repeatedly retry a stuck PID or
        # touch something we've already decided to leave alone.
        pre_existing_acrobat_pids = set(_snapshot_pids(BATCH_END_CLOSE_PROCESS_NAMES))
        _close_download_dir_documents(logger=logger)

    for idx, row in enumerate(item_rows, start=1):
        source_row = row["Source_Row"]
        doc_number = (row.get("Accounting_Doc") or "").strip()
        result: dict[str, Any] = {"Source_Row": source_row}

        if not doc_number:
            result["Attachment_Status"] = "NO_ACCOUNTING_DOC"
            result["Attachment_Count"] = 0
            results.append(result)
            continue

        posting_date = (row.get("Posting_Date") or "").strip()
        fiscal_year = posting_date.split(".")[0] if posting_date else ""
        if not fiscal_year:
            result["Attachment_Status"] = "NO_FISCAL_YEAR"
            result["Attachment_Count"] = 0
            results.append(result)
            continue

        if logger:
            logger.info(
                "Row %d/%d (Source_Row=%s): checking GOS attachments for doc %s/%s/%s...",
                idx, total, source_row, doc_number, company_code, fiscal_year,
            )

        try:
            open_fb03(session, doc_number, company_code, fiscal_year)
            open_attachment_list(session)
            files = read_attachment_list(session)
            result["Attachment_Count"] = len(files)
            result["Files"] = files

            if download_files and files:
                dest_dir = Path(dest_root) / f"Source_Row_{source_row}"
                copied_paths = []
                for file_idx in range(len(files)):
                    try:
                        dest = open_and_copy_attachment(session, file_idx, dest_dir, logger=logger)
                        copied_paths.append(str(dest))
                    except GosAttachmentError as exc:
                        if logger:
                            logger.error("Row %s file %d: download failed: %s", source_row, file_idx, exc)
                result["Downloaded_Paths"] = copied_paths

            close_attachment_list(session)
            result["Attachment_Status"] = "OK"

        except Exception as exc:  # noqa: BLE001
            result["Attachment_Status"] = "ERROR"
            result["Attachment_Error"] = str(exc)
            if logger:
                logger.error("Row %s: GOS attachment processing failed: %s", source_row, exc)
            try:
                if session.Children.Count > 1:
                    close_attachment_list(session)
            except Exception:  # noqa: BLE001
                pass

        results.append(result)

        if download_files and close_shared_viewer_every > 0 and idx % close_shared_viewer_every == 0:
            _sweep_shared_viewers()

    if download_files:
        _sweep_shared_viewers()  # catch the remainder after the last full window

    return results

"""
SAP GUI navigation helpers.

Only performs navigation actions that are explicitly allowed by project
rules: entering a transaction code and executing display/search actions.
Never performs Save/Post/Change/Delete/Release/Payment actions.

Uses the standard SAP GUI Scripting toolbar element wnd[0]/tbar[0]/okcd,
which is a stable, framework-level element present on virtually every
SAP GUI screen (not a guessed, screen-specific ID).
"""
from __future__ import annotations

import time

WRITE_ACTION_KEYWORDS = (
    "save",
    "post",
    "delete",
    "release",
    "change",
    "modify",
    "payment",
    "execute payment",
    "저장",
    "변경",
    "삭제",
    "전기",
)


class SapNavigationError(RuntimeError):
    pass


class SapWriteScreenDetected(RuntimeError):
    """Raised when the automation lands on what looks like a change/write
    screen. The caller must stop interacting with that screen."""


def open_transaction(session, tcode: str, wait_seconds: float = 0.5) -> None:
    """Navigate to a transaction using the standard command field.

    This is a read-only navigation action (equivalent to a user typing a
    transaction code and pressing Enter). It does not submit any business
    data and does not save anything.
    """
    try:
        okcd = session.findById("wnd[0]/tbar[0]/okcd")
    except Exception as exc:  # noqa: BLE001
        raise SapNavigationError(f"Could not find the command field (okcd): {exc}") from exc

    okcd.text = f"/n{tcode}"
    try:
        session.findById("wnd[0]").sendVKey(0)  # Enter
    except Exception as exc:  # noqa: BLE001
        raise SapNavigationError(f"Failed to send Enter after entering transaction {tcode}: {exc}") from exc

    time.sleep(wait_seconds)


def get_window_title(session) -> str:
    try:
        return session.findById("wnd[0]").Text
    except Exception:  # noqa: BLE001
        return ""


def check_not_write_screen(session) -> None:
    """Heuristic safety check: raise if the current screen title suggests
    a change/write screen. Does not click or modify anything - read-only
    inspection of the window title / status bar only.
    """
    title = get_window_title(session).lower()
    for kw in WRITE_ACTION_KEYWORDS:
        if kw in title:
            raise SapWriteScreenDetected(
                f"Current screen title '{title}' looks like a write/change screen "
                f"(matched keyword '{kw}'). Aborting interaction with this screen."
            )

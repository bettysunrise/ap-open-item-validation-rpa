"""
SAP GUI Scripting connection utilities.

READ-ONLY / ATTACH-ONLY module.

This module NEVER logs into SAP and NEVER creates a new SAP connection.
The user must already be logged into SAP GUI manually before running any
automation. This module only locates and attaches to an already-open
SAP GUI session via the SAP GUI Scripting API (the Running Object Table).

No SAP write actions are performed anywhere in this module.
"""
from __future__ import annotations

import win32com.client


class SapConnectionError(RuntimeError):
    """Raised when no active/attachable SAP GUI session can be found."""


def get_scripting_engine():
    """Return the SAP GUI Scripting engine (GuiApplication) via the ROT.

    Requires:
      - SAP Logon / SAP GUI to be running.
      - SAP GUI Scripting to be enabled (client + server side).
      - The user to already be logged into at least one session.
    """
    try:
        sap_gui_auto = win32com.client.GetObject("SAPGUI")
    except Exception as exc:  # noqa: BLE001 - want to wrap any COM error
        raise SapConnectionError(
            "Could not find the SAP GUI scripting ROT object 'SAPGUI'. "
            "Make sure SAP Logon is running, you are logged into a session, "
            "and SAP GUI Scripting is enabled. "
            f"Original error: {exc}"
        ) from exc

    try:
        engine = sap_gui_auto.GetScriptingEngine
    except Exception as exc:  # noqa: BLE001
        raise SapConnectionError(
            f"Found SAP GUI but could not get the scripting engine. "
            f"Scripting may be disabled. Original error: {exc}"
        ) from exc

    return engine


def list_sessions():
    """List every open session across every open connection.

    Returns a list of dicts: {connection_index, session_index, session,
    connection_description}. Does not open or close any connection.
    """
    engine = get_scripting_engine()
    sessions = []
    for ci in range(engine.Children.Count):
        connection = engine.Children.ElementAt(ci)
        try:
            conn_desc = connection.Description
        except Exception:  # noqa: BLE001
            conn_desc = "<unknown connection>"
        for si in range(connection.Children.Count):
            session = connection.Children.ElementAt(si)
            sessions.append(
                {
                    "connection_index": ci,
                    "session_index": si,
                    "connection_description": conn_desc,
                    "session": session,
                }
            )
    return sessions


def attach_session(connection_index: int | None = None, session_index: int | None = None):
    """Attach to an already-logged-in SAP GUI session.

    If indices are omitted, attaches to the first available session.
    Raises SapConnectionError if no session is found.

    This function never creates a connection and never logs in.
    """
    sessions = list_sessions()
    if not sessions:
        raise SapConnectionError(
            "No active SAP GUI session found. Please log into SAP manually "
            "first, then run this program again."
        )

    if connection_index is None or session_index is None:
        return sessions[0]["session"]

    for entry in sessions:
        if entry["connection_index"] == connection_index and entry["session_index"] == session_index:
            return entry["session"]

    raise SapConnectionError(
        f"No session found at connection_index={connection_index}, "
        f"session_index={session_index}. Available sessions: "
        f"{[(e['connection_index'], e['session_index']) for e in sessions]}"
    )


def get_session_info(session) -> dict:
    """Return a plain-dict snapshot of session.Info, tolerant of missing fields."""
    info = session.Info
    fields = [
        "SystemName",
        "SystemNumber",
        "SystemSessionId",
        "Client",
        "User",
        "Language",
        "SessionNumber",
        "ScreenNumber",
        "Transaction",
        "Program",
        "ScreenTitle",
        "ApplicationServer",
        "Codepage",
        "IsLowSpeedConnection",
        "ResponseTime",
        "InterpretationTime",
        "RoundTrips",
        "Flushes",
    ]
    result = {}
    for field in fields:
        try:
            result[field] = getattr(info, field)
        except Exception:  # noqa: BLE001
            result[field] = None
    return result

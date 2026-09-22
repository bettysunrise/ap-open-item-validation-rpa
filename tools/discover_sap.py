"""
tools/discover_sap.py

Diagnostic/discovery utility. READ-ONLY.

Attaches to the currently active SAP GUI session (the user must already be
logged in) and dumps:
  - session info (system, client, user, transaction, program, screen)
  - the current screen's GUI component tree (Id/Name/Type/Text)
  - if an ALV grid (GuiCtrlGridView) is present on screen, its column
    technical IDs, display titles, row count and a small data sample

Output is written under sap_discovery/ so we can build automation against
REAL discovered Object IDs instead of guessing them.

Usage:
    python tools/discover_sap.py
    python tools/discover_sap.py --connection 0 --session 0
    python tools/discover_sap.py --max-depth 6
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sap.connection import SapConnectionError, attach_session, get_session_info, list_sessions  # noqa: E402
from sap.discovery import describe_component, find_first_grid, describe_grid  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "sap_discovery"


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover real SAP GUI object IDs from the live session.")
    parser.add_argument("--connection", type=int, default=None, help="Connection index (default: first available)")
    parser.add_argument("--session", type=int, default=None, help="Session index (default: first available)")
    parser.add_argument("--max-depth", type=int, default=8, help="Max tree depth to walk")
    parser.add_argument("--tag", type=str, default=None, help="Label appended to output filenames, e.g. ap_open_item_selection")
    args = parser.parse_args()

    OUT_DIR.mkdir(exist_ok=True)

    try:
        sessions = list_sessions()
    except SapConnectionError as exc:
        print(f"[ERROR] {exc}")
        return 1

    print(f"Found {len(sessions)} active SAP GUI session(s):")
    for entry in sessions:
        info = get_session_info(entry["session"])
        print(
            f"  conn={entry['connection_index']} sess={entry['session_index']} "
            f"system={info.get('SystemName')} client={info.get('Client')} "
            f"user={info.get('User')} transaction={info.get('Transaction')}"
        )

    try:
        session = attach_session(args.connection, args.session)
    except SapConnectionError as exc:
        print(f"[ERROR] {exc}")
        return 1

    info = get_session_info(session)
    print("\nAttached session info:")
    print(json.dumps(info, indent=2, default=str))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = f"_{args.tag}" if args.tag else ""

    session_info_path = OUT_DIR / "session_info.json"
    session_info_path.write_text(json.dumps(info, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {session_info_path}")

    try:
        wnd0 = session.findById("wnd[0]")
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Could not access wnd[0]: {exc}")
        return 1

    print("Walking current screen component tree (this may take a few seconds)...")
    tree = describe_component(wnd0, max_depth=args.max_depth)

    screen_tag = (info.get("Transaction") or "screen").lower()
    screen_path = OUT_DIR / f"{screen_tag}{tag}_{timestamp}.json"
    screen_path.write_text(json.dumps(tree, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {screen_path}")

    print("Searching for an ALV grid on the current screen...")
    grid = find_first_grid(wnd0)
    if grid is not None:
        grid_id = getattr(grid, "Id", "<unknown>")
        print(f"Found grid: {grid_id}")
        grid_info = describe_grid(grid)
        grid_info["_grid_id"] = grid_id
        grid_path = OUT_DIR / f"{screen_tag}{tag}_grid_{timestamp}.json"
        grid_path.write_text(json.dumps(grid_info, indent=2, default=str), encoding="utf-8")
        print(f"Wrote {grid_path}")
        print(f"Row count: {grid_info.get('RowCount')}, Columns: {len(grid_info.get('ColumnOrder', []))}")
    else:
        print("No ALV grid found on the current screen.")

    print("\nDone. Inspect the JSON files under sap_discovery/ to find real Object IDs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

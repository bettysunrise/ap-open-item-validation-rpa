"""
SAP GUI screen/object discovery utilities.

READ-ONLY. This module only reads properties off SAP GUI Scripting objects
(Id, Name, Type, Text, grid metadata, etc.) and never sets values or
triggers actions, with the sole exception that the caller may pass in a
container root that was reached via normal (allowed) navigation elsewhere.

Purpose: let us discover REAL SAP GUI Object IDs from the live session
instead of guessing them, per project rules.
"""
from __future__ import annotations

from typing import Any


# GuiGridView (ALV grid) does not expose its cells as scripting Children,
# so it needs dedicated handling via its own API (ColumnOrder, RowCount, ...).
GRID_TYPES = {"GuiCtrlGridView", "GuiShell"}


def describe_component(comp, max_depth: int = 8, _depth: int = 0, max_nodes: int = 4000, _counter: list[int] | None = None) -> dict[str, Any]:
    """Recursively describe a GuiComponent tree.

    Captures Id, Name, Type, Text (when available) and recurses into
    Children up to max_depth. Every property access is wrapped so a
    single unsupported property never aborts the whole dump.
    """
    if _counter is None:
        _counter = [0]
    _counter[0] += 1

    node: dict[str, Any] = {}

    for attr in ("Id", "Name", "Type"):
        try:
            node[attr] = getattr(comp, attr)
        except Exception:  # noqa: BLE001
            node[attr] = None

    try:
        if hasattr(comp, "Text"):
            node["Text"] = comp.Text
    except Exception:  # noqa: BLE001
        pass

    try:
        if hasattr(comp, "Tooltip"):
            node["Tooltip"] = comp.Tooltip
    except Exception:  # noqa: BLE001
        pass

    comp_type = node.get("Type") or ""

    # ALV grid / GuiShell controls: describe via grid-specific API instead
    # of trying to walk (nonexistent) Children.
    if comp_type in GRID_TYPES:
        try:
            subtype = getattr(comp, "SubType", None)
        except Exception:  # noqa: BLE001
            subtype = None
        node["SubType"] = subtype
        if comp_type == "GuiCtrlGridView" or subtype == "GridView":
            node["GridInfo"] = describe_grid(comp)

    if _depth < max_depth and _counter[0] < max_nodes:
        try:
            children_coll = comp.Children if hasattr(comp, "Children") else None
        except Exception:  # noqa: BLE001
            children_coll = None

        if children_coll is not None:
            try:
                count = children_coll.Count
            except Exception:  # noqa: BLE001
                count = 0
            children = []
            for i in range(count):
                if _counter[0] >= max_nodes:
                    children.append({"_truncated": True, "reason": "max_nodes reached"})
                    break
                try:
                    child = children_coll.ElementAt(i)
                except Exception as exc:  # noqa: BLE001
                    children.append({"_error": str(exc)})
                    continue
                children.append(describe_component(child, max_depth, _depth + 1, max_nodes, _counter))
            if children:
                node["Children"] = children

    return node


def describe_grid(grid, sample_rows: int = 5) -> dict[str, Any]:
    """Describe a GuiCtrlGridView (ALV grid) via its dedicated API.

    Never modifies the grid (no SelectColumn/SelectAll/etc calls) - only
    read-only getters. Returns column technical IDs, display titles,
    row count and a small sample of visible cell values so column
    meaning can be confirmed against what the user sees on screen.
    """
    info: dict[str, Any] = {}

    try:
        info["RowCount"] = grid.RowCount
    except Exception as exc:  # noqa: BLE001
        info["RowCount"] = None
        info["RowCount_error"] = str(exc)

    try:
        info["VisibleRowCount"] = grid.VisibleRowCount
    except Exception:  # noqa: BLE001
        pass

    column_ids: list[str] = []
    try:
        col_order = grid.ColumnOrder
        for i in range(col_order.Count):
            column_ids.append(col_order.ElementAt(i))
        info["ColumnOrder"] = column_ids
    except Exception as exc:  # noqa: BLE001
        info["ColumnOrder_error"] = str(exc)

    columns_meta = {}
    for col_id in column_ids:
        meta: dict[str, Any] = {}
        try:
            titles = grid.GetColumnTitles(col_id)
            meta["titles"] = [titles.ElementAt(i) for i in range(titles.Count)]
        except Exception as exc:  # noqa: BLE001
            meta["titles_error"] = str(exc)
        columns_meta[col_id] = meta
    info["Columns"] = columns_meta

    row_count = info.get("RowCount") or 0
    n_sample = min(sample_rows, row_count)
    sample = []
    for r in range(n_sample):
        row_vals = {}
        for col_id in column_ids:
            try:
                row_vals[col_id] = grid.GetCellValue(r, col_id)
            except Exception as exc:  # noqa: BLE001
                row_vals[col_id] = f"<error: {exc}>"
        sample.append(row_vals)
    info["SampleRows"] = sample

    return info


def find_first_grid(root, max_depth: int = 10):
    """Walk the tree from root and return the first GuiCtrlGridView/GuiShell
    grid component found, or None. Read-only traversal."""
    try:
        comp_type = getattr(root, "Type", None)
    except Exception:  # noqa: BLE001
        comp_type = None

    if comp_type == "GuiCtrlGridView":
        return root

    if comp_type == "GuiShell":
        try:
            if getattr(root, "SubType", None) == "GridView":
                return root
        except Exception:  # noqa: BLE001
            pass

    if max_depth <= 0:
        return None

    try:
        children = root.Children if hasattr(root, "Children") else None
    except Exception:  # noqa: BLE001
        children = None

    if children is None:
        return None

    try:
        count = children.Count
    except Exception:  # noqa: BLE001
        return None

    for i in range(count):
        try:
            child = children.ElementAt(i)
        except Exception:  # noqa: BLE001
            continue
        found = find_first_grid(child, max_depth - 1)
        if found is not None:
            return found

    return None

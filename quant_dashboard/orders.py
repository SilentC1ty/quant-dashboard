from __future__ import annotations

import pandas as pd

from .models import StrategyData


def current_orders(strategy: StrategyData) -> pd.DataFrame:
    """Join immutable creation records, execution history and the live queue."""
    columns = ["strategy_key", "order_id", "symbol", "side", "requested_qty", "filled_qty", "remaining_qty", "current_status", "reason"]
    orders, fills = strategy.orders, strategy.fills
    pending = strategy.state.get("pending_orders", [])
    pending_by_id = {str(row.get("order_id")): row for row in pending}
    ids = set(pending_by_id)
    for frame in (orders, fills):
        if "order_id" in frame:
            ids.update(frame.order_id.astype(str))
    result = []
    for order_id in sorted(ids):
        creation = orders.loc[orders.order_id.astype(str) == order_id] if "order_id" in orders else pd.DataFrame()
        executed = fills.loc[fills.order_id.astype(str) == order_id] if "order_id" in fills else pd.DataFrame()
        queued = order_id in pending_by_id
        row = creation.iloc[-1].to_dict() if not creation.empty else (executed.iloc[0].to_dict() if not executed.empty else pending_by_id[order_id])
        requested = float(row.get("requested_qty", 0))
        qty = float(pd.to_numeric(executed.get("filled_qty", pd.Series(dtype=float)), errors="coerce").sum())
        reason = ""
        conflict = len(creation) > 1 or sum(str(p.get("order_id")) == order_id for p in pending) > 1
        for source in (creation, executed):
            for field in ("symbol", "side", "requested_qty"):
                if field in source and any(str(value) != str(row.get(field)) for value in source[field]):
                    # Numeric requested quantities can differ in string dtype only.
                    if field != "requested_qty" or any(float(value) != requested for value in source[field]):
                        conflict = True
        rejected = not executed.empty and "status" in executed and executed.status.eq("REJECTED").any()
        if conflict or requested <= 0 or qty > requested or (qty >= requested and queued) or (rejected and (queued or qty > 0)):
            status, reason = "CONFLICT", "订单、成交与待成交队列冲突"
        elif qty == requested:
            status = "FILLED"
        elif qty > 0:
            status = "PARTIAL_PENDING" if queued else "PARTIAL_CLOSED"
        elif rejected:
            status = "REJECTED"
        elif queued:
            status = "PENDING"
        elif str(row.get("status")) == "CANCELLED":
            status = "CANCELLED"
        else:
            status, reason = "UNKNOWN", "无成交记录且不在待成交队列，不能推断已完成"
        result.append({**row, "strategy_key": strategy.key, "filled_qty": qty,
                       "remaining_qty": max(requested - qty, 0), "current_status": status, "reason": reason})
    if not result:
        return pd.DataFrame(columns=columns)
    view = pd.DataFrame(result)
    priority = ["strategy_key", "order_id", "current_status", "symbol", "side", "requested_qty", "filled_qty", "remaining_qty", "reason"]
    return view[priority + [column for column in view if column not in priority]]

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from quant_dashboard.loader import load_strategy
from quant_dashboard.metrics import (
    drawdown_curve,
    normalized_nav,
    rolling_return,
    rolling_sharpe,
    strategy_metrics,
)
from quant_dashboard.models import StrategyData
from quant_dashboard.sources import OPTIONAL_FILES, SourceRegistry, discover_strategy_dirs


st.set_page_config(page_title="Quant Dashboard", page_icon="📈", layout="wide")


@st.cache_data(show_spinner=False)
def _load_cached(path: str, label: str, signature: tuple[tuple[str, float, int], ...]) -> StrategyData:
    # signature only invalidates the cache when source files change.
    _ = signature
    return load_strategy(path, custom_label=label)


def _file_signature(data_dir: Path) -> tuple[tuple[str, float, int], ...]:
    names = ("state.json", "nav.csv", *OPTIONAL_FILES)
    signature: list[tuple[str, float, int]] = []
    for name in names:
        path = data_dir / name
        if path.is_file():
            stat = path.stat()
            signature.append((name, stat.st_mtime, stat.st_size))
    return tuple(signature)


def _load_registered(registry: SourceRegistry) -> tuple[list[StrategyData], list[str]]:
    loaded: list[StrategyData] = []
    errors: list[str] = []
    for item in registry.load():
        try:
            path = Path(item["path"]).expanduser().resolve()
            strategy = _load_cached(str(path), item.get("label", ""), _file_signature(path))
            loaded.append(strategy)
        except Exception as exc:
            errors.append(f"{item.get('path', '-')}: {exc}")
    return loaded, errors


def _unique_options(strategies: list[StrategyData]) -> tuple[dict[str, StrategyData], list[str]]:
    mapping: dict[str, StrategyData] = {}
    options: list[str] = []
    seen: dict[str, int] = {}
    for strategy in strategies:
        base = strategy.display_name
        seen[base] = seen.get(base, 0) + 1
        label = base if seen[base] == 1 else f"{base} [{strategy.key[-4:]}]"
        mapping[label] = strategy
        options.append(label)
    return mapping, options


def _format_pct(value: float | None) -> str:
    return "-" if value is None or pd.isna(value) else f"{value:.2%}"


def _format_money(value: float | None) -> str:
    return "-" if value is None or pd.isna(value) else f"¥{value:,.2f}"


def _render_source_page(registry: SourceRegistry, strategies: list[StrategyData], load_errors: list[str]) -> None:
    st.title("Data Sources")
    st.caption("只读取源目录；Dashboard 只会在 ~/.quant-dashboard/sources.json 保存路径和自定义名称。")

    with st.container(border=True):
        st.subheader("添加数据源")
        source_path = st.text_input(
            "本地/NAS 目录路径",
            placeholder="例如 /Volumes/NAS/quant-weekly 或 /Volumes/NAS/quant-experiments",
        )
        custom_label = st.text_input("自定义名称（可选，仅单个数据源时使用）", placeholder="例如 Weekly V0.3")
        col1, col2, _ = st.columns([1, 1, 3])

        if col1.button("添加", type="primary", use_container_width=True):
            if not source_path.strip():
                st.warning("请输入目录路径。")
            else:
                try:
                    found = discover_strategy_dirs(source_path, recursive=False)
                    if not found:
                        st.warning("没有找到兼容的 paper 数据目录。需要至少存在 state.json 和 nav.csv。")
                    else:
                        added = registry.add(found, label=custom_label)
                        st.success(f"发现 {len(found)} 份数据，新增 {added} 份。")
                        st.cache_data.clear()
                        st.rerun()
                except Exception as exc:
                    st.error(str(exc))

        if col2.button("递归扫描", use_container_width=True):
            if not source_path.strip():
                st.warning("请输入目录路径。")
            else:
                try:
                    found = discover_strategy_dirs(source_path, recursive=True)
                    if not found:
                        st.warning("该目录下没有找到兼容的 paper 数据。")
                    else:
                        added = registry.add(found)
                        st.success(f"扫描到 {len(found)} 份数据，新增 {added} 份。")
                        st.cache_data.clear()
                        st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    if load_errors:
        with st.expander(f"无法加载的数据源（{len(load_errors)}）", expanded=False):
            for error in load_errors:
                st.error(error)

    st.subheader("已添加的数据源")
    entries = registry.load()
    loaded_by_path = {str(item.data_dir): item for item in strategies}
    if not entries:
        st.info("还没有数据源。添加单个 quant 项目、paper 目录，或递归扫描一个父目录即可。")
        return

    for index, entry in enumerate(entries):
        path = str(Path(entry["path"]).expanduser().resolve())
        strategy = loaded_by_path.get(path)
        with st.container(border=True):
            top, remove_col = st.columns([5, 1])
            if strategy is not None:
                top.markdown(f"**{strategy.display_name}**  ·  `{strategy.strategy_version}`  ·  {strategy.execution_label}")
                latest = strategy.latest_date.strftime("%Y-%m-%d") if strategy.latest_date is not None else "-"
                top.caption(f"{path}  ·  最新数据 {latest}  ·  NAV {len(strategy.nav):,} 行")
            else:
                top.markdown("**无法加载**")
                top.caption(path)

            if remove_col.button("移除", key=f"remove-{index}", use_container_width=True):
                registry.remove(path)
                st.cache_data.clear()
                st.rerun()

            label_col, save_col = st.columns([5, 1])
            new_label = label_col.text_input(
                "显示名称",
                value=entry.get("label", ""),
                placeholder="留空则自动使用策略版本与调仓频率",
                key=f"label-{index}",
                label_visibility="collapsed",
            )
            if save_col.button("保存名称", key=f"save-label-{index}", use_container_width=True):
                registry.update_label(path, new_label)
                st.cache_data.clear()
                st.rerun()

            if strategy is not None:
                project = str(strategy.project_root) if strategy.project_root else "未识别"
                available = [name for name in ("state.json", "nav.csv", *OPTIONAL_FILES) if (strategy.data_dir / name).is_file()]
                st.caption(f"项目根目录：{project}")
                st.caption("文件：" + ", ".join(available))
                for warning in strategy.warnings:
                    st.warning(warning)


def _render_overview(selected: list[StrategyData]) -> None:
    st.title("Overview")
    st.caption("各策略按自身初始资金计算累计表现；曲线统一归一化为初始值 100。")

    rows = [strategy_metrics(strategy) for strategy in selected]
    rows = [row for row in rows if row]
    if not rows:
        st.info("当前策略没有可用 NAV 数据。")
        return

    display = pd.DataFrame(rows).rename(
        columns={
            "strategy": "策略",
            "version": "版本",
            "execution": "调仓",
            "latest_date": "最新日期",
            "nav": "NAV",
            "total_return": "累计收益",
            "annualized_return": "年化收益",
            "max_drawdown": "最大回撤",
            "sharpe": "Sharpe",
            "annualized_volatility": "年化波动",
            "trades": "成交笔数",
            "positions": "持仓数",
            "commission": "佣金",
            "slippage": "滑点",
            "total_cost": "总成本",
            "dividends": "分红",
            "cash": "现金",
            "cash_weight": "现金比例",
        }
    )
    st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
        column_config={
            "NAV": st.column_config.NumberColumn(format="¥ %.2f"),
            "累计收益": st.column_config.NumberColumn(format="percent"),
            "年化收益": st.column_config.NumberColumn(format="percent"),
            "最大回撤": st.column_config.NumberColumn(format="percent"),
            "Sharpe": st.column_config.NumberColumn(format="%.2f"),
            "年化波动": st.column_config.NumberColumn(format="percent"),
            "佣金": st.column_config.NumberColumn(format="¥ %.2f"),
            "滑点": st.column_config.NumberColumn(format="¥ %.2f"),
            "总成本": st.column_config.NumberColumn(format="¥ %.2f"),
            "分红": st.column_config.NumberColumn(format="¥ %.2f"),
            "现金": st.column_config.NumberColumn(format="¥ %.2f"),
            "现金比例": st.column_config.NumberColumn(format="percent"),
        },
    )

    fig = go.Figure()
    for strategy in selected:
        curve = normalized_nav(strategy)
        if curve.empty:
            continue
        fig.add_trace(go.Scatter(x=curve["date"], y=curve["normalized"], mode="lines", name=strategy.display_name))
    fig.update_layout(title="归一化净值（初始 = 100）", xaxis_title=None, yaxis_title="净值指数", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    if len(rows) >= 2:
        st.subheader("当前差异")
        best = max(rows, key=lambda item: float(item["total_return"] or 0.0))
        cheapest = min(rows, key=lambda item: float(item["total_cost"] or 0.0))
        c1, c2, c3 = st.columns(3)
        c1.metric("当前累计收益领先", best["strategy"], _format_pct(best["total_return"]))
        c2.metric("交易成本最低", cheapest["strategy"], _format_money(cheapest["total_cost"]))
        latest_dates = [row["latest_date"] for row in rows]
        c3.metric("策略数量", len(rows), f"最新 {max(latest_dates)}")


def _render_performance(selected: list[StrategyData]) -> None:
    st.title("Performance")

    nav_fig = go.Figure()
    dd_fig = go.Figure()
    return_fig = go.Figure()
    sharpe_fig = go.Figure()
    window = st.selectbox("滚动窗口", options=[20, 63, 126, 252], index=1, format_func=lambda value: f"{value} 个交易日")

    for strategy in selected:
        curve = normalized_nav(strategy)
        if not curve.empty:
            nav_fig.add_trace(go.Scatter(x=curve["date"], y=curve["normalized"], mode="lines", name=strategy.display_name))
        dd = drawdown_curve(strategy)
        if not dd.empty:
            dd_fig.add_trace(go.Scatter(x=dd["date"], y=dd["drawdown"], mode="lines", name=strategy.display_name))
        rr = rolling_return(strategy, window=window)
        if not rr.empty:
            return_fig.add_trace(go.Scatter(x=rr["date"], y=rr["rolling_return"], mode="lines", name=strategy.display_name))
        rs = rolling_sharpe(strategy, window=window)
        if not rs.empty:
            sharpe_fig.add_trace(go.Scatter(x=rs["date"], y=rs["rolling_sharpe"], mode="lines", name=strategy.display_name))

    nav_fig.update_layout(title="归一化净值", hovermode="x unified", yaxis_title="初始 = 100")
    dd_fig.update_layout(title="回撤", hovermode="x unified", yaxis_tickformat=".1%")
    return_fig.update_layout(title=f"{window} 日滚动收益", hovermode="x unified", yaxis_tickformat=".1%")
    sharpe_fig.update_layout(title=f"{window} 日滚动 Sharpe", hovermode="x unified")

    st.plotly_chart(nav_fig, use_container_width=True)
    st.plotly_chart(dd_fig, use_container_width=True)
    st.plotly_chart(return_fig, use_container_width=True)
    st.plotly_chart(sharpe_fig, use_container_width=True)


def _latest_positions(strategy: StrategyData) -> pd.DataFrame:
    positions = strategy.positions.copy()
    rows: list[dict[str, object]] = []
    if not positions.empty and "date" in positions.columns:
        dates = pd.to_datetime(positions["date"], errors="coerce")
        if not dates.dropna().empty:
            latest = dates.max()
            current = positions.loc[dates == latest]
            for _, row in current.iterrows():
                symbol = str(row.get("symbol", ""))
                rows.append(
                    {
                        "策略": strategy.display_name,
                        "日期": latest.strftime("%Y-%m-%d"),
                        "标的": strategy.names.get(symbol, symbol),
                        "代码": symbol,
                        "数量": row.get("quantity"),
                        "市值": row.get("market_value"),
                        "实际权重": row.get("weight"),
                        "目标权重": row.get("target_weight"),
                    }
                )

    metrics = strategy_metrics(strategy)
    if metrics and metrics.get("cash_weight") is not None:
        rows.append(
            {
                "策略": strategy.display_name,
                "日期": metrics["latest_date"],
                "标的": "现金",
                "代码": "CASH",
                "数量": None,
                "市值": metrics["cash"],
                "实际权重": metrics["cash_weight"],
                "目标权重": None,
            }
        )
    return pd.DataFrame(rows)


def _render_positions(selected: list[StrategyData]) -> None:
    st.title("Positions")
    current = pd.concat([_latest_positions(strategy) for strategy in selected], ignore_index=True)
    if current.empty:
        st.info("当前没有持仓快照。")
    else:
        st.subheader("当前持仓")
        st.dataframe(
            current,
            hide_index=True,
            use_container_width=True,
            column_config={
                "市值": st.column_config.NumberColumn(format="¥ %.2f"),
                "实际权重": st.column_config.NumberColumn(format="percent"),
                "目标权重": st.column_config.NumberColumn(format="percent"),
            },
        )

        chart = current.dropna(subset=["实际权重"]).copy()
        fig = go.Figure()
        for strategy_name, group in chart.groupby("策略"):
            fig.add_trace(go.Bar(name=strategy_name, x=group["标的"], y=group["实际权重"]))
        fig.update_layout(title="当前仓位对比", barmode="group", yaxis_tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)

    history_candidates = [strategy for strategy in selected if not strategy.positions.empty and "date" in strategy.positions.columns]
    if not history_candidates:
        return

    st.subheader("历史仓位")
    choice = st.selectbox("策略", history_candidates, format_func=lambda item: item.display_name)
    positions = choice.positions.copy()
    positions["date"] = pd.to_datetime(positions["date"], errors="coerce")
    positions["symbol"] = positions["symbol"].astype(str)
    positions["name"] = positions["symbol"].map(choice.names).fillna(positions["symbol"])
    if "weight" in positions.columns:
        pivot = positions.pivot_table(index="date", columns="name", values="weight", aggfunc="last").fillna(0.0).sort_index()
        fig = go.Figure()
        for column in pivot.columns:
            fig.add_trace(go.Scatter(x=pivot.index, y=pivot[column], mode="lines", stackgroup="one", name=str(column)))
        fig.update_layout(title=f"{choice.display_name} 历史持仓权重", yaxis_tickformat=".0%", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)


def _with_strategy(strategy: StrategyData, frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    out.insert(0, "strategy", strategy.display_name)
    if "symbol" in out.columns:
        out.insert(out.columns.get_loc("symbol") + 1, "name", out["symbol"].astype(str).map(strategy.names).fillna(out["symbol"].astype(str)))
    return out


def _render_trades(selected: list[StrategyData]) -> None:
    st.title("Trades")
    fill_frames = [_with_strategy(strategy, strategy.fills) for strategy in selected if not strategy.fills.empty]
    order_frames = [_with_strategy(strategy, strategy.orders) for strategy in selected if not strategy.orders.empty]

    fill_tab, order_tab, cost_tab = st.tabs(["成交", "订单", "成本"])
    with fill_tab:
        if not fill_frames:
            st.info("暂无成交记录。")
        else:
            fills = pd.concat(fill_frames, ignore_index=True)
            sort_col = "trade_date" if "trade_date" in fills.columns else None
            if sort_col:
                fills = fills.sort_values(sort_col, ascending=False)
            st.dataframe(fills, hide_index=True, use_container_width=True)

    with order_tab:
        if not order_frames:
            st.info("暂无订单记录。")
        else:
            orders = pd.concat(order_frames, ignore_index=True)
            sort_col = "signal_date" if "signal_date" in orders.columns else None
            if sort_col:
                orders = orders.sort_values(sort_col, ascending=False)
            st.dataframe(orders, hide_index=True, use_container_width=True)

    with cost_tab:
        rows = []
        for strategy in selected:
            metrics = strategy_metrics(strategy)
            if not metrics:
                continue
            rows.append(
                {
                    "策略": strategy.display_name,
                    "成交笔数": metrics["trades"],
                    "佣金": metrics["commission"],
                    "滑点": metrics["slippage"],
                    "总交易成本": metrics["total_cost"],
                    "累计分红": metrics["dividends"],
                }
            )
        costs = pd.DataFrame(rows)
        st.dataframe(
            costs,
            hide_index=True,
            use_container_width=True,
            column_config={
                "佣金": st.column_config.NumberColumn(format="¥ %.2f"),
                "滑点": st.column_config.NumberColumn(format="¥ %.2f"),
                "总交易成本": st.column_config.NumberColumn(format="¥ %.2f"),
                "累计分红": st.column_config.NumberColumn(format="¥ %.2f"),
            },
        )


def main() -> None:
    registry = SourceRegistry()
    strategies, load_errors = _load_registered(registry)

    st.sidebar.title("Quant Dashboard")
    page = st.sidebar.radio("页面", ["Overview", "Performance", "Positions", "Trades", "Data Sources"])

    if page == "Data Sources":
        _render_source_page(registry, strategies, load_errors)
        return

    if not strategies:
        st.title("Quant Dashboard")
        st.warning("还没有可用数据源。请先到 Data Sources 添加 quant 项目或 paper 目录。")
        if load_errors:
            for error in load_errors:
                st.error(error)
        return

    mapping, options = _unique_options(strategies)
    selected_labels = st.sidebar.multiselect("比较策略", options, default=options)
    selected = [mapping[label] for label in selected_labels]
    if not selected:
        st.info("请至少选择一个策略。")
        return

    if load_errors:
        st.sidebar.warning(f"另有 {len(load_errors)} 个数据源加载失败")

    if page == "Overview":
        _render_overview(selected)
    elif page == "Performance":
        _render_performance(selected)
    elif page == "Positions":
        _render_positions(selected)
    elif page == "Trades":
        _render_trades(selected)


if __name__ == "__main__":
    main()

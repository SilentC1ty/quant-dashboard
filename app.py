from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from quant_dashboard.benchmarks import (
    BenchmarkData,
    benchmark_drawdown_curve,
    benchmark_metrics,
    benchmark_normalized,
    benchmark_rolling_return,
    benchmark_rolling_sharpe,
    collect_benchmarks,
    excess_return_curve,
)
from quant_dashboard.holdings import current_holding_return_series
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


def _unique_benchmark_options(benchmarks: list[BenchmarkData]) -> tuple[dict[str, BenchmarkData], list[str]]:
    mapping: dict[str, BenchmarkData] = {}
    options: list[str] = []
    seen: dict[str, int] = {}
    for benchmark in benchmarks:
        base = benchmark.display_name
        seen[base] = seen.get(base, 0) + 1
        label = base if seen[base] == 1 else f"{base} [{seen[base]}]"
        mapping[label] = benchmark
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


def _render_benchmark_table(benchmarks: list[BenchmarkData]) -> None:
    if not benchmarks:
        return
    rows = [benchmark_metrics(benchmark) for benchmark in benchmarks]
    rows = [row for row in rows if row]
    if not rows:
        return

    st.subheader("Benchmarks")
    st.caption("基准使用 quant 项目的研究层复权价格缓存构造 Buy & Hold；只在起点建仓一次，并计入一次佣金和滑点。")
    display = pd.DataFrame(rows).rename(
        columns={
            "benchmark": "基准",
            "composition": "构成",
            "latest_date": "最新日期",
            "total_return": "累计收益",
            "annualized_return": "年化收益",
            "max_drawdown": "最大回撤",
            "sharpe": "Sharpe",
            "annualized_volatility": "年化波动",
        }
    )
    st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
        column_config={
            "累计收益": st.column_config.NumberColumn(format="percent"),
            "年化收益": st.column_config.NumberColumn(format="percent"),
            "最大回撤": st.column_config.NumberColumn(format="percent"),
            "Sharpe": st.column_config.NumberColumn(format="%.2f"),
            "年化波动": st.column_config.NumberColumn(format="percent"),
        },
    )


def _render_overview(selected: list[StrategyData], benchmarks: list[BenchmarkData]) -> None:
    st.title("Overview")
    st.caption("策略按自身初始资金计算累计表现；策略和基准曲线统一显示为财富指数 100。")

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

    _render_benchmark_table(benchmarks)

    fig = go.Figure()
    for strategy in selected:
        curve = normalized_nav(strategy)
        if curve.empty:
            continue
        fig.add_trace(go.Scatter(x=curve["date"], y=curve["normalized"], mode="lines", name=strategy.display_name))
    for benchmark in benchmarks:
        curve = benchmark_normalized(benchmark)
        if curve.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=curve["date"],
                y=curve["normalized"],
                mode="lines",
                name=f"Benchmark · {benchmark.display_name}",
                line={"dash": "dash"},
            )
        )
    fig.update_layout(title="策略 vs Benchmark（财富指数）", xaxis_title=None, yaxis_title="初始 ≈ 100", hovermode="x unified")
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


def _render_performance(selected: list[StrategyData], benchmarks: list[BenchmarkData]) -> None:
    st.title("Performance")

    nav_fig = go.Figure()
    dd_fig = go.Figure()
    return_fig = go.Figure()
    sharpe_fig = go.Figure()
    window = st.selectbox(
        "滚动窗口",
        options=[20, 63, 126, 252],
        index=1,
        format_func=lambda value: f"{value} 个交易日",
        key="performance-rolling-window",
    )

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

    for benchmark in benchmarks:
        name = f"Benchmark · {benchmark.display_name}"
        curve = benchmark_normalized(benchmark)
        if not curve.empty:
            nav_fig.add_trace(go.Scatter(x=curve["date"], y=curve["normalized"], mode="lines", name=name, line={"dash": "dash"}))
        dd = benchmark_drawdown_curve(benchmark)
        if not dd.empty:
            dd_fig.add_trace(go.Scatter(x=dd["date"], y=dd["drawdown"], mode="lines", name=name, line={"dash": "dash"}))
        rr = benchmark_rolling_return(benchmark, window=window)
        if not rr.empty:
            return_fig.add_trace(go.Scatter(x=rr["date"], y=rr["rolling_return"], mode="lines", name=name, line={"dash": "dash"}))
        rs = benchmark_rolling_sharpe(benchmark, window=window)
        if not rs.empty:
            sharpe_fig.add_trace(go.Scatter(x=rs["date"], y=rs["rolling_sharpe"], mode="lines", name=name, line={"dash": "dash"}))

    nav_fig.update_layout(title="归一化净值 / Benchmark", hovermode="x unified", yaxis_title="初始 ≈ 100")
    dd_fig.update_layout(title="回撤", hovermode="x unified", yaxis_tickformat=".1%")
    return_fig.update_layout(title=f"{window} 日滚动收益", hovermode="x unified", yaxis_tickformat=".1%")
    sharpe_fig.update_layout(title=f"{window} 日滚动 Sharpe", hovermode="x unified")

    st.plotly_chart(nav_fig, use_container_width=True)
    st.plotly_chart(dd_fig, use_container_width=True)
    st.plotly_chart(return_fig, use_container_width=True)
    st.plotly_chart(sharpe_fig, use_container_width=True)

    if benchmarks:
        st.subheader("累计超额收益")
        st.caption("> 0 表示策略财富相对所选 Benchmark 领先；< 0 表示落后。")
        benchmark_mapping, benchmark_options = _unique_benchmark_options(benchmarks)
        primary_label = st.selectbox(
            "超额收益基准",
            benchmark_options,
            key="performance-excess-benchmark",
        )
        primary = benchmark_mapping[primary_label]
        excess_fig = go.Figure()
        for strategy in selected:
            curve = excess_return_curve(strategy, primary)
            if curve.empty:
                continue
            excess_fig.add_trace(
                go.Scatter(
                    x=curve["date"],
                    y=curve["excess_return"],
                    mode="lines",
                    name=strategy.display_name,
                )
            )
        excess_fig.add_hline(y=0.0)
        excess_fig.update_layout(
            title=f"相对 {primary.display_name} 的累计超额收益",
            hovermode="x unified",
            yaxis_tickformat=".1%",
        )
        st.plotly_chart(excess_fig, use_container_width=True)


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


def _render_current_holding_returns(selected: list[StrategyData]) -> None:
    st.subheader("当前持仓收益走势")
    st.caption(
        "每条曲线从该标的本轮连续持有的首个每日收盘价归零，展示持仓期间的价格收益率。"
        "该指标不分摊单笔佣金/滑点；ETF 分红现金计入账户 NAV，但不计入这里的单标的价格曲线。"
    )

    any_data = False
    for strategy in selected:
        holdings = current_holding_return_series(strategy)
        metrics = strategy_metrics(strategy)
        cash_weight = metrics.get("cash_weight") if metrics else None
        if not holdings and cash_weight is None:
            continue

        any_data = True
        with st.container(border=True):
            st.markdown(f"**{strategy.display_name}**")

            summary_rows: list[dict[str, object]] = []
            for holding in holdings:
                summary_rows.append(
                    {
                        "标的": holding.name,
                        "代码": holding.symbol,
                        "本轮持有起点": holding.start_date.strftime("%Y-%m-%d"),
                        "最新日期": holding.latest_date.strftime("%Y-%m-%d"),
                        "当前权重": holding.current_weight,
                        "持仓期价格收益": holding.latest_return,
                    }
                )

            if cash_weight is not None:
                latest = metrics.get("latest_date") if metrics else "-"
                summary_rows.append(
                    {
                        "标的": "现金",
                        "代码": "CASH",
                        "本轮持有起点": "-",
                        "最新日期": latest,
                        "当前权重": cash_weight,
                        "持仓期价格收益": 0.0,
                    }
                )

            st.dataframe(
                pd.DataFrame(summary_rows),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "当前权重": st.column_config.NumberColumn(format="percent"),
                    "持仓期价格收益": st.column_config.NumberColumn(format="percent"),
                },
            )

            fig = go.Figure()
            earliest: pd.Timestamp | None = None
            latest: pd.Timestamp | None = None
            for holding in holdings:
                curve = holding.curve
                if curve.empty:
                    continue
                earliest = holding.start_date if earliest is None else min(earliest, holding.start_date)
                latest = holding.latest_date if latest is None else max(latest, holding.latest_date)
                fig.add_trace(
                    go.Scatter(
                        x=curve["date"],
                        y=curve["return"],
                        mode="lines+markers",
                        name=f"{holding.name} · {holding.symbol}",
                    )
                )

            if cash_weight is not None and earliest is not None and latest is not None:
                fig.add_trace(
                    go.Scatter(
                        x=[earliest, latest],
                        y=[0.0, 0.0],
                        mode="lines",
                        name="现金",
                        line={"dash": "dot"},
                    )
                )
            elif not holdings and cash_weight is not None and strategy.latest_date is not None:
                fig.add_trace(
                    go.Scatter(
                        x=[strategy.latest_date],
                        y=[0.0],
                        mode="markers",
                        name="现金",
                    )
                )

            fig.add_hline(y=0.0)
            fig.update_layout(
                title="本轮当前持仓价格收益率",
                xaxis_title=None,
                yaxis_title="相对持仓起点",
                yaxis_tickformat=".2%",
                hovermode="x unified",
            )
            st.plotly_chart(fig, use_container_width=True)

    if not any_data:
        st.info("当前没有足够的 positions.csv 数据来计算持仓收益走势。")


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

    _render_current_holding_returns(selected)

    history_candidates = [strategy for strategy in selected if not strategy.positions.empty and "date" in strategy.positions.columns]
    if not history_candidates:
        return

    st.subheader("历史仓位")
    history_mapping, history_options = _unique_options(history_candidates)
    choice_label = st.selectbox("策略", history_options, key="positions-history-strategy")
    choice = history_mapping[choice_label]
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
    page = st.sidebar.radio(
        "页面",
        ["Overview", "Performance", "Positions", "Trades", "Data Sources"],
        key="dashboard-page",
    )

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
    selected_labels = st.sidebar.multiselect("比较策略", options, default=options, key="strategy-selection")
    selected = [mapping[label] for label in selected_labels]
    if not selected:
        st.info("请至少选择一个策略。")
        return

    available_benchmarks, benchmark_warnings = collect_benchmarks(selected)
    selected_benchmarks: list[BenchmarkData] = []
    if available_benchmarks:
        benchmark_mapping, benchmark_options = _unique_benchmark_options(available_benchmarks)
        selected_benchmark_labels = st.sidebar.multiselect(
            "Benchmarks",
            benchmark_options,
            default=benchmark_options,
            key="benchmark-selection",
        )
        selected_benchmarks = [benchmark_mapping[label] for label in selected_benchmark_labels]

    if load_errors:
        st.sidebar.warning(f"另有 {len(load_errors)} 个数据源加载失败")
    if benchmark_warnings:
        st.sidebar.warning(f"{len(benchmark_warnings)} 条 Benchmark 数据提示")
        with st.sidebar.expander("Benchmark 数据提示", expanded=False):
            for warning in benchmark_warnings:
                st.caption(warning)

    if page == "Overview":
        _render_overview(selected, selected_benchmarks)
    elif page == "Performance":
        _render_performance(selected, selected_benchmarks)
    elif page == "Positions":
        _render_positions(selected)
    elif page == "Trades":
        _render_trades(selected)


if __name__ == "__main__":
    main()

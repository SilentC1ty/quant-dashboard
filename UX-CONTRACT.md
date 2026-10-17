# Shared behavior

Visual ownership is recorded in [DESIGN.md](DESIGN.md). This local viewer reads paper ledgers and never edits trading data. Source policy: README.md and `quant_dashboard/sources.py`. Accounting contracts: `quality.py`, `orders.py`, `metrics.py`, `benchmarks.py`, and the quant producer's V0.4 accounting document. There is no billing, remote sharing, account permission editor or legal acceptance workflow.

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Table Selection | Streamlit dataframe, read-only | app.py | Framework sorting and scrolling; no trading actions | tests/test_ui.py and browser |
| Select/Listbox | Streamlit selectbox/multiselect | app.py | Framework authored popup; no native replacement | tests/test_ui.py and keyboard browser check |
| Form | Streamlit labeled text inputs and buttons | Data Sources in app.py | Explicit add/scan/save; no autosave | tests/test_ui.py |
| Scrollbar | Browser and Streamlit native scroll surfaces | Streamlit runtime | Table overflow; natural form/page scroll | Narrow viewport browser check |
| Toast | Streamlit inline info/warning/error/success | app.py | Durable source warnings and inline validation | tests/test_ui.py |
| CRUD | SourceRegistry | quant_dashboard/sources.py | Add, label, remove registry entry only | tests/test_dashboard.py and tests/test_ui.py |

## Flow ledger

Adding a valid directory discovers ledgers and adds only new paths; repeat add is idempotent. Label changes persist to the registry. Removing an entry never removes a source file; the same path can be added again. Page navigation and selections use Streamlit session state. A caller may select `QUANT_DASHBOARD_REGISTRY` for isolated tests or multiple profiles.

Invalid source data is an error, not an empty account. A failed source is excluded from comparison and its error remains accessible. Optional absent files produce limitations; no missing raw data is treated as confirmed zero dividends. Loading uses the framework running indicator; local filesystem failure ends with actionable text and a reload/retry path. Manifest mismatches indicate incomplete updates and require refresh after the producer commits. Config changes invalidate the loader cache and frozen fingerprint mismatches block attribution.

Order status combines immutable creation, fills and the live queue using source identity plus order ID. PARTIAL_PENDING and PARTIAL_CLOSED have distinct meanings. Unresolved absence is UNKNOWN, contradictions are CONFLICT; neither is assumed successful.

Performance uses initial account wealth, including the first NAV transition and its costs. Under 365 calendar days, annualized return is unavailable. Sharpe assumes risk-free rate zero, 252 observations/year and is descriptive for short samples. Initial costs are handled consistently for strategies and benchmarks. Rolling returns compound the selected number of return observations; sample deficits are text, not blank plots. Absolute excess is a difference in returns (percentage points); relative excess is a wealth ratio. Source and complete dates must match. Same-initial-holdings benchmarks retain actual fills, commissions, idle cash and earned dividends, and do not trade thereafter.

Price returns, dividend-inclusive reinvested returns, and account dollar contributions have separate labels. Dividend payment is not another profit event. Slippage is included in actual notional and must not be deducted again. Receivables are assets and are shown separately from available cash.

Accessibility follows native Streamlit keyboard semantics, focus indicators, labeled controls, semantic headings and text error states. Chinese financial labels, CNY values and exchange date-only strings remain consistent. Responsive checks preserve all actions, source warnings and full-value access; framework English chrome is retained from the existing product.

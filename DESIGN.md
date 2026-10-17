---
version: alpha
name: Quant Dashboard
description: A local research ledger for comparing ETF paper accounts with explicit data quality.
colors:
  primary: "#FF4B4B"
typography:
  sans:
    fontFamily: "sans-serif"
  mono:
    fontFamily: "monospace"
omitted:
  - section: spacing
    reason: Streamlit runtime owns responsive spacing; this document does not generate tokens.
  - section: rounded
    reason: Streamlit runtime owns native widget geometry.
components:
  table: {}
  alert: {}
  select: {}
---

# Quant Dashboard Design System

## Overview

The reference is an accountant's reconciliation workbook: dates, quantities and returns have an auditable meaning. Users compare local ETF paper accounts on a desktop, often with NAS data. The Chinese financial copy and existing English page names are established in `app.py`; no broader market or language coverage is claimed. Keep this product register and existing Streamlit presentation. Visual identity changes are outside the accounting repair.

The North Star is an honest comparison: a missing observation must remain visible as missing. Distinctive expression comes from precise accounting language and parallel series, with source and period attached to comparisons. Avoid promotional cards, ornamental gradients and return claims without sample context.

Runtime ownership: installed Streamlit native widgets and its default theme own tokens and responsive layout. This file records the existing theme, rather than generating a second theme. The primary token mirrors Streamlit's default accent; no custom CSS, fonts, radii or spacing adapters are introduced. `premium-ui.json` is the ownership and verification manifest.

## Colors

Use Streamlit's semantic info, warning and error components, with text explaining the condition. Status is expressed in words and never solely by color. Plotly series use their existing runtime palette and dash styles; table values provide a numeric alternative. Support the framework's light and dark themes without hard-coded surface overrides.

## Typography

Use the runtime sans-serif stack and system CJK fallbacks. Preserve readable Chinese explanations and full ETF identifiers. Currency is CNY with two decimal places, returns show percent, and contribution differences explicitly show percentage points. ISO date-only values represent exchange sessions; no invented intraday timestamps.

## Layout

Keep sidebar navigation, wide content and naturally scrolling pages. Dense tables own horizontal overflow; the page and forms retain document scrolling. Do not give the shared page a viewport-locked table height. Chart descriptions and data warnings remain available at narrow widths. Use the same native controls on all five pages.

## Elevation & Depth

Use existing bordered Streamlit containers. No new shadows, blur or decorative depth. Errors belong beside the affected source or dataset.

## Shapes

All widget geometry comes from Streamlit. No page-local replacement controls or radius overrides.

## Components

Use `st.button`, `st.text_input`, `st.radio`, `st.selectbox`, `st.multiselect`, `st.tabs`, `st.dataframe`, `st.info`, `st.warning` and `st.error`. Their native focus, selection, disabled and popup behavior is canonical. Data-source actions validate directory input and display inline feedback. Reversible removal only removes a registry entry. See `UX-CONTRACT.md` for outcomes.

Navigation retains existing page names and session selections. Tables present exact dates and values; charts provide trend context. Empty rolling windows state required and available sample counts. Unknown orders show UNKNOWN; contradictory evidence shows CONFLICT.

Iconography uses framework controls and the existing page icon; actions retain visible labels. No custom motion is added. Reduced motion follows the browser/framework and no meaning depends on animation.

## Do's and Don'ts

- Show errors independently from empty data and zero profit.
- Keep sample length, baseline, costs and dividend treatment close to results.
- Preserve existing Streamlit components across pages.
- Do not hide bad rows, invent missing prices, or silently compare mismatched periods.

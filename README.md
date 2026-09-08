# quant-dashboard

本地多策略量化模拟盘 Dashboard。读取一个或多个 `quant` 项目或 `paper` 数据目录，自动解析长期模拟记录并横向比较策略表现。

## 目标

- 不依赖 Docker，`git clone` 后本地运行。
- 原始策略数据只读，不修改 `state.json`、CSV 或行情缓存。
- 可手动添加 `quant` 项目根目录、`data/paper*` 数据目录，或扫描一个包含多份实验的父目录。
- 自动读取 `state.json`、`nav.csv`、`positions.csv`、`orders.csv`、`fills.csv`、`cash_events.csv`。
- 如果能够定位项目根目录，同时读取 `config/settings.yaml` 和 `config/universe.yaml`，自动识别策略版本、调仓频率、ETF 名称和 Benchmark 配置。
- 支持任意数量策略的净值、回撤、风险、成本、持仓、交易行为和 Benchmark 横向比较。

## 安装

```bash
git clone https://github.com/SilentC1ty/quant-dashboard.git
cd quant-dashboard
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e .
```

## 运行

```bash
streamlit run app.py
```

Windows 已创建虚拟环境后也可以直接双击：

```text
start_dashboard.bat
```

启动后进入 **Data Sources**，输入本地/NAS 已挂载目录路径：

- 单个项目，例如 `/Volumes/NAS/quant-biweekly`
- 直接的数据目录，例如 `/Volumes/NAS/quant-weekly/data/paper-weekly`
- 或一个父目录，并使用“递归扫描”自动发现多份 paper 数据

已添加路径仅保存到当前用户的：

```text
~/.quant-dashboard/sources.json
```

Dashboard 不复制、不写回原始交易数据。

## Benchmark

如果数据源能够定位到完整 `quant` 项目，Dashboard 会读取 `config/settings.yaml` 中的 Benchmark 配置，例如：

```yaml
benchmark:
  csi300_symbol: "510300"
  balanced_weights:
    "510300": 0.60
    "511010": 0.40
```

Benchmark **不会联网下载行情**，而是只读使用 quant 已生成的研究层价格缓存：

```text
data/cache/etf_510300_qfq.csv
data/cache/etf_511010_qfq.csv
```

口径与 quant 的回测 Benchmark 一致：使用研究层复权/总回报价格，只在起点建仓一次，之后权重自然漂移，并计入一次建仓佣金与滑点。当前默认可识别：

- 沪深300 ETF Buy & Hold
- 60/40 股债 Buy & Hold

若本地缺少相应价格缓存，Dashboard 会在侧边栏提示，但不会影响策略数据展示。

## 当前页面

- **Overview**：NAV、累计收益、年化收益、最大回撤、Sharpe、波动率、成交数、佣金、滑点、现金等横向比较，并显示 Benchmark 指标和财富曲线。
- **Performance**：策略 + Benchmark 的归一化净值、回撤、滚动收益与滚动 Sharpe，以及策略相对指定 Benchmark 的累计超额收益。
- **Positions**：当前持仓对比和单策略历史仓位变化。
- **Trades**：成交、订单和交易成本明细。
- **Data Sources**：添加、递归扫描、检查和移除策略数据源。

## 兼容的 quant paper 数据结构

```text
data/paper*/
├── state.json
├── nav.csv
├── positions.csv
├── orders.csv
├── fills.csv
└── cash_events.csv
```

其中 `nav.csv` 与 `state.json` 是识别数据源的核心文件；其余文件允许尚未生成或为空。

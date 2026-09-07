# quant-dashboard

本地多策略量化模拟盘 Dashboard。读取一个或多个 `quant` 项目或 `paper` 数据目录，自动解析长期模拟记录并横向比较策略表现。

## 目标

- 不依赖 Docker，`git clone` 后本地运行。
- 原始策略数据只读，不修改 `state.json` 或 CSV。
- 可手动添加 `quant` 项目根目录、`data/paper*` 数据目录，或扫描一个包含多份实验的父目录。
- 自动读取 `state.json`、`nav.csv`、`positions.csv`、`orders.csv`、`fills.csv`、`cash_events.csv`。
- 如果能够定位项目根目录，同时读取 `config/settings.yaml` 和 `config/universe.yaml`，自动识别策略版本、调仓频率和 ETF 名称。
- 支持任意数量策略的净值、回撤、风险、成本、持仓和交易行为比较。

## 安装

```bash
git clone https://github.com/SilentC1ty/quant-dashboard.git
cd quant-dashboard
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

## 运行

```bash
streamlit run app.py
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

## 当前页面

- **Overview**：NAV、累计收益、年化收益、最大回撤、Sharpe、波动率、成交数、佣金、滑点、现金等横向比较。
- **Performance**：归一化净值、回撤、滚动收益与滚动 Sharpe。
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

# Ledger — Personal Finance Dashboard

Live Demo
Open Ledger Finance Dashboard (https://ledgerfinance-dashboard.streamlit.app/)
A local-first personal finance app built with Streamlit, pandas, Plotly, and SQLite.

## Features

- Month-based overview with prior-month comparisons and cash-flow charts
- Transaction entry, editing, search, and confirmed deletion
- Multiple accounts, opening balances, and account-to-account transfers
- Recurring income and expense schedules with deliberate posting when due
- Monthly category budgets and over-budget indicators
- CSV/Excel import-export, PDF transaction reports, and full JSON backup/restore
- Local login with per-user finance records
- Optional isolated guest trial with sample data
- Savings goals and an SIP estimate calculator
- Latest available SENSEX close and Indian IBJA gold/silver benchmark rates
- Expense trend forecast estimates and rule-based financial insights

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

The SQLite database (`finance.db`) is created beside `database.py` on first launch. Existing finance records are retained and assigned to the first Ledger account created after this upgrade. Create a local account from the login screen. The database is excluded from Git. Download a full JSON backup regularly from **Data & reports**.

In VS Code, open the project folder and choose **Python: Select Interpreter** from the Command Palette, then select `.venv\Scripts\python.exe`. The workspace also includes a Streamlit debug profile; use **Run and Debug → Streamlit: Finance Dashboard** or run `python -m streamlit run app.py` in a terminal with `.venv` active.

## Market data and estimates

Market prices use Yahoo Finance data through yfinance for the latest available SENSEX daily close, plus the latest published IBJA benchmark for 999-purity gold (per 10 g) and silver (per kg). Quotes can be delayed or unavailable; the app shows an error instead of inventing a value. IBJA bullion rates exclude GST and jewellery making charges, and can differ from local retail prices and MCX futures. SIP and expense projections are estimates based on user-entered assumptions or past records and are not guarantees.

## Deployment

The app includes local username/password login, but it has not been designed or audited as a public multi-user service. It is intended for local use. Do not deploy it publicly with personal financial records without an independent security review, durable storage, TLS, and operational protections. Hosted ephemeral filesystems may lose SQLite data after restarts or redeployments.

## Project files

- `app.py` — Streamlit interface
- `database.py` — SQLite storage, authentication, migrations, and user-scoped records
- `finance_tools.py` — SIP estimates, expense forecasting, and financial insights
- `market_data.py` — timestamped market data fetches
- `reporting.py` — Excel exports and PDF report generation
- `sample_data.py` — guest-only demo data loader; rejects regular accounts
- `.streamlit/config.toml` — theme and server settings
- `requirements.txt` — Python package dependencies

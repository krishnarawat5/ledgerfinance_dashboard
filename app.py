"""Personal finance dashboard built with Streamlit."""

import calendar
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from database import (
    init_db, add_transaction, update_transaction, delete_transaction,
    get_all_transactions, get_summary, get_monthly_trend,
    get_budgets, save_budget, delete_budget,
    get_accounts, add_account, get_account_balances, add_transfer,
    add_recurring, get_recurring, delete_recurring, record_recurring,
    import_transactions, create_backup, restore_backup, get_transaction_count,
    clear_all_transactions,
    create_user, authenticate_user, ensure_default_account,
    create_trial_guest_user,
    save_savings_goal, get_savings_goals, delete_savings_goal,
    update_savings_goal,
    EXPENSE_CATEGORIES, INCOME_CATEGORIES,
)
from finance_tools import financial_insights, forecast_expenses, sip_estimate
from market_data import fetch_india_bullion_rates, fetch_latest_quote
from reporting import excel_bytes

st.set_page_config(page_title="Ledger | Personal Finance", page_icon="L", layout="wide")
px.defaults.template = "plotly_dark"
st.markdown("""
<style>
:root { --ink:#e5edf8; --muted:#9aa8bc; --line:#2b3a50; --accent:#79a9e8; }
.stApp { background:#0b1220; color:var(--ink); }
.block-container { max-width: 1400px; padding-top: 2rem; padding-bottom: 3rem; }
[data-testid="stMetric"] { border:1px solid var(--line); border-radius:12px; padding:16px 18px; background:#121e30; }
[data-testid="stMetricLabel"] { color:var(--muted); }
[data-testid="stSidebar"] { background:#101a2a; border-right:1px solid var(--line); }
hr { border-color:var(--line); }
h1,h2,h3 { color:var(--ink); letter-spacing:-.02em; }
@media (max-width:700px) { .block-container { padding-left:1rem; padding-right:1rem; } }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=300, show_spinner=False)
def cached_quote(symbol):
    return fetch_latest_quote(symbol)


@st.cache_data(ttl=300, show_spinner=False)
def cached_india_bullion_rates():
    return fetch_india_bullion_rates()

init_db()
if "user" not in st.session_state:
    st.title("Ledger")
    st.caption("Sign in to your private finance workspace.")
    login_tab, create_tab, guest_tab = st.tabs(["Log in", "Create account", "Try as guest"])
    with login_tab:
        with st.form("login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in", type="primary")
        if submitted:
            signed_in = authenticate_user(username, password)
            if signed_in:
                st.session_state.user = signed_in
                st.session_state.is_trial_guest = False
                ensure_default_account(signed_in["id"])
                st.rerun()
            st.error("Username or password is incorrect.")
    with create_tab:
        st.caption("Passwords are stored as salted PBKDF2 hashes. Choose at least 10 characters.")
        with st.form("create_user"):
            new_username = st.text_input("Username", key="new_username")
            new_password = st.text_input("Password", type="password", key="new_password")
            confirm_password = st.text_input("Confirm password", type="password")
            create_clicked = st.form_submit_button("Create account", type="primary")
        if create_clicked:
            try:
                if new_password != confirm_password:
                    raise ValueError("Passwords do not match.")
                st.session_state.user = create_user(new_username, new_password)
                st.session_state.is_trial_guest = False
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    with guest_tab:
        st.info("This opens a separate trial workspace with sample records. It cannot view the owner's finance data.")
        if st.button("Start a trial session", type="primary"):
            st.session_state.user = create_trial_guest_user()
            st.session_state.is_trial_guest = True
            from sample_data import load_sample_data
            load_sample_data(st.session_state.user["id"])
            st.rerun()
    st.stop()

user = st.session_state.get("user")

if not user:
    st.warning("Please log in to continue.")
    st.stop()
    raise SystemExit("Ledger must run under Streamlit. Start it with: streamlit run app.py")

owner_id = int(user["id"])
ensure_default_account(owner_id)
df = get_all_transactions(owner_id)

with st.sidebar:
    st.markdown("## Ledger")
    st.caption(f"Signed in as **{user['username']}**" + (" · isolated trial" if st.session_state.get("is_trial_guest") else ""))
    page = st.radio("Workspace", ["Overview", "Transactions", "Accounts", "Recurring", "Budgets", "Savings goals", "Calculators", "Market prices", "Insights", "Trends", "Data & reports"], label_visibility="collapsed")
    st.divider()
    st.caption(f"{get_transaction_count(owner_id):,} transactions")
    if st.button("Log out", use_container_width=True):
        del st.session_state.user
        st.session_state.is_trial_guest = False
        st.rerun()
    with st.expander("Data tools"):
        if st.session_state.get("is_trial_guest") and len(df) == 0 and st.button("Load demo data", use_container_width=True):
            from sample_data import load_sample_data
            load_sample_data(owner_id)
            st.rerun()
        if len(df) > 0:
            st.caption("Before clearing data, export a CSV backup.")
            confirm_clear = st.checkbox("I understand this permanently deletes all transactions")
            if st.button("Clear all transactions", disabled=not confirm_clear, use_container_width=True):
                clear_all_transactions(owner_id)
                st.rerun()

st.title({"Overview":"Overview", "Transactions":"Transactions", "Accounts":"Accounts", "Recurring":"Recurring transactions", "Budgets":"Monthly budgets", "Savings goals":"Savings goals", "Calculators":"Calculators", "Market prices":"Market prices", "Insights":"Financial insights", "Trends":"Trends", "Data & reports":"Data & reports"}[page])
st.caption("A clear view of your cash flow and spending.")

if page == "Overview":
    if df.empty:
        st.info("No transactions yet. Add your first transaction from the Transactions page.")
    else:
        months = sorted(df["date"].dt.strftime("%Y-%m").unique(), reverse=True)
        selected = st.selectbox("Reporting month", months, format_func=lambda x: date.fromisoformat(x + "-01").strftime("%B %Y"))
        period = df[df["date"].dt.strftime("%Y-%m") == selected]
        summary = get_summary(period, owner_id)
        current_month = date.fromisoformat(selected + "-01")
        previous_month = (current_month - pd.Timedelta(days=1)).strftime("%Y-%m")
        previous_summary = get_summary(df[df["date"].dt.strftime("%Y-%m") == previous_month], owner_id)
        metrics = st.columns(4)
        for col, label, key in zip(metrics, ["Income", "Expenses", "Net cash flow", "Savings rate"], ["total_income", "total_expenses", "savings", "savings_rate"]):
            val = summary[key]
            before = previous_summary[key]
            delta = f"{val-before:+.1f} pp" if key == "savings_rate" else f"₹{val-before:+,.2f}"
            col.metric(label, f"{val:.1f}%" if key == "savings_rate" else f"₹{val:,.2f}", delta=f"{delta} vs prior month")
        st.divider()
        left, right = st.columns([1.1, 1])
        with left:
            st.subheader("Spending by category")
            exp = period[period["type"] == "Expense"].groupby("category", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
            if exp.empty: st.caption("No expenses for this month.")
            else: st.plotly_chart(px.bar(exp, x="amount", y="category", orientation="h", labels={"amount":"₹","category":""}, color_discrete_sequence=["#315c8c"]), use_container_width=True)
        with right:
            st.subheader("Income and expenses")
            monthly = get_monthly_trend(df, owner_id)
            monthly = monthly[monthly["month"].isin(months[:12])]
            st.plotly_chart(px.bar(monthly, x="month", y="amount", color="type", barmode="group", color_discrete_map={"Income":"#4f806d","Expense":"#b66a62"}, labels={"month":"","amount":"₹","type":""}), use_container_width=True)
        st.subheader("Recent activity")
        view = period.head(8).copy()
        view["date"] = view["date"].dt.strftime("%d %b %Y")
        view["amount"] = view["amount"].map(lambda x:f"₹{x:,.2f}")
        st.dataframe(view[["date","type","category","amount","description"]], hide_index=True, use_container_width=True)

elif page == "Transactions":
    with st.expander("Add transaction", expanded=True):
        with st.form("add_txn", clear_on_submit=True):
            a,b = st.columns(2)
            txn_date = a.date_input("Date", value=date.today(), max_value=date.today())
            txn_type = b.selectbox("Type", ["Expense","Income"])
            c,d = st.columns(2)
            category = c.selectbox("Category", EXPENSE_CATEGORIES if txn_type == "Expense" else INCOME_CATEGORIES)
            amount = d.number_input("Amount (₹)", min_value=0.01, step=100.0, format="%.2f")
            accounts = [a["name"] for a in get_accounts(owner_id)]
            account = st.selectbox("Account", accounts)
            description = st.text_input("Description")
            if st.form_submit_button("Save transaction", type="primary"):
                add_transaction(txn_date, txn_type, category, amount, description, account, owner_id)
                st.rerun()
    if df.empty:
        st.info("Your transaction list will appear here.")
    else:
        st.subheader("All transactions")
        q = st.text_input("Search description or category")
        shown = df.copy()
        if q: shown = shown[shown["description"].str.contains(q, case=False, na=False) | shown["category"].str.contains(q, case=False, na=False)]
        st.dataframe(shown[["id","date","type","category","amount","account","description"]], hide_index=True, use_container_width=True, column_config={"amount":st.column_config.NumberColumn("Amount (₹)", format="₹%.2f"),"date":st.column_config.DateColumn("Date")})
        st.caption("Edit or delete by transaction ID.")
        ids = shown["id"].astype(int).tolist()
        if ids:
            selected_id = st.selectbox("Select transaction", ids)
            row = shown[shown["id"] == selected_id].iloc[0]
            with st.expander("Edit selected transaction"):
                with st.form("edit_txn"):
                    typ = st.selectbox("Type", ["Expense","Income"], index=0 if row["type"] == "Expense" else 1)
                    cat_options = EXPENSE_CATEGORIES if typ == "Expense" else INCOME_CATEGORIES
                    cat = st.selectbox("Category", cat_options, index=cat_options.index(row["category"]) if row["category"] in cat_options else 0)
                    edate = st.date_input("Date", value=row["date"].date(), max_value=date.today())
                    amt = st.number_input("Amount (₹)", min_value=0.01, value=float(row["amount"]), format="%.2f")
                    account_names = [a["name"] for a in get_accounts(owner_id)]
                    old_account = row.get("account", "Cash")
                    acct = st.selectbox("Account", account_names, index=account_names.index(old_account) if old_account in account_names else 0)
                    desc = st.text_input("Description", value=row["description"] or "")
                    if st.form_submit_button("Save changes", type="primary"):
                        update_transaction(int(selected_id), edate, typ, cat, amt, desc, acct, owner_id)
                        st.rerun()
            with st.expander("Delete selected transaction"):
                st.warning(f"This will permanently delete transaction #{selected_id}.")
                confirm = st.checkbox("Confirm deletion", key=f"confirm_{selected_id}")
                if st.button("Delete transaction", disabled=not confirm):
                    delete_transaction(int(selected_id), owner_id)
                    st.rerun()

elif page == "Accounts":
    st.caption("Track balances by account and record transfers without counting them as income or spending.")
    balances = get_account_balances(owner_id)
    if balances:
        cols = st.columns(min(len(balances), 4))
        for i, account_data in enumerate(balances):
            cols[i % len(cols)].metric(account_data["name"], f"₹{account_data['balance']:,.2f}")
    with st.expander("Add account"):
        with st.form("account_form"):
            account_name = st.text_input("Account name")
            opening = st.number_input("Opening balance (₹)", step=500.0, format="%.2f")
            if st.form_submit_button("Save account", type="primary"):
                try:
                    add_account(account_name, opening, owner_id)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not add account: {exc}")
    if len(balances) >= 2:
        st.subheader("Transfer between accounts")
        names = [a["name"] for a in balances]
        with st.form("transfer_form"):
            c1, c2 = st.columns(2)
            source = c1.selectbox("From", names)
            destination = c2.selectbox("To", names, index=1)
            amount = st.number_input("Amount (₹)", min_value=0.01, step=500.0, format="%.2f")
            transfer_date = st.date_input("Date", value=date.today(), max_value=date.today())
            note = st.text_input("Note (optional)")
            if st.form_submit_button("Record transfer", type="primary"):
                try:
                    add_transfer(transfer_date, source, destination, amount, note, owner_id)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

elif page == "Recurring":
    st.caption("Create scheduled transactions, then record each occurrence when it is due.")
    accounts = [a["name"] for a in get_accounts(owner_id)]
    with st.expander("Add recurring transaction", expanded=True):
        with st.form("recurring_form"):
            c1, c2 = st.columns(2)
            recurring_type = c1.selectbox("Type", ["Expense", "Income"])
            frequency = c2.selectbox("Frequency", ["Monthly", "Weekly", "Yearly"])
            c3, c4 = st.columns(2)
            recurring_category = c3.selectbox("Category", EXPENSE_CATEGORIES if recurring_type == "Expense" else INCOME_CATEGORIES)
            recurring_amount = c4.number_input("Amount (₹)", min_value=0.01, step=100.0, format="%.2f")
            due_date = st.date_input("Next date", value=date.today())
            recurring_account = st.selectbox("Account", accounts)
            recurring_note = st.text_input("Description")
            if st.form_submit_button("Save schedule", type="primary"):
                add_recurring(recurring_type, recurring_category, recurring_amount, recurring_note, recurring_account, frequency, due_date, owner_id)
                st.rerun()
    schedules = get_recurring(owner_id)
    if schedules:
        st.subheader("Schedules")
        for schedule in schedules:
            due = date.fromisoformat(schedule["next_date"])
            with st.container():
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.markdown(f"**{schedule['category']}** · {schedule['type']} · ₹{schedule['amount']:,.2f}")
                c2.caption(f"{schedule['frequency']} · next on {due:%d %b %Y} · {schedule['account']}")
                if due <= date.today() and c3.button("Record", key=f"record_{schedule['id']}"):
                    if schedule["frequency"] == "Weekly":
                        next_due = due + timedelta(days=7)
                    elif schedule["frequency"] == "Yearly":
                        next_due = due.replace(year=due.year + 1, day=min(due.day, calendar.monthrange(due.year + 1, due.month)[1]))
                    else:
                        next_month = (due.month % 12) + 1
                        next_year = due.year + (due.month // 12)
                        next_due = due.replace(year=next_year, month=next_month, day=min(due.day, calendar.monthrange(next_year, next_month)[1]))
                    record_recurring(schedule["id"], due, next_due, owner_id)
                    st.rerun()
                if due > date.today():
                    c3.caption("Not due")
                if st.button("Remove schedule", key=f"remove_recurring_{schedule['id']}"):
                    delete_recurring(schedule["id"], owner_id)
                    st.rerun()

elif page == "Budgets":
    st.caption("Set monthly spending limits by category. Budgets apply to the selected calendar month.")
    month = st.date_input("Month", value=date.today().replace(day=1), help="Choose any date in the month")
    month_key = month.strftime("%Y-%m")
    budgets = get_budgets(month_key, owner_id)
    spent = df[(df["type"] == "Expense") & (df["date"].dt.strftime("%Y-%m") == month_key)].groupby("category")["amount"].sum().to_dict() if not df.empty else {}
    for category_name, limit in budgets.items():
        actual = float(spent.get(category_name, 0))
        st.write(f"**{category_name}** · ₹{actual:,.2f} of ₹{limit:,.2f}")
        st.progress(min(actual / limit, 1.0) if limit > 0 else 0)
        if actual > limit: st.warning(f"Over budget by ₹{actual-limit:,.2f}")
    st.divider()
    with st.form("budget_form"):
        bc1,bc2 = st.columns(2)
        budget_category = bc1.selectbox("Expense category", EXPENSE_CATEGORIES)
        budget_limit = bc2.number_input("Monthly limit (₹)", min_value=0.01, step=500.0)
        if st.form_submit_button("Save budget", type="primary"):
            save_budget(month_key, budget_category, budget_limit, owner_id)
            st.rerun()
    if budgets:
        remove_category = st.selectbox("Remove budget", list(budgets))
        if st.button("Remove selected budget"):
            delete_budget(month_key, remove_category, owner_id)
            st.rerun()

elif page == "Savings goals":
    with st.form("savings_goal_form", clear_on_submit=True):
        goal_name = st.text_input("Goal name", placeholder="Emergency fund")
        c1, c2, c3 = st.columns(3)
        target_amount = c1.number_input("Target amount", min_value=1.0, step=1000.0)
        saved_amount = c2.number_input("Already saved", min_value=0.0, step=500.0)
        target_date = c3.date_input("Target date", value=date.today() + timedelta(days=365))
        if st.form_submit_button("Add savings goal", type="primary"):
            try:
                save_savings_goal(owner_id, goal_name, target_amount, saved_amount, target_date)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    goals = get_savings_goals(owner_id)
    if goals:
        for goal in goals:
            progress = min(goal["saved_amount"] / goal["target_amount"], 1.0)
            st.write(f"**{goal['name']}** · INR {goal['saved_amount']:,.2f} / INR {goal['target_amount']:,.2f} · target {goal['target_date']}")
            st.progress(progress)
            with st.expander(f"Update {goal['name']}"):
                with st.form(f"update_goal_{goal['id']}"):
                    revised_saved = st.number_input("Amount saved", min_value=0.0, value=float(goal["saved_amount"]), step=500.0)
                    revised_target = st.number_input("Target amount", min_value=1.0, value=float(goal["target_amount"]), step=1000.0)
                    revised_date = st.date_input("Target date", value=date.fromisoformat(goal["target_date"]))
                    if st.form_submit_button("Save progress"):
                        try:
                            update_savings_goal(goal["id"], owner_id, revised_saved, revised_target, revised_date)
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
            if st.button("Delete goal", key=f"delete_goal_{goal['id']}"):
                delete_savings_goal(goal["id"], owner_id)
                st.rerun()
    else:
        st.info("Add a goal to track progress toward a savings target.")

elif page == "Calculators":
    st.subheader("SIP calculator")
    st.caption("Results are estimates based on your assumptions. Returns are not guaranteed.")
    st.caption("Estimate assumes end-of-month contributions and a constant annual return compounded monthly.")
    with st.form("sip_calculator"):
        monthly_contribution = st.number_input("Monthly contribution", min_value=0.0, value=5000.0, step=500.0)
        annual_return = st.number_input("Assumed annual return (%)", min_value=0.0, value=12.0, step=0.5)
        duration_years = st.number_input("Duration (years)", min_value=1, max_value=50, value=10)
        calculate_sip = st.form_submit_button("Calculate estimate")
    if calculate_sip:
        result = sip_estimate(monthly_contribution, annual_return, duration_years)
        a, b, c = st.columns(3)
        a.metric("Total contributions (estimate)", f"INR {result['invested']:,.2f}")
        b.metric("Future value (estimate)", f"INR {result['estimated_value']:,.2f}")
        c.metric("Estimated growth", f"INR {result['estimated_gain']:,.2f}")

elif page == "Market prices":
    st.caption("India market snapshot: latest available SENSEX close and IBJA gold/silver benchmark rates. Market data may be delayed.")
    if st.button("Refresh prices"):
        st.cache_data.clear()
    sensex, gold, silver = st.columns(3)
    quote = cached_quote("^BSESN")
    with sensex:
        st.subheader("SENSEX")
        if quote.get("ok"):
            st.metric("Latest available close", f"{quote['price']:,.2f}")
            st.caption("Index points · source: Yahoo Finance")
            st.caption(f"Market time: {quote['market_time']}")
        else:
            st.error(quote.get("error", "SENSEX price is unavailable."))

    bullion = cached_india_bullion_rates()
    with gold:
        st.subheader("Gold 999")
        if bullion.get("ok"):
            st.metric("IBJA benchmark", f"₹{bullion['gold_999_per_10g']:,.2f}")
            st.caption("Per 10 g · excludes GST and making charges")
        else:
            st.error(bullion.get("error", "Gold benchmark is unavailable."))
    with silver:
        st.subheader("Silver 999")
        if bullion.get("ok"):
            st.metric("IBJA benchmark", f"₹{bullion['silver_999_per_kg']:,.2f}")
            st.caption("Per kg · excludes GST")
        else:
            st.error(bullion.get("error", "Silver benchmark is unavailable."))
    if bullion.get("ok"):
        st.caption(f"Gold and silver source: {bullion['source']} · Rate date: {bullion['market_date']} · fetched: {bullion['fetched_at']}")
        st.caption("IBJA rates are daily bullion benchmarks; jeweller retail prices and MCX futures may differ.")

elif page == "Insights":
    if df.empty:
        st.info("Add transactions to generate spending insights and forecasts.")
    else:
        months = sorted(df["date"].dt.strftime("%Y-%m").unique(), reverse=True)
        selected_month = st.selectbox("Month", months)
        for insight in financial_insights(df, get_budgets(selected_month, owner_id), selected_month):
            st.info(insight)
        st.subheader("Expense forecast")
        st.caption("Statistical estimate from recorded monthly expense totals; it is not a promise of future spending.")
        forecast, note = forecast_expenses(df)
        if forecast is None:
            st.info(note)
        else:
            st.plotly_chart(px.line(forecast, x="month", y="estimated_expenses", markers=True, labels={"estimated_expenses":"Estimated expenses"}), use_container_width=True)

elif page == "Data & reports":
    export_df = df.drop(columns=["created_at", "owner_id", "id"], errors="ignore")
    st.download_button("Export transactions (CSV)", export_df.to_csv(index=False).encode("utf-8"), "ledger-transactions.csv", "text/csv")
    try:
        excel_file = excel_bytes(export_df)
        st.download_button("Export transactions (Excel)", excel_file, "ledger-transactions.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except ImportError:
        st.info("Excel export needs openpyxl. Install project dependencies with: python -m pip install -r requirements.txt")
    try:
        from reporting import transactions_pdf
        pdf_file = transactions_pdf(df)
        st.download_button("Download PDF report", pdf_file, "ledger-report.pdf", "application/pdf")
    except ImportError:
        st.info("PDF export needs reportlab. Install project dependencies with: python -m pip install -r requirements.txt")
    st.download_button("Download full backup (JSON)", create_backup(owner_id), "ledger-backup.json", "application/json")
    upload = st.file_uploader("Import transactions (CSV or Excel)", type=["csv", "xlsx"], key="finance_import")
    if upload and st.button("Import transactions", type="primary"):
        try:
            incoming = pd.read_csv(upload) if upload.name.lower().endswith(".csv") else pd.read_excel(upload)
            required = {"date", "type", "category", "amount"}
            if not required.issubset(incoming.columns):
                raise ValueError("Required columns: date, type, category, amount.")
            records = []
            for row in incoming.to_dict("records"):
                parsed_date = pd.to_datetime(row["date"], errors="raise")
                if pd.isna(parsed_date):
                    raise ValueError("Every row needs a valid date.")
                records.append({"date": parsed_date.date().isoformat(), "type": row["type"], "category": row["category"], "amount": row["amount"], "description": row.get("description", ""), "account": row.get("account", "Cash")})
            import_transactions(records, owner_id)
            st.success(f"Imported {len(records)} transactions.")
            st.rerun()
        except Exception as exc:
            st.error(f"Import failed: {exc}")
    st.divider()
    backup_upload = st.file_uploader("Restore full Ledger backup", type=["json"], key="full_backup_restore")
    if backup_upload:
        confirm_restore = st.checkbox("I understand this replaces my current finance records", key="restore_confirmed")
        if st.button("Restore backup", disabled=not confirm_restore):
            try:
                restore_backup(backup_upload.getvalue(), owner_id)
                st.success("Backup restored.")
                st.rerun()
            except Exception as exc:
                st.error(f"Restore failed: {exc}")

elif page == "Trends":
    if df.empty: st.info("Add transactions to see trends.")
    else:
        st.subheader("Monthly cash flow")
        trend = get_monthly_trend(df, owner_id)
        st.plotly_chart(px.line(trend, x="month", y="amount", color="type", markers=True, color_discrete_map={"Income":"#4f806d","Expense":"#b66a62"}, labels={"month":"","amount":"₹","type":""}), use_container_width=True)
        st.subheader("Category totals")
        expenses = df[df["type"] == "Expense"].groupby("category", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
        if not expenses.empty: st.dataframe(expenses, hide_index=True, use_container_width=True, column_config={"amount":st.column_config.NumberColumn("Total (₹)", format="₹%.2f")})

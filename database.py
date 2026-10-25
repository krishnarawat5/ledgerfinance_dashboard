"""
database.py — SQLite Database Layer for Personal Finance Dashboard

This file handles ALL database operations:
- Creating tables (transactions + jars)
- Adding, updating, deleting transactions
- Querying data for charts and summaries
- Managing budget jars

The database file (finance.db) is auto-created in the same folder.
"""

import sqlite3
import os
import pandas as pd
from datetime import datetime
import json
import math
import hashlib
import hmac
import secrets
from datetime import date

# Database file lives next to this script
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finance.db")

# ─── Expense categories available in the app ────────────────────────────────
EXPENSE_CATEGORIES = [
    "Food",
    "Shopping",
    "Travel",
    "Bills",
    "Education",
    "Entertainment",
    "Health",
    "Groceries",
    "Rent",
    "Gifts",
    "Investments",
    "Other",
]

INCOME_CATEGORIES = [
    "Salary",
    "Freelance",
    "Business",
    "Interest",
    "Gifts Received",
    "Refund",
    "Other",
]

# ─── Default Jar Configuration (6 Jars System) ─────────────────────────────
DEFAULT_JARS = [
    ("Necessities", 55, "#FF6B6B", "Rent, bills, groceries, essentials"),
    ("Education", 10, "#4ECDC4", "Books, courses, self-improvement"),
    ("Savings", 10, "#45B7D1", "Emergency fund, long-term savings"),
    ("Entertainment", 10, "#96CEB4", "Fun, movies, dining out, hobbies"),
    ("Giving", 5, "#FFEAA7", "Gifts, charity, donations"),
    ("Financial Freedom", 10, "#DDA0DD", "Investments, side business"),
]

# ─── Mapping: which expense categories belong to which jar ──────────────────
# This connects your spending categories to the jar system
JAR_CATEGORY_MAP = {
    "Necessities": ["Bills", "Rent", "Groceries", "Health"],
    "Education": ["Education"],
    "Savings": [],  # Savings jar doesn't have direct expense categories
    "Entertainment": ["Entertainment", "Food", "Travel", "Shopping"],
    "Giving": ["Gifts"],
    "Financial Freedom": ["Investments"],
}


def get_connection():
    """Create and return a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Access columns by name
    return conn


def init_db():
    """
    Create database tables if they don't exist.

    Called once when the app starts. Safe to call multiple times —
    'IF NOT EXISTS' prevents errors if tables already exist.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        password_salt TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")

    # Transactions table — stores every income/expense entry
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT    NOT NULL,
            type        TEXT    NOT NULL CHECK(type IN ('Income', 'Expense')),
            category    TEXT    NOT NULL,
            amount      REAL    NOT NULL CHECK(amount > 0),
            description TEXT    DEFAULT '',
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    """)

    # Add account tracking safely to older databases; old records stay in Cash.
    txn_columns = {row[1] for row in cursor.execute("PRAGMA table_info(transactions)")}
    if "account" not in txn_columns:
        cursor.execute("ALTER TABLE transactions ADD COLUMN account TEXT NOT NULL DEFAULT 'Cash'")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            opening_balance REAL NOT NULL DEFAULT 0
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO accounts (name, opening_balance) VALUES ('Cash', 0)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            source TEXT NOT NULL,
            destination TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            description TEXT DEFAULT ''
        )
    """)

    cursor.execute("""CREATE TABLE IF NOT EXISTS savings_goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL REFERENCES users(id),
        name TEXT NOT NULL,
        target_amount REAL NOT NULL CHECK(target_amount > 0),
        saved_amount REAL NOT NULL DEFAULT 0 CHECK(saved_amount >= 0),
        target_date TEXT DEFAULT ''
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL REFERENCES users(id),
        symbol TEXT NOT NULL,
        UNIQUE(owner_id, symbol)
    )""")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recurring (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK(type IN ('Income', 'Expense')),
            category TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            description TEXT DEFAULT '',
            account TEXT NOT NULL DEFAULT 'Cash',
            frequency TEXT NOT NULL CHECK(frequency IN ('Weekly', 'Monthly', 'Yearly')),
            next_date TEXT NOT NULL
        )
    """)

    # Jars table — stores budget jar definitions
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jars (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL UNIQUE,
            percentage  REAL    NOT NULL CHECK(percentage >= 0 AND percentage <= 100),
            color       TEXT    NOT NULL,
            description TEXT    DEFAULT ''
        )
    """)

    # Monthly category budgets are separate from the legacy jar feature.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            month TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            PRIMARY KEY (month, category)
        )
    """)

    # User-owned data migration. Existing rows stay unclaimed until the first
    # user registers, then claim_legacy_data assigns them to that user.
    for table in ("transactions", "accounts", "transfers", "recurring", "budgets"):
        columns = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
        if "owner_id" not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN owner_id INTEGER REFERENCES users(id)")

    # Replace the old globally unique account-name index with per-user names.
    account_sql = cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone()[0]
    if "UNIQUE(owner_id, name)" not in account_sql:
        cursor.execute("""CREATE TABLE accounts_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            opening_balance REAL NOT NULL DEFAULT 0,
            owner_id INTEGER REFERENCES users(id),
            UNIQUE(owner_id, name)
        )""")
        cursor.execute("INSERT INTO accounts_new (id, name, opening_balance, owner_id) SELECT id, name, opening_balance, owner_id FROM accounts")
        cursor.execute("DROP TABLE accounts")
        cursor.execute("ALTER TABLE accounts_new RENAME TO accounts")

    budget_sql = cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='budgets'").fetchone()[0]
    if "PRIMARYKEY(owner_id,month,category)" not in budget_sql.replace(" ", ""):
        cursor.execute("""CREATE TABLE budgets_new (
            owner_id INTEGER REFERENCES users(id),
            month TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            PRIMARY KEY(owner_id, month, category)
        )""")
        cursor.execute("INSERT INTO budgets_new (month, category, amount, owner_id) SELECT month, category, amount, owner_id FROM budgets")
        cursor.execute("DROP TABLE budgets")
        cursor.execute("ALTER TABLE budgets_new RENAME TO budgets")

    # Insert default jars if the table is empty
    cursor.execute("SELECT COUNT(*) FROM jars")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO jars (name, percentage, color, description) VALUES (?, ?, ?, ?)",
            DEFAULT_JARS,
        )

    conn.commit()
    first_regular_user = cursor.execute(
        "SELECT id FROM users WHERE username NOT LIKE 'trial-%' ORDER BY id LIMIT 1"
    ).fetchone()
    conn.close()
    # Recover safely if an older signup inserted the user but failed while
    # claiming legacy records; unowned rows are still migrated on next start.
    if first_regular_user:
        claim_legacy_data(first_regular_user["id"])


def _password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 310_000).hex()


def user_count():
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return count


def create_user(username, password):
    username = username.strip().lower()
    if len(username) < 3 or len(username) > 64:
        raise ValueError("Username must be 3 to 64 characters.")
    if username.startswith("trial-"):
        raise ValueError("Usernames beginning with 'trial-' are reserved for trial sessions.")
    if len(password) < 10:
        raise ValueError("Password must contain at least 10 characters.")
    salt = secrets.token_hex(16)
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, password_salt) VALUES (?, ?, ?)",
                (username, _password_hash(password, salt), salt),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError as exc:
        raise ValueError("That username is already in use.") from exc
    finally:
        conn.close()
    conn = get_connection()
    first_user_id = conn.execute("SELECT MIN(id) FROM users WHERE username NOT LIKE 'trial-%'").fetchone()[0]
    conn.close()
    if user_id == first_user_id:
        claim_legacy_data(user_id)
    else:
        ensure_default_account(user_id)
    return {"id": user_id, "username": username}


def authenticate_user(username, password):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
    conn.close()
    if row and hmac.compare_digest(_password_hash(password, row["password_salt"]), row["password_hash"]):
        return {"id": row["id"], "username": row["username"]}
    return None


def create_trial_guest_user():
    """Create a fresh isolated, password-free trial profile."""
    username = "trial-" + secrets.token_urlsafe(12).replace("-", "x").replace("_", "y").lower()
    password = secrets.token_urlsafe(32)
    salt = secrets.token_hex(16)
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, password_salt) VALUES (?, ?, ?)",
                (username, _password_hash(password, salt), salt),
            )
            user_id = cursor.lastrowid
            conn.execute("INSERT INTO accounts (name, opening_balance, owner_id) VALUES ('Cash', 0, ?)", (user_id,))
    finally:
        conn.close()
    return {"id": user_id, "username": "Trial guest", "is_trial_guest": True}


def claim_legacy_data(owner_id):
    conn = get_connection()
    with conn:
        for table in ("transactions", "transfers", "recurring", "budgets"):
            conn.execute(f"UPDATE {table} SET owner_id=? WHERE owner_id IS NULL", (owner_id,))

        # Legacy databases may contain multiple unowned accounts with the
        # same name. Claiming them in one UPDATE violates the per-user unique
        # index on (owner_id, name). Merge their opening balances instead.
        legacy_accounts = conn.execute(
            "SELECT id, name, opening_balance FROM accounts WHERE owner_id IS NULL ORDER BY id"
        ).fetchall()
        for account in legacy_accounts:
            owned = conn.execute(
                "SELECT id FROM accounts WHERE owner_id=? AND name=? LIMIT 1",
                (owner_id, account["name"]),
            ).fetchone()
            if owned:
                conn.execute(
                    "UPDATE accounts SET opening_balance=opening_balance+? WHERE id=?",
                    (account["opening_balance"], owned["id"]),
                )
                conn.execute("DELETE FROM accounts WHERE id=?", (account["id"],))
            else:
                conn.execute("UPDATE accounts SET owner_id=? WHERE id=?", (owner_id, account["id"]))
        conn.execute("INSERT OR IGNORE INTO accounts (name, opening_balance, owner_id) VALUES ('Cash', 0, ?)", (owner_id,))
    conn.close()


def ensure_default_account(owner_id):
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO accounts (name, opening_balance, owner_id) VALUES ('Cash', 0, ?)", (owner_id,))
    conn.commit()
    conn.close()


# ─── Transaction CRUD Operations ────────────────────────────────────────────


def add_transaction(date, txn_type, category, amount, description="", account="Cash", owner_id=1):
    """
    Add a new transaction to the database.

    Parameters:
        date (str):        Date in 'YYYY-MM-DD' format
        txn_type (str):    'Income' or 'Expense'
        category (str):    Category name (e.g., 'Food', 'Salary')
        amount (float):    Amount (must be positive)
        description (str): Optional note about the transaction
    """
    conn = get_connection()
    conn.execute(
        "INSERT INTO transactions (date, type, category, amount, description, account, owner_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(date), txn_type, category, round(amount, 2), description, account, owner_id),
    )
    conn.commit()
    conn.close()


def update_transaction(txn_id, date, txn_type, category, amount, description="", account="Cash", owner_id=1):
    """Update an existing transaction by its ID."""
    conn = get_connection()
    conn.execute(
        """UPDATE transactions
           SET date=?, type=?, category=?, amount=?, description=?, account=?
           WHERE id=? AND owner_id=?""",
        (str(date), txn_type, category, round(amount, 2), description, account, txn_id, owner_id),
    )
    conn.commit()
    conn.close()


def delete_transaction(txn_id, owner_id=1):
    """Delete a transaction by its ID."""
    conn = get_connection()
    conn.execute("DELETE FROM transactions WHERE id=? AND owner_id=?", (txn_id, owner_id))
    conn.commit()
    conn.close()


def get_all_transactions(owner_id=1):
    """
    Fetch all transactions as a pandas DataFrame.

    Returns an empty DataFrame with correct columns if no data exists.
    This prevents errors in charts and tables when the database is new.
    """
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM transactions WHERE owner_id=? ORDER BY date DESC, id DESC", conn, params=(owner_id,)
    )
    conn.close()

    if df.empty:
        # Return empty DataFrame with expected columns
        return pd.DataFrame(
            columns=["id", "date", "type", "category", "amount", "description", "created_at", "account"]
        )

    df["date"] = pd.to_datetime(df["date"])
    return df


def get_transactions_by_date_range(start_date, end_date, owner_id=1):
    """Fetch transactions within a date range."""
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM transactions WHERE owner_id=? AND date BETWEEN ? AND ? ORDER BY date DESC",
        conn,
        params=(owner_id, str(start_date), str(end_date)),
    )
    conn.close()

    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


# ─── Summary & Analytics Queries ────────────────────────────────────────────


def get_summary(df=None, owner_id=1):
    """
    Calculate total income, expenses, and savings.

    Returns a dictionary:
        {
            'total_income': 50000.0,
            'total_expenses': 35000.0,
            'savings': 15000.0,
            'savings_rate': 30.0
        }
    """
    if df is None:
        df = get_all_transactions(owner_id)

    if df.empty:
        return {
            "total_income": 0,
            "total_expenses": 0,
            "savings": 0,
            "savings_rate": 0,
        }

    total_income = df[df["type"] == "Income"]["amount"].sum()
    total_expenses = df[df["type"] == "Expense"]["amount"].sum()
    savings = total_income - total_expenses
    savings_rate = (savings / total_income * 100) if total_income > 0 else 0

    return {
        "total_income": round(total_income, 2),
        "total_expenses": round(total_expenses, 2),
        "savings": round(savings, 2),
        "savings_rate": round(savings_rate, 1),
    }


def get_expense_by_category(df=None, owner_id=1):
    """Get total spending per expense category."""
    if df is None:
        df = get_all_transactions(owner_id)

    expenses = df[df["type"] == "Expense"]
    if expenses.empty:
        return pd.DataFrame(columns=["category", "amount"])

    return expenses.groupby("category")["amount"].sum().reset_index().sort_values(
        "amount", ascending=False
    )


def get_monthly_trend(df=None, owner_id=1):
    """Get monthly income and expense totals for trend charts."""
    if df is None:
        df = get_all_transactions(owner_id)

    if df.empty:
        return pd.DataFrame(columns=["month", "type", "amount"])

    df_copy = df.copy()
    df_copy["month"] = df_copy["date"].dt.to_period("M").astype(str)

    return df_copy.groupby(["month", "type"])["amount"].sum().reset_index()


# ─── Jar/Budget Operations ──────────────────────────────────────────────────


def get_jars(owner_id=1):
    """Fetch all budget jars as a list of dictionaries."""
    conn = get_connection()
    cursor = conn.execute("SELECT * FROM jars ORDER BY id")
    jars = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jars


def update_jar_percentage(jar_id, percentage):
    """Update a jar's percentage allocation."""
    conn = get_connection()
    conn.execute("UPDATE jars SET percentage=? WHERE id=?", (percentage, jar_id))
    conn.commit()
    conn.close()


def get_jar_summary(df=None, owner_id=1):
    """
    Calculate how much money is allocated to each jar and how much is spent.

    For each jar:
        - allocated = total_income × jar_percentage / 100
        - spent = sum of expenses in categories mapped to this jar
        - remaining = allocated - spent

    Returns a list of dicts with jar details + financial data.
    """
    if df is None:
        df = get_all_transactions(owner_id)

    summary = get_summary(df, owner_id)
    total_income = summary["total_income"]
    jars = get_jars()

    jar_summary = []
    for jar in jars:
        # Calculate how much money this jar gets
        allocated = total_income * jar["percentage"] / 100

        # Calculate how much has been spent from this jar
        mapped_categories = JAR_CATEGORY_MAP.get(jar["name"], [])
        spent = 0
        if mapped_categories and not df.empty:
            expenses = df[(df["type"] == "Expense") & (df["category"].isin(mapped_categories))]
            spent = expenses["amount"].sum() if not expenses.empty else 0

        remaining = allocated - spent
        usage_pct = (spent / allocated * 100) if allocated > 0 else 0

        jar_summary.append({
            "name": jar["name"],
            "percentage": jar["percentage"],
            "color": jar["color"],
            "description": jar["description"],
            "allocated": round(allocated, 2),
            "spent": round(spent, 2),
            "remaining": round(remaining, 2),
            "usage_percent": round(usage_pct, 1),
            "id": jar["id"],
        })

    return jar_summary


def clear_all_transactions(owner_id=1):
    """Delete all transactions — used when resetting sample data."""
    conn = get_connection()
    conn.execute("DELETE FROM transactions WHERE owner_id=?", (owner_id,))
    conn.commit()
    conn.close()


def get_transaction_count(owner_id=1):
    """Return the number of transactions in the database."""
    conn = get_connection()
    cursor = conn.execute("SELECT COUNT(*) FROM transactions WHERE owner_id=?", (owner_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_budgets(month, owner_id=1):
    """Return category spending limits for a YYYY-MM calendar month."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT category, amount FROM budgets WHERE month=? AND owner_id=? ORDER BY category", (month, owner_id)
    ).fetchall()
    conn.close()
    return {row["category"]: row["amount"] for row in rows}


def save_budget(month, category, amount, owner_id=1):
    """Create or update a monthly category spending limit."""
    if not (len(month) == 7 and month[4] == "-"):
        raise ValueError("Month must use YYYY-MM format.")
    amount = round(float(amount), 2)
    if amount <= 0:
        raise ValueError("Budget must be greater than zero.")
    conn = get_connection()
    conn.execute(
        "INSERT INTO budgets (month, category, amount, owner_id) VALUES (?, ?, ?, ?) "
        "ON CONFLICT DO UPDATE SET amount=excluded.amount",
        (month, category, amount, owner_id),
    )
    conn.commit()
    conn.close()


def delete_budget(month, category, owner_id=1):
    """Remove a monthly category spending limit."""
    conn = get_connection()
    conn.execute("DELETE FROM budgets WHERE month=? AND category=? AND owner_id=?", (month, category, owner_id))
    conn.commit()
    conn.close()


def get_accounts(owner_id=1):
    """List account names and opening balances."""
    conn = get_connection()
    rows = conn.execute("SELECT name, opening_balance FROM accounts WHERE owner_id=? ORDER BY name", (owner_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def add_account(name, opening_balance=0, owner_id=1):
    name = name.strip()
    if not name:
        raise ValueError("Account name is required.")
    conn = get_connection()
    conn.execute(
        "INSERT INTO accounts (name, opening_balance, owner_id) VALUES (?, ?, ?)",
        (name, round(float(opening_balance), 2), owner_id),
    )
    conn.commit()
    conn.close()


def get_account_balances(owner_id=1):
    """Calculate account balances from opening balance, transactions and transfers."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT a.name, a.opening_balance
            + COALESCE(SUM(CASE WHEN t.type='Income' THEN t.amount
                                WHEN t.type='Expense' THEN -t.amount ELSE 0 END), 0)
            + COALESCE((SELECT SUM(amount) FROM transfers x WHERE x.destination=a.name AND x.owner_id=a.owner_id), 0)
            - COALESCE((SELECT SUM(amount) FROM transfers x WHERE x.source=a.name AND x.owner_id=a.owner_id), 0) AS balance
        FROM accounts a
        LEFT JOIN transactions t ON t.account=a.name AND t.owner_id=a.owner_id
        GROUP BY a.name, a.opening_balance
        HAVING a.owner_id=?
        ORDER BY a.name
    """, (owner_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def add_transfer(transfer_date, source, destination, amount, description="", owner_id=1):
    if source == destination:
        raise ValueError("Choose two different accounts.")
    amount = round(float(amount), 2)
    if amount <= 0:
        raise ValueError("Transfer amount must be greater than zero.")
    conn = get_connection()
    conn.execute(
        "INSERT INTO transfers (date, source, destination, amount, description, owner_id) VALUES (?, ?, ?, ?, ?, ?)",
        (str(transfer_date), source, destination, amount, description, owner_id),
    )
    conn.commit()
    conn.close()


def add_recurring(type_, category, amount, description, account, frequency, next_date, owner_id=1):
    if type_ not in {"Income", "Expense"} or frequency not in {"Weekly", "Monthly", "Yearly"}:
        raise ValueError("Invalid recurring transaction type or frequency.")
    if float(amount) <= 0:
        raise ValueError("Amount must be greater than zero.")
    conn = get_connection()
    conn.execute(
        "INSERT INTO recurring (type, category, amount, description, account, frequency, next_date, owner_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (type_, category, round(float(amount), 2), description, account, frequency, str(next_date), owner_id),
    )
    conn.commit()
    conn.close()


def get_recurring(owner_id=1):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM recurring WHERE owner_id=? ORDER BY next_date, id", (owner_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_recurring(recurring_id, owner_id=1):
    conn = get_connection()
    conn.execute("DELETE FROM recurring WHERE id=? AND owner_id=?", (recurring_id, owner_id))
    conn.commit()
    conn.close()


def record_recurring(recurring_id, recorded_date, next_date, owner_id=1):
    conn = get_connection()
    row = conn.execute("SELECT * FROM recurring WHERE id=? AND owner_id=?", (recurring_id, owner_id)).fetchone()
    if row is None:
        conn.close()
        raise ValueError("Recurring transaction not found.")
    conn.execute(
        "INSERT INTO transactions (date, type, category, amount, description, account, owner_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(recorded_date), row["type"], row["category"], row["amount"], row["description"], row["account"], owner_id),
    )
    conn.execute("UPDATE recurring SET next_date=? WHERE id=? AND owner_id=?", (str(next_date), recurring_id, owner_id))
    conn.commit()
    conn.close()


BACKUP_TABLES = ("accounts", "transactions", "transfers", "recurring", "budgets", "savings_goals", "watchlist")


def import_transactions(records, owner_id=1):
    """Validate and insert an entire CSV import atomically."""
    cleaned = []
    for index, item in enumerate(records, start=1):
        try:
            txn_date = date.fromisoformat(str(item["date"]))
            txn_type = str(item["type"])
            category = str(item["category"]).strip()
            amount = float(item["amount"])
            account = str(item.get("account") or "Cash").strip()
            description = item.get("description", "")
            description = "" if pd.isna(description) else str(description)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid data on row {index}: {exc}") from exc
        if txn_type not in {"Income", "Expense"}:
            raise ValueError(f"Row {index}: type must be Income or Expense.")
        if not category or not account:
            raise ValueError(f"Row {index}: category and account are required.")
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError(f"Row {index}: amount must be a positive number.")
        cleaned.append((txn_date.isoformat(), txn_type, category, round(amount, 2), description, account))

    conn = get_connection()
    try:
        with conn:
            for _, _, _, _, _, account in cleaned:
                conn.execute("INSERT OR IGNORE INTO accounts (name, owner_id) VALUES (?, ?)", (account, owner_id))
            conn.executemany(
                "INSERT INTO transactions (date, type, category, amount, description, account, owner_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(*row, owner_id) for row in cleaned],
            )
    finally:
        conn.close()


def create_backup(owner_id=1):
    """Return a portable JSON backup containing all finance tables."""
    conn = get_connection()
    try:
        data = {table: [dict(row) for row in conn.execute(
            f"SELECT * FROM {table} WHERE owner_id=?", (owner_id,)
        ).fetchall()] for table in BACKUP_TABLES}
    finally:
        conn.close()
    return json.dumps({"format": "ledger-backup", "version": 1, "tables": data}, indent=2).encode("utf-8")


def restore_backup(payload, owner_id=1):
    """Replace finance data from a Ledger JSON backup in one transaction."""
    try:
        backup = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("File is not valid JSON.") from exc
    if backup.get("format") != "ledger-backup" or backup.get("version") != 1:
        raise ValueError("Unsupported backup format or version.")
    tables = backup.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(BACKUP_TABLES):
        raise ValueError("Backup is missing required finance tables.")

    conn = get_connection()
    try:
        allowed_columns = {
            table: {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for table in BACKUP_TABLES
        }
        for table, rows in tables.items():
            if not isinstance(rows, list):
                raise ValueError(f"Invalid rows for {table}.")
            for row in rows:
                if (not isinstance(row, dict) or not set(row).issubset(allowed_columns[table])
                        or "owner_id" not in row):
                    raise ValueError(f"Invalid record in {table}.")

        with conn:
            for table in reversed(BACKUP_TABLES):
                conn.execute(f"DELETE FROM {table} WHERE owner_id=?", (owner_id,))
            for table in BACKUP_TABLES:
                for row in tables[table]:
                    if row:
                        row = dict(row)
                        row["owner_id"] = owner_id
                        columns = list(row)
                        if "id" in columns:
                            columns.remove("id")
                        placeholders = ", ".join("?" for _ in columns)
                        column_sql = ", ".join(f'"{column}"' for column in columns)
                        conn.execute(
                            f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})',
                            [row[column] for column in columns],
                        )
            if not tables["accounts"]:
                conn.execute("INSERT INTO accounts (name, opening_balance, owner_id) VALUES ('Cash', 0, ?)", (owner_id,))
    finally:
        conn.close()


def get_savings_goals(owner_id):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM savings_goals WHERE owner_id=? ORDER BY id DESC", (owner_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_savings_goal(owner_id, name, target_amount, saved_amount, target_date):
    name = name.strip()
    target_amount, saved_amount = float(target_amount), float(saved_amount)
    if not name or not math.isfinite(target_amount) or not math.isfinite(saved_amount) or target_amount <= 0 or saved_amount < 0:
        raise ValueError("Enter a goal name, a positive target, and a non-negative saved amount.")
    conn = get_connection()
    conn.execute(
        "INSERT INTO savings_goals (owner_id, name, target_amount, saved_amount, target_date) VALUES (?, ?, ?, ?, ?)",
        (owner_id, name, target_amount, saved_amount, str(target_date or "")),
    )
    conn.commit()
    conn.close()


def delete_savings_goal(goal_id, owner_id):
    conn = get_connection()
    conn.execute("DELETE FROM savings_goals WHERE id=? AND owner_id=?", (goal_id, owner_id))
    conn.commit()
    conn.close()


def update_savings_goal(goal_id, owner_id, saved_amount, target_amount, target_date):
    saved_amount, target_amount = float(saved_amount), float(target_amount)
    if not math.isfinite(saved_amount) or not math.isfinite(target_amount) or saved_amount < 0 or target_amount <= 0:
        raise ValueError("Enter a positive target and a non-negative saved amount.")
    conn = get_connection()
    conn.execute(
        "UPDATE savings_goals SET saved_amount=?, target_amount=?, target_date=? WHERE id=? AND owner_id=?",
        (saved_amount, target_amount, str(target_date or ""), goal_id, owner_id),
    )
    conn.commit()
    conn.close()


def get_watchlist(owner_id):
    conn = get_connection()
    rows = conn.execute("SELECT symbol FROM watchlist WHERE owner_id=? ORDER BY symbol", (owner_id,)).fetchall()
    conn.close()
    return [row["symbol"] for row in rows]


def add_watchlist_symbol(owner_id, symbol):
    symbol = symbol.strip().upper()
    if not symbol or len(symbol) > 20:
        raise ValueError("Enter a valid market symbol.")
    conn = get_connection()
    try:
        conn.execute("INSERT INTO watchlist (owner_id, symbol) VALUES (?, ?)", (owner_id, symbol))
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError("That symbol is already on your watchlist.") from exc
    finally:
        conn.close()


def remove_watchlist_symbol(owner_id, symbol):
    conn = get_connection()
    conn.execute("DELETE FROM watchlist WHERE owner_id=? AND symbol=?", (owner_id, symbol))
    conn.commit()
    conn.close()

"""Transparent, estimate-only planning helpers for Ledger."""

import numpy as np
import pandas as pd


def sip_estimate(monthly_amount, annual_return_pct, years):
    months = int(years * 12)
    if months <= 0 or monthly_amount < 0 or annual_return_pct < 0:
        raise ValueError("Enter a positive duration and non-negative assumptions.")
    monthly_rate = annual_return_pct / 100 / 12
    invested = monthly_amount * months
    estimated_value = invested if monthly_rate == 0 else monthly_amount * (((1 + monthly_rate) ** months - 1) / monthly_rate)
    return {"invested": invested, "estimated_value": estimated_value, "estimated_gain": estimated_value - invested}


def forecast_expenses(transactions, months=3):
    expenses = transactions[transactions["type"] == "Expense"].copy()
    if expenses.empty:
        return None, "Add expense transactions to build an estimate."
    monthly = expenses.set_index("date")["amount"].resample("MS").sum()
    if len(monthly) < 3:
        return None, "At least three months of expense history are needed for a forecast estimate."
    x = np.arange(len(monthly), dtype=float)
    slope, intercept = np.polyfit(x, monthly.to_numpy(dtype=float), 1)
    future_x = np.arange(len(monthly), len(monthly) + months, dtype=float)
    predicted = np.maximum(0, slope * future_x + intercept)
    dates = pd.date_range(start=monthly.index[-1] + pd.offsets.MonthBegin(1), periods=months, freq="MS")
    return pd.DataFrame({"month": dates, "estimated_expenses": predicted}), None


def financial_insights(transactions, budgets, selected_month):
    insights = []
    if transactions.empty:
        return ["Add transactions to see personalized spending insights."]
    month = pd.Period(selected_month, freq="M")
    current = transactions[transactions["date"].dt.to_period("M") == month]
    previous = transactions[transactions["date"].dt.to_period("M") == month - 1]
    current_expenses = current[current["type"] == "Expense"]
    prev_expenses = previous[previous["type"] == "Expense"]
    total = float(current_expenses["amount"].sum())
    prev_total = float(prev_expenses["amount"].sum())
    if prev_total > 0:
        change = (total - prev_total) / prev_total * 100
        direction = "up" if change > 0 else "down"
        insights.append(f"Monthly expenses are {direction} {abs(change):.1f}% versus the prior month (based on recorded transactions).")
    if not current_expenses.empty:
        top_category = current_expenses.groupby("category")["amount"].sum().idxmax()
        top_amount = current_expenses.groupby("category")["amount"].sum().max()
        insights.append(f"{top_category} is the largest expense category this month at INR {top_amount:,.2f}.")
    for category, limit in budgets.items():
        spent = float(current_expenses.loc[current_expenses["category"] == category, "amount"].sum())
        if spent >= limit * 0.8:
            insights.append(f"{category} spending is INR {spent:,.2f} of its INR {limit:,.2f} monthly budget.")
    if not insights:
        insights.append("No spending alerts for this month based on the records and budgets available.")
    return insights

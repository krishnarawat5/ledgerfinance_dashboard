"""CSV-adjacent Excel and PDF report generation helpers."""

from io import BytesIO

import pandas as pd


def transactions_pdf(transactions):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=landscape(A4), rightMargin=14*mm, leftMargin=14*mm, topMargin=14*mm, bottomMargin=14*mm)
    styles = getSampleStyleSheet()
    rows = [["Date", "Type", "Category", "Account", "Description", "Amount (INR)"]]
    for _, txn in transactions.iterrows():
        description = "" if pd.isna(txn.get("description")) else str(txn.get("description", ""))
        description = description.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        rows.append([
            txn["date"].strftime("%d %b %Y") if not pd.isna(txn["date"]) else "",
            str(txn["type"]), str(txn["category"]), str(txn.get("account", "Cash")),
            Paragraph(description, styles["BodyText"]), f"{float(txn['amount']):,.2f}",
        ])
    income = transactions.loc[transactions["type"] == "Income", "amount"].sum() if not transactions.empty else 0
    expenses = transactions.loc[transactions["type"] == "Expense", "amount"].sum() if not transactions.empty else 0
    summary = f"Transactions: {len(transactions):,} | Income: INR {income:,.2f} | Expenses: INR {expenses:,.2f} | Net: INR {income-expenses:,.2f}"
    table = Table(rows, colWidths=[25*mm, 19*mm, 28*mm, 27*mm, 105*mm, 30*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#315c8c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 10), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#d9e0e8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7fa")]),
        ("ALIGN", (-1, 1), (-1, -1), "RIGHT"), ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    document.build([Paragraph("Ledger - Transaction Report", styles["Title"]), Spacer(1, 5*mm), Paragraph(summary, styles["BodyText"]), Spacer(1, 5*mm), table])
    return output.getvalue()


def excel_bytes(transactions):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        transactions.drop(columns=["created_at", "owner_id", "id"], errors="ignore").to_excel(writer, index=False, sheet_name="Transactions")
    return output.getvalue()

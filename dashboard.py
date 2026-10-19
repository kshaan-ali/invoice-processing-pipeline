#!/usr/bin/env python3
"""
Streamlit dashboard for reviewing processed invoices.

Reads records from the `invoices` DynamoDB table (written by
lambda_function.py) and presents them in a searchable list with a detail view
showing line items and the Bedrock AI analysis.

Run:
    streamlit run dashboard.py

Requires configured AWS credentials with dynamodb:Scan / dynamodb:GetItem on
the `invoices` table.
"""

import os
from decimal import Decimal

import boto3
import pandas as pd
import streamlit as st

TABLE_NAME = os.environ.get("INVOICES_TABLE", "invoices")


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
def inject_styles():
    """Hide Streamlit chrome (incl. the Deploy button) and apply a theme."""
    st.markdown(
        """
        <style>
        /* Hide the top-right toolbar (Deploy button), main menu, and footer */
        [data-testid="stToolbar"] {visibility: hidden; height: 0; position: fixed;}
        [data-testid="stDecoration"] {display: none;}
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}

        /* App background */
        .stApp {
            background: linear-gradient(160deg, #0f172a 0%, #1e293b 100%);
            color: #e2e8f0;
        }

        /* Headings */
        h1, h2, h3, h4 { color: #f8fafc !important; letter-spacing: 0.2px; }

        /* Metric cards */
        [data-testid="stMetric"] {
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 14px;
            padding: 16px 18px;
            box-shadow: 0 4px 18px rgba(0, 0, 0, 0.25);
        }
        [data-testid="stMetricLabel"] { color: #94a3b8 !important; }
        [data-testid="stMetricValue"] { color: #f1f5f9 !important; }

        /* Inputs */
        [data-testid="stTextInput"] input,
        [data-testid="stSelectbox"] div[data-baseweb="select"] {
            border-radius: 10px;
        }

        /* Dataframes */
        [data-testid="stDataFrame"] {
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid rgba(148, 163, 184, 0.15);
        }

        /* Sidebar */
        [data-testid="stSidebar"] {
            background: rgba(15, 23, 42, 0.85);
            border-right: 1px solid rgba(148, 163, 184, 0.15);
        }

        /* Analysis panel */
        .analysis-card {
            background: rgba(56, 189, 248, 0.06);
            border-left: 4px solid #38bdf8;
            border-radius: 10px;
            padding: 16px 20px;
            line-height: 1.6;
            color: #e2e8f0;
        }

        /* Section divider spacing */
        hr { border-color: rgba(148, 163, 184, 0.2); }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def _clean(value):
    """Convert DynamoDB Decimal values to plain numbers for display."""
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return value


@st.cache_data(ttl=30, show_spinner=False)
def load_invoices(table_name, region):
    """
    Scan the invoices table and return the records as a list of dicts.

    Cached for 30s so repeated interactions don't re-scan on every click.
    """
    dynamodb = boto3.resource("dynamodb", region_name=region) if region else boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    items = []
    scan_kwargs = {}
    while True:
        response = table.scan(**scan_kwargs)
        items.extend(response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            break
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    # Normalize Decimals so pandas/Streamlit render cleanly.
    for item in items:
        for k, v in list(item.items()):
            item[k] = _clean(v)
    return items


def summary_frame(invoices):
    """Build a summary DataFrame for the list view."""
    rows = []
    for inv in invoices:
        rows.append({
            "Invoice #": inv.get("invoice_number"),
            "Invoice ID": inv.get("invoice_id"),
            "Receipt Date": inv.get("receipt_date"),
            "Due Date": inv.get("due_date"),
            "Total": inv.get("total"),
            "Line Items": len(inv.get("line_items") or []),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
def render_detail(inv):
    """Render the detail view for a single invoice."""
    st.markdown(
        f"### 🧾 Invoice "
        f"`{inv.get('invoice_number') or inv.get('invoice_id') or '(unknown)'}`"
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 Total", inv.get("total") or "—")
    c2.metric("📅 Receipt Date", inv.get("receipt_date") or "—")
    c3.metric("⏳ Due Date", inv.get("due_date") or "—")
    c4.metric("📦 Line Items", len(inv.get("line_items") or []))

    st.markdown("#### Line Items")
    line_items = inv.get("line_items") or []
    if line_items:
        st.dataframe(pd.DataFrame(line_items), use_container_width=True, hide_index=True)
    else:
        st.info("No line items were extracted for this invoice.")

    st.markdown("#### 🤖 AI Analysis")
    analysis = inv.get("llm_analysis")
    if analysis:
        st.markdown(f'<div class="analysis-card">{analysis}</div>', unsafe_allow_html=True)
    else:
        st.info("No AI analysis available for this invoice.")


def main():
    st.set_page_config(
        page_title="Invoice Analysis Dashboard",
        page_icon="📄",
        layout="wide",
        menu_items={},  # removes the hamburger menu items
    )
    inject_styles()

    st.title("📄 Invoice Analysis Dashboard")
    st.caption("Processed invoices from Textract + Bedrock, stored in DynamoDB.")

    # Sidebar controls
    with st.sidebar:
        st.header("⚙️ Settings")
        region = st.text_input("AWS region (optional)", value=os.environ.get("AWS_REGION", ""))
        table_name = st.text_input("DynamoDB table", value=TABLE_NAME)
        if st.button("🔄 Refresh data", use_container_width=True):
            load_invoices.clear()

    try:
        invoices = load_invoices(table_name, region or None)
    except Exception as e:
        st.error(f"Could not load invoices from '{table_name}': {e}")
        st.stop()

    if not invoices:
        st.warning(f"No invoices found in table '{table_name}'.")
        st.stop()

    # Top-level metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("📚 Total Invoices", len(invoices))
    m2.metric("📦 Total Line Items", sum(len(inv.get("line_items") or []) for inv in invoices))
    flagged = sum(1 for inv in invoices if inv.get("llm_analysis"))
    m3.metric("🤖 With AI Analysis", flagged)

    st.divider()

    search = st.text_input(
        "🔎 Search",
        placeholder="Search by invoice number, id, total, date, or analysis text…",
    ).strip().lower()
    if search:
        def matches(inv):
            haystack = " ".join(str(inv.get(f, "")) for f in
                                ("invoice_id", "invoice_number", "total",
                                 "receipt_date", "due_date", "llm_analysis")).lower()
            return search in haystack
        invoices = [inv for inv in invoices if matches(inv)]
        if not invoices:
            st.warning("No invoices match your search.")
            st.stop()

    st.markdown("### 📋 Invoices")
    st.dataframe(summary_frame(invoices), use_container_width=True, hide_index=True)

    # Detail selector
    def label(inv):
        return (inv.get("invoice_number") or inv.get("invoice_id") or "(unknown)")

    options = list(range(len(invoices)))
    selected = st.selectbox(
        "Select an invoice to view details",
        options,
        format_func=lambda i: label(invoices[i]),
    )

    st.divider()
    render_detail(invoices[selected])


if __name__ == "__main__":
    main()

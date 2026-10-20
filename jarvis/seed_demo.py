"""Generate deterministic, idempotent demo data for a bar tenant.

Usage: ``python -m jarvis.seed_demo --seed 42 --output demo.sql``
The SQL is safe to apply repeatedly and can be reviewed before importing.
"""
from __future__ import annotations

import argparse
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

PRODUCTS = (
    ("Lager", "Beer"), ("IPA", "Beer"), ("Cider", "Beer"), ("House red", "Wine"),
    ("House white", "Wine"), ("Prosecco", "Wine"), ("Gin & tonic", "Spirits"),
    ("Rum & cola", "Spirits"), ("Whisky", "Spirits"), ("Vodka soda", "Spirits"),
    ("Tequila shot", "Spirits"), ("Espresso martini", "Cocktails"),
    ("Margarita", "Cocktails"), ("Negroni", "Cocktails"), ("Mojito", "Cocktails"),
    ("Cola", "Soft drinks"), ("Ginger beer", "Soft drinks"), ("Tonic", "Soft drinks"),
    ("Sparkling water", "Soft drinks"), ("Still water", "Soft drinks"),
    ("Fries", "Food"), ("Nachos", "Food"), ("Olives", "Food"), ("Burger", "Food"),
    ("Cheese toastie", "Food"), ("Chicken wings", "Food"), ("Brownie", "Food"),
    ("Crisps", "Snacks"), ("Peanuts", "Snacks"), ("Mixed nuts", "Snacks"),
    ("Lemonade", "Soft drinks"), ("Mocktail", "Soft drinks"),
)


def build_demo(seed: int = 42, days: int = 90, end_date: date = date(2025, 12, 31)) -> dict:
    """Return stable products, sales, and daily summaries for testing or export."""
    rng = random.Random(seed)
    count = rng.randint(25, 40)
    products = []
    for index, (name, category) in enumerate(PRODUCTS[:count], 1):
        cost = Decimal(str(round(rng.uniform(0.45, 6.5), 2)))
        price = (cost * Decimal(str(rng.uniform(2.2, 4.4)))).quantize(Decimal("0.01"))
        products.append({"sku": f"DEMO-{index:03d}", "name": name, "category": category,
                         "cost_price": cost, "sell_price": price,
                         "stock_quantity": rng.randint(0, 45)})
    sales, summaries = [], []
    start = end_date - timedelta(days=days - 1)
    for offset in range(days):
        day = start + timedelta(days=offset)
        weekend = day.weekday() >= 5
        events = rng.randint(18, 34) if weekend else rng.randint(7, 18)
        gross = refunds = voids = units = Decimal("0")
        for event in range(events):
            product = rng.choice(products)
            hour = rng.randint(17, 23) if rng.random() < 0.78 else rng.randint(11, 16)
            quantity = Decimal(str(rng.choice([1, 1, 1, 2])))
            kind = "refund" if rng.random() < 0.025 else ("void" if rng.random() < 0.018 else "sale")
            amount = (quantity * product["sell_price"]).quantize(Decimal("0.01"))
            if kind == "refund": refunds += amount
            elif kind == "void": voids += amount
            else: gross += amount; units += quantity
            sales.append({"key": f"demo-{seed}-{day.isoformat()}-{event:03d}",
                          "sku": product["sku"], "date": day.isoformat(), "hour": hour,
                          "quantity": quantity, "unit_price": product["sell_price"], "event_type": kind})
        summaries.append({"date": day.isoformat(), "transaction_count": events,
                          "gross_sales": gross, "refunds": refunds, "voids": voids,
                          "net_sales": gross - refunds - voids, "units_sold": units})
    return {"products": products, "sales": sales, "daily_summary": summaries,
            "seed": seed, "days": days}


def sql_for_demo(data: dict, business_name: str = "Demo Bar") -> str:
    q = lambda value: "'" + str(value).replace("'", "''") + "'"
    lines = ["START TRANSACTION;",
             "INSERT INTO business_metadata (metadata_id,business_name,business_type,demo_mode) "
             f"VALUES (1,{q(business_name)},'bar',1) ON DUPLICATE KEY UPDATE business_name=VALUES(business_name),demo_mode=1;"]
    for p in data["products"]:
        lines.append("INSERT INTO products (sku,name,category,cost_price,sell_price,stock_quantity) "
                     f"VALUES ({q(p['sku'])},{q(p['name'])},{q(p['category'])},{p['cost_price']},{p['sell_price']},{p['stock_quantity']}) "
                     "ON DUPLICATE KEY UPDATE name=VALUES(name),stock_quantity=VALUES(stock_quantity);")
    for s in data["sales"]:
        lines.append("INSERT INTO sales (product_id,quantity,unit_price,sale_date,imported_from,event_type,source_row_key,occurred_at) "
                     f"SELECT product_id,{s['quantity']},{s['unit_price']},{q(s['date'])},'demo',"
                     f"{q(s['event_type'])},{q(s['key'])},CONCAT({q(s['date'])},' {s['hour']:02d}:00:00') FROM products WHERE sku={q(s['sku'])} "
                     "ON DUPLICATE KEY UPDATE source_row_key=VALUES(source_row_key);")
    for summary in data["daily_summary"]:
        lines.append("INSERT INTO daily_summary (summary_date,transaction_count,gross_sales,refunds,voids,net_sales,units_sold) "
                     f"VALUES ({q(summary['date'])},{summary['transaction_count']},{summary['gross_sales']},{summary['refunds']},{summary['voids']},{summary['net_sales']},{summary['units_sold']}) "
                     "ON DUPLICATE KEY UPDATE transaction_count=VALUES(transaction_count),gross_sales=VALUES(gross_sales),"
                     "refunds=VALUES(refunds),voids=VALUES(voids),net_sales=VALUES(net_sales),units_sold=VALUES(units_sold);")
    lines += ["COMMIT;", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--end-date", type=lambda value: date.fromisoformat(value), default=date(2025, 12, 31))
    parser.add_argument("--business-name", default="Demo Bar")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = sql_for_demo(build_demo(args.seed, args.days, args.end_date), args.business_name)
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()

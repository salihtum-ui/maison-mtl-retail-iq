"""Deterministic SYNTHETIC sales, inventory and replenishment simulation for the Maison MTL Retail IQ demo.

The clean simulation is the source of truth. `raw_tables()` then injects reversible data-quality defects (duplicates,
inconsistent codes, null/negative quantities, orphan keys) that the Silver layer must remove to recover the truth.
"""
from datetime import date, datetime, timedelta
from functools import lru_cache
import math
import random

from mtl_reference import (BLACK_FRIDAY, BRANDS, CLOSED, COLD_SNAP_START, DC_CODE, DOW, END, PRODUCTS,
                              REGIONS, SEASON, SEED, START, STORES, SUPPLIERS)

DAYS = (END - START).days + 1
DATES = [START + timedelta(days=i) for i in range(DAYS)]
SELLING = [s for s in STORES if s[1] != DC_CODE]
SUPPLIER_BY_CODE = {s[1]: s for s in SUPPLIERS}


def _season_curve(values):
    """366-entry day-of-year curve linearly interpolated between mid-month anchors (cyclic)."""
    anchors = [(date(2025, m, 15).timetuple().tm_yday, v) for m, v in enumerate(values, 1)]
    anchors = [(anchors[-1][0] - 365, anchors[-1][1])] + anchors + [(anchors[0][0] + 365, anchors[0][1])]
    curve = []
    for doy in range(1, 367):
        for (d0, v0), (d1, v1) in zip(anchors, anchors[1:]):
            if d0 <= doy <= d1:
                curve.append(v0 + (v1 - v0) * (doy - d0) / (d1 - d0))
                break
    return curve


CURVES = {name: _season_curve(values) for name, values in SEASON.items()}


def closed(day):
    return (day.month, day.day) in CLOSED


def markdown(day, profile):
    """Planned markdown percentage for a product season profile on a day (known promotional calendar)."""
    pct = 0.0
    if profile in ("Winter", "FallWinter") and ((day.month == 1 and day.day >= 2) or day.month == 2):
        pct = 0.30
    if profile == "Summer" and ((day.month == 7 and day.day >= 10) or day.month == 8):
        pct = 0.40
    if profile == "Spring" and day.month == 6:
        pct = 0.30
    if day.month == 12 and day.day >= 26 and profile in ("Winter", "FallWinter", "Holiday", "HolidayPeak"):
        pct = max(pct, 0.25)
    if any(0 <= (day - bf).days <= 2 for bf in BLACK_FRIDAY):
        pct = max(pct, 0.20)
    return pct


def event_factor(day, department):
    factor = 1.0
    for bf in BLACK_FRIDAY:
        offset = (day - bf).days
        if offset in (0, 1, 2, 3):
            factor *= (2.2, 1.8, 1.5, 1.2)[offset]
    if day.month == 12:
        if 15 <= day.day <= 24:
            factor *= 1.25 if department in ("Accessories", "Home") else 1.1
        elif day.day == 26:
            factor *= 2.4
        elif day.day >= 27:
            factor *= 1.5
    return factor


def weather_factor(day, profile):
    """Unplanned demand shocks that planners could not anticipate."""
    if profile in ("Winter", "FallWinter") and day >= COLD_SNAP_START:
        ramp = min(1.0, ((day - COLD_SNAP_START).days + 1) / 8)
        return 1 + ramp * (1.05 if profile == "Winter" else 0.35)
    if profile == "Winter" and day.year == 2025 and day.month == 12:
        return 1.15
    if profile == "Summer" and day.year == 2025 and day.month == 7:
        return 1.2
    if profile == "Spring" and day.year == 2026 and day.month in (3, 4):
        return 1.1
    return 1.0


def trend(day):
    return 1.05 ** ((day - START).days / 365)


def poisson(rng, mean):
    if mean <= 0:
        return 0
    if mean > 30:
        return max(0, int(round(rng.gauss(mean, math.sqrt(mean)))))
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def store_affinity(rng):
    return {(store[1], product[0]): rng.uniform(0.8, 1.2) for store in SELLING for product in PRODUCTS}


def plan_rate(product, day):
    """Planned chain-neutral daily units for a traffic index of 1.0 (season, calendar events, markdown lift)."""
    if closed(day):
        return 0.0
    profile = product[9]
    season = CURVES[profile][day.timetuple().tm_yday - 1]
    lift = 1 + 1.4 * markdown(day, profile)
    return product[10] * season * DOW[day.weekday()] * event_factor(day, product[2]) * trend(day) * lift


def lead_time(product):
    supplier = SUPPLIER_BY_CODE[product[6]]
    return supplier[4] + (int(product[0][-1]) % 3) * 2


@lru_cache(maxsize=1)
def simulate():
    """Run the deterministic store + DC replenishment simulation and return clean source-of-truth rows."""
    rng = random.Random(SEED)
    affinity = store_affinity(rng)
    horizon = DAYS + 120
    plan = {p[0]: [plan_rate(p, START + timedelta(days=i)) for i in range(horizon)] for p in PRODUCTS}

    def window(sku, index, length):
        values = plan[sku][index:index + length]
        return sum(values) / len(values)

    store_state = {}
    for store in SELLING:
        for product in PRODUCTS:
            factor = store[11] * affinity[(store[1], product[0])]
            rate = window(product[0], 0, 7) * factor
            transfer = store[12]
            ss = max(1, math.ceil(rate * 3))
            rop = math.ceil(rate * (transfer + 2)) + ss
            out = rop + max(product[11], math.ceil(rate * 10))
            store_state[(store[1], product[0])] = {"on_hand": out, "pipeline": [], "factor": factor}
    dc_state = {}
    for product in PRODUCTS:
        chain = sum(s[11] * affinity[(s[1], product[0])] for s in SELLING)
        lt = lead_time(product)
        dc_state[product[0]] = {"on_hand": int(window(product[0], 0, lt + 14) * chain * (lt + 21)),
                                "pipeline": [], "chain": chain, "lt": lt}

    sales, inventory, orders = [], [], []
    order_seq = {"TO": 0, "PO": 0}

    def new_order(kind, day, sku, source, target, qty, arrival):
        order_seq[kind] += 1
        number = f"{kind}-{day.year}-{order_seq[kind]:06d}"
        orders.append({"order_number": number, "order_type": "Store transfer" if kind == "TO" else "Supplier PO",
                       "sku": sku, "from_location": source, "to_location": target, "order_date": day,
                       "expected_date": arrival["expected"], "received_date": arrival["actual"], "ordered_units": qty})
        return arrival["actual"]

    for index, day in enumerate(DATES):
        for product in PRODUCTS:
            sku, profile, case = product[0], product[9], product[11]
            dc = dc_state[sku]
            dc_received = sum(q for d, q in dc["pipeline"] if d == day)
            dc["pipeline"] = [(d, q) for d, q in dc["pipeline"] if d != day]
            dc["on_hand"] += dc_received
            md = markdown(day, profile)
            price = float(product[8])
            weather = weather_factor(day, profile)
            base_rate = window(sku, index + 1, 7)
            for store in SELLING:
                key = (store[1], sku)
                state = store_state[key]
                received = sum(q for d, q in state["pipeline"] if d == day)
                state["pipeline"] = [(d, q) for d, q in state["pipeline"] if d != day]
                state["on_hand"] += received
                mean = plan[sku][index] * state["factor"] * weather
                demand = 0 if mean == 0 else poisson(rng, mean * rng.gammavariate(8, 1 / 8))
                units = min(demand, state["on_hand"])
                state["on_hand"] -= units
                if units:
                    gross = round(units * price, 2)
                    discount = round(gross * md, 2)
                    sales.append((day, store[1], sku, units, gross, discount, round(gross - discount, 2), demand))
                rate = base_rate * state["factor"]
                ss = max(1, math.ceil(rate * 3))
                rop = math.ceil(rate * (store[12] + 2)) + ss
                out = rop + max(case, math.ceil(rate * 10))
                position = state["on_hand"] + sum(q for _, q in state["pipeline"])
                if position <= rop and dc["on_hand"] > 0:
                    qty = math.ceil((out - position) / case) * case
                    qty = min(qty, dc["on_hand"])
                    if qty > 0:
                        dc["on_hand"] -= qty
                        arrival = day + timedelta(days=store[12])
                        new_order("TO", day, sku, DC_CODE, store[1], qty, {"expected": arrival, "actual": arrival})
                        state["pipeline"].append((arrival, qty))
                on_order = sum(q for _, q in state["pipeline"])
                inventory.append((day, store[1], sku, state["on_hand"], on_order, received, rop, ss))
            lt = dc["lt"]
            dc_rate = window(sku, index + 1, lt + 14) * dc["chain"]
            dc_ss = math.ceil(dc_rate * 7)
            dc_rop = math.ceil(dc_rate * lt) + dc_ss
            dc_out = dc_rop + math.ceil(dc_rate * 28)
            position = dc["on_hand"] + sum(q for _, q in dc["pipeline"])
            if position <= dc_rop and dc_rate > 0:
                qty = math.ceil((dc_out - position) / (case * 10)) * case * 10
                supplier = SUPPLIER_BY_CODE[product[6]]
                expected = day + timedelta(days=lt)
                delay = 0 if rng.random() * 100 < supplier[5] else rng.randint(3, 14)
                if product[6] in ("SUP-NFC", "SUP-ABO") and date(2026, 9, 15) <= day <= date(2026, 10, 31):
                    delay += 12
                actual = expected + timedelta(days=delay)
                new_order("PO", day, sku, product[6], DC_CODE, qty, {"expected": expected, "actual": actual})
                dc["pipeline"].append((actual, qty))
            inventory.append((day, DC_CODE, sku, dc["on_hand"], sum(q for _, q in dc["pipeline"]), dc_received,
                              dc_rop, dc_ss))
    for order in orders:
        if order["received_date"] > END:
            order["received_date"] = None
            order["received_units"] = 0
            order["status"] = "In transit" if order["order_type"] == "Store transfer" else "Open"
        else:
            order["received_units"] = order["ordered_units"]
            order["status"] = "Received"
    return {"sales": sales, "inventory": inventory, "orders": orders}


def master():
    stores = [{"store_id": s[0], "store_code": s[1], "store_name": s[2], "city": s[3], "region": s[4],
               "province": "QC", "store_format": s[6], "opened_year": s[7], "selling_area_sqft": s[8],
               "latitude": s[9], "longitude": s[10], "location_type": "Distribution centre" if s[1] == DC_CODE else "Store",
               "traffic_index": s[11], "dc_transfer_days": s[12]} for s in STORES]
    suppliers = [{"supplier_id": s[0], "supplier_code": s[1], "supplier_name": s[2], "country": s[3],
                  "lead_time_days": s[4], "on_time_pct": s[5]} for s in SUPPLIERS]
    products = []
    for number, p in enumerate(PRODUCTS, 1):
        rate = plan_rate(p, END)
        ss = max(1, math.ceil(rate * 3))
        products.append({"product_id": number, "sku": p[0], "product_name": p[1], "department": p[2], "category": p[3],
                         "subcategory": p[4], "brand": p[5], "supplier_code": p[6], "unit_cost": float(p[7]),
                         "unit_price": float(p[8]), "season_profile": p[9], "case_pack": p[11],
                         "lead_time_days": lead_time(p), "reorder_point": math.ceil(rate * 4) + ss, "safety_stock": ss})
    return {"stores": stores, "suppliers": suppliers, "products": products,
            "regions": REGIONS, "brands": BRANDS}


# ----------------------------------------------------------------------------------------------------------------------
# Raw operational tables with deliberate, reversible data-quality defects
# ----------------------------------------------------------------------------------------------------------------------

COLUMNS = {
    "stores": ["store_id", "store_code", "store_name", "city", "region", "province", "store_format", "opened_year",
               "selling_area_sqft", "latitude", "longitude", "location_type", "traffic_index", "dc_transfer_days",
               "updated_at"],
    "suppliers": ["supplier_id", "supplier_code", "supplier_name", "country", "lead_time_days", "on_time_pct",
                  "updated_at"],
    "products": ["product_id", "sku", "product_name", "department", "category", "subcategory", "brand",
                 "supplier_code", "unit_cost", "unit_price", "season_profile", "case_pack", "lead_time_days",
                 "reorder_point", "safety_stock", "is_active", "updated_at"],
    "sales_daily": ["sales_id", "sale_date", "store_code", "sku", "units_sold", "gross_sales", "discount_amount",
                    "net_sales", "pos_batch_id", "loaded_at"],
    "inventory_daily": ["snapshot_id", "snapshot_date", "store_code", "sku", "on_hand_units", "on_order_units",
                        "received_units", "reorder_point_units", "safety_stock_units", "loaded_at"],
    "replenishment_orders": ["order_id", "order_number", "order_type", "sku", "from_location", "to_location",
                             "order_date", "expected_date", "received_date", "ordered_units", "received_units",
                             "status", "loaded_at"],
}

MASTER_LOADED = datetime(2026, 11, 3, 23, 0)


def std_code(value):
    return value.strip().upper().replace("_", "-") if value is not None else None


def _code_variant(rng, code):
    return rng.choice([code.lower(), " " + code + " ", code.replace("-", "_"), code.lower().replace("-", "_")])


def _loaded(day, store_code, hour=2):
    store_offset = sum(ord(c) for c in store_code) % 50
    return datetime(day.year, day.month, day.day, hour, store_offset) + timedelta(days=1)


@lru_cache(maxsize=1)
def raw_tables():
    """Return {table: list of row tuples in COLUMNS order} plus expected data-quality event counts."""
    sim, ref = simulate(), master()
    rng = random.Random(SEED + 7)
    dq = {}

    def bump(entity, rule, count=1):
        dq[(entity, rule)] = dq.get((entity, rule), 0) + count

    stores = []
    for s in ref["stores"]:
        raw_province = next(x[5] for x in STORES if x[1] == s["store_code"])
        if raw_province != "QC":
            bump("stores", "Province standardized to QC")
        stores.append(tuple([s["store_id"], s["store_code"], s["store_name"], s["city"], s["region"], raw_province,
                             s["store_format"], s["opened_year"], s["selling_area_sqft"], s["latitude"], s["longitude"],
                             s["location_type"], s["traffic_index"], s["dc_transfer_days"], MASTER_LOADED]))
    suppliers = []
    for s in ref["suppliers"]:
        country = "canada" if s["supplier_code"] == "SUP-MTM" else s["country"]
        if country != s["country"]:
            bump("suppliers", "Country name standardized")
        suppliers.append((s["supplier_id"], s["supplier_code"], s["supplier_name"], country, s["lead_time_days"],
                          s["on_time_pct"], MASTER_LOADED))
    products = []
    bad_category = {"W-OUT-102": "OUTERWEAR", "M-KNT-202": "knitwear", "H-BTH-202": "Bath ", "A-CWA-104":
                    "cold-weather accessories", "K-APP-302": " Apparel", "W-SWM-502": "SWIMWEAR"}
    bad_brand = {"M-SHT-302": "Ligne Urbaine  ", "H-DEC-302": " Maison Laurentienne", "W-DNM-402": "Twill & Co. ",
                 "A-SUN-302": "Rivage "}
    for p in ref["products"]:
        category = bad_category.get(p["sku"], p["category"])
        brand = bad_brand.get(p["sku"], p["brand"])
        if category != p["category"]:
            bump("products", "Category casing and spacing standardized")
        if brand != p["brand"]:
            bump("products", "Brand whitespace trimmed")
        products.append((p["product_id"], p["sku"], p["product_name"], p["department"], category, p["subcategory"],
                         brand, p["supplier_code"], p["unit_cost"], p["unit_price"], p["season_profile"],
                         p["case_pack"], p["lead_time_days"], p["reorder_point"], p["safety_stock"], True,
                         MASTER_LOADED))
    for number, sku in enumerate(["W-OUT-101", "A-CWA-101", "H-DEC-301"], 1001):
        p = next(x for x in ref["products"] if x["sku"] == sku)
        products.append((number, sku, p["product_name"], p["department"], p["category"], p["subcategory"], p["brand"],
                         p["supplier_code"], round(p["unit_cost"] * 0.95, 2), round(p["unit_price"] * 0.9, 2),
                         p["season_profile"], p["case_pack"], p["lead_time_days"], p["reorder_point"],
                         p["safety_stock"], True, datetime(2025, 3, 1, 9, 0)))
        bump("products", "Stale product version removed")

    sales = []
    for row in sim["sales"]:
        day, store, sku, units, gross, discount, net, _ = row
        loaded = _loaded(day, store)
        raw_store, raw_sku = store, sku
        if rng.random() < 0.025:
            raw_store = _code_variant(rng, store)
        if rng.random() < 0.015:
            raw_sku = sku.lower()
        batch = f"POS-{store}-{day:%Y%m%d}"
        sales.append([day, raw_store, raw_sku, units, gross, discount, net, batch, loaded])
        if rng.random() < 0.006:
            sales.append([day, raw_store, raw_sku, units, gross, discount, net, batch + "-R",
                          loaded + timedelta(hours=rng.randint(3, 20))])
            bump("sales_daily", "Duplicate POS resend removed")
    picks = rng.sample(range(len(sim["sales"])), 60)
    for n, index in enumerate(picks):
        day, store, sku, units, gross, discount, net, _ = sim["sales"][index]
        loaded = _loaded(day, store, hour=5)
        if n < 36:
            sales.append([day, store, sku, -units, -gross, -discount, -net, f"ADJ-{store}-{day:%Y%m%d}", loaded])
            bump("sales_daily", "Negative quantity quarantined")
        else:
            sales.append([day, store, sku, None, None, None, None, f"POS-{store}-{day:%Y%m%d}-P", loaded])
            bump("sales_daily", "Null quantity quarantined")
    for n in range(30):
        day = DATES[rng.randrange(DAYS)]
        if n < 18:
            store, sku = SELLING[n % len(SELLING)][1], ["W-OUT-999", "TEST-SKU-01", "X-PROMO-00"][n % 3]
            bump("sales_daily", "Unknown product quarantined")
        else:
            store, sku = "ZZ-TRAIN", PRODUCTS[n][0]
            bump("sales_daily", "Unknown store quarantined")
        sales.append([day, store, sku, 2, 100.0, 0.0, 100.0, f"POS-{store}-{day:%Y%m%d}", _loaded(day, store)])
    sales_rows = [tuple([i] + r) for i, r in enumerate(sales, 1)]

    inventory = []
    for row in sim["inventory"]:
        day, store, sku, on_hand, on_order, received, rop, ss = row
        loaded = _loaded(day, store, hour=3)
        raw_store = store
        if rng.random() < 0.02:
            raw_store = store.lower()
        inventory.append([day, raw_store, sku, on_hand, on_order, received, rop, ss, loaded])
        if rng.random() < 0.003:
            inventory.append([day, raw_store, sku, on_hand, on_order, received, rop, ss,
                              loaded + timedelta(hours=rng.randint(1, 6))])
            bump("inventory_daily", "Duplicate snapshot removed")
    for n, index in enumerate(rng.sample(range(len(sim["inventory"])), 48)):
        day, store, sku, on_hand, on_order, received, rop, ss = sim["inventory"][index]
        loaded = _loaded(day, store, hour=1)
        if n < 30:
            inventory.append([day, store, sku, None, on_order, received, rop, ss, loaded])
            bump("inventory_daily", "Null on-hand quarantined")
        else:
            inventory.append([day, store, sku, -rng.randint(1, 5), on_order, received, rop, ss, loaded])
            bump("inventory_daily", "Negative on-hand quarantined")
    inventory_rows = [tuple([i] + r) for i, r in enumerate(inventory, 1)]

    orders = []
    for o in sim["orders"]:
        loaded = _loaded(o["order_date"], o["to_location"], hour=4)
        target = o["to_location"]
        if rng.random() < 0.02:
            target = target.lower()
        orders.append([o["order_number"], o["order_type"], o["sku"], o["from_location"], target, o["order_date"],
                       o["expected_date"], o["received_date"], o["ordered_units"], o["received_units"], o["status"],
                       loaded])
    for index in rng.sample(range(len(sim["orders"])), 9):
        copy = list(orders[index])
        copy[-1] = copy[-1] + timedelta(hours=6)
        orders.append(copy)
        bump("replenishment_orders", "Duplicate order line removed")
    for n, index in enumerate(rng.sample(range(len(sim["orders"])), 14)):
        o = sim["orders"][index]
        orders.append([o["order_number"][:3] + "TST-" + f"{n:04d}", o["order_type"], o["sku"], o["from_location"],
                       o["to_location"], o["order_date"], o["expected_date"], o["order_date"] - timedelta(days=3),
                       o["ordered_units"], o["ordered_units"], "Received", _loaded(o["order_date"], "X")])
        bump("replenishment_orders", "Receipt before order date quarantined")
    order_rows = [tuple([i] + r) for i, r in enumerate(orders, 1)]
    standardized = {
        ("sales_daily", "Store code standardized"): sum(1 for r in sales_rows if r[2] != std_code(r[2])),
        ("sales_daily", "SKU standardized"): sum(1 for r in sales_rows if r[3] != std_code(r[3])),
        ("inventory_daily", "Location code standardized"): sum(1 for r in inventory_rows if r[2] != std_code(r[2])),
        ("replenishment_orders", "Location code standardized"):
            sum(1 for r in order_rows if r[4] != std_code(r[4]) or r[5] != std_code(r[5])),
    }
    for (entity, rule), count in standardized.items():
        bump(entity, rule, count)
    tables = {"stores": stores, "suppliers": suppliers, "products": products, "sales_daily": sales_rows,
              "inventory_daily": inventory_rows, "replenishment_orders": order_rows}
    return tables, {f"{k[0]}|{k[1]}": v for k, v in sorted(dq.items())}


# ----------------------------------------------------------------------------------------------------------------------
# Governed controls computed from the clean truth (used by Silver/Gold asserts, the model, the agent and the app)
# ----------------------------------------------------------------------------------------------------------------------

def _between(day, start, end):
    return start <= day <= end


def truth():
    sim, ref = simulate(), master()
    tables, dq = raw_tables()
    cost = {p["sku"]: p["unit_cost"] for p in ref["products"]}
    category = {p["sku"]: p["category"] for p in ref["products"]}
    store_name = {s["store_code"]: s["store_name"] for s in ref["stores"]}
    last28 = (END - timedelta(days=27), END)
    ly28 = (last28[0] - timedelta(days=364), END - timedelta(days=364))
    ytd = (date(2026, 1, 1), END)
    ly_ytd = (date(2025, 1, 1), date(2025, 11, 3))
    agg = {"net2025": 0.0, "units2025": 0, "gm2025": 0.0, "netYtd": 0.0, "netLyYtd": 0.0, "net28": 0.0,
           "netLy28": 0.0, "units28": 0, "gm28": 0.0}
    by_store, by_category = {}, {}
    for day, store, sku, units, gross, discount, net, _ in sim["sales"]:
        margin = net - units * cost[sku]
        if day.year == 2025:
            agg["net2025"] += net
            agg["units2025"] += units
            agg["gm2025"] += margin
        if _between(day, *ytd):
            agg["netYtd"] += net
        if _between(day, *ly_ytd):
            agg["netLyYtd"] += net
        if _between(day, *last28):
            agg["net28"] += net
            agg["units28"] += units
            agg["gm28"] += margin
            by_store[store] = by_store.get(store, 0) + net
            by_category[category[sku]] = by_category.get(category[sku], 0) + net
        if _between(day, *ly28):
            agg["netLy28"] += net
    end = [r for r in sim["inventory"] if r[0] == END and r[1] != DC_CODE]
    top_store = max(by_store, key=by_store.get)
    top_category = max(by_category, key=by_category.get)
    oos_by_sku = {}
    for r in end:
        if r[3] == 0:
            oos_by_sku[r[2]] = oos_by_sku.get(r[2], 0) + 1
    worst_sku = max(oos_by_sku, key=lambda k: (oos_by_sku[k], k))
    return {
        "snapshotDate": END.isoformat(),
        "rawRows": {name: len(rows) for name, rows in tables.items()},
        "silverRows": {"stores": len(ref["stores"]), "suppliers": len(ref["suppliers"]),
                       "products": len(ref["products"]), "sales_daily": len(sim["sales"]),
                       "inventory_daily": len(sim["inventory"]), "replenishment_orders": len(sim["orders"])},
        "dqEvents": dq,
        "dqAffectedRows": sum(dq.values()),
        "netSales2025": round(agg["net2025"], 2),
        "units2025": agg["units2025"],
        "grossMarginPct2025": round(100 * agg["gm2025"] / agg["net2025"], 2),
        "netSalesYtd2026": round(agg["netYtd"], 2),
        "netSalesYtd2025": round(agg["netLyYtd"], 2),
        "ytdGrowthPct": round(100 * (agg["netYtd"] / agg["netLyYtd"] - 1), 2),
        "netSalesLast28": round(agg["net28"], 2),
        "netSalesLast28LY": round(agg["netLy28"], 2),
        "last28GrowthPct": round(100 * (agg["net28"] / agg["netLy28"] - 1), 2),
        "unitsLast28": agg["units28"],
        "grossMarginPctLast28": round(100 * agg["gm28"] / agg["net28"], 2),
        "topStoreLast28": {"code": top_store, "name": store_name[top_store], "netSales": round(by_store[top_store], 2)},
        "topCategoryLast28": {"category": top_category, "netSales": round(by_category[top_category], 2)},
        "storeOnHandUnits": sum(r[3] for r in end),
        "storeOnOrderUnits": sum(r[4] for r in end),
        "dcOnHandUnits": sum(r[3] for r in sim["inventory"] if r[0] == END and r[1] == DC_CODE),
        "positions": len(end),
        "outOfStockPositions": sum(1 for r in end if r[3] == 0),
        "belowReorderPointPositions": sum(1 for r in end if r[3] < r[6]),
        "mostOutOfStockSku": {"sku": worst_sku, "stores": oos_by_sku[worst_sku]},
        "openSupplierPOs": sum(1 for o in sim["orders"] if o["order_type"] == "Supplier PO" and o["status"] == "Open"),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(truth(), indent=2, ensure_ascii=False))


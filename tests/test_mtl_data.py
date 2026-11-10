"""Prove the injected raw defects are reversible: applying the Silver rules to raw rows recovers the clean truth."""
from collections import Counter
from datetime import date
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mtl_data as d  # noqa: E402


def silver(rows, key, valid, standardize):
    kept, quarantined = {}, 0
    for row in rows:
        row = standardize(row)
        if not valid(row):
            quarantined += 1
            continue
        k = key(row)
        if k not in kept or row[-1] > kept[k][-1]:
            kept[k] = row
    return kept, quarantined


class MtlDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = d.simulate()
        cls.raw, cls.dq = d.raw_tables()
        cls.truth = d.truth()
        cls.skus = {p[0] for p in d.PRODUCTS}
        cls.stores = {s[1] for s in d.STORES}

    def test_window_and_scale(self):
        self.assertEqual(d.DAYS, 730)
        self.assertEqual(d.DATES[-1], date(2026, 11, 3))
        self.assertEqual(len(d.PRODUCTS), 60)
        self.assertEqual(len(d.SELLING), 10)
        self.assertEqual(self.truth["positions"], 600)

    def test_every_table_has_unique_primary_key(self):
        for name, rows in self.raw.items():
            keys = [r[0] for r in rows]
            self.assertEqual(len(keys), len(set(keys)), name)

    def test_sales_silver_recovers_truth(self):
        def std(r):
            return (r[0], r[1], d.std_code(r[2]), d.std_code(r[3])) + r[4:]

        def valid(r):
            return r[4] is not None and r[4] > 0 and r[3] in self.skus and r[2] in self.stores and r[2] != d.DC_CODE

        kept, quarantined = silver(self.raw["sales_daily"], lambda r: (r[1], r[2], r[3]), valid, std)
        expected = {(s[0], s[1], s[2]): s[3] for s in self.sim["sales"]}
        self.assertEqual({k: v[4] for k, v in kept.items()}, expected)
        self.assertEqual(quarantined, sum(v for k, v in self.dq.items() if k.startswith("sales_daily|")
                                          and "quarantined" in k))

    def test_inventory_silver_recovers_truth(self):
        def std(r):
            return (r[0], r[1], d.std_code(r[2]), d.std_code(r[3])) + r[4:]

        kept, _ = silver(self.raw["inventory_daily"], lambda r: (r[1], r[2], r[3]),
                         lambda r: r[4] is not None and r[4] >= 0, std)
        expected = {(s[0], s[1], s[2]): s[3] for s in self.sim["inventory"]}
        self.assertEqual({k: v[4] for k, v in kept.items()}, expected)

    def test_orders_silver_recovers_truth(self):
        def std(r):
            return r[:4] + (d.std_code(r[4]), d.std_code(r[5])) + r[6:]

        kept, quarantined = silver(self.raw["replenishment_orders"], lambda r: r[1],
                                   lambda r: r[8] is None or r[8] >= r[6], std)
        self.assertEqual(len(kept), len(self.sim["orders"]))
        self.assertEqual(quarantined, self.dq["replenishment_orders|Receipt before order date quarantined"])

    def test_cold_snap_creates_winter_stock_risk(self):
        end = [r for r in self.sim["inventory"] if r[0] == d.END and r[1] != d.DC_CODE]
        oos = Counter(r[2] for r in end if r[3] == 0)
        self.assertGreaterEqual(self.truth["outOfStockPositions"], 5)
        winter = {p[0] for p in d.PRODUCTS if p[9] == "Winter"}
        self.assertTrue(set(oos) <= winter)
        self.assertGreater(self.truth["last28GrowthPct"], 0)

    def test_dq_defects_present(self):
        for rule in ["sales_daily|Duplicate POS resend removed", "sales_daily|Negative quantity quarantined",
                     "sales_daily|Unknown product quarantined", "inventory_daily|Null on-hand quarantined",
                     "products|Stale product version removed", "stores|Province standardized to QC"]:
            self.assertGreater(self.dq[rule], 0, rule)

    def test_documented_controls(self):
        """Figures quoted in docs/ (DATA_MODEL, DEMO_NARRATIVE) come from this deterministic generator."""
        self.assertEqual(self.truth["netSalesLast28"], 3010708.0)
        self.assertEqual(self.truth["last28GrowthPct"], 21.3)
        self.assertEqual(self.truth["ytdGrowthPct"], 6.35)
        self.assertEqual(self.truth["topStoreLast28"], {"code": "MT-CV", "name": "Maison MTL Montréal Centre-Ville",
                                                        "netSales": 459997.0})
        self.assertEqual(self.truth["outOfStockPositions"], 19)
        self.assertEqual(self.truth["belowReorderPointPositions"], 95)
        self.assertEqual(self.truth["mostOutOfStockSku"], {"sku": "W-FTW-601", "stores": 7})
        self.assertEqual(self.truth["rawRows"], {"stores": 11, "suppliers": 8, "products": 63, "sales_daily": 243893,
                                                 "inventory_daily": 483268, "replenishment_orders": 27901})

    def test_fictional_store_names(self):
        selling = [s for s in d.STORES if s[1] != d.DC_CODE]
        self.assertTrue(all(s[2].startswith("Maison MTL ") for s in selling))


if __name__ == "__main__":
    unittest.main()

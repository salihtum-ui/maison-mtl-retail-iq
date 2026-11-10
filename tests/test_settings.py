"""Configuration loading and validation (no network, no Azure sign-in)."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import settings  # noqa: E402

VALID = {
    "tenantId": "11111111-1111-1111-1111-111111111111",
    "subscriptionId": "22222222-2222-2222-2222-222222222222",
    "fabric": {"capacityId": "33333333-3333-3333-3333-333333333333"},
    "sql": {"network": "public", "serverName": "sql-maison-mtl-test", "createServer": True},
}


def write(folder, value):
    path = Path(folder) / "config.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        settings.reset()

    def tearDown(self):
        os.environ.pop("MTL_CONFIG", None)
        settings.reset()
        self.tmp.cleanup()

    def test_example_is_complete_but_not_deployable(self):
        example = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        merged = settings.merge(settings.DEFAULTS, example)
        self.assertEqual(set(merged), set(settings.DEFAULTS))
        problems = " ".join(settings.errors(merged))
        for field in ("tenantId", "subscriptionId", "fabric.capacityId", "sql.serverName"):
            self.assertIn(field, problems)

    def test_valid_public_config(self):
        cfg = settings.load(write(self.tmp.name, VALID))
        self.assertEqual(cfg["sql"]["database"], "mtl_retail")
        self.assertEqual(cfg["fabric"]["workspaceName"], "Maison MTL Retail IQ")
        self.assertEqual(settings.sql_fqdn(cfg), "sql-maison-mtl-test.database.windows.net")
        self.assertEqual(settings.sql_server_id(cfg), "/subscriptions/22222222-2222-2222-2222-222222222222/resourceGroups/"
                         "rg-maison-mtl-retail-iq/providers/Microsoft.Sql/servers/sql-maison-mtl-test")
        self.assertFalse(settings.is_private(cfg))

    def test_private_mode_needs_gateway_and_existing_server(self):
        private = settings.merge(VALID, {"sql": {"network": "private"}})
        problems = " ".join(settings.errors(settings.merge(settings.DEFAULTS, private)))
        self.assertIn("privateNetwork.gatewayId", problems)
        self.assertIn("createServer", problems)
        fixed = settings.merge(private, {"sql": {"createServer": False},
                                         "privateNetwork": {"gatewayId": "44444444-4444-4444-4444-444444444444"}})
        self.assertEqual(settings.errors(settings.merge(settings.DEFAULTS, fixed)), [])

    def test_rejects_bad_values(self):
        bad = settings.merge(VALID, {"sql": {"network": "vpn", "serverName": "Bad_Name", "autoPauseDelayMinutes": 15}})
        problems = " ".join(settings.errors(settings.merge(settings.DEFAULTS, bad)))
        self.assertIn("sql.network", problems)
        self.assertIn("sql.serverName", problems)
        self.assertIn("autoPauseDelayMinutes", problems)
        with self.assertRaises(settings.ConfigError):
            settings.load(write(self.tmp.name, bad))

    def test_env_override_and_missing_file(self):
        path = write(self.tmp.name, VALID)
        os.environ["MTL_CONFIG"] = str(path)
        self.assertEqual(settings.config_path(), path)
        self.assertEqual(settings.get()["tenantId"], VALID["tenantId"])
        os.environ["MTL_CONFIG"] = str(Path(self.tmp.name) / "missing.json")
        settings.reset()
        with self.assertRaises(settings.ConfigError):
            settings.get()


if __name__ == "__main__":
    unittest.main()

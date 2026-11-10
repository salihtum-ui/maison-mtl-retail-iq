"""Safety guards, teardown planning, agent bootstrap and deploy wiring (no network, no Azure sign-in)."""
import base64
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fabric as f  # noqa: E402
import settings  # noqa: E402

WS = "aaaaaaaa-0000-0000-0000-000000000001"
OTHER = "bbbbbbbb-0000-0000-0000-000000000002"
CONN = "cccccccc-0000-0000-0000-000000000003"
ONT = "dddddddd-0000-0000-0000-000000000004"
GATEWAY = "eeeeeeee-0000-0000-0000-000000000005"
API = "https://api.fabric.microsoft.com/v1"
CONFIG = {
    "tenantId": "11111111-1111-1111-1111-111111111111",
    "subscriptionId": "22222222-2222-2222-2222-222222222222",
    "fabric": {"capacityId": "33333333-3333-3333-3333-333333333333"},
    "sql": {"network": "public", "serverName": "sql-maison-mtl-test", "createServer": True},
}
MODULES = ["settings", "fabric", "azure_sql", "spn", "mirror", "seed_loader", "medallion", "model", "report", "ontology",
           "agent", "app_sync", "deploy", "teardown"]


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_art = f.ART
        f.ART = Path(self.tmp.name) / "artifacts"
        f.ART.mkdir()
        self.configure(CONFIG)
        f.use_loader(False)
        f.allow_teardown(False)
        f.save("workspace.json", {"id": WS, "displayName": "Maison MTL Retail IQ"})

    def tearDown(self):
        f.ART = self.original_art
        f.allow_teardown(False)
        os.environ.pop("MTL_CONFIG", None)
        settings.reset()
        self.tmp.cleanup()

    def configure(self, value):
        path = Path(self.tmp.name) / "config.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        os.environ["MTL_CONFIG"] = str(path)
        settings.reset()

    def test_modules_import_without_config(self):
        os.environ["MTL_CONFIG"] = str(Path(self.tmp.name) / "missing.json")
        settings.reset()
        for name in MODULES:
            importlib.import_module(name)

    def test_writes_are_scoped_to_the_tracked_workspace(self):
        f.check_write("GET", API + "/workspaces/" + OTHER + "/items", None)
        f.check_write("POST", API + "/workspaces/" + WS + "/lakehouses", {})
        f.check_write("POST", f"https://api.powerbi.com/v1.0/myorg/groups/{WS}/datasets/x/refreshes", {})
        f.check_write("POST", API + "/workspaces", f.workspace_body())
        for method, url, body in [
            ("POST", API + "/workspaces/" + OTHER + "/lakehouses", {}),
            ("POST", f"https://api.powerbi.com/v1.0/myorg/groups/{OTHER}/datasets", {}),
            ("POST", API + "/workspaces", {"displayName": "Someone else's workspace"}),
            ("POST", "https://management.azure.com/subscriptions", {}),
            ("POST", API + "/connections", {"displayName": "Another connection"}),
        ]:
            with self.assertRaises(ValueError, msg=url):
                f.check_write(method, url, body)
        f.check_write("POST", API + "/connections", {"displayName": "Maison MTL Retail IQ - mtl_retail"})

    def test_deletes_need_an_explicit_teardown(self):
        f.save("connection.json", {"id": CONN})
        for url in (API + "/workspaces/" + WS, API + "/connections/" + CONN):
            with self.assertRaises(ValueError):
                f.check_write("DELETE", url, None)
        f.allow_teardown()
        f.check_write("DELETE", API + "/workspaces/" + WS, None)
        f.check_write("DELETE", API + "/connections/" + CONN, None)
        with self.assertRaises(ValueError):
            f.check_write("DELETE", API + "/workspaces/" + OTHER, None)

    def test_graph_writes_are_pinned(self):
        import spn
        f.save("spn.json", {"applicationObjectId": "app-object", "appId": "app-id", "displayName": "sp"})
        for endpoint, method in (("/applications/app-object", "DELETE"), ("/applications/other/addPassword", "POST"),
                                 ("/users", "POST")):
            with self.assertRaises(ValueError):
                spn.graph(endpoint, method, {})

    def test_mirror_connection_matches_network_mode(self):
        import mirror
        body = mirror.connection_body("app-id", "not-a-real-secret")
        self.assertEqual(body["connectivityType"], "ShareableCloud")
        self.assertNotIn("gatewayId", body)
        self.assertEqual(body["connectionDetails"]["parameters"][0]["value"], "sql-maison-mtl-test.database.windows.net")
        self.configure(settings.merge(CONFIG, {"sql": {"network": "private", "createServer": False},
                                               "privateNetwork": {"gatewayId": GATEWAY}}))
        body = mirror.connection_body("app-id", "not-a-real-secret")
        self.assertEqual((body["connectivityType"], body["gatewayId"]), ("VirtualNetworkGateway", GATEWAY))

    def test_teardown_plan_for_created_server(self):
        import teardown
        server = "/subscriptions/x/resourceGroups/rg-test/providers/Microsoft.Sql/servers/sql-test"
        f.save("connection.json", {"id": CONN, "displayName": "c"})
        f.save("spn.json", {"appId": "app-id", "displayName": "sp"})
        f.save("azure-sql-server.json", {"id": server, "name": "sql-test", "serverCreatedByDeploy": True,
                                         "resourceGroupCreatedByDeploy": True})
        f.save("azure-sql.json", {"id": server + "/databases/mtl_retail", "name": "mtl_retail", "createdByDeploy": True})
        actions = teardown.plan()
        self.assertEqual([a["action"] for a in actions],
                         ["delete-workspace", "delete-connection", "delete-app-registration", "delete-sql-server",
                          "delete-resource-group-if-empty", "archive-local-state"])
        self.assertEqual(actions[4]["target"], "rg-test")
        kept = [a["action"] for a in teardown.plan(keep_sql=True)]
        self.assertFalse([a for a in kept if "sql" in a or "resource-group" in a])

    def test_teardown_plan_for_existing_server(self):
        import teardown
        server = "/subscriptions/x/resourceGroups/rg-shared/providers/Microsoft.Sql/servers/shared"
        f.save("loader-workspace.json", {"id": OTHER, "displayName": "Maison MTL Seed Loader"})
        f.save("azure-sql-server.json", {"id": server, "name": "shared", "serverCreatedByDeploy": False})
        f.save("azure-sql.json", {"id": server + "/databases/mtl_retail", "name": "mtl_retail", "createdByDeploy": True})
        f.save("sql-firewall.json", {"azureServicesRuleCreatedByDeploy": False})
        actions = teardown.plan()
        self.assertEqual(actions[0]["action"], "delete-loader-workspace")
        self.assertIn("delete-sql-database", [a["action"] for a in actions])
        self.assertEqual([a["detail"] for a in actions if a["action"] == "delete-firewall-rule"], [teardown.DEPLOYER_RULE])
        self.assertNotIn("delete-sql-server", [a["action"] for a in actions])

    def test_teardown_dry_run_changes_nothing(self):
        import teardown
        refuse = mock.Mock(side_effect=AssertionError("network call during dry run"))
        with mock.patch.object(f, "request", refuse), mock.patch.object(f, "api", refuse), \
                contextlib.redirect_stdout(io.StringIO()):
            actions = teardown.main(yes=False)
        self.assertTrue(actions)
        self.assertTrue(f.exists("workspace.json"))

    def test_agent_bootstrap_adds_the_ontology_source(self):
        import agent
        import ontology
        f.save("ontology.json", {"id": ONT})
        definition = {"definition": {"parts": [f.part("Files/Config/data_agent.json", {"$schema": "x"})]}}
        calls = []

        def fake_api(endpoint, method="GET", body=None, result=True):
            calls.append((endpoint, method, body))
            return definition if endpoint.endswith("/getDefinition") else None

        with mock.patch.object(f, "api", fake_api):
            self.assertTrue(agent.ensure_ontology_source("/workspaces/" + WS + "/dataAgents/agent"))
        update = [body for endpoint, _, body in calls if endpoint.endswith("/updateDefinition")]
        self.assertEqual(len(update), 1)
        parts = {p["path"]: json.loads(base64.b64decode(p["payload"])) for p in update[0]["definition"]["parts"]}
        source = parts[f"Files/Config/draft/ontology-{ontology.NAME}/datasource.json"]
        self.assertEqual((source["artifactId"], source["workspaceId"], source["type"]), (ONT, WS, "ontology"))
        self.assertEqual(len(source["elements"]), len(ontology.ENTITIES))
        self.assertEqual({e["id"] for e in source["elements"] if e["is_selected"]}, set(agent.ONTOLOGY_ENTITIES))
        self.assertEqual(parts["Files/Config/draft/stage_config.json"]["aiInstructions"], agent.INSTRUCTIONS)

        definition["definition"]["parts"] = update[0]["definition"]["parts"]
        calls.clear()
        with mock.patch.object(f, "api", fake_api):
            self.assertFalse(agent.ensure_ontology_source("/workspaces/" + WS + "/dataAgents/agent"))
        self.assertFalse([c for c in calls if c[0].endswith("/updateDefinition")])

    def test_deploy_steps_are_ordered(self):
        import deploy
        self.assertEqual([name for name, _, _ in deploy.STEPS],
                         ["check", "spn", "sql", "workspace", "identity", "seed", "mirror", "medallion", "model",
                          "report", "ontology", "agent", "app", "evaluate"])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            deploy.main(["list"])
        self.assertIn("loop", out.getvalue())


if __name__ == "__main__":
    unittest.main()

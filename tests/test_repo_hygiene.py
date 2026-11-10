"""Repository hygiene: fictional naming only, and no environment IDs, hosts or secrets in committed files."""
import os
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "__pycache__", ".temp", "coverage"}
FORMER_CLIENT = re.compile("si" + "mons", re.I)
GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
PLACEHOLDER = "00000000-0000-0000-0000-000000000000"
ENVIRONMENT_HOSTS = re.compile(r"[a-z0-9-]+\.webapp\.fabricapps\.net|pbidedicated\.windows\.net|\.onmicrosoft\.com|"
                               r"pkgs\.visualstudio\.com|ctid=[0-9a-f]{8}", re.I)
SECRETS = re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY|AccountKey=|"
                     r"client_secret\s*[:=]\s*['\"][^'\"]{8,}|[A-Za-z0-9_~.-]{3}8Q~[A-Za-z0-9_~.-]{31,}")
LOCAL_ONLY = ["config.json", "artifacts", "app/.env.local", "app/rayfin/.env", "app/rayfin/.deployments.json",
              "app/rayfin/functions/src/fabric_config.ts"]


def fake(guid):
    """Obviously synthetic test GUIDs such as 11111111-1111-... or aaaaaaaa-0000-...-000000000001."""
    return len(set(guid[:8])) == 1


def files():
    for folder, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith("artifacts")]
        rel = Path(folder).relative_to(ROOT)
        for name in names:
            path = rel / name
            if path.as_posix() in LOCAL_ONLY:
                continue
            yield path


class RepoHygieneTest(unittest.TestCase):
    def test_no_former_client_name(self):
        hits = [str(p) for p in files() if FORMER_CLIENT.search(str(p)) or
                FORMER_CLIENT.search((ROOT / p).read_text(encoding="utf-8", errors="ignore"))]
        self.assertEqual(hits, [])

    def test_no_environment_ids_hosts_or_secrets(self):
        problems = []
        for path in files():
            text = (ROOT / path).read_text(encoding="utf-8", errors="ignore")
            problems += [f"{path}: GUID {g}" for g in set(GUID.findall(text)) if g != PLACEHOLDER and not fake(g)]
            problems += [f"{path}: host {m}" for m in set(ENVIRONMENT_HOSTS.findall(text))]
            if path.name != Path(__file__).name:
                problems += [f"{path}: secret-like value" for _ in SECRETS.findall(text)]
        self.assertEqual(problems, [])

    def test_local_files_are_ignored(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for entry in ("config.json", "artifacts/", "node_modules/", "dist/", "__pycache__/", ".env", "*.log",
                      "app/rayfin/.deployments.json", "app/rayfin/functions/src/fabric_config.ts",
                      "**/secrets.generated.*", "app/rayfin/functions/local.settings.json", ".temp/"):
            self.assertIn(entry, ignored.splitlines(), entry)


if __name__ == "__main__":
    unittest.main()

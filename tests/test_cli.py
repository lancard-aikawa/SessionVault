import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from sessionvault import config as cfgmod
from sessionvault.cli import main
from sessionvault.paths import ENV_VAULT, app_dir, as_project_dir, project_dir_name, vault_dir


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = str(Path(self.tmp.name) / "sessionvault.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_src_or_dir_is_usage_error(self):
        missing = str(Path(self.tmp.name) / "nope")
        for argv in (["backup"], ["verify"], ["import", missing]):
            with self.subTest(argv=argv):
                self.assertEqual(run(["--config", self.config, "--src", missing, "--vault", missing, *argv])[0], 2)

    def test_repair_needs_destination(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            main(["repair", "abc"])

    def test_config_set_then_show(self):
        vault = str(Path(self.tmp.name) / "v")
        self.assertEqual(run(["--config", self.config, "config", "set", "vault", vault])[0], 0)
        self.assertEqual(run(["--config", self.config, "config", "set", "retention.max_generations", "20"])[0], 0)
        code, out, _ = run(["--config", self.config, "config", "show"])
        self.assertEqual(code, 0)
        shown = json.loads(out)
        self.assertEqual(shown["retention"]["max_generations"], 20)
        self.assertEqual(shown["retention"]["min_keep"], 3)  # 既定値が残る
        with mock.patch.dict(os.environ):
            os.environ.pop(ENV_VAULT, None)
            self.assertEqual(Path(json.loads(run(["--config", self.config, "config", "show"])[1])["_effective_vault"]), Path(vault))

    def test_config_set_rejects_bad_value(self):
        code, _, err = run(["--config", self.config, "config", "set", "retention.max_age_days", "-1"])
        self.assertEqual(code, 2)
        self.assertFalse(Path(self.config).exists())

    def test_config_set_warns_when_old_vault_has_content(self):
        old = Path(self.tmp.name) / "old"
        (old / "mirror").mkdir(parents=True)
        run(["--config", self.config, "config", "set", "vault", str(old)])
        with mock.patch.dict(os.environ):
            os.environ.pop(ENV_VAULT, None)
            _, _, err = run(["--config", self.config, "config", "set", "vault", str(Path(self.tmp.name) / "new")])
        self.assertIn("自動では移しません", err)


class ConfigTest(unittest.TestCase):
    def test_load_keeps_unknown_keys_and_fills_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text('{"future": 1, "retention": {"max_age_days": 30}}', encoding="utf-8")
            cfg = cfgmod.load(p)
        self.assertEqual(cfg["future"], 1)
        self.assertEqual(cfg["retention"]["max_age_days"], 30)
        self.assertEqual(cfg["retention"]["min_keep"], 3)
        self.assertTrue(cfg["include_memory"])

    def test_null_resets_to_unlimited(self):
        cfg = cfgmod.set_value(cfgmod.DEFAULTS, "retention.max_generations", "5")
        cfg = cfgmod.set_value(cfg, "retention.max_generations", "null")
        self.assertIsNone(cfg["retention"]["max_generations"])


class PathsTest(unittest.TestCase):
    def test_order_cli_env_config_default(self):
        with mock.patch.dict(os.environ, {ENV_VAULT: "D:/env"}):
            self.assertEqual(vault_dir("C:/cli", "E:/cfg"), Path("C:/cli"))
            self.assertEqual(vault_dir(None, "E:/cfg"), Path("D:/env"))
        with mock.patch.dict(os.environ):
            os.environ.pop(ENV_VAULT, None)
            self.assertEqual(vault_dir(None, "E:/cfg"), Path("E:/cfg"))
            self.assertEqual(vault_dir(), app_dir() / "vault")

    def test_project_dir_name_matches_claude_code(self):
        # 英数字以外はすべて - になる（2026-10-01 に ~/.claude/projects の実際の名前 24 件で確かめた規則。
        # UNC パスは実際に --<サーバ>-... の名前だったものを、架空の名前に置き換えている）
        self.assertEqual(project_dir_name("C:\\Repos\\mywork\\SessionVault"), "C--Repos-mywork-SessionVault")
        self.assertEqual(project_dir_name("F:\\Repos\\My\\ssldate"), "F--Repos-My-ssldate")
        self.assertEqual(project_dir_name("//fileserver.example/share/app_1"), "--fileserver-example-share-app-1")
        self.assertEqual(as_project_dir("C--Repos-x"), "C--Repos-x")
        self.assertEqual(as_project_dir("C:/Repos/x_y"), "C--Repos-x-y")

    def test_app_dir_is_repo_root_when_not_frozen(self):
        self.assertTrue((app_dir() / "pyproject.toml").is_file())


if __name__ == "__main__":
    unittest.main()

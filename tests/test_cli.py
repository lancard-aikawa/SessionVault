import unittest
from pathlib import Path

from sessionvault.cli import main
from sessionvault.paths import ENV_VAULT, vault_dir


class CliTest(unittest.TestCase):
    def test_subcommands_parse(self):
        for argv in (["backup"], ["verify", "--json"], ["repair", "abc", "--out", "x.jsonl"], ["restore", "abc"]):
            with self.subTest(argv=argv):
                self.assertEqual(main(argv), 2)  # まだ未実装

    def test_repair_needs_destination(self):
        with self.assertRaises(SystemExit):
            main(["repair", "abc"])


class PathsTest(unittest.TestCase):
    def test_cli_value_wins(self):
        self.assertEqual(vault_dir("C:/v"), Path("C:/v"))

    def test_env_then_default(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {ENV_VAULT: "D:/vault"}):
            self.assertEqual(vault_dir(), Path("D:/vault"))
        with mock.patch.dict(os.environ):
            os.environ.pop(ENV_VAULT, None)
            self.assertEqual(vault_dir().name, ".sessionvault")


if __name__ == "__main__":
    unittest.main()

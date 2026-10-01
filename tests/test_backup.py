import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sessionvault import backup, prune
from sessionvault.cli import main
from sessionvault.config import DEFAULTS
from sessionvault.vault import Vault, long_path, ts

T0 = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
SID = "11111111-2222-3333-4444-555555555555"


def line(uuid, parent=None):
    return json.dumps({"type": "user", "uuid": uuid, "parentUuid": parent}) + "\n"


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self.src = root / "projects"
        self.vault = Vault(root / "vault")
        self.proj = self.src / "C--work-demo"
        self.proj.mkdir(parents=True)
        self.session = self.proj / f"{SID}.jsonl"

    def tearDown(self):
        shutil.rmtree(long_path(Path(self.tmp.name)))  # 260 文字を超える木も消す
        self.tmp.cleanup()

    def write(self, path: Path, text: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def append(self, path: Path, text: str):
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def run_backup(self, now=T0, cfg=DEFAULTS):
        return backup.run(self.src, self.vault.root, cfg, now)

    def mirror(self, rel):
        return self.vault.mirror / "C--work-demo" / rel

    def gens(self):
        return sorted(p.relative_to(self.vault.generations).as_posix()
                      for p in self.vault.generations.rglob("*") if p.is_file())

    def logs(self):
        out = []
        for f in sorted(self.vault.log_dir.glob("*.jsonl")):
            with open(f, encoding="utf-8") as fh:
                out += [json.loads(x) for x in fh]
        return out

    def test_targets_follow_design_table(self):
        self.write(self.session, line("a"))
        sd = self.proj / SID
        self.write(sd / "subagents" / "agent-x.jsonl", line("s"))
        self.write(sd / "subagents" / "agent-x.meta.json", "{}")
        self.write(sd / "tool-results" / "r1.txt", "big")
        self.write(sd / "auto-mode-classifier-error.txt", "diag")
        self.write(self.proj / "memory" / "MEMORY.md", "- x")
        self.write(self.proj / "sessions-index.json", "{}")
        rels = sorted(t.rel for t in backup.iter_targets(self.src))
        self.assertEqual(rels, [f"{SID}.jsonl", f"{SID}/subagents/agent-x.jsonl",
                                f"{SID}/subagents/agent-x.meta.json", f"{SID}/tool-results/r1.txt",
                                "memory/MEMORY.md"])
        self.assertNotIn("memory/MEMORY.md", [t.rel for t in backup.iter_targets(self.src, include_memory=False)])

    def test_new_then_unchanged_then_grow(self):
        self.write(self.session, line("a"))
        self.assertEqual(self.run_backup().counts, {"new": 1})
        self.assertEqual(self.run_backup().counts, {})
        self.append(self.session, line("b", "a"))
        self.assertEqual(self.run_backup().counts, {"grow": 1})
        self.assertEqual(self.mirror(f"{SID}.jsonl").read_bytes(), self.session.read_bytes())
        self.assertEqual(self.gens(), [])
        self.assertEqual([e["kind"] for e in self.logs()], ["new", "grow"])

    def test_shrunk_source_pushes_old_mirror_to_generation(self):
        self.write(self.session, line("a") + line("b", "a"))
        self.run_backup()
        good = self.session.read_bytes()
        self.write(self.session, line("a"))  # 途中で切れた
        r = self.run_backup(T0 + timedelta(hours=1))
        self.assertEqual(r.counts, {"diverge": 1})
        stamp = ts(T0 + timedelta(hours=1))
        self.assertEqual(self.gens(), [f"C--work-demo/{SID}.jsonl@{stamp}"])
        self.assertEqual((self.vault.generations / "C--work-demo" / f"{SID}.jsonl@{stamp}").read_bytes(), good)
        self.assertEqual(self.logs()[-1]["generation"], f"generations/C--work-demo/{SID}.jsonl@{stamp}")

    def test_rewritten_prefix_is_diverge_even_if_longer(self):
        self.write(self.session, line("a"))
        self.run_backup()
        self.write(self.session, line("X") + line("b"))
        self.assertEqual(self.run_backup().counts, {"diverge": 1})

    def test_incomplete_last_line_is_not_copied(self):
        self.write(self.session, line("a") + '{"type": "us')
        self.run_backup()
        self.assertEqual(self.mirror(f"{SID}.jsonl").read_text(encoding="utf-8"), line("a"))
        # 書き終わったら grow として追いつく
        self.write(self.session, line("a") + line("b", "a"))
        self.assertEqual(self.run_backup().counts, {"grow": 1})

    def test_only_partial_line_is_skipped(self):
        self.write(self.session, '{"type"')
        self.assertEqual(self.run_backup().counts, {})
        self.assertFalse(self.mirror(f"{SID}.jsonl").exists())

    def test_memory_change_always_makes_generation(self):
        mem = self.proj / "memory" / "note.md"
        self.write(mem, "v1")
        self.run_backup()
        self.write(mem, "v1 and more")  # 先頭が一致しても上書きにしない
        self.assertEqual(self.run_backup(T0 + timedelta(minutes=1)).counts, {"change": 1})
        self.assertEqual(len(self.gens()), 1)

    def test_same_second_generations_do_not_collide(self):
        mem = self.proj / "memory" / "note.md"
        for i in range(3):
            self.write(mem, f"v{i}")
            os.utime(mem, (1_000_000 + i, 1_000_000 + i))
            self.run_backup()
        self.assertEqual(len(self.gens()), 2)

    def test_same_content_new_mtime_is_quiet(self):
        self.write(self.session, line("a"))
        self.run_backup()
        os.utime(self.session, (2_000_000_000, 2_000_000_000))
        self.assertEqual(self.run_backup().counts, {})
        self.assertEqual(self.mirror(f"{SID}.jsonl").stat().st_mtime_ns, self.session.stat().st_mtime_ns)

    def test_src_missing_logged_once_and_mirror_kept(self):
        self.write(self.session, line("a"))
        self.run_backup()
        self.session.unlink()
        self.assertEqual(self.run_backup().counts, {"src-missing": 1})
        self.assertEqual(self.run_backup().counts, {})
        self.assertTrue(self.mirror(f"{SID}.jsonl").exists())

    def test_project_case_variation_goes_to_existing_mirror(self):
        self.write(self.session, line("a"))
        self.run_backup()
        other = self.src / "c--work-demo-memonly"  # 別プロジェクトは別のまま
        self.write(other / "memory" / "m.md", "x")
        self.run_backup()
        if os.path.normcase("A") == "a":
            return  # Windows では同じフォルダになるので綴り違いの木を作れない
        lower = self.src / "c--work-demo"
        self.write(lower / "memory" / "m.md", "x")
        self.run_backup()
        self.assertTrue(self.mirror("memory/m.md").exists())

    @unittest.skipUnless(sys.platform == "win32", "260 文字の制限は Windows だけ")
    def test_paths_longer_than_max_path(self):
        rel = f"{SID}/tool-results/" + "r" * 100 + ".txt"
        self.write(Path(long_path(self.proj)) / rel, "x")
        deep = Path(self.tmp.name) / ("d" * 120) / "vault"
        r = backup.run(self.src, deep, DEFAULTS, T0)
        self.assertEqual((r.counts, r.errors), ({"new": 1}, []))
        self.write(Path(long_path(self.proj)) / rel, "y")
        r = backup.run(self.src, deep, DEFAULTS, T0)
        self.assertEqual((r.counts, r.errors), ({"change": 1}, []))

    def test_vault_format_too_new_is_refused(self):
        self.vault.root.mkdir(parents=True)
        (self.vault.root / "vault.json").write_text('{"format": 99}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_backup()

    def test_cli_backup(self):
        self.write(self.session, line("a"))
        out, err = io.StringIO(), io.StringIO()
        cfg = Path(self.tmp.name) / "none.json"
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--config", str(cfg), "--src", str(self.src), "--vault", str(self.vault.root), "backup"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("new 1", out.getvalue())


class PruneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.vault = Vault(Path(self.tmp.name))
        d = self.vault.generations / "P" / "memory"
        d.mkdir(parents=True)
        # 10 日おきに 6 世代（0 が最新）
        self.files = []
        for i in range(6):
            f = d / f"m.md@{ts(T0 - timedelta(days=10 * i))}"
            f.write_text(str(i), encoding="utf-8")
            self.files.append(f)
        (d / "other.md@" "20200101T000000Z").write_text("o", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, **ret):
        return prune.plan(self.vault, {"max_generations": None, "max_age_days": None, "min_keep": 3, **ret}, T0)

    def test_default_deletes_nothing(self):
        self.assertEqual(self.plan(), [])

    def test_max_generations(self):
        self.assertEqual(self.plan(max_generations=4), sorted(self.files[4:]))

    def test_max_age_respects_min_keep(self):
        # 15 日より古いのは 2..5 と other。min_keep=3 なので m.md は 3..5、other は 1 つしかないので残る
        self.assertEqual(self.plan(max_age_days=15), sorted(self.files[3:]))
        self.assertEqual(self.plan(max_age_days=15, min_keep=1), sorted(self.files[2:]))

    def test_run_deletes_and_logs(self):
        deleted = prune.run(self.vault, {"max_generations": 3, "min_keep": 0}, T0)
        self.assertEqual(len(deleted), 3)
        self.assertFalse(any(f.exists() for f in self.files[3:]))
        self.assertTrue(any(self.vault.log_dir.glob("*.jsonl")))

    def test_dry_run_keeps_files(self):
        self.assertEqual(len(prune.run(self.vault, {"max_generations": 3, "min_keep": 0}, T0, dry_run=True)), 3)
        self.assertTrue(all(f.exists() for f in self.files))


if __name__ == "__main__":
    unittest.main()

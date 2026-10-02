"""窓を出さずに SessionVault を動かすための起動役（scripts/register-task.ps1 が使う）

uv 0.11 の .venv\\Scripts\\pythonw.exe は python.exe と同じコンソール用の起動役で、黒い窓が開く。
そこで本体の Python の pythonw.exe（.venv\\pyvenv.cfg の home）でこのファイルを動かす。
SessionVault は標準ライブラリしか使わないので、src を読み込み先に足せば .venv は要らない。

  <home>\\pythonw.exe scripts\\sessionvault-launch.py backup
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sessionvault.cli import main  # noqa: E402

sys.exit(main())

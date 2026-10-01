"""PyInstaller の入口。exe では sessionvault.exe <サブコマンド> として動く"""
import sys

from sessionvault.cli import main

sys.exit(main())

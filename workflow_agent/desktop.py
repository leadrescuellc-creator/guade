# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from .storage import Ledger


URL = "http://127.0.0.1:8765"


def launch() -> None:
    request = urllib.request.Request(f"{URL}/api/status")
    try:
        urllib.request.urlopen(request, timeout=1).close()
    except (urllib.error.URLError, TimeoutError):
        log = Ledger().home / "dashboard.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        stream = log.open("a", encoding="utf-8")
        root = Path(__file__).resolve().parent.parent
        subprocess.Popen(
            [sys.executable, "-m", "workflow_agent", "dashboard"],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
        stream.close()
        for _ in range(80):
            time.sleep(0.25)
            try:
                urllib.request.urlopen(request, timeout=1).close()
                break
            except (urllib.error.URLError, TimeoutError):
                continue
        else:
            raise SystemExit(f"GUADE did not start. Check {log} for details.")

    browser = next((shutil.which(name) for name in ("chromium", "chromium-browser", "google-chrome") if shutil.which(name)), None)
    if browser:
        subprocess.Popen([browser, f"--app={URL}", "--no-first-run"], start_new_session=True)
    else:
        webbrowser.open(URL)

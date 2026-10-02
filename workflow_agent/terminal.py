# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import os
import queue
import subprocess
import threading
from pathlib import Path
from typing import Any


class LocalTerminal:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()
        self.process: subprocess.Popen[bytes] | None = None
        self.master_fd: int | None = None
        self.output: queue.Queue[str] = queue.Queue()
        self.reader: threading.Thread | None = None

    def start(self) -> None:
        if os.name != "posix":
            raise RuntimeError("The embedded PTY terminal currently requires Linux or macOS.")
        import pty

        master_fd, slave_fd = pty.openpty()
        env = os.environ.copy()
        env.update({"TERM": "xterm-256color", "PS1": "\\[\\e[32m\\]GUADE\\[\\e[0m\\]:\\w$ ", "PAGER": "cat", "GIT_PAGER": "cat"})
        try:
            self.process = subprocess.Popen(
                ["/bin/bash", "--noprofile", "--norc", "-i"],
                cwd=self.cwd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=env,
                close_fds=True,
            )
        except OSError:
            os.close(master_fd)
            os.close(slave_fd)
            raise
        os.close(slave_fd)
        self.master_fd = master_fd
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def send(self, value: str) -> None:
        if not self.process or self.process.poll() is not None or self.master_fd is None:
            raise RuntimeError("This terminal session has ended. Start a new terminal session.")
        if not value or len(value) > 8192 or "\x00" in value:
            raise ValueError("Enter terminal input up to 8,192 characters.")
        os.write(self.master_fd, value.encode("utf-8"))

    def read(self) -> dict[str, Any]:
        parts = []
        while True:
            try:
                parts.append(self.output.get_nowait())
            except queue.Empty:
                break
        return {"output": "".join(parts), "closed": not self.process or self.process.poll() is not None}

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

    def _read_loop(self) -> None:
        import select

        assert self.master_fd is not None
        while self.process and self.process.poll() is None:
            try:
                ready, _, _ = select.select([self.master_fd], [], [], 0.2)
                if ready:
                    data = os.read(self.master_fd, 8192)
                    if not data:
                        return
                    self.output.put(data.decode("utf-8", errors="replace"))
            except (OSError, ValueError):
                return

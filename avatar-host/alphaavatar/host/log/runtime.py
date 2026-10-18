# Copyright 2026 AlphaAvatar project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import json
import logging
import os
import secrets
import select
import shutil
import socket
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import asdict, replace
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

from alphaavatar.core.log.client import LogClient
from alphaavatar.core.log.events import LABELS, safe_fields
from alphaavatar.core.log.records import LOG_ENDPOINT_ENV, MAX_PACKET_BYTES, LogEntry, Redactor
from alphaavatar.host.version import __version__

from .banner import render_banner
from .config import LogConfig
from .format import console_lines, use_color


class _FileSink(RotatingFileHandler):
    failures = 0

    def _open(self):
        def private_file(path: str, flags: int) -> int:
            return os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), 0o600)

        return open(
            self.baseFilename,
            self.mode,
            encoding=self.encoding,
            errors=self.errors,
            opener=private_file,
        )

    def handleError(self, record: logging.LogRecord) -> None:
        # The stdlib fallback can dump the failed record and arguments to stderr.
        self.failures += 1


class HostLog:
    """One private datagram receiver and one writer; never write files on the realtime loop."""

    def __init__(self, *, devmode: bool, stream: TextIO | None = None) -> None:
        if os.name != "posix":
            raise RuntimeError("Native Host logging requires a POSIX local socket")
        self._devmode, self._stream = devmode, stream if stream is not None else sys.stderr
        self._config = LogConfig()
        self._color = False
        self._redact = Redactor()
        self._active = False
        self._closed = False
        self._stop = threading.Event()
        self._finished = threading.Event()
        self._lock = threading.Lock()
        self._file: _FileSink | None = None
        self._early: deque[LogEntry] = deque(maxlen=256)
        self._early_dropped = 0
        self._received = self._invalid = self._reported_dropped = self._sink_failures = 0
        self._failure: BaseException | None = None
        self._saved_endpoint = os.environ.get(LOG_ENDPOINT_ENV)
        self._directory = tempfile.mkdtemp(prefix="alphaavatar-log-")
        self._path = str(Path(self._directory) / "events.sock")
        self._token = secrets.token_hex(32)
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.file_path: Path | None = None
        self._thread: threading.Thread | None = None
        self._client: LogClient | None = None
        try:
            self._socket.bind(self._path)
            self._socket.setblocking(False)
            self._client = LogClient(
                self._path,
                self._token,
                level=logging.DEBUG if devmode else logging.INFO,
                third_party_level=logging.INFO,
            )
            self._export()
            self._thread = threading.Thread(
                target=self._listen, name="host-log-writer", daemon=True
            )
            self._thread.start()
        except BaseException:
            if self._client is not None:
                self._client.close()
            self._socket.close()
            shutil.rmtree(self._directory)
            self._restore_endpoint()
            raise

    @property
    def active(self) -> bool:
        return self._active

    def _conversation(self) -> dict:
        config = self._config.conversation
        return {
            "enabled": config.enabled,
            "content": config.content == "all" or (config.content == "dev" and self._devmode),
            "max_chars": config.max_chars,
        }

    def _export(self) -> None:
        level = self._config.level or ("DEBUG" if self._devmode else "INFO")
        self._endpoint = json.dumps(
            {
                "path": self._path,
                "token": self._token,
                "level": getattr(logging, level),
                "third_party_level": getattr(logging, self._config.third_party_level),
                "conversation": self._conversation(),
            },
            separators=(",", ":"),
        )
        os.environ[LOG_ENDPOINT_ENV] = self._endpoint

    def refresh_secrets(self) -> None:
        with self._lock:
            self._redact.refresh()
        assert self._client is not None
        self._client.refresh()

    def activate(self, config: LogConfig | None = None, *, workspace: str | None = None) -> None:
        if self._active:
            return
        config = config or LogConfig(file=False)
        sink = None
        if config.file and workspace is not None:
            root = (
                Path(config.directory).expanduser()
                if config.directory
                else Path(workspace) / ".logs" / "host"
            )
            root = root.resolve()
            root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            self.file_path = root / f"alphaavatar-{stamp}-{os.getpid()}.jsonl"
            # Unique, private file; only this Host writer rotates it. No shared multi-process file.
            fd = os.open(self.file_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            sink = _FileSink(
                self.file_path,
                maxBytes=config.rotate_bytes,
                backupCount=config.backup_count,
                encoding="utf-8",
                delay=True,
            )
            sink.setFormatter(logging.Formatter("%(message)s"))
        with self._lock:
            self._config, self._file = config, sink
            self._color = use_color(config.color, self._stream)
            self._export()
            assert self._client is not None
            self._client.refresh(
                level=getattr(logging, config.level or ("DEBUG" if self._devmode else "INFO")),
                third_party_level=getattr(logging, config.third_party_level),
                conversation=self._conversation(),
            )
            if config.banner:
                encoding = getattr(self._stream, "encoding", "utf-8") or "utf-8"
                try:
                    "█".encode(encoding)
                    unicode = True
                except (LookupError, UnicodeError):
                    unicode = False
                columns = 0
                if getattr(self._stream, "isatty", lambda: False)():
                    try:
                        columns = os.get_terminal_size(self._stream.fileno()).columns
                    except (AttributeError, OSError, ValueError):
                        columns = 100
                banner = render_banner(
                    __version__,
                    devmode=self._devmode,
                    color=self._color,
                    unicode=unicode,
                    columns=columns,
                )
                self._stream.write(banner)
                self._stream.flush()
            self._active = True
            if self._early_dropped:
                text = f"Startup log buffer dropped {self._early_dropped} records"
                self._write(self._notice(text))
            for entry in self._early:
                self._write(entry)
            self._early.clear()
        if self.file_path is not None:
            logging.getLogger(__name__).info("Diagnostic log file=%s", str(self.file_path))
        if config.conversation.enabled:
            logging.getLogger(__name__).info(
                "Conversation diagnostics enabled text=%s file_content=%s max_chars=%d; "
                "generated text is not a delivery receipt",
                self._conversation()["content"],
                config.conversation.file_content,
                config.conversation.max_chars,
            )

    @staticmethod
    def _notice(text: str) -> LogEntry:
        return LogEntry(
            time.time(),
            logging.WARNING,
            "alphaavatar.host.log",
            "host/log/runtime.py",
            0,
            os.getpid(),
            "MainProcess",
            text,
        )

    def _write(self, entry: LogEntry) -> None:
        content, truncated = entry.content, entry.content_truncated
        if entry.event is not None:
            policy = self._conversation()
            if not policy["enabled"]:
                return
            if not policy["content"]:
                content, truncated = None, False
            elif content is not None:
                content = self._redact(content)
                truncated = truncated or len(content) > policy["max_chars"]
                content = content[: policy["max_chars"]]
        entry = replace(
            entry,
            text=LABELS[entry.event]
            if entry.event
            else self._redact(entry.text, logger=entry.logger),
            fields=safe_fields(entry.fields, self._redact),
            content=content,
            content_truncated=truncated,
        )
        try:
            self._stream.write(console_lines(entry, color=self._color))
            self._stream.flush()
        except (OSError, ValueError, UnicodeError):
            self._sink_failures += 1
        if self._file is not None:
            saved = (
                entry
                if self._config.conversation.file_content
                else replace(entry, content=None, content_truncated=False)
            )
            payload = json.dumps(asdict(saved), ensure_ascii=False, allow_nan=False)
            record = logging.LogRecord("alphaavatar.log", entry.level, "", 0, payload, (), None)
            self._file.handle(record)

    def _receive(self, payload: bytes) -> None:
        try:
            entry = LogEntry.decode(payload, self._token)
        except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError):
            self._invalid += 1
            return
        self._received += 1
        with self._lock:
            entries = [entry]
            if entry.dropped:
                self._reported_dropped += entry.dropped
                text = f"Diagnostic log transport dropped={entry.dropped} producer_pid={entry.pid}"
                entries.insert(0, self._notice(text))
            for item in entries:
                if self._active:
                    self._write(item)
                else:
                    if len(self._early) == self._early.maxlen:
                        self._early_dropped += 1
                    self._early.append(item)

    def _listen(self) -> None:
        try:
            while True:
                readable, _, _ = select.select((self._socket,), (), (), 0.05)
                if readable:
                    # Drain a bounded batch so a noisy producer cannot prevent shutdown checks.
                    for _ in range(256):
                        try:
                            payload = self._socket.recv(MAX_PACKET_BYTES + 1)
                        except BlockingIOError:
                            break
                        self._receive(payload)
                elif self._stop.is_set():
                    break
        except BaseException as error:
            self._failure = error
        finally:
            try:
                if self._file is not None:
                    self._file.close()
            except Exception as error:
                self._failure = self._failure or error
            finally:
                self._socket.close()
                shutil.rmtree(self._directory, ignore_errors=True)
                self._finished.set()

    def _restore_endpoint(self) -> None:
        if os.environ.get(LOG_ENDPOINT_ENV) != getattr(self, "_endpoint", None):
            return
        if self._saved_endpoint is None:
            os.environ.pop(LOG_ENDPOINT_ENV, None)
        else:
            os.environ[LOG_ENDPOINT_ENV] = self._saved_endpoint

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        errors: list[Exception] = []
        if not self._active:
            try:
                self.activate()
            except Exception as error:
                errors.append(error)
        assert self._client is not None
        self._client.close()
        self._restore_endpoint()
        self._stop.set()
        if self._thread is not None:
            deadline = time.monotonic() + self._config.shutdown_timeout
            while not self._finished.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Diagnostic log writer did not drain before its deadline")
                try:
                    self._finished.wait(remaining)
                except KeyboardInterrupt:
                    # Only diagnostic draining remains; a repeated Ctrl+C cannot abandon it.
                    continue
            self._thread.join(0)
        if self._failure is not None:
            failure = RuntimeError("Diagnostic log writer failed")
            failure.__cause__ = self._failure
            errors.append(failure)
        if self._sink_failures or (self._file is not None and self._file.failures):
            errors.append(RuntimeError("Diagnostic log sink failed; some records were not written"))
        if errors:
            raise ExceptionGroup("Host logging cleanup failed", errors)

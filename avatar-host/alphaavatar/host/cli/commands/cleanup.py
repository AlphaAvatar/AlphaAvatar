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
"""`alphaavatar cleanup`: what upgrades and setups leave in this Linux installation, removed.

``--dry-run`` lists the environments and builds cleanup removes, the space they take, and what
stays and why, changing nothing. Otherwise they are removed under the installation's lock, the
environments first. Only the prefix's envs/ and versions/ change; the application home, with
configurations, credentials, workspaces and the model cache, never does. The lock keeps other
installations out, not a running Host: `alphaavatar start` of this installation stops first.
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path
from typing import Any

from alphaavatar.host.cli.render import STATUS, Report, home_relative


def _interrupt(signum: int, frame: Any) -> None:
    raise SystemExit(128 + signum)


def _installation():
    from alphaavatar.host.tools.setup.environment import Installation, SetupError

    try:
        return Installation.running()
    except SetupError:
        raise SetupError(
            "cleanup removes what upgrades leave in an AlphaAvatar package install.sh "
            f"installed; {sys.base_prefix} is not one"
        ) from None


def _apart(out: Report, started: int) -> None:
    """A blank line after what the steps printed, before the result on stderr."""
    if out.lines > started:
        out.write()


def _listed(out: Report, heading: str, rows: list[tuple[str, str]]) -> None:
    if rows:
        out.heading(heading)
        column = out.column([label for label, _ in rows])
        for label, value in rows:
            out.row(label, value, column=column)


def cleanup(args: argparse.Namespace) -> int:
    # SIGTERM and SIGHUP unwind like Ctrl-C: what is being removed stays in its marked stage.
    handlers = {
        signum: signal.signal(signum, _interrupt) for signum in (signal.SIGTERM, signal.SIGHUP)
    }
    try:
        return _cleanup(args)
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def _cleanup(args: argparse.Namespace) -> int:
    from alphaavatar.host.configs import application_paths, format_failure
    from alphaavatar.host.configs.credentials import load_env_file
    from alphaavatar.host.tools.cleanup.cleanup import Entry, Survey, cleanup, survey
    from alphaavatar.host.tools.setup.environment import SetupError, megabytes

    out, errors = Report(), Report(sys.stderr)
    out.title("Cleanup")
    out.write()
    started = out.lines
    installation = None
    gone: list[Entry] = []

    def relative(path: Path) -> str:
        return str(path.relative_to(installation.prefix))

    def surveyed(found: Survey) -> None:
        summary = f"{len(found.removable)} to remove · {megabytes(found.size)}"
        out.step(1, "Survey", f"{summary} · {len(found.kept)} kept")
        if found.removable and not args.dry_run:
            out.begin(2, "Remove")

    def removed(entry: Entry) -> None:
        gone.append(entry)
        out.progress(f"Removed {relative(entry.path)}")

    def done() -> str:
        size = megabytes(sum(entry.size for entry in gone))
        return f"removed {len(gone)} first, {size}" if gone else "nothing was removed"

    try:
        installation = _installation()
        load_env_file()  # The home start would use: ALPHAAVATAR_HOME may come from the .env.
        paths = application_paths()
        keep = (paths.root, paths.cache.root)  # Never removed, nor anything around them.
        out.begin(1, "Survey")
        if args.dry_run:
            found = survey(installation, keep=keep)
            surveyed(found)
        else:
            found = cleanup(installation, keep=keep, surveyed=surveyed, removed=removed)
            if found.removable:
                out.step(2, "Remove", f"{len(gone)} removed · {megabytes(found.size)}")
        base = installation.current_base()
    except (KeyboardInterrupt, SystemExit) as stop:
        _apart(out, started)
        stopped = "Interrupted" if isinstance(stop, KeyboardInterrupt) else "Stopped"
        errors.status("WARN", f"{stopped}; {done()}")
        if not args.dry_run:
            errors.note(
                "What was being removed is in a marked stage of envs/ or versions/; the next "
                "cleanup or installation removes it.",
                indent=STATUS,
            )
        errors.write()
        if isinstance(stop, KeyboardInterrupt):
            return 130
        return stop.code if isinstance(stop.code, int) else 1
    except SetupError as error:
        _apart(out, started)
        errors.status("FAIL", f"Cleanup failed; {done()}")
        errors.verbatim(str(error), indent=STATUS)
        errors.write()
        return 1
    except Exception as error:
        _apart(out, started)
        errors.status("FAIL", f"Cleanup failed; {done()}")
        errors.verbatim(format_failure(error))
        errors.write()
        return 2
    width = max([len(megabytes(entry.size)) for entry in found.removable] or [0])
    out.write()
    facts = {"Prefix": home_relative(installation.prefix)}
    facts["Current"] = relative(found.current) + (f" · AlphaAvatar {base}" if base else "")
    column = out.column(list(facts))
    for key, value in facts.items():
        out.row(key, value, column=column)
    _listed(
        out,
        "Would remove" if args.dry_run else "Removed",
        [
            (relative(entry.path), f"{megabytes(entry.size):>{width}} · {entry.what}")
            for entry in found.removable
        ],
    )
    _listed(out, "Kept", [(relative(entry.path), entry.kept or "") for entry in found.kept])
    out.write()
    size = megabytes(found.size)
    if not found.removable:
        out.status("OK", "Nothing to remove")
    elif args.dry_run:
        out.status("OK", f"Would free {size}; nothing was removed")
        out.heading("Next")
        out.note("With every `alphaavatar start` of this installation stopped:", indent=2)
        out.command("alphaavatar cleanup")
    else:
        out.status("OK", f"Freed {size}")
    out.write()
    return 0

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
"""`alphaavatar upgrade`: this Linux installation to another build, switched to once checked.

``--check`` reads the current build and the target's, and changes nothing. Otherwise the
target's package is verified and unpacked beside the current version and, when setup made the
environment current runs, the default bundle's environment is planned by the target, installed
beside it and checked; current then switches once. The default bundle and its credentials are
read under the installation's lock, not here. A failure or signal before that leaves what a
person uses as it was, and says what current runs on stderr. Nothing here starts a session,
runner or model, nor writes to the application home; ``alphaavatar cleanup`` removes what the
previous build leaves.
"""

from __future__ import annotations

import argparse
import os
import shlex
import signal
import sys
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
            "upgrade replaces an AlphaAvatar package install.sh installed; "
            f"{sys.base_prefix} is not one. In a checkout, `git pull` and "
            "`uv sync --all-packages --locked` update it"
        ) from None


def _source(args: argparse.Namespace):
    from alphaavatar.host.tools.upgrade.upgrade import package_file, release

    if args.file is not None:
        return package_file(args.file, sha256=args.sha256, artifacts=args.artifacts)
    return release(args.version, sha256=args.sha256, artifacts=args.artifacts)


def _again(args: argparse.Namespace) -> str:
    """The upgrade --check looked for."""
    words = ["alphaavatar", "upgrade"]
    for option in ("version", "file", "sha256", "artifacts"):
        if (value := getattr(args, option)) is not None:
            words += [f"--{option}", value]
    return shlex.join(words)


def _check(args: argparse.Namespace, installation, out: Report) -> int:
    from alphaavatar.host.tools.upgrade.upgrade import compare, current_manifest, inspect

    current = current_manifest(installation)
    source = _source(args)
    target = inspect(source)
    verdict = compare(current, target)
    out.status(
        *{
            "current": ("OK", f"The target is current already: AlphaAvatar {current['id']}"),
            "upgrade": ("OK", f"Upgradable to AlphaAvatar {target['id']}"),
            "older": ("WARN", f"Not an upgrade: AlphaAvatar {target['version']} is older"),
        }[verdict]
    )
    facts = {"Current": current["id"], "Target": target["id"], "From": str(source.package)}
    column = out.column(list(facts))
    for key, value in facts.items():
        out.row(key, value, indent=STATUS, column=column)
    if verdict == "upgrade":
        out.heading("Next")
        out.command(_again(args))
    out.write()
    return 0


def _apart(out: Report, started: int) -> None:
    """A blank line after what the steps printed, before the result on stderr."""
    if out.lines > started:
        out.write()


def _outcome(installation, before: str | None) -> str:
    """What current runs as the upgrade ends, as the disk has it."""
    from alphaavatar.host.tools.setup.environment import SetupError

    try:
        now = installation.current_base() if installation is not None else None
    except SetupError:
        now = None
    if before is None:
        return "nothing changed"
    if now is None or now == before:
        return f"AlphaAvatar {before} stays current"
    return f"AlphaAvatar {now} is current"


def upgrade(args: argparse.Namespace) -> int:
    # SIGTERM and SIGHUP unwind like Ctrl-C, so the upgrade's cleanups run.
    handlers = {
        signum: signal.signal(signum, _interrupt) for signum in (signal.SIGTERM, signal.SIGHUP)
    }
    try:
        return _upgrade(args)
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def _upgrade(args: argparse.Namespace) -> int:
    from alphaavatar.agents.env import init_env
    from alphaavatar.host.configs import application_paths, format_failure
    from alphaavatar.host.tools.setup.environment import SetupError
    from alphaavatar.host.tools.setup.plan import PlanError
    from alphaavatar.host.tools.upgrade.upgrade import upgrade as upgrading

    out, errors = Report(), Report(sys.stderr)
    out.title("Upgrade")
    out.write()
    started = out.lines
    installation = before = None
    failed = "Check failed" if args.check else "Upgrade failed"

    def step(number: int, name: str, summary: str | None) -> None:
        if summary is None:
            out.begin(number, name)
        else:
            out.step(number, name, summary)

    def progress(line: str) -> None:
        if not line.startswith("Checking the environment"):  # Validate is its own step.
            out.progress(line)

    try:
        installation = _installation()
        before = installation.current_base()
        if args.check:
            return _check(args, installation, out)
        init_env()  # The .env file start reads; the stored credentials are read under the lock.
        result = upgrading(
            installation,
            _source(args),
            paths=application_paths(),
            environ=dict(os.environ),
            step=step,
            progress=progress,
        )
    except (KeyboardInterrupt, SystemExit) as stop:
        _apart(out, started)
        stopped = "Interrupted" if isinstance(stop, KeyboardInterrupt) else "Stopped"
        errors.status("WARN", f"{stopped}; {_outcome(installation, before)}")
        errors.write()
        if isinstance(stop, KeyboardInterrupt):
            return 130
        return stop.code if isinstance(stop.code, int) else 1
    except (SetupError, PlanError) as error:
        _apart(out, started)
        errors.status("FAIL", f"{failed}; {_outcome(installation, before)}")
        errors.verbatim(str(error), indent=STATUS)
        errors.write()
        return 1
    except Exception as error:
        _apart(out, started)
        errors.status("FAIL", f"{failed}; {_outcome(installation, before)}")
        errors.verbatim(format_failure(error))
        errors.write()
        return 2
    if result.current == result.previous:
        out.status("OK", f"AlphaAvatar {result.current} is current already; nothing to do")
        out.write()
        return 0
    out.write()
    out.status("OK", f"Upgraded to AlphaAvatar {result.current}")
    bundle = result.bundle
    facts = {"Previous": result.previous, "Current": home_relative(result.path)}
    if bundle is not None:
        facts["Bundle"] = bundle
    column = out.column(list(facts))
    for key, value in facts.items():
        out.row(key, value, indent=STATUS, column=column)
    kept = "version and its environment stay" if bundle is not None else "version stays"
    removed = "them" if bundle is not None else "it"
    out.note(f"The previous {kept} until `alphaavatar cleanup` removes {removed}.", indent=STATUS)
    out.heading("Next")
    out.command(f"alphaavatar doctor {bundle}" if bundle is not None else "alphaavatar setup")
    out.write()
    return 0

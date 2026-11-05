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
"""`alphaavatar setup`: choose capabilities, install what they need, check it, then enable.

Asked interactively, or given a preset for CI and unattended installs; both take the same
path. Credentials come from the person, or with a preset from the environment, and are stored
privately only once everything they serve is installed and checked. Nothing here starts a
session, runner or model.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from alphaavatar.core.log.records import clean


def _ask(question: str, default: str) -> str:
    answer = input(f"{question} [{default}]: ").strip()
    return answer or default


def _yes(question: str, default: bool = True) -> bool:
    while True:
        answer = input(f"{question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes", "n", "no"):
            return answer.startswith("y")


def _choose(args: argparse.Namespace):
    from alphaavatar.host.setup.choices import PRESETS, Selection

    if args.preset is not None:
        selection = PRESETS[args.preset]
        return Selection(
            voice=selection.voice and not args.no_voice,
            vision=selection.vision and not args.no_vision,
            local_models=selection.local_models,
            vector_store=args.vector_store or selection.vector_store,
        )
    print("\nWhat should this Avatar run with?")
    print("  1  Default bundle    voice, vision, memory and persona, with turn taking,")
    print("                       addressing, face and speaker models on this machine")
    print("  2  Remote inference  the same, with no model on this machine but the voice")
    print("                       activity detection speech input needs")
    print("  3  Choose each")
    while (choice := _ask("Choice", "1")) not in ("1", "2", "3"):
        pass
    if choice != "3":
        return PRESETS["default" if choice == "1" else "remote"]
    voice = _yes("Voice: speech in and out, voice activity detected on this machine?")
    vision = _yes("Vision: camera frames reach the model?")
    local = _yes("Models on this machine: turn taking, addressing, face and speaker recognition?")
    print("Vectors for memory and persona:  1  LanceDB in the Avatar workspace  2  your Qdrant")
    while (store := _ask("Vector store", "1")) not in ("1", "2"):
        pass
    return Selection(voice, vision, local, "lancedb" if store == "1" else "qdrant")


def _credentials(selection, interactive: bool, path: Path) -> dict[str, str]:
    """Values to store: asked for, or with a preset read from the environment."""
    import getpass

    from alphaavatar.host.setup.choices import credentials
    from alphaavatar.host.setup.environment import SetupError

    values, missing = {}, []
    if interactive:
        print(f"\nCredentials, stored in {clean(str(path))}, readable only by you:")
    for credential in credentials(selection):
        present = os.environ.get(credential.name)
        if interactive:
            keep = " (set; Enter keeps it)" if present else ""
            prompt = f"  {credential.name}, for {credential.purpose}{keep}: "
            value = (getpass.getpass(prompt) if credential.secret else input(prompt)).strip()
            value = value or present or ""
        else:
            value = present or ""
        if value:
            values[credential.name] = value
        elif credential.required:
            missing.append(credential.name)
    if missing:
        raise SetupError(f"Missing credentials: {', '.join(missing)} (set them in the environment)")
    return values


def _machine(plan) -> list[str]:
    """What this machine lacks for the plan's native code."""
    problems = []
    found = os.confstr("CS_GNU_LIBC_VERSION") or ""
    have = tuple(map(int, found.split()[-1].split("."))) if found.startswith("glibc") else None
    if plan.glibc is not None and (have is None or have < tuple(map(int, plan.glibc.split(".")))):
        problems.append(f"glibc {plan.glibc} or newer; found {found or 'none'}")
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
        flags = set(next(line for line in text.splitlines() if line.startswith("flags")).split())
    except (OSError, StopIteration):
        flags = set()
    if lacking := [flag for flag in plan.cpu if flag not in flags]:
        problems.append(f"a CPU with {', '.join(plan.cpu)}; {', '.join(lacking)} missing")
    return problems


def _single_file(texts: dict[str, str], name: str, home: Path, target: Path) -> None:
    """The bundle with its profiles inlined, as config check reads it before files exist."""
    import yaml

    bundle = yaml.safe_load(texts[f"bundles/{name}.yaml"])
    for section, reference in bundle.pop("profiles").items():
        bundle[section] = yaml.safe_load(texts[f"profiles/{reference}.yaml"])
    bundle["application"] = {"home": str(home)}
    target.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), "utf-8")


def _megabytes(size: int) -> str:
    return f"{size / 1e6:,.0f} MB"


def _interrupt(signum: int, frame: Any) -> None:
    raise SystemExit(128 + signum)


def setup(args: argparse.Namespace) -> int:
    # SIGTERM and SIGHUP unwind like Ctrl-C, so the installation's cleanups run.
    handlers = {
        signum: signal.signal(signum, _interrupt) for signum in (signal.SIGTERM, signal.SIGHUP)
    }
    try:
        return _setup(args)
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def _setup(args: argparse.Namespace) -> int:
    from alphaavatar.host.configs import ConfigReferenceError, application_paths, format_failure
    from alphaavatar.host.configs.bundles import bundle_path, read_settings
    from alphaavatar.host.configs.credentials import (
        credentials_path,
        load_environment,
        store_credentials,
    )
    from alphaavatar.host.configs.template import create_bundle, render_bundle
    from alphaavatar.host.setup import choices
    from alphaavatar.host.setup.environment import (
        Installation,
        SetupError,
        Sources,
        check_environment,
        complete,
        install,
    )
    from alphaavatar.host.setup.plan import PlanError, plan_install

    interactive = args.preset is None
    try:
        if interactive and not sys.stdin.isatty():
            raise SetupError("No terminal to ask in: pass --preset (default or remote)")
        load_environment()  # Credentials already set or stored count as given.
        installation = Installation.running()
        manifest, catalog = installation.manifest, installation.catalog
        selection = _choose(args)
        name = args.name or (_ask("\nBundle name", "avatar") if interactive else "avatar")
        avatar_id = args.avatar_id or (_ask("Avatar ID", name) if interactive else name)
        paths = application_paths()
        read_settings(paths)  # Unreadable settings refuse before anything happens.
        if bundle_path(paths, name).exists():
            raise ConfigReferenceError(
                f"Bundle {name!r} exists: {bundle_path(paths, name)}; choose another --name"
            )
        sections = choices.sections(selection)
        environment = [(c.name, c.purpose) for c in choices.credentials(selection)]
        texts = render_bundle(name, avatar_id, sections=sections, environment=environment)
        # Installing for this bundle never takes from another: what the current environment
        # holds stays planned, and the same plan reuses it.
        kept = installation.installed_requirements()
        requirements = {*choices.requirements(selection), *kept}
        plan = plan_install(catalog, requirements, base=manifest["id"])
        if args.plan:
            document = plan.document() | {"id": plan.id, "download_bytes": plan.download_bytes}
            print(json.dumps(document, indent=1))
            return 0
        if problems := _machine(plan):
            raise SetupError("This machine lacks what the plan needs: " + "; ".join(problems))
        target = installation.environment(plan)
        reused = complete(target, plan)
        free = os.statvfs(installation.prefix)
        # Installed packages take about three times their download; downloads go first.
        if not reused and free.f_bavail * free.f_frsize < 4 * plan.download_bytes:
            raise SetupError(
                f"{_megabytes(free.f_bavail * free.f_frsize)} free in {installation.prefix}; "
                f"the plan downloads {_megabytes(plan.download_bytes)} and needs about four times"
            )
        values = _credentials(selection, interactive, credentials_path(paths))

        print(f"\nAlphaAvatar {plan.version} ({plan.platform}), plan {plan.id[:16]}:")
        for line in choices.capabilities(selection):
            print(f"  {line}")
        if extra := sorted(set(kept) - set(choices.requirements(selection))):
            print(f"  kept from the current environment: {', '.join(extra)}")
        if reused:
            print(f"  {len(plan.artifacts)} packages, installed already: nothing to download")
        else:
            print(
                f"  {len(plan.artifacts)} packages, {_megabytes(plan.download_bytes)} to download"
            )
        print(f"  environment {clean(str(target))}; bundle {name}, made the default")
        if interactive and not _yes("Install and enable?"):
            return 1

        def enable() -> None:
            undo: Callable[[], None] = (
                store_credentials(paths, values) if values else (lambda: None)
            )
            try:
                create_bundle(
                    paths,
                    name,
                    avatar_id=avatar_id,
                    sections=sections,
                    environment=environment,
                    make_default=True,
                )
            except BaseException:
                undo()
                raise

        with tempfile.TemporaryDirectory() as scratch:
            config = Path(scratch) / f"{name}.yaml"
            _single_file(texts, name, paths.root, config)
            env = os.environ | values
            install(
                installation,
                plan,
                Sources(args.artifacts, manifest.get("release")),
                check=lambda environment: check_environment(environment, config, env),
                enable=enable,
                progress=lambda line: print(line, flush=True),
            )
    except KeyboardInterrupt:
        print("\nInterrupted; nothing was enabled.", file=sys.stderr)
        return 130
    except SystemExit as stop:
        print("\nStopped; nothing was enabled.", file=sys.stderr)
        return stop.code if isinstance(stop.code, int) else 1
    except (SetupError, PlanError) as error:
        print(f"\nSetup failed; nothing was enabled:\n{clean(str(error))}\n", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"\nSetup failed; nothing was enabled:\n{format_failure(error)}\n", file=sys.stderr)
        return 2
    print(f"\nEnabled bundle {name} (default) with {len(plan.artifacts)} packages in {target}.")
    print("Next:\n  alphaavatar dev        # start in development mode\n")
    return 0

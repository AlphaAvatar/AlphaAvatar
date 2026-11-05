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
path. With a preset, credentials come from the environment and stay there. Asked for, they are
stored privately only if the person says so, a stored value other bundles may read replaced
only on a yes, and only once everything they serve is installed and checked. Nothing here
starts a session, runner or model.
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


def _needed(question: str, default: str = "") -> str:
    while not (answer := _ask(question, default) if default else input(f"{question}: ").strip()):
        pass
    return answer


def _server(question: str) -> str:
    from urllib.parse import urlsplit

    while True:
        url = _needed(question, "http://localhost:8000/v1").rstrip("/")
        parts = urlsplit(url)
        if parts.scheme in ("http", "https") and parts.hostname and not parts.query:
            return url
        print("  An http:// or https:// API root, such as http://gpu-host:8000/v1")


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
    from alphaavatar.host.setup.choices import Models, Speech

    voice = _yes("Voice: speech in and out, voice activity detected on this machine?")
    vision = _yes("Vision: camera frames reach the model?")
    local = _yes("Models on this machine: turn taking, addressing, face and speaker recognition?")
    print("Vectors for memory and persona:  1  LanceDB in the Avatar workspace  2  your Qdrant")
    while (store := _ask("Vector store", "1")) not in ("1", "2"):
        pass
    models = speech = None
    if not _yes(
        "Models from OpenAI? No: a server of your own with OpenAI's API, Responses included"
    ):
        url = _server("  Server URL")
        chat = _needed("  Conversation model")
        models = Models(
            url, chat, _needed("  Memory and persona model", chat), _needed("  Embedding model")
        )
    if voice and not _yes("Speech from OpenAI? No: a server of your own with OpenAI's audio API"):
        speech = Speech(
            _server("  Server URL"),
            _needed("  Transcription model"),
            _needed("  Speech model"),
            _needed("  Voice"),
        )
    return Selection(voice, vision, local, "lancedb" if store == "1" else "qdrant", models, speech)


def _credentials(selection, interactive: bool, path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """The values the check and the bundle read, and those to store.

    A preset reads them from the environment and stores none. Asked for, they are stored only
    on a yes, and a stored value, which other bundles may read, is replaced only on another.
    """
    import getpass

    from dotenv import dotenv_values

    from alphaavatar.host.setup.choices import credentials
    from alphaavatar.host.setup.environment import SetupError

    values, missing = {}, []
    if interactive:
        print("\nCredentials:")
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
    stored = dotenv_values(path, interpolate=False) if path.is_file() else {}
    new = {name: value for name, value in values.items() if stored.get(name) != value}
    if not interactive or not new:
        return values, {}
    if not _yes(f"Store {', '.join(new)} in {clean(str(path))}, readable only by you?", False):
        print("  Not stored: start reads them from the environment or .env")
        return values, {}
    saved = {}
    for name, value in new.items():
        if stored.get(name) is not None and not _yes(
            f"  {name} is stored already and other bundles may read it; replace it for all?", False
        ):
            print(f"  {name} stays as stored; this bundle reads it unless the environment sets it")
            continue
        saved[name] = value
    return values, saved


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
    enabled: list[str] = []
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
        values, saved = _credentials(selection, interactive, credentials_path(paths))

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
            # Signals wait meanwhile: current, the bundle and its credentials agree at the end.
            undo: Callable[[], None] = store_credentials(paths, saved) if saved else (lambda: None)
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
                if read_settings(paths).get("default_bundle") != name:
                    undo()
                    raise
                # The settings replacement committed: the bundle is the default, enabled.
            enabled.append(name)

        def replan(installed: tuple[str, ...]):
            needed = {*choices.requirements(selection), *installed}
            return plan_install(catalog, needed, base=manifest["id"])

        with tempfile.TemporaryDirectory() as scratch:
            config = Path(scratch) / f"{name}.yaml"
            _single_file(texts, name, paths.root, config)
            env = os.environ | values
            target = install(
                installation,
                plan,
                Sources(args.artifacts, manifest.get("release")),
                check=lambda environment: check_environment(environment, config, env),
                enable=enable,
                replan=replan,
                progress=lambda line: print(line, flush=True),
            )
    except (KeyboardInterrupt, SystemExit) as stop:
        done = f"bundle {enabled[0]} was enabled first" if enabled else "nothing was enabled"
        print(
            f"\n{'Interrupted' if isinstance(stop, KeyboardInterrupt) else 'Stopped'}; {done}.",
            file=sys.stderr,
        )
        if isinstance(stop, KeyboardInterrupt):
            return 130
        return stop.code if isinstance(stop.code, int) else 1
    except (SetupError, PlanError) as error:
        print(f"\nSetup failed; nothing was enabled:\n{clean(str(error))}\n", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"\nSetup failed; nothing was enabled:\n{format_failure(error)}\n", file=sys.stderr)
        return 2
    from dotenv import dotenv_values

    print(f"\nEnabled bundle {name} (default) in {clean(str(target))}.")
    stored = credentials_path(paths)
    found = dotenv_values(stored, interpolate=False) if stored.is_file() else {}
    if unstored := [key for key in values if found.get(key) is None]:
        print(f"Start reads {', '.join(unstored)} from the environment or .env.")
    print("Next:\n  alphaavatar dev        # start in development mode\n")
    return 0

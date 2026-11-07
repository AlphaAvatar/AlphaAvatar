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
"""`alphaavatar setup`: install what a bundle needs, check it, then enable it.

Asked in a terminal, setup starts from the reference configuration `config init` writes and
asks for each part, the credentials, then whether to install the plan. Given an existing
bundle, as `config init` makes it or as edited since, it installs what that bundle's settings
need, with the credentials the environment holds: CI and unattended installs take this way.
Asked for, credentials are stored privately only if the person says so, a stored value other
bundles may read replaced only on a yes, and only once everything they serve is installed and
checked. Nothing here starts a session, runner or model.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import tempfile
from pathlib import Path
from typing import Any

from alphaavatar.core.log.records import clean
from alphaavatar.host.cli.render import STATUS, Report, home_relative


def _ask(out: Report, question: str, default: str) -> str:
    answer = out.ask(f"{question} [{default}]: ").strip()
    return answer or default


def _needed(out: Report, question: str, default: str = "") -> str:
    while not (
        answer := _ask(out, question, default) if default else out.ask(f"{question}: ").strip()
    ):
        pass
    return answer


def _server(out: Report, question: str, *, speech: bool) -> str:
    from alphaavatar.host.setup.choices import server_problem

    while True:
        url = _needed(out, question, "http://localhost:8000/v1").rstrip("/")
        if (problem := server_problem(url, speech=speech)) is None:
            return url
        out.wrapped(problem.capitalize(), indent=6)


def _yes(out: Report, question: str, default: bool = True) -> bool:
    while True:
        answer = out.ask(f"{question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes", "n", "no"):
            return answer.startswith("y")


def _choose(out: Report):
    """Each part of the reference configuration, kept or changed; a server of one's own for
    the models or speech, if chosen."""
    from alphaavatar.host.setup.choices import Models, Selection, Speech

    out.wrapped(
        "From the reference configuration: voice and vision on, memory and persona, each "
        "model from the backend chosen below.",
        indent=4,
    )
    voice = _yes(out, "Voice: speech in and out, voice activity detected on this machine?")
    vision = _yes(out, "Vision: camera frames reach the model?")
    local = _yes(
        out, "Models on this machine: turn taking, addressing, face and speaker recognition?"
    )
    out.write("    Vectors for memory and persona:")
    out.item("1  ", "LanceDB in the Avatar workspace", indent=6)
    out.item("2  ", "your Qdrant", indent=6)
    while (store := _ask(out, "Vector store", "1")) not in ("1", "2"):
        pass
    models = speech = None
    if not _yes(
        out, "Models from OpenAI? No: a server of your own with OpenAI's API, Responses included"
    ):
        url = _server(out, "  Server URL", speech=False)
        chat = _needed(out, "  Conversation model")
        models = Models(
            url,
            chat,
            _needed(out, "  Memory and persona model", chat),
            _needed(out, "  Embedding model"),
        )
    if voice and not _yes(
        out, "Speech from OpenAI? No: a server of your own with OpenAI's audio API"
    ):
        speech = Speech(
            _server(out, "  Server URL", speech=True),
            _needed(out, "  Transcription model"),
            _needed(out, "  Speech model"),
            _needed(out, "  Voice"),
        )
    store = "lancedb" if store == "1" else "qdrant"
    return Selection(voice, vision, local, store, models, speech)


def _described(*, voice: bool, vision: bool, local: bool, qdrant: bool, own: list[str]) -> str:
    """What a bundle runs with, on one line."""
    on = {True: "on", False: "off"}
    parts = [f"Voice {on[voice]}", f"Vision {on[vision]}", f"Local models {on[local]}"]
    return " · ".join([*parts, *(["Qdrant"] if qdrant else []), *own])


def _selection_line(selection) -> str:
    own = ["Models from your server"] if selection.models is not None else []
    if selection.voice and selection.speech is not None:
        own.append("Speech from your server")
    return _described(
        voice=selection.voice,
        vision=selection.vision,
        local=selection.local_models,
        qdrant=selection.vector_store == "qdrant",
        own=own,
    )


def _bundle_line(avatar, needs: dict[str, str]) -> str:
    """An existing bundle's switches, as its settings and its plan have them."""
    from alphaavatar.agents.runtime.plugin import plugin_requirement
    from alphaavatar.agents.utils.vdb.config import vdb_requirement

    local = ("router", "semantic"), ("router", "turn-taking"), ("persona", "speaker")
    local += (("persona", "face"),)
    return _described(
        voice=avatar.voice.stt.plugin is not None or avatar.voice.tts.plugin is not None,
        vision=bool(avatar.vision.enabled),
        local=any(plugin_requirement(*part) in needs for part in local),
        qdrant=vdb_requirement("qdrant") in needs,
        own=[],
    )


def _session_credentials(rtc, env, *, typed: bool = False) -> None:
    """Start's session transport credentials, as start reads them, checked offline before
    anything is stored or installed: a bundle setup enables can start. The error names the
    variables, never their values."""
    from pydantic import ValidationError

    from alphaavatar.core.log import error_fields
    from alphaavatar.host.sessions.factory import check_session_credentials
    from alphaavatar.host.setup.environment import SetupError

    try:
        check_session_credentials(rtc, env)
    except ValidationError as error:
        # The bundle's own transport settings: the validator quotes their values, which may
        # be a secret written where none belongs, so only the fields are named.
        fields = ", ".join(f"host.rtc.init_config.{field}" for field in error_fields(error))
        raise SetupError(
            f"The session transport ({rtc.backend}) cannot start: its settings are not valid "
            f"(fields: {fields or 'host.rtc.init_config'}); fix them in the bundle's host profile"
        ) from None
    except ValueError as error:
        raise SetupError(
            f"The session transport ({rtc.backend}) cannot start: {error}, "
            + ("as typed or " * typed)
            + "in the environment, .env or the stored credentials"
        ) from None


def _credentials(selection, paths, out: Report, rtc) -> tuple[dict[str, str], dict[str, str]]:
    """The values the check and the bundle read, asked for, and those to store: stored only on
    a yes, and a stored value, which other bundles may read, replaced only on another. The
    values that take effect, typed or set already, are checked before either."""
    import getpass

    from alphaavatar.host.configs.credentials import stored_credentials
    from alphaavatar.host.setup.choices import credentials
    from alphaavatar.host.setup.environment import SetupError

    values, missing = {}, []
    for credential in credentials(selection):
        present = os.environ.get(credential.name)
        keep = " (set; Enter keeps it)" if present else ""
        question = f"{credential.name}, for {credential.purpose}{keep}: "
        answer = getpass.getpass(out.prompt(question)) if credential.secret else out.ask(question)
        value = answer.strip() or present or ""
        if value:
            values[credential.name] = value
        elif credential.required:
            missing.append(credential.name)
    if missing:
        raise SetupError(f"Missing credentials: {', '.join(missing)} (set them in the environment)")
    _session_credentials(rtc, os.environ | values, typed=True)
    stored = stored_credentials(paths)
    new = {name: value for name, value in values.items() if stored.get(name) != value}
    if not new:
        return values, {}
    where = clean(str(paths.settings_dir))
    if not _yes(out, f"Store {', '.join(new)} in {where}, readable only by you?", False):
        out.write("    Not stored: start reads them from the environment or .env")
        return values, {}
    saved = {}
    for name, value in new.items():
        if stored.get(name) is not None and not _yes(
            out,
            f"  {name} is stored already and other bundles may read it; replace it for all?",
            False,
        ):
            out.wrapped(
                f"{name} stays as stored; this bundle reads it unless the environment sets it",
                indent=4,
            )
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


def _apart(out: Report, started: int) -> None:
    """A blank line after what the steps printed, before the result on stderr."""
    if out.lines > started:
        out.write()


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
    from alphaavatar.host.configs import (
        ConfigReferenceError,
        application_paths,
        format_failure,
        load_selections,
        select_configuration,
    )
    from alphaavatar.host.configs.bundles import bundle_path, check_bundle_name, read_settings
    from alphaavatar.host.configs.credentials import load_environment, stored_credentials
    from alphaavatar.host.configs.template import create_bundle, render_bundle, set_default_bundle
    from alphaavatar.host.setup import choices
    from alphaavatar.host.setup.environment import (
        Installation,
        SetupError,
        Sources,
        check_environment,
        install,
    )
    from alphaavatar.host.setup.plan import PlanError, plan_install

    existing = args.bundle  # Set up as its settings say; without one, each part is asked.
    terminal = sys.stdin.isatty()
    # The steps, and the questions under them; with --plan, stdout holds the plan alone.
    out = Report(sys.stderr if args.plan else sys.stdout)
    errors = Report(sys.stderr)
    enabled: list[str] = []
    out.title("Setup")
    out.write()
    started = out.lines
    try:
        if existing is None and not terminal:
            raise SetupError(
                "No terminal to ask in: set up an existing bundle, `alphaavatar setup <bundle>`; "
                "`alphaavatar config init <bundle> --avatar-id <id>` creates one"
            )
        settings = load_environment()  # Credentials already set or stored count as given.
        installation = Installation.running()
        manifest, catalog = installation.manifest, installation.catalog
        paths = application_paths()
        read_settings(paths)  # Unreadable settings refuse before anything happens.
        if existing is None:
            out.begin(1, "Capabilities")
            selection = _choose(out)
            name = args.name or _ask(out, "Bundle name", "avatar")
            avatar_id = args.avatar_id or _ask(out, "Avatar ID", name)
            if bundle_path(paths, name).exists():
                raise ConfigReferenceError(
                    f"Bundle {name!r} exists: {bundle_path(paths, name)}; choose another name, "
                    f"or set it up as it is: `alphaavatar setup {name}`"
                )
            out.step(1, "Capabilities", _selection_line(selection))
            sections = choices.sections(selection)
            environment = [(c.name, c.purpose) for c in choices.credentials(selection)]
            texts = render_bundle(name, avatar_id, sections=sections, environment=environment)
            needed = choices.requirements(selection)
        else:
            name = check_bundle_name(existing)
            # Planned from the bundle's own settings, with no plugin installed yet.
            host, avatar = load_selections(select_configuration(name, (), settings))
            found, unserved = choices.bundle_requirements(host, avatar, catalog.get("plugins", {}))
            if unserved:
                raise SetupError(
                    "This release's setup installs nothing for: " + "; ".join(unserved)
                )
            out.step(1, "Capabilities", f"Bundle {name} · {_bundle_line(avatar, found)}")
            needed = tuple(sorted(found))
        # Installing for this bundle never takes from another: what the current environment
        # holds stays planned, and the same plan reuses it.
        kept = installation.installed_requirements()
        plan = plan_install(catalog, {*needed, *kept}, base=manifest["id"])
        if args.plan:
            document = plan.document() | {"id": plan.id, "download_bytes": plan.download_bytes}
            print(json.dumps(document, indent=1))
            return 0
        if problems := _machine(plan):
            raise SetupError("This machine lacks what the plan needs: " + "; ".join(problems))
        target = installation.environment(plan)
        reused = installation.reusable(plan)
        free = os.statvfs(installation.prefix)
        # Installed packages take about three times their download; downloads go first.
        if not reused and free.f_bavail * free.f_frsize < 4 * plan.download_bytes:
            raise SetupError(
                f"{_megabytes(free.f_bavail * free.f_frsize)} free in {installation.prefix}; "
                f"the plan downloads {_megabytes(plan.download_bytes)} and needs about four times"
            )
        if existing is None:
            out.begin(2, "Credentials")
            with tempfile.TemporaryDirectory() as scratch:
                _single_file(texts, name, paths.root, Path(scratch) / f"{name}.yaml")
                host, _ = load_selections(Path(scratch) / f"{name}.yaml")
            values, saved = _credentials(selection, paths, out, host.rtc)
            out.step(2, "Credentials", f"Ready · {len(saved)} to store" if saved else "Ready")
        else:
            values, saved = {}, {}
            _session_credentials(host.rtc, os.environ)
            out.step(2, "Credentials", "From the environment, .env or those stored")

        size = "installed already" if reused else _megabytes(plan.download_bytes)
        planned = f"{len(plan.artifacts)} packages · {size}"
        out.begin(3, "Install")
        if extra := sorted(set(kept) - set(needed)):
            out.wrapped(f"Kept from the current environment: {', '.join(extra)}", indent=4)
        if terminal:
            # The plan, and what it downloads, before anything is installed.
            plan_lines = [
                f"AlphaAvatar {plan.version} ({plan.platform}), plan {plan.id[:16]}",
                *(choices.capabilities(selection) if existing is None else ()),
                f"{planned}{'' if reused else ' to download'}",
                f"Environment {home_relative(target)}; bundle {name}, made the default",
            ]
            for line in plan_lines:
                out.wrapped(line, indent=4)
            if not _yes(out, "Install and enable?"):
                out.write()
                errors.status("WARN", "Cancelled; nothing was enabled")
                errors.write()
                return 1
            out.begin(3, "Install")  # Its progress, on the step's line again.

        def check(environment: Path) -> None:
            out.step(3, "Install", planned)
            out.begin(4, "Validate")
            count = check_environment(environment, config if existing is None else name, env)
            out.step(4, "Validate", "PASS" + (f" · {count} runners" if count is not None else ""))

        def progress(line: str) -> None:
            # Each artifact, then the check: the step's line on a terminal shows the latest.
            if line.startswith("Checking the environment"):
                return
            out.progress(line)

        def enable() -> None:
            # Signals wait meanwhile; one settings replacement makes the bundle the default
            # and names the credentials it stores, so even a kill leaves both or neither.
            try:
                if existing is not None:
                    set_default_bundle(paths, name)
                else:
                    create_bundle(
                        paths,
                        name,
                        avatar_id=avatar_id,
                        sections=sections,
                        environment=environment,
                        make_default=True,
                        credentials=saved,
                    )
            except BaseException:
                if read_settings(paths).get("default_bundle") != name:
                    raise
                # The settings replacement committed: the bundle is the default, enabled.
            enabled.append(name)

        def replan(installed: tuple[str, ...]):
            return plan_install(catalog, {*needed, *installed}, base=manifest["id"])

        with tempfile.TemporaryDirectory() as scratch:
            config = Path(scratch) / f"{name}.yaml"
            if existing is None:
                _single_file(texts, name, paths.root, config)
            env = os.environ | values
            target = install(
                installation,
                plan,
                Sources(args.artifacts, manifest.get("release")),
                check=check,
                enable=enable,
                replan=replan,
                progress=progress,
            )
    except (KeyboardInterrupt, SystemExit) as stop:
        done = f"bundle {enabled[0]} was enabled first" if enabled else "nothing was enabled"
        _apart(out, started)
        stopped = "Interrupted" if isinstance(stop, KeyboardInterrupt) else "Stopped"
        errors.status("WARN", f"{stopped}; {done}")
        errors.write()
        if isinstance(stop, KeyboardInterrupt):
            return 130
        return stop.code if isinstance(stop.code, int) else 1
    except (SetupError, PlanError) as error:
        _apart(out, started)
        errors.status("FAIL", "Setup failed; nothing was enabled")
        errors.verbatim(str(error), indent=STATUS)
        errors.write()
        return 1
    except Exception as error:
        _apart(out, started)
        errors.status("FAIL", "Setup failed; nothing was enabled")
        errors.verbatim(format_failure(error))
        errors.write()
        return 2
    found_stored = stored_credentials(paths)
    out.write()
    out.status("OK", "Bundle enabled")
    facts = {"Default": name, "Environment": home_relative(target)}
    column = out.column(list(facts))
    for key, value in facts.items():
        out.row(key, value, indent=STATUS, column=column)
    if unstored := [key for key in values if found_stored.get(key) is None]:
        out.note(f"Start reads {', '.join(unstored)} from the environment or .env.", indent=STATUS)
    out.heading("Next")
    out.command(f"alphaavatar doctor {name}")
    out.write()
    return 0

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

LOCAL_SERVER = "http://localhost:8000/v1"
# How the speech implementations are offered.
SPEECH = {
    "openai_segment": "OpenAI, segment by segment",
    "openai_realtime": "OpenAI Realtime, as it is spoken",
    "openai": "OpenAI",
    "voiceai": "Voice.ai",
}
# What each part's questions call it.
PARTS = {
    "loop": "the conversation",
    "conversation": "memory",
    "tool": "tool memory",
    "profiler": "persona profiles",
    "environment": "ENV memory",
    "embedding": "embeddings",
    "transcription": "speech recognition",
    "synthesis": "speech synthesis",
}


def _ask(out: Report, question: str, default: str) -> str:
    answer = out.ask(f"{question} [{default}]: ").strip()
    return answer or default


def _needed(out: Report, question: str, default: str = "") -> str:
    while not (
        answer := _ask(out, question, default) if default else out.ask(f"{question}: ").strip()
    ):
        pass
    return answer


def _server(out: Report, question: str, *, speech: bool, default: str) -> str:
    from alphaavatar.host.tools.setup.choices import server_problem

    while True:
        url = _needed(out, question, default).rstrip("/")
        if (problem := server_problem(url, speech=speech)) is None:
            return url
        out.wrapped(problem[0].upper() + problem[1:], indent=6)


def _yes(out: Report, question: str, default: bool = True) -> bool:
    while True:
        answer = out.ask(f"{question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes", "n", "no"):
            return answer.startswith("y")


def _switches(out: Report) -> dict[str, Any]:
    """The capabilities on or off, and where vectors are kept."""
    from alphaavatar.host.cli.render import Option
    from alphaavatar.host.tools.setup.choices import TOOLS

    out.wrapped(
        "Each question starts from the reference configuration: Enter keeps its answer.", indent=4
    )
    voice = _yes(out, "Voice: speech in and out, voice activity detected on this machine?")
    vision = _yes(out, "Vision: camera frames reach the model?")
    local = _yes(
        out, "Models on this machine: turn taking, addressing, face and speaker recognition?"
    )
    env = _yes(
        out,
        "ENV memory: memories drawn from the session's audio and video by Google's Gemini, "
        "an external model?",
    )
    stores = [Option("LanceDB in the Avatar workspace", "lancedb"), Option("Your Qdrant", "qdrant")]
    store = out.choose("Vectors for memory and persona", stores)
    out.wrapped(TOOLS[0].upper() + TOOLS[1:] + ".", indent=4)
    return {
        "voice": voice,
        "vision": vision,
        "local_models": local,
        "env_memory": env,
        "vector_store": store,
    }


def _model(out: Report, part: str, chosen: dict[str, Any], servers: list[str]):
    """A part's provider, from a list with the reference's marked, or a model chosen for an
    earlier part; then its model: the reference's offered only from the reference's provider."""
    from alphaavatar.host.cli.render import Option
    from alphaavatar.host.tools.setup.choices import (
        NAMES,
        PROVIDERS,
        REFERENCE,
        REUSE,
        SERVED,
        Model,
        default_model,
        reusable,
    )

    what = PARTS[part]
    options = [Option(NAMES[provider], provider) for provider in PROVIDERS[part]]
    if part in SERVED:
        api = "OpenAI's Responses API" if part == "loop" else "OpenAI's API"
        options.append(Option(f"A server of your own with {api}", "server"))
    default = [option.value for option in options].index(REFERENCE[part].provider)
    for earlier in REUSE.get(part, ()):
        model = chosen[earlier]
        taken = [option.value for option in options]
        if reusable(part, model) and model != REFERENCE[part] and model not in taken:
            options.insert(0, Option(f"As for {PARTS[earlier]}: {model.describe()}", model))
            default += 1
    if len(options) == 1:
        out.wrapped(f"{what[0].upper()}{what[1:]}: from {options[0].label}, the only one", indent=4)
        picked = options[0].value
    else:
        picked = out.choose(f"Provider for {what}", options, default)
    if isinstance(picked, Model):
        return picked
    server = None
    if picked == "server":
        server = _server(
            out, f"  Server URL for {what}", speech=False, default=(servers or [LOCAL_SERVER])[-1]
        )
        servers.append(server)
        picked = "openai"
    model = _needed(out, f"  Model for {what}", default_model(part, picked, server) or "")
    return Model(picked, model, server)


def _speech(out: Report, servers: list[str]) -> dict[str, Any]:
    """Speech in and out: each implementation, or a server of one's own with OpenAI's audio
    API; its model; for speech out, its voice and speed where it takes them."""
    from alphaavatar.agents.configs.plugins.foundation.voice_config import TTSConfig
    from alphaavatar.host.cli.render import Option
    from alphaavatar.host.tools.setup.choices import (
        REFERENCE,
        SPEECH_SERVED,
        SYNTHESIS,
        TRANSCRIPTION,
        Synthesis,
        Transcription,
        default_model,
        server_problem,
    )

    def implementation(part: str, offered: tuple[str, ...]) -> tuple[str, str | None, str]:
        """The implementation, the server if one's own, and the model."""
        what = PARTS[part]
        options = [Option(f"{SPEECH[plugin]} ({plugin})", plugin) for plugin in offered]
        served = SPEECH_SERVED[part]
        options.append(Option(f"A server of your own with OpenAI's audio API ({served})", None))
        plugin, url = out.choose(f"Provider for {what}", options), None
        if plugin is None:
            # The speech server typed before, else a model server speech may use as well.
            fit = [typed for typed in servers if server_problem(typed, speech=True) is None]
            default = (fit or [LOCAL_SERVER])[-1]
            url = _server(out, f"  Server URL for {what}", speech=True, default=default)
            servers.append(url)
            plugin = served
        model = _needed(out, f"  Model for {what}", default_model(part, plugin, url) or "")
        return plugin, url, model

    plugin, url, model = implementation("transcription", TRANSCRIPTION)
    stt = Transcription(plugin, model, url)
    plugin, url, model = implementation("synthesis", SYNTHESIS)
    reference = REFERENCE["synthesis"]
    if plugin == "voiceai":
        speaker = out.ask("  Voice ID (Enter: the model's own): ").strip() or None
    elif url is None and plugin == reference.plugin:
        speaker = _needed(out, "  Voice", reference.speaker)
    else:
        speaker = _needed(out, "  Voice")
    if not TTSConfig.takes_instructions(plugin, model):
        out.note(f"{model} takes no instructions: the reference's are left out.", indent=6)
    speed = None
    if not TTSConfig.takes_speed(plugin):
        out.note(f"{SPEECH[plugin]} speaks at 1.0: it takes no speed.", indent=6)
    else:
        while True:
            answer = _ask(out, "  Speed, 0.25 to 4.0", f"{REFERENCE['speed']:g}")
            try:
                speed = float(answer)
            except ValueError:
                out.wrapped("A number", indent=6)
                continue
            try:
                Synthesis(plugin, model, speaker, speed, url)
                break
            except ValueError as error:  # Out of range.
                out.wrapped(str(error), indent=6)
    return {"transcription": stt, "synthesis": Synthesis(plugin, model, speaker, speed, url)}


def _models(out: Report, switches: dict[str, Any]) -> dict[str, Any]:
    """Each running part's provider and model, then speech's if voice is on."""
    chosen: dict[str, Any] = {}
    servers: list[str] = []  # Each server typed, offered again to the next.
    for part in ("loop", "conversation", "tool", "profiler", "environment", "embedding"):
        if part != "environment" or switches["env_memory"]:
            chosen[part] = _model(out, part, chosen, servers)
    if switches["voice"]:
        chosen |= _speech(out, servers)
    return chosen


def _name(out: Report, paths, given: str | None) -> str:
    """A new bundle's name: given, or asked until it is one no bundle has."""
    from alphaavatar.host.configs import ConfigReferenceError
    from alphaavatar.host.configs.bundles import bundle_path

    while True:
        name = given or _ask(out, "Bundle name", "avatar")
        try:
            path = bundle_path(paths, name)
            if path.exists():
                raise ConfigReferenceError(
                    f"Bundle {name!r} exists: {path}; choose another name, or set it up as it "
                    f"is: `alphaavatar setup {name}`"
                )
        except ConfigReferenceError as error:
            if given is not None:
                raise
            out.wrapped(str(error), indent=6)
            continue
        return name


def _described(*, voice: bool, vision: bool, local: bool, env: bool, qdrant: bool) -> str:
    """What a bundle runs with, on one line."""
    on = {True: "on", False: "off"}
    parts = [f"Voice {on[voice]}", f"Vision {on[vision]}", f"Local models {on[local]}"]
    parts.append(f"ENV memory {on[env]}")
    return " · ".join([*parts, *(["Qdrant"] if qdrant else [])])


def _models_line(selection) -> str:
    """The providers the running parts' models come from, each once."""
    from alphaavatar.host.tools.setup.choices import NAMES

    parts = list(selection.models().values()) + list(selection.speech() or ())
    found = ["your server" if part.server else NAMES[part.provider] for part in parts]
    return " · ".join(dict.fromkeys(found))


def _bundle_line(avatar, needs: dict[str, str]) -> str:
    """An existing bundle's switches, as its settings and its plan have them."""
    from alphaavatar.agents.runtime.plugin import plugin_requirement
    from alphaavatar.agents.utils.vdb.config import vdb_requirement

    local = ("router", "semantic"), ("router", "turn-taking"), ("persona", "speaker")
    local += (("persona", "face"),)
    environment = avatar.memory.init_config.get("environment")
    return _described(
        voice=avatar.voice.stt.plugin is not None or avatar.voice.tts.plugin is not None,
        vision=bool(avatar.vision.enabled),
        local=any(plugin_requirement(*part) in needs for part in local),
        # ENV memory runs only where its settings switch it on.
        env=isinstance(environment, dict) and environment.get("enabled") is True,
        qdrant=vdb_requirement("qdrant") in needs,
    )


def _session_credentials(rtc, env, *, typed: bool = False) -> None:
    """Start's session transport credentials, as start reads them, checked offline before
    anything is stored or installed: a bundle setup enables can start. The error names the
    variables, never their values."""
    from pydantic import ValidationError

    from alphaavatar.core.log import error_fields
    from alphaavatar.host.service.sessions.factory import check_session_credentials
    from alphaavatar.host.tools.setup.environment import SetupError

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

    from alphaavatar.agents.utils import credential as configured
    from alphaavatar.host.configs.credentials import stored_credentials
    from alphaavatar.host.tools.setup.choices import credentials
    from alphaavatar.host.tools.setup.environment import SetupError

    values, missing = {}, []
    for credential in credentials(selection):
        present = configured(credential.name)
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


def _host(texts: dict[str, str], name: str):
    """A new bundle's Host settings, from its host profile alone: the Avatar's sections may read
    credentials, such as QDRANT_URL, that are still to be asked for."""
    import yaml

    from alphaavatar.host.service.application.config import HostConfig

    profile = yaml.safe_load(texts[f"bundles/{name}.yaml"])["profiles"]["host"]
    return HostConfig.model_validate(yaml.safe_load(texts[f"profiles/{profile}.yaml"]))


def _single_file(texts: dict[str, str], name: str, home: Path, target: Path) -> None:
    """The bundle with its profiles inlined, as config check reads it before files exist."""
    import yaml

    bundle = yaml.safe_load(texts[f"bundles/{name}.yaml"])
    for section, reference in bundle.pop("profiles").items():
        bundle[section] = yaml.safe_load(texts[f"profiles/{reference}.yaml"])
    bundle["application"] = {"home": str(home)}
    target.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), "utf-8")


def _apart(out: Report, started: int) -> None:
    """A blank line after what the steps printed, before the result on stderr."""
    if out.lines > started:
        out.write()


def _refused(args: argparse.Namespace, diagnostic: str) -> None:
    """With --plan, stdout holds JSON even for a refusal: why, as the report shows it."""
    if args.plan:
        print(json.dumps({"error": {"diagnostic": diagnostic}}, indent=1))


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
        application_paths,
        format_failure,
        load_selections,
        select_configuration,
    )
    from alphaavatar.host.configs.bundles import check_bundle_name, read_settings
    from alphaavatar.host.configs.credentials import (
        fill_configured,
        load_environment,
        stored_credentials,
    )
    from alphaavatar.host.configs.template import create_bundle, render_bundle, set_default_bundle
    from alphaavatar.host.tools.setup import choices
    from alphaavatar.host.tools.setup.environment import (
        Installation,
        SetupError,
        Sources,
        check_environment,
        check_machine,
        install,
        megabytes,
    )
    from alphaavatar.host.tools.setup.plan import PlanError, plan_install

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
            switches = _switches(out)
            name = _name(out, paths, args.name)
            avatar_id = args.avatar_id or _ask(out, "Avatar ID", name)
            line = _described(
                voice=switches["voice"],
                vision=switches["vision"],
                local=switches["local_models"],
                env=switches["env_memory"],
                qdrant=switches["vector_store"] == "qdrant",
            )
            out.step(1, "Capabilities", f"Bundle {name} · {line}")
            out.begin(2, "Models")
            selection = choices.Selection(**switches, **_models(out, switches))
            out.step(2, "Models", _models_line(selection))
            sections = choices.sections(selection)
            environment = [(c.name, c.purpose) for c in choices.credentials(selection)]
            texts = render_bundle(name, avatar_id, sections=sections, environment=environment)
            needed = choices.requirements(selection)
        else:
            name = check_bundle_name(existing)
            # Planned from the bundle's own settings, with no plugin installed yet.
            host, avatar = load_selections(select_configuration(name, (), settings), (), settings)
            found, unserved = choices.bundle_requirements(host, avatar, catalog.get("plugins", {}))
            if unserved:
                raise SetupError(
                    "This release's setup installs nothing for: " + "; ".join(unserved)
                )
            out.step(1, "Capabilities", f"Bundle {name} · {_bundle_line(avatar, found)}")
            out.step(2, "Models", "As the bundle's settings choose them")
            needed = tuple(sorted(found))
        # Installing for this bundle never takes from another: what the current environment
        # holds stays planned, and the same plan reuses it.
        kept = installation.installed_requirements()
        plan = plan_install(catalog, {*needed, *kept}, base=manifest["id"])
        if args.plan:
            document = plan.document() | {"id": plan.id, "download_bytes": plan.download_bytes}
            print(json.dumps(document, indent=1))
            return 0
        check_machine(installation, plan)
        target = installation.environment(plan)
        reused = installation.reusable(plan)
        if existing is None:
            out.begin(3, "Credentials")
            # What the new bundle reads, filled where the environment holds none from .env or
            # the stored credentials, as start fills them: Enter keeps those as well.
            fill_configured([variable for variable, _ in environment], settings)
            values, saved = _credentials(selection, paths, out, _host(texts, name).rtc)
            out.step(3, "Credentials", f"Ready · {len(saved)} to store" if saved else "Ready")
        else:
            values, saved = {}, {}
            _session_credentials(host.rtc, os.environ)
            out.step(3, "Credentials", "From the environment, .env or those stored")

        size = "installed already" if reused else megabytes(plan.download_bytes)
        planned = f"{len(plan.artifacts)} packages · {size}"
        out.begin(4, "Install")
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
            out.begin(4, "Install")  # Its progress, on the step's line again.

        def check(environment: Path) -> None:
            out.step(4, "Install", planned)
            out.begin(5, "Validate")
            count = check_environment(environment, config if existing is None else name, env)
            out.step(5, "Validate", "PASS" + (f" · {count} runners" if count is not None else ""))

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
    except EOFError:
        # The input ended at a question: nothing chosen is kept.
        _apart(out, started)
        errors.status("WARN", "The input ended; nothing was enabled")
        errors.write()
        return 1
    except (SetupError, PlanError) as error:
        _apart(out, started)
        errors.status("FAIL", "Setup failed; nothing was enabled")
        errors.verbatim(str(error), indent=STATUS)
        errors.write()
        _refused(args, str(error))
        return 1
    except Exception as error:
        _apart(out, started)
        errors.status("FAIL", "Setup failed; nothing was enabled")
        errors.verbatim(format_failure(error))
        errors.write()
        _refused(args, format_failure(error))
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

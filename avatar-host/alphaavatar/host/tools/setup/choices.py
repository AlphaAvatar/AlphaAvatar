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
"""What `alphaavatar setup` offers, independent of how a platform delivers it.

A selection, made from the reference configuration `config init` writes, becomes the sections
of a bundle, the requirements its capabilities need, and the credentials its backends read; an
existing bundle's own settings give its requirements too. Any device, the Linux CLI or an App,
chooses with these; only installing the requirements is the platform's own. The requirements
are what ``resolve_capabilities`` finds for the configuration once installed: the tests hold the
two to the same answer.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, NamedTuple
from urllib.parse import urlsplit

from alphaavatar.agents.runtime.plugin import plugin_requirement
from alphaavatar.agents.utils.env_utils import server_key
from alphaavatar.agents.utils.vdb.config import vdb_requirement

if TYPE_CHECKING:
    from alphaavatar.agents.configs import AvatarConfig
    from alphaavatar.host.configs.template import Change
    from alphaavatar.host.service.application.config import HostConfig

VectorStore = Literal["lancedb", "qdrant"]
OPENAI_KEY = "OPENAI_API_KEY"
GOOGLE_KEY = "GOOGLE_API_KEY"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")

# The providers each part takes, as its backend implements them and this release's catalog
# installs them, the reference's first: the loop streams OpenAI's Responses API; the memory and
# persona tasks are LangChain's structured output; ENV memory is Gemini's audio and video.
TASK_PROVIDERS = ("openai", "anthropic", "google", "openrouter")
PROVIDERS = {
    "loop": ("openai",),
    "conversation": TASK_PROVIDERS,
    "tool": TASK_PROVIDERS,
    "environment": ("google",),
    "profiler": TASK_PROVIDERS,
    "embedding": ("openai", "google"),
}
# The parts a server of one's own with OpenAI's API can serve, besides speech.
SERVED = frozenset({"loop", "conversation", "tool", "profiler", "embedding"})
# The earlier parts whose model a part can take as well, where it takes their provider: the
# chat models'. ENV memory's reads audio and video, and embeddings are a kind of their own.
REUSE = {
    "conversation": ("loop",),
    "tool": ("loop", "conversation"),
    "profiler": ("loop", "conversation", "tool"),
}
TRANSCRIPTION = ("openai_segment", "openai_realtime")
SYNTHESIS = ("openai", "voiceai")
# What a speech server of one's own with OpenAI's audio API runs as: OpenAI's realtime
# transcription is a WebSocket API of its own.
SPEECH_SERVED = {"transcription": "openai_segment", "synthesis": "openai"}
KEYS = {
    "openai": OPENAI_KEY,
    "anthropic": "ANTHROPIC_API_KEY",
    "google": GOOGLE_KEY,
    "openrouter": "OPENROUTER_API_KEY",
    "voiceai": "VOICEAI_API_KEY",
}
NAMES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "openrouter": "OpenRouter",
    "voiceai": "Voice.ai",
}


def server_problem(url: str, *, speech: bool) -> str | None:
    """Why the backends a server's URL is for would refuse it, or None.

    The OpenAI clients take an http(s) API root without credentials, query or fragment, on a
    valid port; speech synthesis sends its key over HTTPS unless the server is on this machine.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "an http:// or https:// API root, such as https://gpu-host:8000/v1"
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        return "an API root without credentials, query or fragment"
    try:
        port = parts.port
    except ValueError:
        port = 0
    if port == 0:
        return "a port from 1 to 65535, or none"
    if speech and parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
        return "https:// for a speech server on another machine; http:// only on this one"
    return None


def _model(model: str) -> None:
    if not model.strip():
        raise ValueError("A model ID is required")


@dataclass(frozen=True, slots=True)
class Model:
    """A part's provider and model; ``server``, the API root of a server of one's own that
    speaks OpenAI's API, as provider openai."""

    provider: str
    model: str
    server: str | None = None

    def __post_init__(self) -> None:
        _model(self.model)
        if self.server is None:
            return
        if self.provider != "openai":
            raise ValueError("A server of your own speaks OpenAI's API: its provider is openai")
        if problem := server_problem(self.server, speech=False):
            raise ValueError(f"Model server {self.server}: {problem}")

    @property
    def key(self) -> str:
        """The variable its key is read from: the provider's, or its server's own."""
        return server_key(self.server) if self.server else KEYS[self.provider]

    def describe(self) -> str:
        return (
            f"{self.model} on {self.server}"
            if self.server
            else f"{NAMES[self.provider]} {self.model}"
        )


@dataclass(frozen=True, slots=True)
class Transcription:
    """Speech in: the STT implementation, its model, and a server of one's own with OpenAI's
    audio API."""

    plugin: str
    model: str
    server: str | None = None

    def __post_init__(self) -> None:
        if self.plugin not in TRANSCRIPTION:
            raise ValueError(f"Speech recognition takes {' or '.join(TRANSCRIPTION)}")
        _model(self.model)
        if self.server is None:
            return
        if self.plugin != SPEECH_SERVED["transcription"]:
            raise ValueError(
                "A speech server of your own speaks OpenAI's audio API: openai_segment"
            )
        if problem := server_problem(self.server, speech=True):
            raise ValueError(f"Speech server {self.server}: {problem}")

    @property
    def provider(self) -> str:
        return "openai"

    @property
    def key(self) -> str:
        return server_key(self.server) if self.server else OPENAI_KEY


@dataclass(frozen=True, slots=True)
class Synthesis:
    """Speech out: the TTS implementation, its model and voice, its speed, and a server of
    one's own with OpenAI's audio API. A speed left unset is the reference's where the
    implementation takes one; the reference's instructions stay where the model reads them."""

    plugin: str
    model: str
    speaker: str | None
    speed: float | None = None
    server: str | None = None

    def __post_init__(self) -> None:
        from alphaavatar.agents.configs.plugins.foundation.voice_config import TTSConfig

        if self.plugin not in SYNTHESIS:
            raise ValueError(f"Speech synthesis takes {' or '.join(SYNTHESIS)}")
        _model(self.model)
        if self.plugin == "openai" and not (self.speaker or "").strip():
            raise ValueError("OpenAI speech needs a voice, such as ash")
        if self.speed is not None and not TTSConfig.takes_speed(self.plugin) and self.speed != 1.0:
            raise ValueError(f"{NAMES[self.plugin]} speech takes no speed: it speaks at 1.0")
        if self.speed is not None and not 0.25 <= self.speed <= 4.0:
            raise ValueError("A speed from 0.25 to 4.0")
        if self.server is not None:
            if self.plugin != SPEECH_SERVED["synthesis"]:
                raise ValueError("A speech server of your own speaks OpenAI's audio API: openai")
            if problem := server_problem(self.server, speech=True):
                raise ValueError(f"Speech server {self.server}: {problem}")

    @property
    def provider(self) -> str:
        return self.plugin

    @property
    def key(self) -> str:
        return server_key(self.server) if self.server else KEYS[self.plugin]


def _task(part: str, name: str) -> tuple[str, ...]:
    return ("init_config", part, "provider", "gateway", "tasks", name)


# Where each part's model is set, by section and path: the reference's read there, a
# selection's written there, an existing bundle's read there to be shown.
MODEL_SETTINGS = {
    "loop": ("loop", ("init_config", "model")),
    "conversation": ("memory", _task("conversation", "memory.conversation_delta")),
    "tool": ("memory", _task("tool", "memory.tool_delta")),
    "environment": ("memory", _task("environment", "memory.env_delta")),
    "profiler": ("persona", _task("profiler", "persona.profile_delta")),
    "embedding": ("memory", ("vdb_config", "embedding")),
}
# Each store's embedding: one chosen for all.
EMBEDDINGS = (
    ("memory", ("vdb_config", "embedding")),
    ("persona", ("vdb_config", "embedding")),
    ("tools", ("mcp", "vdb_config", "embedding")),
)


def _at(settings: Any, *path: str) -> Any:
    for key in path:
        settings = settings.get(key) if isinstance(settings, Mapping) else None
    return settings


def _reference() -> dict[str, Any]:
    """The reference configuration's choices, from the default profiles setup starts from."""
    import yaml

    from alphaavatar.host.configs.template import SECTIONS

    profile = {section: yaml.safe_load(SECTIONS[section]) for section in ("loop", "voice")}
    profile |= {section: yaml.safe_load(SECTIONS[section]) for section in ("memory", "persona")}

    def model(part: str) -> Model:
        section, path = MODEL_SETTINGS[part]
        found = _at(profile[section], *path)
        return Model(found["provider"], found["model"])

    voice = profile["voice"]
    return {
        **{part: model(part) for part in MODEL_SETTINGS},
        "transcription": Transcription(voice["stt"]["plugin"], voice["stt"]["model"]),
        "synthesis": Synthesis(
            voice["tts"]["plugin"], voice["tts"]["model"], voice["tts"]["speaker"]
        ),
        "speed": voice["tts"]["speed"],
    }


REFERENCE = _reference()


def default_model(part: str, provider: str, server: str | None = None) -> str | None:
    """The model a part's question offers: the reference's, from its own provider only; from
    another provider, or a server of one's own, none, so none is carried over to it. Speech
    names its implementation as the provider."""
    reference = REFERENCE[part]
    same = (getattr(reference, "plugin", None) or reference.provider) == provider
    return reference.model if same and server is None else None


def reusable(part: str, chosen: Model) -> bool:
    """Whether a part can take a model chosen for another, as ``REUSE`` names them."""
    return chosen.provider in PROVIDERS[part] and (chosen.server is None or part in SERVED)


@dataclass(frozen=True, slots=True)
class Selection:
    """What a new bundle runs with: its parts on or off, and each part's model. Unset, a part
    is as the reference configuration has it; the same decision gives the bundle's settings,
    the packages they need, the credentials they read and the summary shown before installing.
    """

    voice: bool = True  # Speech in and out; speech segments come from on-device VAD.
    vision: bool = True  # Camera frames reach the loop's model.
    local_models: bool = True  # Turn taking, addressing, face and speaker models on-device.
    env_memory: bool = True  # Memories drawn from the session's audio and video, by Gemini.
    vector_store: VectorStore = "lancedb"  # Memory and persona vectors: workspace or Qdrant.
    loop: Model = REFERENCE["loop"]
    conversation: Model = REFERENCE["conversation"]
    tool: Model = REFERENCE["tool"]
    environment: Model = REFERENCE["environment"]
    profiler: Model = REFERENCE["profiler"]
    embedding: Model = REFERENCE["embedding"]
    transcription: Transcription = REFERENCE["transcription"]
    synthesis: Synthesis = REFERENCE["synthesis"]

    def __post_init__(self) -> None:
        for part, offered in PROVIDERS.items():
            chosen = getattr(self, part)
            if chosen.provider not in offered:
                raise ValueError(f"{part} takes {', '.join(offered)}, not {chosen.provider}")
            if chosen.server is not None and part not in SERVED:
                raise ValueError(f"{part} takes no server of your own")

    @property
    def speed(self) -> float:
        """The speed speech is synthesized at: as chosen, else the reference's where taken."""
        from alphaavatar.agents.configs.plugins.foundation.voice_config import TTSConfig

        if self.synthesis.speed is not None:
            return self.synthesis.speed
        return REFERENCE["speed"] if TTSConfig.takes_speed(self.synthesis.plugin) else 1.0

    def speech(self) -> tuple[Transcription, Synthesis] | None:
        """Speech in and out as the bundle runs them: none while voice is off, whatever was
        chosen for them; the choice stays in its settings, to switch voice on again."""
        return (self.transcription, self.synthesis) if self.voice else None

    def models(self) -> dict[str, Model]:
        """The parts that run a model: ENV memory's only while it is on."""
        parts = ("loop", "conversation", "tool", "environment", "profiler", "embedding")
        return {p: getattr(self, p) for p in parts if p != "environment" or self.env_memory}


@dataclass(frozen=True, slots=True)
class Credential:
    name: str
    purpose: str
    secret: bool = True
    required: bool = True


def requirements(selection: Selection) -> tuple[str, ...]:
    """The packages the selection's capabilities need, as PEP 508 requirements."""
    host = "alpha-avatar-host[livekit]"  # Sessions reach devices through LiveKit.
    needed = [
        host,
        plugin_requirement("loop"),
        plugin_requirement("context"),
        # The loop's model; the memory and persona tasks and embeddings, by the default backend.
        plugin_requirement("provider", "openai"),
        plugin_requirement("provider", "langchain"),
        plugin_requirement("status"),
        plugin_requirement("router"),
        plugin_requirement("memory"),
        plugin_requirement("persona"),
        vdb_requirement(selection.vector_store),
    ]
    if selection.voice:
        needed += [plugin_requirement("voice"), plugin_requirement("voice", "silero")]
    if selection.voice and selection.local_models:
        needed += [
            plugin_requirement("router", "semantic"),
            plugin_requirement("router", "turn-taking"),
            plugin_requirement("persona", "speaker"),
        ]
    if selection.local_models:
        needed.append(plugin_requirement("persona", "face"))
    return tuple(sorted(needed))


def bundle_requirements(
    host: HostConfig, avatar: AvatarConfig, plugins: Mapping[str, Mapping[str, str]]
) -> tuple[dict[str, str], tuple[str, ...]]:
    """What an existing bundle's settings need, as ``requirements`` gives a selection's, each
    with the first setting that needs it; and the selections nothing here installs.

    Each selected implementation needs what ``plugins`` (the catalog's, by capability type and
    name) says installs it; so do the provider backends its tasks name and its vector stores'
    embeddings. Its vector stores need their backends, and the built-in router and persona
    their runners' extras, by the switches that start those runners; a switch the settings
    leave out counts as on, at worst one package more. Nothing is imported from the plugins:
    a bare base plans with this before any of them is installed.
    """
    from alphaavatar.agents.runtime.plugin import AvatarModule
    from alphaavatar.agents.utils.vdb.config import vdb_backend, vdb_embeddings
    from alphaavatar.host.configs.capabilities import with_extra
    from alphaavatar.host.version import DISTRIBUTION

    needs: dict[str, str] = {}
    unserved: list[str] = []

    def install(location: str, module: AvatarModule, name: str) -> None:
        if (found := plugins.get(module.value, {}).get(name)) is None:
            unserved.append(f"{location}: {module.value} {name!r}")
        else:
            needs.setdefault(found, location)

    needs[with_extra(DISTRIBUTION, host.rtc.backend)] = "host.rtc.backend"
    selected = avatar.plugin_factories()
    for location, (module, name) in selected.items():
        install(location, module, name)
        settings = getattr(avatar.section(location), "init_config", None)
        for kind, backend, at in _tasks(settings, f"{location.rpartition('.')[0]}.init_config"):
            llm = kind == "llm"
            install(
                at, AvatarModule.PROVIDER_LLM if llm else AvatarModule.PROVIDER_EMBEDDING, backend
            )
    stores = {
        "memory.plugin": avatar.memory.vdb_config,
        "persona.plugin": avatar.persona.vdb_config,
    }
    for location, vdb in (*stores.items(), ("tools.mcp.plugin", None)):
        if selected.get(location, (None, None))[1] != "default":
            continue
        # The MCP catalog's runner keeps its own LanceDB; the others use what they configure.
        needs.setdefault(
            vdb_requirement(vdb_backend(vdb) if vdb is not None else "lancedb"), location
        )
        for module, backend in vdb_embeddings():
            install(f"{location} (embeddings)", AvatarModule(module), backend)
    if selected.get("router.plugin", (None, None))[1] == "default":
        router = avatar.router.init_config
        if _on(router, "addressing", "semantic") and avatar.voice.stt.plugin is not None:
            needs.setdefault(
                plugin_requirement("router", "semantic"), "router.init_config.addressing.semantic"
            )
        if _on(router, "turn_taking"):
            needs.setdefault(
                plugin_requirement("router", "turn-taking"), "router.init_config.turn_taking"
            )
    if selected.get("persona.plugin", (None, None))[1] == "default":
        persona = avatar.persona.init_config
        for part in ("speaker", "face"):
            if _on(persona, part):
                needs.setdefault(plugin_requirement("persona", part), f"persona.init_config.{part}")
    return needs, tuple(unserved)


def _on(settings: Any, *path: str) -> bool:
    for key in path:
        settings = settings.get(key, {}) if isinstance(settings, dict) else {}
    return not isinstance(settings, dict) or settings.get("enabled", True) is not False


def _tasks(value: Any, location: str) -> Iterator[tuple[str, str, str]]:
    """Each provider task in a plugin's settings, as start finds them: its kind, its backend
    and where it is; a part switched off has none.

    A task is a mapping with a model name, as ``ProviderTaskConfig`` requires it; what it
    leaves out, its kind and backend, takes that schema's defaults. Other settings name a
    model by ``name``, never by a string ``model``.
    """
    from alphaavatar.agents.configs.plugins.foundation.provider_config import ProviderTaskConfig

    if isinstance(value, dict):
        if value.get("enabled") is False:
            return
        if isinstance(value.get("model"), str):
            fields = ProviderTaskConfig.model_fields
            kind = value.get("kind", fields["kind"].default)
            yield (
                str(getattr(kind, "value", kind)),
                str(value.get("backend", fields["backend"].default)),
                location,
            )
            return
        for key, item in value.items():
            yield from _tasks(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _tasks(item, f"{location}.{index}")


def requirements_offered() -> frozenset[str]:
    """Every requirement some selection installs. Each provider a part takes is served by the
    same packages; its switches and vector store choose them."""
    stores: tuple[VectorStore, ...] = ("lancedb", "qdrant")
    switches = (True, False)
    return frozenset(
        needed
        for voice in switches
        for vision in switches
        for local in switches
        for store in stores
        for needed in requirements(
            Selection(voice=voice, vision=vision, local_models=local, vector_store=store)
        )
    )


# What reads each part's key, in the order the questions name them.
USES = {
    "loop": "the conversation model",
    "conversation": "memory",
    "tool": "tool memory",
    "environment": "ENV memory",
    "profiler": "persona profiles",
    "embedding": "embeddings",
    "transcription": "speech recognition",
    "synthesis": "speech synthesis",
}


def credentials(selection: Selection) -> tuple[Credential, ...]:
    """What the chosen services read: each variable once, with every part that reads it; a
    part switched off reads none, so ENV memory off asks no Google key of its own."""
    parts: dict[str, Model | Transcription | Synthesis] = dict(selection.models())
    if speech := selection.speech():
        parts |= dict(zip(("transcription", "synthesis"), speech, strict=True))
    readers: dict[str, list[str]] = {}
    servers: dict[str, str] = {}
    owners: dict[str, str] = {}
    for part, chosen in parts.items():
        readers.setdefault(chosen.key, []).append(USES[part])
        if chosen.server is not None:
            servers[chosen.key] = chosen.server
        owners[chosen.key] = chosen.provider
    found = []
    for name, users in readers.items():
        what = ", ".join(users)
        if name in servers:
            found.append(
                Credential(name, f"your server {servers[name]}: {what}; any text if it needs none")
            )
        else:
            found.append(Credential(name, f"{what}, from {NAMES[owners[name]]}"))
    found += [
        Credential("LIVEKIT_URL", "the LiveKit server sessions use", secret=False),
        Credential("LIVEKIT_API_KEY", "LiveKit"),
        Credential("LIVEKIT_API_SECRET", "LiveKit"),
    ]
    if selection.vector_store == "qdrant":
        found += [
            Credential("QDRANT_URL", "your Qdrant server", secret=False),
            Credential("QDRANT_API_KEY", "your Qdrant server, if it asks for one", required=False),
        ]
    return tuple(found)


def _takes_instructions(synthesis: Synthesis) -> bool:
    from alphaavatar.agents.configs.plugins.foundation.voice_config import TTSConfig

    return TTSConfig.takes_instructions(synthesis.plugin, synthesis.model)


def public_address(url: str) -> str:
    """A server's address as it may be shown: its scheme, host, port and path, never a
    credential, query or fragment."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        port = ""
    if not parts.scheme or not host:
        return "a server of your own"
    return f"{parts.scheme}://{f'[{host}]' if ':' in host else host}{port}{parts.path}"


def _switch(value: Any) -> bool | None:
    """A switch as the plugins' settings schemas read one (a bool, ``"true"``, ``"no"``, 1, …,
    as pydantic reads ``bool``), whatever interpolation left it as; None for one they refuse."""
    from pydantic import TypeAdapter, ValidationError

    try:
        return TypeAdapter(bool).validate_python(value)
    except ValidationError:
        return None


class _Processor(NamedTuple):
    """How a default plugin's processor chooses its model, as its settings' schema has it: its
    section and name, its switch where unset, the setting naming its gateway task, and the
    task where that is unset (None: there is none, so it must be set)."""

    section: str
    name: str
    enabled: bool
    setting: str
    task: str | None


# The processors of the default memory and persona plugins that run a model of their own, by
# part. Another implementation chooses as it does, which its settings do not tell.
PROCESSORS = {
    "conversation": _Processor("memory", "conversation", True, "task", "memory.conversation_delta"),
    "tool": _Processor("memory", "tool", True, "task", "memory.tool_delta"),
    "environment": _Processor("memory", "environment", False, "task", None),
    "profiler": _Processor(
        "persona", "profiler", True, "profile_delta_task", "persona.profile_delta"
    ),
}


@dataclass(frozen=True, slots=True)
class Part:
    """A part as setup shows it: who runs it (its provider, or for speech its
    implementation), its model and where a server of one's own is (``public_address``);
    whether it runs, and why its model is not told where its settings do not tell it."""

    provider: str | None
    model: str | None
    server: str | None = None
    on: bool | None = True  # None: whether it runs is not told either.
    unknown: str | None = None


@dataclass(frozen=True, slots=True)
class Shown:
    """What a bundle runs with, as shown before installing: a new bundle's selection, or an
    existing bundle's settings, in the same terms."""

    voice: bool
    vision: bool
    local_models: bool
    env_memory: bool | None  # None: not told, as its row in ``models`` says why.
    models: dict[str, Part]  # Each part with a model of its own, by its name in ``LABELS``.
    embeddings: tuple[tuple[Part, tuple[str, ...]], ...]  # Each embedding, and its stores.
    transcription: Part | None  # None: no speech in.
    synthesis: Part | None
    speaker: str | None  # The voice; None, the model's own.
    speed: float | None
    instructions: bool  # Whether the speech model reads instructions.
    # By store: its backend, and where it is (a directory, a server; None, the workspace's).
    vectors: dict[str, tuple[str, str | None]]
    tools: tuple[str, ...]  # Each tool on, described.


def shown(selection: Selection) -> Shown:
    """A new bundle's selection as shown: one embedding for its stores, no tool on."""

    def part(chosen: Model | Transcription | Synthesis, provider: str) -> Part:
        return Part(provider, chosen.model, chosen.server and public_address(chosen.server))

    speech = selection.speech()
    store = (selection.vector_store, None)
    models = selection.models()
    embedding = models.pop("embedding")
    return Shown(
        voice=selection.voice,
        vision=selection.vision,
        local_models=selection.local_models,
        env_memory=selection.env_memory,
        models={name: part(m, m.provider) for name, m in models.items()},
        embeddings=((part(embedding, embedding.provider), ("memory", "persona")),),
        transcription=speech and part(speech[0], speech[0].plugin),
        synthesis=speech and part(speech[1], speech[1].plugin),
        speaker=selection.synthesis.speaker,
        speed=selection.speed,
        instructions=_takes_instructions(selection.synthesis),
        vectors={"memory": store, "persona": store},
        tools=(),
    )


def bundle_shown(avatar: Any, needs: Mapping[str, str]) -> Shown:
    """An existing bundle as shown, from its settings as written and what its plan installs
    (``needs``, from ``bundle_requirements``): each processor's model as the task it selects
    names it, off where switched off; each store's embedding and where it is; each tool on.
    Nothing is imported from the plugins: what a default leaves to them is their schema's
    (``PROCESSORS``), and what another implementation chooses is said not to be told."""
    from alphaavatar.agents.configs.plugins.foundation.voice_config import TTSConfig
    from alphaavatar.agents.utils.vdb.config import vdb_backend

    settings = avatar.model_dump()
    local = ("router", "semantic"), ("router", "turn-taking"), ("persona", "speaker")
    local += (("persona", "face"),)
    mcp = settings["tools"]["mcp"]

    def part(found: Any, provider: str | None = None, *, on: bool = True) -> Part | None:
        if not isinstance(found, Mapping) or not found.get("model"):
            return None
        server = found.get("base_url") or _at(found, "extra", "base_url")
        name = provider or str(found.get("provider") or "openai")
        return Part(name, str(found["model"]), server and public_address(str(server)), on=on)

    def processor(chooses: _Processor) -> Part | None:
        # As start chooses it: the task its provider names, else its schema's default.
        plugin = _at(settings, chooses.section, "plugin")
        if plugin is None:
            return None  # No part of the section runs.
        if plugin != "default":
            return Part(None, None, on=None, unknown=f"as {chooses.section} {plugin!r} chooses it")
        found = _at(settings, chooses.section, "init_config", chooses.name)
        found = found if isinstance(found, Mapping) else {}
        if (on := _switch(found.get("enabled", chooses.enabled))) is None:
            why = f"its switch {found['enabled']!r} is not true or false"
            return Part(None, None, on=None, unknown=why)
        provider = found.get("provider") if isinstance(found.get("provider"), Mapping) else {}
        task = provider[chooses.setting] if chooses.setting in provider else chooses.task
        if task and (model := part(_at(provider, "gateway", "tasks", task), on=on)) is not None:
            return model
        if not on:
            return Part(None, None, on=False)
        why = f"its task {task!r} is not in its gateway" if task else "no task set"
        return Part(None, None, unknown=why)

    models = {}
    if _at(settings, "loop", "plugin") is not None:
        section, path = MODEL_SETTINGS["loop"]
        if (loop := part(_at(settings, section, *path))) is not None:
            models["loop"] = loop
    for name, chooses in PROCESSORS.items():
        if (found := processor(chooses)) is not None:
            models[name] = found
    # ENV memory on or off as its processor's row says, or not told with it.
    env_memory = models["environment"].on if "environment" in models else False

    # Each store's embedding, those alike in one: memory, persona and MCP where they run.
    uses: dict[Part, list[str]] = {}
    for section, path in EMBEDDINGS:
        if section == "tools":
            runs = bool(mcp.get("enabled") and mcp.get("plugin"))
        else:
            runs = _at(settings, section, "plugin") is not None
        if runs and (found := part(_at(settings, section, *path))) is not None:
            uses.setdefault(found, []).append("MCP" if section == "tools" else section)

    stt, tts = settings["voice"]["stt"], settings["voice"]["tts"]
    transcription = part(stt, stt["plugin"]) if stt.get("plugin") else None
    synthesis = part(tts, tts["plugin"]) if tts.get("plugin") else None

    vectors = {}
    for section in ("memory", "persona"):
        vdb = _at(settings, section, "vdb_config")
        if _at(settings, section, "plugin") is None or not isinstance(vdb, Mapping):
            continue
        backend = vdb_backend(dict(vdb))
        if backend == "qdrant":
            where = public_address(vdb["url"]) if vdb.get("url") else f"{vdb['host']}:{vdb['port']}"
        else:
            where = str(vdb["client_path"]) if vdb.get("client_path") else None
        vectors[section] = (backend, where)

    tools = []
    for name, shown_as in (("deepresearch", "DeepResearch"), ("rag", "RAG")):
        if plugin := _at(settings, "tools", name, "plugin"):
            tools.append(f"{shown_as} ({plugin})")
    if mcp.get("enabled") and mcp.get("plugin"):
        servers = len(mcp.get("servers") or {})
        tools.append(f"MCP ({mcp['plugin']}, {servers} server{'' if servers == 1 else 's'})")

    plugin = tts.get("plugin")
    return Shown(
        voice=stt.get("plugin") is not None or plugin is not None,
        vision=bool(avatar.vision.enabled),
        local_models=any(plugin_requirement(*part) in needs for part in local),
        env_memory=env_memory,
        models=models,
        embeddings=tuple((found, tuple(users)) for found, users in uses.items()),
        transcription=transcription,
        synthesis=synthesis,
        speaker=tts.get("speaker"),
        speed=(tts.get("speed") if TTSConfig.takes_speed(plugin) else 1.0) if plugin else None,
        instructions=bool(plugin) and TTSConfig.takes_instructions(plugin, tts.get("model")),
        vectors=vectors,
        tools=tuple(tools),
    )


def _changes(selection: Selection) -> dict[str, list[Change]]:
    """Each setting of the default profiles the selection changes, by profile."""
    from alphaavatar.agents.configs.plugins.foundation.voice_config import TTSConfig
    from alphaavatar.host.configs.template import Change

    found: dict[str, list[Change]] = {}

    def put(
        section: str, *path: str, value: Any, note: str | None = None, after: str | None = None
    ) -> None:
        found.setdefault(section, []).append(Change(path, value, note, after))

    def model(section: str, path: tuple[str, ...], chosen: Model, reference: Model) -> None:
        if chosen.provider != reference.provider:
            put(section, *path, "provider", value=chosen.provider)
        if chosen.model != reference.model:
            put(section, *path, "model", value=chosen.model)
        if chosen.server is not None:
            put(
                section,
                *path,
                "extra",
                value={"base_url": chosen.server, "api_key_env": chosen.key},
            )

    if not selection.vision:
        put("vision", "enabled", value=False)
    if not (selection.voice and selection.local_models):
        put("router", "init_config", "addressing", "semantic", "enabled", value=False)
        put("router", "init_config", "turn_taking", "enabled", value=False)
        put("persona", "init_config", "speaker", "enabled", value=False)
    if not selection.local_models:
        # Visual addressing reads the faces persona finds.
        put("router", "init_config", "addressing", "visual", "enabled", value=False)
        put("persona", "init_config", "face", "enabled", value=False)
    if not selection.env_memory:
        put("memory", "init_config", "environment", "enabled", value=False)

    for part, (section, path) in MODEL_SETTINGS.items():
        if part != "embedding":
            model(section, path, getattr(selection, part), REFERENCE[part])
    for section, path in EMBEDDINGS:
        model(section, path, selection.embedding, REFERENCE["embedding"])

    # Voice decides whether each part runs: off, none does, what was chosen kept beside it.
    stt, tts = selection.transcription, selection.synthesis
    for part, plugin, reference in (
        ("vad", "silero", "silero"),
        ("stt", stt.plugin, REFERENCE["transcription"].plugin),
        ("tts", tts.plugin, REFERENCE["synthesis"].plugin),
    ):
        if selection.speech() is None:
            put("voice", part, "plugin", value=None, note=f"Voice off; {plugin} turns it on.")
        elif plugin != reference:
            put("voice", part, "plugin", value=plugin)
    if stt.model != REFERENCE["transcription"].model:
        put("voice", "stt", "model", value=stt.model)
    for key, reference, chosen in (
        ("model", REFERENCE["synthesis"].model, tts.model),
        ("speaker", REFERENCE["synthesis"].speaker, tts.speaker),
    ):
        if chosen != reference:
            put("voice", "tts", key, value=chosen)
    if selection.speed != REFERENCE["speed"]:
        takes = TTSConfig.takes_speed(tts.plugin)
        put(
            "voice",
            "tts",
            "speed",
            value=selection.speed,
            note=None if takes else "Voice.ai takes no speed.",
        )
    if not TTSConfig.takes_instructions(tts.plugin, tts.model):
        reads = "Voice.ai takes" if tts.plugin == "voiceai" else f"{tts.model} takes"
        put("voice", "tts", "instructions", value=None, note=f"{reads} no instructions.")
    for part, chosen in (("stt", stt), ("tts", tts)):
        if chosen.server is not None:
            put("voice", part, "base_url", value=chosen.server)
            put("voice", part, "api_key_env", value=chosen.key)

    for section in ("memory", "persona"):
        if selection.vector_store == "qdrant":
            # Resolved from the environment, or the stored credentials, when the bundle loads.
            put(
                section,
                "vdb_config",
                "url",
                value="${oc.env:QDRANT_URL}",
                note="Your Qdrant server.",
            )
            put(
                section, "vdb_config", "api_key", value="${oc.env:QDRANT_API_KEY,null}", after="url"
            )
    return found


def sections(selection: Selection) -> dict[str, str]:
    """The default profiles the selection changes, each changed in place: every other setting,
    comment and blank line as the profile ships."""
    from alphaavatar.host.configs.template import SECTIONS, change_profile

    return {
        section: "# Chosen with `alphaavatar setup`.\n" + change_profile(SECTIONS[section], found)
        for section, found in _changes(selection).items()
    }

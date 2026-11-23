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
from typing import TYPE_CHECKING, Any, Literal
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
TRANSCRIPTION = ("openai_segment", "openai_realtime")
SYNTHESIS = ("openai", "voiceai")
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
        if self.server is not None and (problem := server_problem(self.server, speech=True)):
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
            if self.plugin != "openai":
                raise ValueError("A speech server of your own speaks OpenAI's audio API: openai")
            if problem := server_problem(self.server, speech=True):
                raise ValueError(f"Speech server {self.server}: {problem}")

    @property
    def provider(self) -> str:
        return self.plugin

    @property
    def key(self) -> str:
        return server_key(self.server) if self.server else KEYS[self.plugin]


def _reference() -> dict[str, Any]:
    """The reference configuration's choices, from the default profiles setup starts from."""
    import yaml

    from alphaavatar.host.configs.template import SECTIONS

    profile = {section: yaml.safe_load(SECTIONS[section]) for section in ("loop", "voice")}
    profile |= {section: yaml.safe_load(SECTIONS[section]) for section in ("memory", "persona")}

    def task(section: str, part: str, name: str) -> Model:
        found = profile[section]["init_config"][part]["provider"]["gateway"]["tasks"][name]
        return Model(found["provider"], found["model"])

    loop, voice = profile["loop"]["init_config"]["model"], profile["voice"]
    embedding = profile["memory"]["vdb_config"]["embedding"]
    return {
        "loop": Model(loop["provider"], loop["model"]),
        "conversation": task("memory", "conversation", "memory.conversation_delta"),
        "tool": task("memory", "tool", "memory.tool_delta"),
        "environment": task("memory", "environment", "memory.env_delta"),
        "profiler": task("persona", "profiler", "persona.profile_delta"),
        "embedding": Model(embedding["provider"], embedding["model"]),
        "transcription": Transcription(voice["stt"]["plugin"], voice["stt"]["model"]),
        "synthesis": Synthesis(
            voice["tts"]["plugin"], voice["tts"]["model"], voice["tts"]["speaker"]
        ),
        "speed": voice["tts"]["speed"],
    }


REFERENCE = _reference()


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
    if selection.voice:
        parts |= {"transcription": selection.transcription, "synthesis": selection.synthesis}
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


def capabilities(selection: Selection) -> tuple[str, ...]:
    """What the selection runs with, in words, as shown before anything is installed."""
    on = {True: "on", False: "off"}
    store = {"lancedb": "LanceDB in the Avatar workspace", "qdrant": "your Qdrant server"}
    found = [
        f"voice {on[selection.voice]} · vision {on[selection.vision]} · models on this machine "
        f"{on[selection.local_models]} · ENV memory {on[selection.env_memory]}",
        "sessions through LiveKit",
        f"conversation: {selection.loop.describe()}",
        f"memory: {selection.conversation.describe()}; tool memory {selection.tool.describe()}",
    ]
    if selection.env_memory:
        found.append(f"ENV memory: {selection.environment.describe()}, from audio and video")
    found += [
        f"persona profiles: {selection.profiler.describe()}",
        f"embeddings: {selection.embedding.describe()}",
    ]
    if selection.voice:
        stt, tts = selection.transcription, selection.synthesis
        found.append(
            f"speech in: {stt.plugin} {stt.model}" + (f" on {stt.server}" * bool(stt.server))
        )
        voice = f", voice {tts.speaker}" if tts.speaker else ""
        found.append(
            f"speech out: {tts.plugin} {tts.model}{voice}, speed {selection.speed:g}"
            + (f" on {tts.server}" * bool(tts.server))
        )
    if selection.local_models:
        local = "turn taking, addressing, speaker and face recognition"
        found.append(f"models on this machine: {local if selection.voice else 'face recognition'}")
    found += [
        f"memory and persona: vectors in {store[selection.vector_store]}",
        "tools: none on; switched on in the tools profile, `alphaavatar setup <bundle>` installs "
        "DeepResearch and MCP, and this release's setup does not offer RAG",
    ]
    return tuple(found)


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

    if not selection.voice:
        for part, plugin in (("vad", "silero"), ("stt", "openai_segment"), ("tts", "openai")):
            put("voice", part, "plugin", value=None, note=f"Voice off; {plugin} turns it on.")
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

    model("loop", ("init_config", "model"), selection.loop, REFERENCE["loop"])
    for section, part, task in (
        ("memory", "conversation", "memory.conversation_delta"),
        ("memory", "tool", "memory.tool_delta"),
        ("memory", "environment", "memory.env_delta"),
        ("persona", "profiler", "persona.profile_delta"),
    ):
        path = ("init_config", part, "provider", "gateway", "tasks", task)
        model(section, path, getattr(selection, part), REFERENCE[part])
    for section, path in (
        ("memory", ("vdb_config", "embedding")),
        ("persona", ("vdb_config", "embedding")),
        ("tools", ("mcp", "vdb_config", "embedding")),
    ):
        model(section, path, selection.embedding, REFERENCE["embedding"])

    stt, tts = selection.transcription, selection.synthesis
    for key, reference, chosen in (
        ("plugin", REFERENCE["transcription"].plugin, stt.plugin),
        ("model", REFERENCE["transcription"].model, stt.model),
    ):
        if chosen != reference:
            put("voice", "stt", key, value=chosen)
    for key, reference, chosen in (
        ("plugin", REFERENCE["synthesis"].plugin, tts.plugin),
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

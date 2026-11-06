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

A selection becomes the sections of a bundle, the requirements its capabilities need, and the
credentials its backends read. Any device, the Linux CLI or an App, chooses with these; only
installing the requirements is the platform's own. The requirements are what
``resolve_capabilities`` finds for the configuration once installed: the tests hold the two
to the same answer for every selection.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from alphaavatar.agents.runtime.plugin import plugin_requirement
from alphaavatar.agents.utils.vdb.config import vdb_requirement

VectorStore = Literal["lancedb", "qdrant"]
OPENAI_KEY = "OPENAI_API_KEY"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


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


def server_key(url: str) -> str:
    """The variable a server of one's own reads its key from, named after that endpoint: a key
    serves only the server it was given for, and only the same endpoint shares one."""
    parts = urlsplit(url)
    port = parts.port or {"http": 80, "https": 443}[parts.scheme]
    endpoint = f"{parts.scheme}://[{parts.hostname}]:{port}{parts.path.rstrip('/')}"
    return "ALPHAAVATAR_SERVER_KEY_" + hashlib.sha256(endpoint.encode()).hexdigest()[:12].upper()


@dataclass(frozen=True, slots=True)
class Models:
    """An OpenAI-compatible server of one's own for the models: the loop's through the
    Responses API, which it streams; the memory and persona tasks' and the embeddings."""

    url: str  # Its API root, e.g. http://gpu-host:8000/v1
    chat: str  # The loop's model
    tasks: str  # Memory and persona tasks
    embedding: str

    def __post_init__(self) -> None:
        if problem := server_problem(self.url, speech=False):
            raise ValueError(f"Model server {self.url}: {problem}")


@dataclass(frozen=True, slots=True)
class Speech:
    """An OpenAI-compatible server of one's own for transcription and speech."""

    url: str  # HTTPS unless on this machine, e.g. https://speech-host:8001/v1
    transcription: str
    synthesis: str
    voice: str

    def __post_init__(self) -> None:
        if problem := server_problem(self.url, speech=True):
            raise ValueError(f"Speech server {self.url}: {problem}")


@dataclass(frozen=True, slots=True)
class Selection:
    voice: bool = True  # Speech in and out; speech segments come from on-device VAD.
    vision: bool = True  # Camera frames reach the loop's model.
    local_models: bool = True  # Turn taking, addressing, face and speaker models on-device.
    vector_store: VectorStore = "lancedb"  # Memory and persona vectors: workspace or Qdrant.
    models: Models | None = None  # None: OpenAI's.
    speech: Speech | None = None  # None: OpenAI's; with voice only.


# The reference bundle, as `config init` writes it; and every inference remote except the
# voice activity detection speech input needs.
PRESETS = {"default": Selection(), "remote": Selection(local_models=False)}


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


def requirements_offered() -> frozenset[str]:
    """Every requirement some selection installs."""
    stores: tuple[VectorStore, ...] = ("lancedb", "qdrant")
    switches = (True, False)
    return frozenset(
        needed
        for voice in switches
        for vision in switches
        for local in switches
        for store in stores
        for needed in requirements(Selection(voice, vision, local, store))
    )


def speech_key(selection: Selection) -> str | None:
    """The variable speech reads its key from: OpenAI's, or its server's own."""
    if not selection.voice:
        return None
    return OPENAI_KEY if selection.speech is None else server_key(selection.speech.url)


def credentials(selection: Selection) -> tuple[Credential, ...]:
    """What the selection's services read: OpenAI's key, and each own server's by its URL."""
    official = {
        (True, True): "the model, embeddings, memory/persona tasks and speech",
        (True, False): "the model, embeddings and memory/persona tasks",
        (False, True): "speech",
    }.get((selection.models is None, speech_key(selection) == OPENAI_KEY))
    found = [Credential(OPENAI_KEY, f"OpenAI's {official}")] if official else []
    servers = [selection.models.url] if selection.models else []
    if selection.voice and selection.speech:
        servers.append(selection.speech.url)
    for name, url in {server_key(url): url for url in servers}.items():
        found.append(Credential(name, f"your server {url}; any text if it needs none"))
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
    """What the selection does, in words."""
    store = {"lancedb": "LanceDB in the Avatar workspace", "qdrant": "your Qdrant server"}
    models, speech = selection.models, selection.speech
    found = ["sessions through LiveKit"]
    found.append(
        f"models from {models.url}: {models.chat}; tasks {models.tasks}; "
        f"embeddings {models.embedding}"
        if models
        else "model and embeddings from OpenAI"
    )
    if selection.voice:
        found.append(
            f"speech from {speech.url}: {speech.transcription}, {speech.synthesis} ({speech.voice})"
            if speech
            else "speech from OpenAI"
        )
    if selection.voice:
        found.append("voice: speech in and out, voice activity detected on this machine")
    found.append("vision: camera frames reach the model" if selection.vision else "vision off")
    if selection.local_models:
        local = "turn taking, addressing, speaker and face recognition"
        if not selection.voice:
            local = "face recognition"
        found.append(f"models on this machine: {local}")
    else:
        found.append("no other models on this machine")
    found.append(f"memory and persona: vectors in {store[selection.vector_store]}")
    return tuple(found)


def sections(selection: Selection) -> dict[str, str]:
    """The bodies of the template sections the selection changes, as profile texts."""
    import yaml

    from alphaavatar.host.configs.template import SECTIONS

    changed: dict[str, Any] = {}

    def edit(section: str, *path: str, value: Any) -> None:
        body = changed.setdefault(section, yaml.safe_load(SECTIONS[section]))
        for key in path[:-1]:
            body = body.setdefault(key, {})
        body[path[-1]] = value

    if not selection.voice:
        for part in ("vad", "stt", "tts"):
            changed.setdefault("voice", {})[part] = {"plugin": None}
    if not selection.vision:
        edit("vision", "enabled", value=False)
    if not (selection.voice and selection.local_models):
        edit("router", "init_config", "addressing", "semantic", "enabled", value=False)
        edit("router", "init_config", "turn_taking", "enabled", value=False)
        edit("persona", "init_config", "speaker", "enabled", value=False)
    if not selection.local_models:
        # Visual addressing reads the faces persona finds.
        edit("router", "init_config", "addressing", "visual", "enabled", value=False)
        edit("persona", "init_config", "face", "enabled", value=False)
    if models := selection.models:
        server = {"base_url": models.url, "api_key_env": server_key(models.url)}
        edit(
            "loop",
            "init_config",
            "model",
            value={
                "backend": "openai",
                "provider": "openai",
                "model": models.chat,
                "extra": server,
            },
        )
        for section, part, task in (
            ("memory", "conversation", "memory.conversation_delta"),
            ("memory", "tool", "memory.tool_delta"),
            ("persona", "profiler", "persona.profile_delta"),
        ):
            settings = {"provider": "openai", "model": models.tasks, "temperature": 0.1}
            edit(
                section,
                "init_config",
                part,
                "provider",
                "gateway",
                "tasks",
                task,
                value=settings | {"extra": server},
            )
        for section in ("memory", "persona"):
            embedding = {"provider": "openai", "model": models.embedding, "extra": server}
            edit(section, "vdb_config", "embedding", value=embedding)
    if (speech := selection.speech) and selection.voice:
        edit("voice", "stt", "model", value=speech.transcription)
        edit("voice", "stt", "base_url", value=speech.url)
        edit("voice", "tts", "model", value=speech.synthesis)
        edit("voice", "tts", "speaker", value=speech.voice)
        edit("voice", "tts", "base_url", value=speech.url)
        for part in ("stt", "tts"):
            edit("voice", part, "api_key_env", value=speech_key(selection))
    for section in ("memory", "persona"):
        if selection.vector_store == "qdrant":
            # Resolved from the environment, or the stored credentials, when the bundle loads.
            edit(section, "vdb_config", "url", value="${oc.env:QDRANT_URL}")
            edit(section, "vdb_config", "api_key", value="${oc.env:QDRANT_API_KEY,null}")
        else:
            # Explicitly none: a QDRANT_URL in the environment does not move the vectors.
            edit(section, "vdb_config", "url", value=None)
    return {
        section: "# Chosen with `alphaavatar setup`.\n"
        + yaml.safe_dump(body, sort_keys=False, allow_unicode=True)
        for section, body in changed.items()
    }

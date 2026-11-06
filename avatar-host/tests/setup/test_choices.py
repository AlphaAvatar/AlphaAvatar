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
"""What setup offers: each selection asks for exactly what its bundle needs once installed."""

from __future__ import annotations

import asyncio
import importlib.util
import itertools
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import pytest
import yaml
from omegaconf import OmegaConf
from pydantic import BaseModel

# Imported at collection: the persona plugin's OpenCV adjusts process variables (O-2).
import alphaavatar.plugins.persona.factory  # noqa: F401
from alphaavatar.agents.runtime.inference import plan_inference_runners
from alphaavatar.host.configs import resolve_capabilities, validate_application
from alphaavatar.host.configs.template import render_bundle
from alphaavatar.host.setup.choices import (
    OPENAI_KEY,
    PRESETS,
    Models,
    Selection,
    Speech,
    credentials,
    requirements,
    sections,
    server_key,
    server_problem,
)
from alphaavatar.host.setup.plan import plan_install
from alphaavatar.host.workspace import ApplicationPaths

ROOT = Path(__file__).resolve().parents[3]
SELECTIONS = [
    Selection(*values)
    for values in itertools.product(
        (True, False), (True, False), (True, False), ("lancedb", "qdrant")
    )
]
# Models and the libraries that run them, besides Silero's ONNX Runtime; and CUDA.
LOCAL = {
    "insightface",
    "llama-cpp-python",
    "onnx",
    "safetensors",
    "scikit-image",
    "scipy",
    "tokenizers",
    "torch",
    "torchaudio",
    "transformers",
}


def compose(selection: Selection, home: Path):
    texts = render_bundle("chosen", "chosen", sections=sections(selection))
    bundle = yaml.safe_load(texts["bundles/chosen.yaml"])
    for section, reference in bundle.pop("profiles").items():
        bundle[section] = yaml.safe_load(texts[f"profiles/{reference}.yaml"])
    resolved = OmegaConf.to_container(OmegaConf.create(bundle), resolve=True)
    return validate_application(resolved, paths=ApplicationPaths.from_root(home))


def label(selection: Selection) -> str:
    parts = (selection.voice, selection.vision, selection.local_models, selection.vector_store)
    return "-".join(map(str, parts))


@pytest.mark.parametrize("selection", SELECTIONS, ids=label)
def test_each_selection_asks_for_exactly_what_its_bundle_resolves_to(
    selection: Selection, tmp_path: Path
) -> None:
    # An endpoint in the environment moves no vector store a LanceDB selection chose.
    with mock.patch.dict(os.environ, {"QDRANT_URL": "http://qdrant.invalid:6333"}):
        config = compose(selection, tmp_path / "home")
        found = sorted({need.requirement for need in resolve_capabilities(config).needs})
    assert found == list(requirements(selection))
    names = [credential.name for credential in credentials(selection) if credential.required]
    assert ("QDRANT_URL" in names) == (selection.vector_store == "qdrant")


def test_own_servers_take_what_the_installed_providers_send_there(tmp_path: Path) -> None:
    from alphaavatar.plugins.provider.openai.llms.config import OpenAIClientConfig

    models = Models("http://gpu.invalid:8000/v1", "qwen3-32b", "qwen3-8b", "bge-m3")
    speech = Speech("https://speech.invalid:8001/v1", "whisper-large-v3", "kokoro", "af_heart")
    own = Selection(models=models, speech=speech)
    config = compose(own, tmp_path / "home")
    models_key, speech_key = server_key(models.url), server_key(speech.url)
    avatar, server = config.avatar, {"base_url": models.url, "api_key_env": models_key}
    loop = avatar.loop.init_config["model"]
    assert (loop["backend"], loop["model"], loop["extra"]) == ("openai", "qwen3-32b", server)
    # The loop's Responses client is pointed at the server; tasks and embeddings go there too.
    assert OpenAIClientConfig.model_validate(loop["extra"]).base_url == models.url
    tasks = avatar.persona.init_config["profiler"]["provider"]["gateway"]["tasks"]
    assert tasks["persona.profile_delta"] == {
        "provider": "openai",
        "model": "qwen3-8b",
        "temperature": 0.1,
        "extra": server,
    }
    for section in (avatar.memory, avatar.persona):
        assert section.vdb_config["embedding"] == {
            "provider": "openai",
            "model": "bge-m3",
            "extra": server,
        }
    voice = avatar.voice
    assert (voice.stt.base_url, voice.stt.model) == (speech.url, "whisper-large-v3")
    assert (voice.tts.base_url, voice.tts.model, voice.tts.speaker) == (
        speech.url,
        "kokoro",
        "af_heart",
    )
    assert voice.stt.api_key_env == voice.tts.api_key_env == speech_key != models_key
    # The same packages serve them; each server's key is whatever that server expects.
    found = sorted({need.requirement for need in resolve_capabilities(config).needs})
    assert found == list(requirements(own)) == list(requirements(Selection()))
    asked = {credential.name: credential.purpose for credential in credentials(own)}
    assert OPENAI_KEY not in asked
    assert asked[models_key] == f"your server {models.url}; any text if it needs none"
    assert asked[speech_key] == f"your server {speech.url}; any text if it needs none"


class Server:
    """A server of one's own: it refuses every request, keeping the key each one carried."""

    def __init__(self) -> None:
        keys = self.keys = []

        class Refuse(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                keys.append(self.headers.get("Authorization"))
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                body = b'{"error": {"message": "refused", "type": "invalid_request_error"}}'
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True

            def log_message(self, *args: object) -> None:
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Refuse)
        self.url = f"http://127.0.0.1:{self.http.server_port}/v1"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.http.shutdown()
        self.http.server_close()


async def _request_each(avatar, models: bool, speech: bool) -> None:
    """One request from each backend the session would point at a server of one's own."""
    from alphaavatar.agents.avatar.provider.enums import ModelRole
    from alphaavatar.agents.avatar.provider.factory import create_llm_model
    from alphaavatar.agents.avatar.provider.schemas import (
        ModelInput,
        ModelInputMessage,
        ModelRequest,
        ModelTextPart,
    )
    from alphaavatar.agents.configs.plugins.foundation.provider_config import ProviderTaskConfig
    from alphaavatar.core.media import AudioFrame

    class Answer(BaseModel):
        text: str

    said = ModelInput((ModelInputMessage("m", ModelRole.USER, (ModelTextPart("Hello"),)),))
    attempts = []
    if models:
        loop = create_llm_model(ProviderTaskConfig.model_validate(avatar.loop.init_config["model"]))
        tasks = avatar.persona.init_config["profiler"]["provider"]["gateway"]["tasks"]
        task = create_llm_model(ProviderTaskConfig.model_validate(tasks["persona.profile_delta"]))

        async def responses() -> None:
            async with loop.stream(ModelRequest(said)) as events:
                async for _ in events:
                    pass

        attempts += [responses(), task.ainvoke_structured(said, output_schema=Answer)]
    if speech:
        stt, tts = avatar.voice.stt.get_plugin(), avatar.voice.tts.get_plugin()

        async def transcription() -> None:
            async with stt.stream(source_id="probe") as stream:
                stream.push_frame(AudioFrame(16000, 1, 8000, bytes(16000)), segment_id="s")
                stream.commit_segment("s")
                stream.end_input()
                async for _ in stream:
                    pass

        async def synthesis() -> None:
            async for _ in tts.synthesize("Hello."):
                pass

        attempts += [transcription(), synthesis()]
    for attempt in attempts:
        try:
            await asyncio.wait_for(attempt, 30)
        except Exception:
            pass  # Refused: what matters is the key the request carried.
    if speech:
        await tts.aclose()


@pytest.mark.parametrize("own", ["models", "speech", "both", "one server"])
def test_each_server_of_ones_own_receives_its_own_key_and_never_openais(
    own: str, tmp_path: Path, owned_endpoints: set[object]
) -> None:
    model_server, speech_server = Server(), Server()
    if own == "one server":
        speech_server.close()
        speech_server = model_server
    for server in (model_server, speech_server):
        owned_endpoints.add(server.http.server_address[:2])
    try:
        check_keys(own, model_server, speech_server, tmp_path)
    finally:
        for server in {id(model_server): model_server, id(speech_server): speech_server}.values():
            server.close()


def check_keys(own: str, model_server: Server, speech_server: Server, tmp_path: Path) -> None:
    from alphaavatar.agents.avatar.provider.factory import create_embedding_model
    from alphaavatar.agents.configs.plugins.foundation.provider_config import ProviderTaskConfig

    models = Models(model_server.url, "chat", "tasks", "embed")
    speech = Speech(speech_server.url, "transcribe", "speak", "voice")
    selection = Selection(
        models=models if own != "speech" else None, speech=speech if own != "models" else None
    )
    MODELS_KEY, SPEECH_KEY = server_key(model_server.url), server_key(speech_server.url)
    keys = {OPENAI_KEY: "sk-openai-fictional", MODELS_KEY: "models-fictional"}
    if SPEECH_KEY != MODELS_KEY:
        keys[SPEECH_KEY] = "speech-fictional"
    names = {credential.name for credential in credentials(selection)}
    proxies = dict.fromkeys(("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy"), "")
    with mock.patch.dict(os.environ, keys | proxies):
        avatar = compose(selection, tmp_path / "home").avatar
        asyncio.run(_request_each(avatar, own != "speech", own != "models"))
        embedding = avatar.memory.vdb_config["embedding"]
        embedder = create_embedding_model(
            ProviderTaskConfig.model_validate(embedding | {"kind": "embedding"})
        )
    model_key = f"Bearer {keys[MODELS_KEY]}"
    if own == "one server":
        assert len(model_server.keys) == 4 and set(model_server.keys) == {model_key}
        assert SPEECH_KEY == MODELS_KEY and names >= {MODELS_KEY} and OPENAI_KEY not in names
    if own in ("models", "both"):
        # The loop's Responses request and a task's, each with the model server's key.
        assert len(model_server.keys) == 2 and set(model_server.keys) == {model_key}
        assert embedder._model.openai_api_key.get_secret_value() == keys[MODELS_KEY]
    if own in ("speech", "both"):
        # A transcription and a synthesis, each with the speech server's key.
        assert len(speech_server.keys) == 2
        assert set(speech_server.keys) == {f"Bearer {keys[SPEECH_KEY]}"}
    # What goes to OpenAI reads OpenAI's key, and it is asked for only then.
    assert (OPENAI_KEY in names) == (own in ("models", "speech"))
    if own == "speech":
        assert "api_key_env" not in avatar.loop.init_config["model"].get("extra", {})
        assert embedder._model.openai_api_key.get_secret_value() == keys[OPENAI_KEY]
    if own == "models":
        assert avatar.voice.stt.api_key_env is avatar.voice.tts.api_key_env is None


def test_a_server_of_ones_own_has_one_key_variable_for_its_endpoint_alone() -> None:
    same = (
        "http://gpu.invalid:8000/v1",
        "http://GPU.invalid:8000/v1/",
        "http://gpu.invalid:8000/v1/",
    )
    assert len({server_key(url) for url in same}) == 1
    # Another port, path, scheme or host is another server: never the same variable.
    others = (
        "http://gpu.invalid:8000/v1",
        "http://gpu.invalid:8001/v1",
        "http://gpu.invalid:8000/v2",
        "https://gpu.invalid:8000/v1",
        "http://cpu.invalid:8000/v1",
    )
    assert len({server_key(url) for url in others}) == len(others)
    assert server_key("https://gpu.invalid/v1") == server_key("https://gpu.invalid:443/v1")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/v1",
        "http://localhost:8000/v1",
        "http://[::1]:8000/v1",
        "https://gpu.invalid/v1",
        "http://gpu.invalid:8000/v1",
        "https://user:pw@gpu.invalid/v1",
        "https://gpu.invalid/v1?key=1",
        "https://gpu.invalid/v1#x",
        "ftp://gpu.invalid/v1",
        "gpu.invalid:8000/v1",
        "https://@gpu.invalid/v1",
        "https://:@gpu.invalid/v1",
        "https://gpu.invalid:99999/v1",
        "https://gpu.invalid:0/v1",
        "https://gpu.invalid:port/v1",
        "http://localhost:65535/v1",
    ],
)
def test_a_server_url_is_taken_where_the_backends_it_serves_take_it(url: str) -> None:
    """The wizard's rule is the backends' own: refused before setup enables anything."""
    from alphaavatar.plugins.provider.openai.llms.config import OpenAIClientConfig
    from alphaavatar.plugins.voice.tts.openai import OpenAITTS

    def accepts(build) -> bool:
        try:
            build()
        except ValueError:
            return False
        return True

    models = accepts(lambda: OpenAIClientConfig(base_url=url))
    speech = accepts(lambda: OpenAITTS(model="m", speaker="s", api_key="k", base_url=url))
    assert (server_problem(url, speech=False) is None) == models
    assert (server_problem(url, speech=True) is None) == speech
    assert accepts(lambda: Models(url, "c", "t", "e")) == models
    assert accepts(lambda: Speech(url, "t", "s", "v")) == speech


def test_the_presets_keep_vision_and_plan_their_runners(tmp_path: Path) -> None:
    default = compose(PRESETS["default"], tmp_path / "default")
    remote = compose(PRESETS["remote"], tmp_path / "remote")
    assert default.avatar.vision.enabled and remote.avatar.vision.enabled
    assert len(plan_inference_runners(default.avatar)) == 8
    # Remote inference keeps the voice activity detection speech segments come from.
    assert sorted(plan_inference_runners(remote.avatar)) == [
        "alphaavatar.memory.vdb.lancedb",
        "alphaavatar.persona.vdb.lancedb",
        "alphaavatar.voice.vad.silero",
    ]


def test_remote_inference_plans_no_local_model_nor_its_accelerators() -> None:
    """From uv.lock through the Linux build's own catalog logic to setup's plan."""
    spec = importlib.util.spec_from_file_location("catalog", ROOT / "packaging/linux/catalog.py")
    assert spec is not None and spec.loader is not None
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)
    keys = catalog.requirement_keys(catalog.Lock(ROOT), ROOT)
    names = sorted({name for closure in keys.values() for name in closure})
    artifact = {"version": "0", "sha256": "0" * 64, "size": 1, "url": None}
    document = {
        "format": 1,
        "version": "0",
        "platform": catalog.PLATFORM,
        "base": sorted({*catalog.base_names(ROOT), *catalog.BASE_MEMBERS}),
        "requirements": {key: sorted(closure) for key, closure in keys.items()},
        "distributions": {name: artifact | {"file": f"{name}.whl"} for name in names},
    }

    def planned(selection: Selection) -> set[str]:
        plan = plan_install(document, requirements(selection), base="base")
        return {item.name for item in plan.artifacts}

    default, remote = planned(PRESETS["default"]), planned(PRESETS["remote"])
    silent = planned(Selection(voice=False, local_models=False))
    assert LOCAL <= default and "onnxruntime" in default
    assert not LOCAL & remote and "onnxruntime" in remote  # Silero VAD only.
    assert not LOCAL & silent and "onnxruntime" not in silent
    for plan in (default, remote, silent):
        # No CUDA library, and only the headless OpenCV.
        assert not {n for n in plan if n.startswith("nvidia-") or n in ("triton", "opencv-python")}
        assert not plan & set(document["base"])

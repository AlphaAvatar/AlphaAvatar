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
"""A minimal application configuration a person completes, then loads like any other."""

from __future__ import annotations

import json
from pathlib import Path

# Credentials stay in the environment (or the .env file named by ENV_FILE), never in the file.
REQUIRED_ENVIRONMENT = (
    ("OPENAI_API_KEY", "model, speech, embedding and memory/persona providers"),
    ("LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET", "session transport (host.rtc)"),
)

_TEMPLATE = """\
# AlphaAvatar application configuration, created by `alphaavatar config init`.
# Never write credentials here. Before `alphaavatar start`, set in the environment or .env:
{environment}
# Optionally validate with `alphaavatar config check <this file>`; start validates it too.
# examples/agent_configs has more options.
# application.home is chosen per platform; set it only to keep data somewhere else.

avatar:
  id: {avatar_id}
  name: Assistant
  introduction: You are a helpful voice AI assistant.

defaults:
  openai_embedding: &openai_embedding
    provider: openai
    model: text-embedding-3-small
  openai_task: &openai_task
    provider: openai
    model: gpt-4o
    temperature: 0.1

loop:
  plugin: realtime
  init_config:
    model:
      backend: openai
      provider: openai
      model: gpt-5.6-luna

voice:
  vad:
    plugin: silero
  stt:
    plugin: openai_segment
    model: gpt-4o-transcribe
  tts:
    plugin: openai
    model: gpt-4o-mini-tts
    speaker: ash

vision:
  enabled: false

memory:
  vdb_config:
    collection_name: memory
    embedding: *openai_embedding
  init_config:
    conversation:
      provider:
        gateway:
          tasks:
            memory.conversation_delta: *openai_task
    tool:
      provider:
        gateway:
          tasks:
            memory.tool_delta: *openai_task

persona:
  vdb_config:
    profiler_collection_name: persona_profiler
    speaker_collection_name: persona_speaker
    face_collection_name: persona_face
    embedding: *openai_embedding
  init_config:
    profiler:
      provider:
        gateway:
          tasks:
            persona.profile_delta: *openai_task

tools:
  deepresearch:
    plugin: null  # Tavily research reads TAVILY_API_KEY when enabled.
  rag:
    plugin: null
  mcp:
    enabled: false
    # Reference credentials with <ENV_VAR> placeholders; they resolve when the file loads:
    # servers:
    #   docs:
    #     url: https://example.com/mcp
    #     headers:
    #       Authorization: Bearer <MCP_DOCS_TOKEN>
"""


def render_template(avatar_id: str) -> str:
    """Render and validate the template; an invalid Avatar ID fails before any file exists."""
    import yaml

    from alphaavatar.agents.configs import AvatarConfig

    text = _TEMPLATE.format(
        # A JSON string is a valid double-quoted YAML scalar for any accepted identifier.
        avatar_id=json.dumps(avatar_id, ensure_ascii=False),
        environment="\n".join(f"#   {name:<50} {use}" for name, use in REQUIRED_ENVIRONMENT),
    )
    AvatarConfig.model_validate(yaml.safe_load(text))
    return text


def write_template(path: str | Path, *, avatar_id: str) -> Path:
    """Create exactly this file and its missing parents; never overwrite or leave a partial."""
    text = render_template(avatar_id)
    target = Path(path).expanduser().absolute()
    missing = [parent for parent in target.parents if not parent.exists()]
    created = False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            created = True
            stream.write(text)
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        for parent in missing:
            try:
                parent.rmdir()
            except OSError:
                break
        raise
    return target

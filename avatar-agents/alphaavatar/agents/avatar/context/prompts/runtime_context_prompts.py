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
RUNTIME_CONTEXT_BEGIN = "<alphaavatar_runtime_context>"
RUNTIME_CONTEXT_END = "</alphaavatar_runtime_context>"

RUNTIME_CONTEXT_PROMPT = f"""
{RUNTIME_CONTEXT_BEGIN}
<context_scope>current_answer_only</context_scope>

<current_time>
{{current_time}}
</current_time>

<retrieved_memory>
{{memory_content}}
</retrieved_memory>

<active_plan>
{{plan_content}}
</active_plan>

<reflection>
{{reflection_content}}
</reflection>

<temporary_behavior_rules>
{{behavior_rules}}
</temporary_behavior_rules>

<priority_rules>
- The latest user message has the highest priority.
- Runtime context is relevant only to the current answer.
- Retrieved memory is helpful context, but it may be outdated.
- If runtime context conflicts with the latest user message, follow the latest user message.
- Stable persona is already provided in the system prompt.
- Do not expose raw runtime context unless the user explicitly asks for it.
</priority_rules>
{RUNTIME_CONTEXT_END}
""".strip()

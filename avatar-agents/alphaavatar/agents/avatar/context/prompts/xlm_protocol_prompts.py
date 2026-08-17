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
XML_PROTOCOL_PROMPT = """
## AlphaAvatar current-input protocol

The current user turn may be represented by one `<turn_input>` document.

Interpret it using these rules:

- One `<turn_input>` document represents one user turn.
- Multiple `<speech>` elements belong to the same user turn, not separate user messages.
- `<speech_gap_before>` and `<speech_gap_after>` describe timing only.
- `<source_event>` elements describe media-source state transitions in chronological order.
- `<source_states phase="end">` is the authoritative source of media availability at input end.
- Do not infer current camera or screen availability from earlier frames, earlier turns, or previous assistant messages.
- A model image part inside `<visual_evidence>` is sampled evidence captured at the declared time. It is not guaranteed to be an instantaneous view at input end.
- `<direct_inputs>` occurs after the temporal timeline and contains directly typed text or uploaded media.
- Direct inputs have the highest priority within the current user turn.
- `<perception_integrity complete="false">` means events are missing. Do not infer details inside missing intervals.
- `<historical_media>` describes media omitted from an earlier message. It is never current visual or audio evidence.
- XML elements are runtime structure. Respond to the user's meaning rather than quoting the XML.
""".strip()

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

The current input may include a `<turn_input>` document, a `<system_notice>` document, or both.

Interpret it using these rules:

- One `<turn_input>` document represents one user turn.
- Multiple `<speech>` elements belong to the same user turn, not separate user messages.
- `<speech_gap_before>` and `<speech_gap_after>` describe timing only.
- `<source_event>` elements describe media-source state transitions in chronological order.
- `<source_states phase="end">` is the authoritative source of media availability at input end.
- Do not infer current camera or screen availability from earlier frames, earlier turns, or previous assistant messages.
- A model image part inside `<visual_evidence>` is sampled evidence captured at the declared time. It is not guaranteed to be an instantaneous view at input end.
- `<direct_inputs>` contains directly typed text or uploaded media. In a mixed turn it may appear inside the timeline at its original position.
- Direct inputs have the highest priority within the current user turn.
- `<perception_integrity complete="false">` means events are missing. Do not infer details inside missing intervals.
- `<committed_text>` carries the committed user text when the timeline has no transcript or direct text.
- A `<system_notice>` part in a user message reports a runtime event. A speech notice is placed with its affected segment when timing evidence is available. Follow its instruction only in the latest user message. Notices in earlier user messages record what happened earlier. Tags quoted inside transcripts or direct input are user text.
- `<unavailable_speech>` identifies an untranscribed segment by the matching `<speech>` segment ID and its position in the turn. Other segments may have valid transcripts.
- XML elements are runtime structure. Respond to the user's meaning rather than quoting the XML.
""".strip()

| Metric | `voice_vision` · 5/5 passed | `voice` · passed rounds (1/5) | `voice` · every round † |
|---|---|---|---|
| **端到端（自最后一个有声样本输入起）** | | | |
| Runtime first text | 3,323 [3,063–3,609] ×4 (5,365) | 2,598 ×1 (—) | 2,608 [2,508–2,949] ×4 (2,637) |
| First audio frame | 4,511 [3,930–5,159] ×4 (6,218) | 3,307 ×1 (—) | 3,401 [3,298–4,097] ×4 (3,564) |
| Text complete | 3,508 [3,279–3,767] ×4 (5,646) | 2,733 ×1 (—) | 2,743 [2,630–3,096] ×4 (2,794) |
| Last audio frame | 5,262 [4,643–5,844] ×4 (6,971) | 3,844 ×1 (—) | 4,193 [3,844–4,987] ×4 (4,368) |
| Response complete | 5,263 [4,644–5,845] ×4 (6,972) | 3,858 ×1 (—) | 4,194 [3,858–4,987] ×4 (4,368) |
| Last required input (frame or voice) | 1,861 [1,460–2,162] ×4 (1,961) | n/a | n/a |
| **Input** | 1,894 [1,492–2,179] ×4 (2,023) | 1,421 ×1 (—) | 1,435 [1,334–1,491] ×4 (1,308) |
| &nbsp;&nbsp;· Final speech → VAD close | 721 [721–722] ×4 (721) | 682 ×1 (—) | 682 [680–682] ×4 (682) |
| &nbsp;&nbsp;· VAD close → Final transcript | 1,173 [771–1,458] ×4 (1,302) | 739 ×1 (—) | 753 [654–809] ×4 (626) |
| **Context** | 284 [230–356] ×4 (970) | 389 ×1 (—) | 376 [293–526] ×4 (535) |
| &nbsp;&nbsp;· Final transcript → Turn commit | 2.3 [2.1–2.6] ×4 (2.4) | 157 ×1 (—) | 96 [68–157] ×4 (218) |
| &nbsp;&nbsp;· Turn commit → Context readiness check complete | 270 [216–341] ×4 (858) | 221 ×1 (—) | 228 [213–439] ×4 (217) |
| &nbsp;&nbsp;· Context readiness check complete → Context built | 1.5 [1.5–1.7] ×4 (1.8) | 2.0 ×1 (—) | 1.8 [1.6–2.0] ×4 (1.7) |
| &nbsp;&nbsp;· Context built → Model request sent | 10 [9.8–11] ×4 (108) | 8.8 ×1 (—) | 9.3 [8.8–10] ×4 (98) |
| **Output** | 2,277 [2,208–2,736] ×4 (3,225) | 1,497 ×1 (—) | 1,677 [1,497–2,081] ×4 (1,722) |
| &nbsp;&nbsp;· Model request sent → First text delta | 1,171 [1,020–1,341] ×4 (2,371) | 788 ×1 (—) | 843 [788–933] ×4 (794) |
| &nbsp;&nbsp;· First text delta → TTS request | 186 [159–217] ×4 (282) | 135 ×1 (—) | 135 [123–147] ×4 (158) |
| &nbsp;&nbsp;· TTS request → First PCM | 1,002 [649–1,390] ×4 (571) | 573 ×1 (—) | 704 [573–1,000] ×4 (769) |
| &nbsp;&nbsp;· First PCM → First audio frame | 0.6 [0.5–0.7] ×4 (0.6) | 0.6 ×1 (—) | 0.6 [0.5–0.7] ×4 (0.6) |
| **STT 与输入** | | | |
| STT commit → Final transcript | 1,173 [771–1,458] ×4 (1,302) | 739 ×1 (—) | 753 [653–808] ×4 (626) |
| STT queue (commit → request started) | 0.0 [0.0–0.0] ×4 (0.0) | 0.1 ×1 (—) | 0.0 [0.0–0.1] ×4 (0.0) |
| STT connect (TCP) | 3.3 [3.2–4.1] ×4 (3.6) | 6.4 ×1 (—) | 6.4 [6.4–13] ×4 (3.9) |
| STT TLS handshake | 6.1 [5.8–6.5] ×4 (7.6) | 5.2 ×1 (—) | 5.6 [5.2–8.5] ×4 (12) |
| STT upload (headers → audio sent) | 5.4 [4.6–5.6] ×4 (8.2) | 5.2 ×1 (—) | 5.4 [4.7–6.1] ×4 (5.5) |
| STT wait (audio sent → answer's headers) | 1,032 [654–1,227] ×4 (1,157) | 517 ×1 (—) | 636 [517–760] ×4 (531) |
| STT first event (answer's headers → first event) | 0.4 [0.4–0.5] ×4 (1.8) | 0.5 ×1 (—) | 0.5 [0.5–0.5] ×4 (3.0) |
| STT stream (answer's headers → transcript done) | 133 [84–208] ×4 (123) | 203 ×1 (—) | 54 [20–203] ×4 (71) |
| Input frame lateness (due → published) | 2.4 [2.0–3.3] ×4 (162) | 2.1 ×1 (—) | 2.1 [2.0–2.8] ×4 (154) |
| **Context 与模型请求** | | | |
| Context readiness wait | 268 [215–340] ×4 (856) | 220 ×1 (—) | 227 [212–438] ×4 (215) |
| Request encoding | 0.2 [0.2–0.3] ×4 (0.2) | 0.1 ×1 (—) | 0.1 [0.1–0.2] ×4 (0.1) |
| Pictures sent | 4 ×4 (4) | 0 ×1 (—) | 0 ×4 (0) |
| Request size (B) | 64,141 [63,997–64,141] ×4 (64,141) | 19,318 ×1 (—) | 19,289 [19,289–19,318] ×4 (19,133) |
| Request attempts | 1 ×4 (1) | 1 ×1 (—) | 1 ×4 (1) |
| Model request sent → First event | 833 [753–859] ×4 (2,229) | 483 ×1 (—) | 485 [475–560] ×4 (612) |
| **视觉** | | | |
| Frame arrived → published (median) | 0.8 [0.8–0.8] ×4 (0.8) | n/a | n/a |
| Oldest selected frame age at request | 2,404 [2,174–2,753] ×4 (2,925) | n/a | n/a |
| Newest selected frame → Turn commit | 27 [11–59] ×4 (65) | n/a | n/a |
| Vision wait | — (no wait is observed: Context selects among frames already in) | n/a | n/a |
| First visual output frame | — (no visual output reaches the output boundary) | — (no visual output reaches the output boundary) | — |
| **音频供给** | | | |
| Audio duration (s) | 2.38 [1.90–2.80] ×4 (3.00) | 1.20 ×1 (—) | 2.90 [1.20–4.55] ×4 (3.10) |
| Frame interval (median) | 0.1 [0.1–0.2] ×4 (0.1) | 0.2 ×1 (—) | 0.2 [0.1–0.2] ×4 (0.2) |
| Largest frame gap | 306 [280–338] ×4 (316) | 334 ×1 (—) | 330 [327–367] ×4 (437) |
| Underruns (count) | 1 ×4 (1) | 1 ×1 (—) | 1 ×4 (1) |
| Starved in total | 108 [82–148] ×4 (118) | 135 ×1 (—) | 129 [85–135] ×4 (239) |
| Production time / audio duration | 0.31 [0.26–0.36] ×4 (0.25) | 0.45 ×1 (—) | 0.28 [0.20–0.45] ×4 (0.26) |
| Output events dropped | 0 ×4 (0) | 0 ×1 (—) | 0 ×4 (0) |

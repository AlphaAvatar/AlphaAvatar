| Metric | `voice_vision` · 5/5 passed | `voice` · passed rounds (1/5) | `voice` · every round † |
|---|---|---|---|
| **端到端（自最后一个有声样本输入起）** | | | |
| Runtime first text | 2,907 [2,439–5,180] ×4 (5,984) | 2,605 ×1 (—) | 2,635 [2,574–2,851] ×4 (3,293) |
| First audio frame | 4,055 [3,573–5,909] ×4 (7,521) | 3,771 ×1 (—) | 3,643 [3,492–3,771] ×4 (4,039) |
| Text complete | 3,092 [2,602–5,325] ×4 (6,168) | 2,689 ×1 (—) | 2,857 [2,689–2,991] ×4 (3,435) |
| Last audio frame | 4,706 [4,212–6,653] ×4 (8,243) | 4,186 ×1 (—) | 4,247 [4,186–4,502] ×4 (4,751) |
| Response complete | 4,707 [4,213–6,653] ×4 (8,244) | 4,187 ×1 (—) | 4,248 [4,187–4,503] ×4 (4,752) |
| Last required input (frame or voice) | 1,511 [1,360–2,160] ×4 (2,460) | n/a | n/a |
| **Input** | 1,531 [1,401–2,173] ×4 (2,481) | 1,481 ×1 (—) | 1,482 [1,307–1,647] ×4 (1,483) |
| &nbsp;&nbsp;· Final speech → VAD close | 720 [719–722] ×4 (720) | 679 ×1 (—) | 680 [679–681] ×4 (681) |
| &nbsp;&nbsp;· VAD close → Final transcript | 810 [680–1,454] ×4 (1,761) | 802 ×1 (—) | 801 [626–967] ×4 (803) |
| **Context** | 255 [235–889] ×4 (365) | 457 ×1 (—) | 346 [272–457] ×4 (525) |
| &nbsp;&nbsp;· Final transcript → Turn commit | 2.0 [1.9–2.2] ×4 (2.3) | 134 ×1 (—) | 95 [70–134] ×4 (184) |
| &nbsp;&nbsp;· Turn commit → Context readiness check complete | 241 [222–876] ×4 (255) | 313 ×1 (—) | 241 [191–313] ×4 (245) |
| &nbsp;&nbsp;· Context readiness check complete → Context built | 1.7 [1.5–2.0] ×4 (2.0) | 1.8 ×1 (—) | 1.8 [1.6–1.9] ×4 (1.8) |
| &nbsp;&nbsp;· Context built → Model request sent | 9.6 [9.5–9.7] ×4 (105) | 8.6 ×1 (—) | 8.5 [8.2–8.6] ×4 (93) |
| **Output** | 2,153 [1,538–3,479] ×4 (4,675) | 1,832 ×1 (—) | 1,785 [1,649–1,992] ×4 (2,031) |
| &nbsp;&nbsp;· Model request sent → First text delta | 817 [780–2,750] ×4 (3,139) | 667 ×1 (—) | 825 [667–1,038] ×4 (1,285) |
| &nbsp;&nbsp;· First text delta → TTS request | 174 [146–189] ×4 (185) | 85 ×1 (—) | 137 [85–346] ×4 (143) |
| &nbsp;&nbsp;· TTS request → First PCM | 641 [576–1,616] ×4 (1,351) | 1,081 ×1 (—) | 749 [572–1,081] ×4 (603) |
| &nbsp;&nbsp;· First PCM → First audio frame | 0.6 [0.5–1.0] ×4 (0.6) | 0.5 ×1 (—) | 0.6 [0.5–0.7] ×4 (0.7) |
| **STT 与输入** | | | |
| STT commit → Final transcript | 809 [680–1,454] ×4 (1,761) | 802 ×1 (—) | 801 [626–967] ×4 (802) |
| Input frame lateness (due → published) | 2.1 [2.1–2.1] ×4 (163) | 2.9 ×1 (—) | 2.5 [2.1–6.0] ×4 (160) |
| **Context 与模型请求** | | | |
| Context readiness wait | 240 [221–875] ×4 (249) | 312 ×1 (—) | 239 [190–312] ×4 (244) |
| Request encoding | 0.2 [0.2–0.2] ×4 (0.2) | 0.1 ×1 (—) | 0.1 [0.1–0.1] ×4 (0.2) |
| Pictures sent | 4 ×4 (4) | 0 ×1 (—) | 0 ×4 (0) |
| Request size (B) | 63,996 [63,996–64,140] ×4 (64,140) | 19,311 ×1 (—) | 19,284 [19,284–19,311] ×4 (19,129) |
| Request attempts | 1 ×4 (1) | 1 ×1 (—) | 1 ×4 (1) |
| Model request sent → First event | 556 [525–2,495] ×4 (3,116) | 463 ×1 (—) | 557 [463–679] ×4 (1,112) |
| **视觉** | | | |
| Frame arrived → published (median) | 0.8 [0.8–0.8] ×4 (0.8) | n/a | n/a |
| Oldest selected frame age at request | 2,775 [2,461–3,381] ×4 (2,781) | n/a | n/a |
| Newest selected frame → Turn commit | 28 [2.7–43] ×4 (23) | n/a | n/a |
| Vision wait | — (no wait is observed: Context selects among frames already in) | n/a | n/a |
| First visual output frame | — (no visual output reaches the output boundary) | — (no visual output reaches the output boundary) | — |
| **音频供给** | | | |
| Audio duration (s) | 2.70 [2.15–3.00] ×4 (2.60) | 1.10 ×1 (—) | 3.00 [1.10–3.20] ×4 (3.05) |
| Frame interval (median) | 0.1 [0.1–0.1] ×4 (0.1) | 0.2 ×1 (—) | 0.2 [0.2–0.2] ×4 (0.2) |
| Largest frame gap | 230 [206–638] ×4 (340) | 232 ×1 (—) | 284 [232–464] ×4 (297) |
| Underruns (count) | 1 ×4 (1) | 1 ×1 (—) | 1 ×4 (1) |
| Starved in total | 32 [7.5–440] ×4 (142) | 33 ×1 (—) | 86 [33–265] ×4 (99) |
| Production time / audio duration | 0.26 [0.21–0.30] ×4 (0.28) | 0.38 ×1 (—) | 0.26 [0.21–0.38] ×4 (0.23) |
| Output events dropped | 0 ×4 (0) | 0 ×1 (—) | 0 ×4 (0) |

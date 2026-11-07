| Metric | `voice_vision` · 5/5 passed | `voice` · passed rounds (1/5) | `voice` · every round † |
|---|---|---|---|
| **端到端（自最后一个有声样本输入起）** | | | |
| Runtime first text | 2,589 [2,547–2,766] ×4 (3,369) | 2,708 ×1 (—) | 2,747 [2,681–2,832] ×4 (2,603) |
| First audio frame | 3,461 [3,392–3,615] ×4 (4,360) | 3,603 ×1 (—) | 3,612 [3,415–3,662] ×4 (3,313) |
| Text complete | 2,798 [2,749–2,944] ×4 (3,536) | 3,006 ×1 (—) | 2,935 [2,859–3,006] ×4 (2,736) |
| Last audio frame | 4,180 [4,120–4,349] ×4 (5,174) | 4,031 ×1 (—) | 4,331 [4,031–4,368] ×4 (3,835) |
| Response complete | 4,180 [4,120–4,350] ×4 (5,174) | 4,031 ×1 (—) | 4,331 [4,031–4,369] ×4 (3,835) |
| Last required input (frame or voice) | 1,361 [1,261–1,461] ×4 (1,562) | n/a | n/a |
| **Input** | 1,446 [1,351–1,483] ×4 (1,616) | 1,392 ×1 (—) | 1,408 [1,336–1,483] ×4 (1,327) |
| &nbsp;&nbsp;· Final speech → VAD close | 721 [721–721] ×4 (721) | 680 ×1 (—) | 681 [680–682] ×4 (680) |
| &nbsp;&nbsp;· VAD close → Final transcript | 725 [630–762] ×4 (895) | 712 ×1 (—) | 727 [655–803] ×4 (647) |
| **Context** | 240 [224–364] ×4 (513) | 380 ×1 (—) | 347 [297–380] ×4 (535) |
| &nbsp;&nbsp;· Final transcript → Turn commit | 2.0 [1.9–2.2] ×4 (2.3) | 151 ×1 (—) | 93 [69–151] ×4 (221) |
| &nbsp;&nbsp;· Turn commit → Context readiness check complete | 226 [211–350] ×4 (417) | 219 ×1 (—) | 230 [217–246] ×4 (219) |
| &nbsp;&nbsp;· Context readiness check complete → Context built | 1.5 [1.4–1.7] ×4 (1.7) | 1.6 ×1 (—) | 1.7 [1.6–1.9] ×4 (1.7) |
| &nbsp;&nbsp;· Context built → Model request sent | 9.9 [9.8–11] ×4 (92) | 8.5 ×1 (—) | 8.5 [8.4–8.9] ×4 (92) |
| **Output** | 1,763 [1,719–1,888] ×4 (2,231) | 1,831 ×1 (—) | 1,871 [1,635–1,918] ×4 (1,451) |
| &nbsp;&nbsp;· Model request sent → First text delta | 894 [866–1,039] ×4 (1,240) | 936 ×1 (—) | 989 [901–1,122] ×4 (741) |
| &nbsp;&nbsp;· First text delta → TTS request | 203 [179–216] ×4 (168) | 298 ×1 (—) | 153 [126–298] ×4 (134) |
| &nbsp;&nbsp;· TTS request → First PCM | 660 [601–714] ×4 (823) | 597 ×1 (—) | 630 [555–747] ×4 (576) |
| &nbsp;&nbsp;· First PCM → First audio frame | 0.7 [0.5–0.8] ×4 (0.7) | 0.6 ×1 (—) | 0.6 [0.6–0.7] ×4 (0.7) |
| **STT 与输入** | | | |
| STT commit → Final transcript | 725 [630–762] ×4 (895) | 712 ×1 (—) | 726 [655–803] ×4 (647) |
| STT queue (commit → request started) | 0.0 [0.0–0.0] ×4 (0.0) | 0.0 ×1 (—) | 0.0 [0.0–0.1] ×4 (0.1) |
| STT connect (TCP) | 3.2 [3.0–3.3] ×4 (3.8) | 6.5 ×1 (—) | 6.6 [6.5–6.8] ×4 (4.1) |
| STT TLS handshake | 5.9 [5.3–6.8] ×4 (5.7) | 6.5 ×1 (—) | 6.6 [5.8–7.1] ×4 (9.5) |
| STT upload (headers → audio sent) | 5.1 [4.5–6.1] ×4 (4.6) | 6.1 ×1 (—) | 5.7 [4.2–8.4] ×4 (7.0) |
| STT wait (audio sent → answer's headers) | 638 [531–669] ×4 (649) | 602 ×1 (—) | 633 [593–748] ×4 (481) |
| STT first event（标注为 headers 起，实为请求头写完起，见下） | 643 [536–676] ×4 (655) | 608 ×1 (—) | 641 [598–754] ×4 (490) |
| STT stream（同上） | 714 [619–750] ×4 (786) | 696 ×1 (—) | 711 [640–789] ×4 (536) |
| Input frame lateness (due → published) | 2.1 [2.0–3.2] ×4 (165) | 2.0 ×1 (—) | 3.1 [2.0–4.5] ×4 (152) |
| **Context 与模型请求** | | | |
| Context readiness wait | 225 [210–349] ×4 (415) | 218 ×1 (—) | 229 [216–244] ×4 (218) |
| Request encoding | 0.2 [0.2–0.3] ×4 (0.2) | 0.1 ×1 (—) | 0.1 [0.1–0.3] ×4 (0.1) |
| Pictures sent | 4 ×4 (4) | 0 ×1 (—) | 0 ×4 (0) |
| Request size (B) | 63,997 ×4 (63,997) | 19,316 ×1 (—) | 19,289 [19,289–19,316] ×4 (19,133) |
| Request attempts | 1 ×4 (1) | 1 ×1 (—) | 1 ×4 (1) |
| Model request sent → First event | 611 [597–720] ×4 (1,156) | 470 ×1 (—) | 565 [444–870] ×4 (648) |
| **视觉** | | | |
| Frame arrived → published (median) | 0.8 [0.8–0.8] ×4 (0.8) | n/a | n/a |
| Oldest selected frame age at request | 2,728 [2,703–2,755] ×4 (3,076) | n/a | n/a |
| Newest selected frame → Turn commit | 85 [24–98] ×4 (56) | n/a | n/a |
| Vision wait | — (no wait is observed: Context selects among frames already in) | n/a | n/a |
| First visual output frame | — (no visual output reaches the output boundary) | — (no visual output reaches the output boundary) | — |
| **音频供给** | | | |
| Audio duration (s) | 2.58 [1.80–3.10] ×4 (2.30) | 1.65 ×1 (—) | 3.08 [1.65–3.60] ×4 (3.60) |
| Frame interval (median) | 0.1 [0.1–0.2] ×4 (0.1) | 0.2 ×1 (—) | 0.2 [0.2–0.2] ×4 (0.2) |
| Largest frame gap | 303 [293–314] ×4 (428) | 206 ×1 (—) | 286 [206–329] ×4 (300) |
| Underruns (count) | 1 ×4 (1) | 1 ×1 (—) | 1 ×4 (1) |
| Starved in total | 105 [95–116] ×4 (231) | 8.0 ×1 (—) | 88 [8.0–131] ×4 (102) |
| Production time / audio duration | 0.29 [0.24–0.39] ×4 (0.35) | 0.26 ×1 (—) | 0.26 [0.21–0.26] ×4 (0.14) |
| Output events dropped | 0 ×4 (0) | 0 ×1 (—) | 0 ×4 (0) |

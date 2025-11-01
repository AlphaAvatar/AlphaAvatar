<div align="center"> <a name="readme-top"></a>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="/.github/banner_dark.png">
  <source media="(prefers-color-scheme: light)" srcset="/.github/banner_light.png">
  <img style="width:100%;" alt="The AvatarAlpha icon, the name of the repository." src="https://raw.githubusercontent.com/AlphaAvatar/AlphaAvatar/main/.github/banner_dark.png">
</picture>

<br />

[![PRs Welcome](https://img.shields.io/badge/PRs-welcome!-brightgreen.svg?style=flat-square)](https://github.com/AlphaAvatar/AlphaAvatar/pulls)
[![GitHub last commit](https://img.shields.io/github/last-commit/AlphaAvatar/AlphaAvatar)](https://github.com/AlphaAvatar/AlphaAvatar/commits/main)
[![License](https://img.shields.io/github/license/AlphaAvatar/AlphaAvatar)](https://github.com/AlphaAvatar/AlphaAvatar/blob/main/LICENSE)

[![GitHub watchers](https://img.shields.io/github/watchers/AlphaAvatar/AlphaAvatar?style=social&label=Watch)](https://GitHub.com/AlphaAvatar/AlphaAvatar/watchers/?WT.mc_id=academic-105485-koreyst)
[![GitHub forks](https://img.shields.io/github/forks/AlphaAvatar/AlphaAvatar?style=social&label=Fork)](https://GitHub.com/AlphaAvatar/AlphaAvatar/network/?WT.mc_id=academic-105485-koreyst)
[![GitHub stars](https://img.shields.io/github/stars/AlphaAvatar/AlphaAvatar?style=social&label=Star)](https://GitHub.com/AlphaAvatar/AlphaAvatar/stargazers/?WT.mc_id=academic-105485-koreyst)


<h3 align="center">
Learnable, configurable, and pluggable Omni-Avatar Assistant for everyone
</h3>

<p align="center">
  <a href="ROADMAP.md">ROADMAP</a>
</p>

</div>

---

<h3>AlphaAvatar Plugins</h3>

<table>
<tr>
<td width="50%">
<h3>🧠 Memory</h3>
<p>Self-improving memory module for Omni-Avatar.</p>
<p>
<a href="https://github.com/AlphaAvatar/AlphaAvatar/blob/main/avatar-plugins/avatar-plugins-memory/README.md">README↗</a>
</p>
</td>
<td width="50%">
<h3>🧬 Persona</h3>
<p>Automatic extraction and real-time matching of user full modality persona.</p>
<p>
<a href="https://github.com/AlphaAvatar/AlphaAvatar/blob/main/avatar-plugins/avatar-plugins-persona/README.md">README↗</a>
</p>
</td>
</tr>

<tr>
<td width="50%">
<h3> Planning</h3>
<p></p>
<p>
<a href="examples/voice_agents/basic_agent.py">README↗</a>
</p>
</td>
<td width="50%">
<h3>🤖 Behavior</h3>
<p>Controls AlphaAvatar’s behavior logic and process flow.</p>
<p>
<a href="examples/voice_agents/push_to_talk.py">README↗</a>
</p>
</td>
</tr>

<tr>
<td width="50%">
<h3>💡 Reflection</h3>
<p>An Optimizer for Omni-Avatar that can automatically build an internal knowledge base for avatars.</p>
<p>
<a href="examples/voice_agents/basic_agent.py">README↗</a>
</p>
</td>
<td width="50%">
<h3>😊 Avatar</h3>
<p>The real-time generated digital avatar during the conversation.</p>
<p>
<a href="examples/voice_agents/push_to_talk.py">README↗</a>
</p>
</td>
</tr>

</table>

---

<h3>Tools Plugins</h3>

---

<h3>Docs and guides</h3>

<h4>Latest News 🔥</h4>

- [2025/09]


<br/>

<h4>Quick Start ⚡️<h4>

```bash
export LIVEKIT_API_KEY=<your API Key>
export LIVEKIT_API_SECRET=<your API Secret>
export LIVEKIT_URL=<your LiveKit server URL>
export OPENAI_API_KEY=<your OpenAI API Key>
export QDRANT_URL='https://xxxxxx-xxxxx-xxxxx-xxxx-xxxxxxxxx.us-east.aws.cloud.qdrant.io:6333'
export QDRANT_API_KEY=<your QDRANT API Key>

alphaavatar dev examples/pipline_openai_dev.yaml
```

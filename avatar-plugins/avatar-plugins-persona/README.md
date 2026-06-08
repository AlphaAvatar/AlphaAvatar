# 👤 Persona Plugin for AlphaAvatar

> Give AlphaAvatar the ability to **recognize who you are** — by your voice, your face, and your conversation style.

---

## 🤔 What is the Persona Plugin?

Imagine if every time you walked into a store, the staff forgot who you were. Frustrating, right?

The **Persona Plugin** solves this for AlphaAvatar. It builds a **profile of each user** based on how they talk, what they look like, and how they behave — so AlphaAvatar can:

- Recognize you by your **voice**
- Recognize you by your **face**
- Understand your **personality, preferences, and habits**
- Instantly personalize every response just for you

Think of it like AlphaAvatar building a mental picture of who you are — and getting better at recognizing you over time.

---

## 💡 How Does it Work? (Simple Flow)

```
You start talking to AlphaAvatar
            ↓
Persona Plugin listens and watches
(your voice, face, conversation style)
            ↓
It extracts key traits about you
(who you are, how you speak, what you look like)
            ↓
Your profile is saved as a vector (a smart fingerprint)
            ↓
Next time you interact
            ↓
AlphaAvatar matches your voice/face to your saved profile
            ↓
Instantly knows who you are and personalizes the response
```

No manual login needed. It recognizes you automatically.

---

## ✨ Features

### 🧠 Automatic Persona Extraction
AlphaAvatar builds your profile automatically — you don't have to fill out any form or settings.

It learns from:
- Your **conversation history** (what you talk about, how you phrase things)
- Your **behavioral cues** (how you interact, what you ask for)
- **Multimodal inputs** (your voice tone, your face)

Your profile is stored as a **vector embedding** — a smart digital fingerprint that makes matching fast and accurate.

### ⚡ Real-time Persona Matching
Every time you interact, AlphaAvatar instantly matches your voice and face against saved profiles — so it knows who you are within seconds, even in a group conversation.

---

## 📦 What Does a Persona Profile Contain?

| Type | Example |
|------|---------|
| 🗣️ Voice fingerprint | Unique pattern of how your voice sounds |
| 😊 Face fingerprint | Unique pattern of your facial features |
| 💬 Conversation style | How formal/casual you speak |
| ❤️ Preferences | Topics you care about, things you've mentioned |
| 👤 Identity | Your name, age group, gender (if detected) |
| 🔁 Behavioral patterns | How often you interact, what you typically ask |

---

## 🔧 Installation

```bash
pip install alpha-avatar-plugins-persona
```

That's it. The plugin works automatically when you run AlphaAvatar.

---

## 🛠️ How it Recognizes You (The Tech Behind It)

You don't need to understand this to use AlphaAvatar — but here's a simple breakdown of what's happening under the hood:

### 🗄️ Vector Store (Where profiles are saved)

| Module | What it Does |
|--------|-------------|
| **Qdrant** | Stores your persona profile as a smart searchable fingerprint |

### 👤 Profile Extraction (How traits are pulled out)

| Module | What it Does |
|--------|-------------|
| **LangChain** | Reads your conversations and extracts key personality traits and preferences |

### 🎤 Speaker Recognition (How your voice is identified)

| Module | What it Does |
|--------|-------------|
| **ERes2NetV2** | State-of-the-art model that creates a unique fingerprint from your voice |
| **wav2vec2** | Identifies your voice and also detects your age group and gender |

### 👁️ Face Recognition (How your face is identified)

| Module | What it Does |
|--------|-------------|
| **buffalo_l** | Creates a unique fingerprint from your face and links it to your persona profile |

---

## 🔗 How Persona Connects to Other Plugins

Persona doesn't work alone — it feeds into the entire AlphaAvatar experience:

```
Persona Plugin
      ├── → Memory Plugin    (stores what was learned about you)
      ├── → RAG Plugin       (retrieves documents relevant to your profile)
      ├── → Reflection*      (refines your profile over time)
      └── → Planning*        (sets reminders based on your habits and goals)

* Coming soon
```

---

## 🙋 Common Questions

**Q: Does AlphaAvatar need me to log in to recognize me?**
No — it recognizes you automatically using your voice and face.

**Q: What if two people sound similar?**
The speaker recognition models are trained to distinguish even similar voices. Face recognition adds an extra layer of accuracy.

**Q: Can I use Persona without a camera?**
Yes — voice-only recognition works without a camera. Face recognition is an optional extra layer.

**Q: Is my face and voice data stored safely?**
All data is stored locally on your machine by default as vector embeddings — not as raw images or audio recordings.

**Q: Can I delete my persona profile?**
The ability to view and delete persona profiles is coming soon.

---

## 🚀 Coming Soon

The Persona plugin is actively being improved. Here's what's coming:

| Feature | Description |
|---------|-------------|
| 🌐 Multimodal Persona | Build profiles from voice, face, text, and video together |
| 👥 Multi-user Support | Recognize and separate multiple users in the same session |
| 🔒 Privacy Controls | Let users view, edit, export, or delete their persona profile |
| 📊 Persona Dashboard | Visual panel to see what AlphaAvatar knows about you |
| 🔄 Continuous Learning | Profile gets smarter and more accurate the more you interact |

---

## 📚 Related Links

- [Qdrant Documentation](https://qdrant.tech)
- [LangChain Documentation](https://www.langchain.com)
- [3D-Speaker (ERes2NetV2)](https://github.com/modelscope/3D-Speaker)
- [wav2vec2 Age & Gender Model](https://github.com/audeering/w2v2-age-gender-how-to)
- [InsightFace (buffalo_l)](https://github.com/deepinsight/insightface)
- [AlphaAvatar ROADMAP — Persona Section](https://github.com/AlphaAvatar/AlphaAvatar/blob/main/ROADMAP.md#-persona)
- [Memory Plugin](https://github.com/AlphaAvatar/AlphaAvatar/blob/main/avatar-plugins/avatar-plugins-memory/README.md)

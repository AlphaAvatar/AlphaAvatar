# 🧠 Memory Plugin for AlphaAvatar

> Give AlphaAvatar the ability to **remember you** — across conversations, sessions, and time.

---

## 🤔 What is the Memory Plugin?

Imagine talking to an assistant that forgets everything you said the moment you close the app. Frustrating, right?

The **Memory Plugin** solves this. It allows AlphaAvatar to:
- Remember your **name, preferences, and habits**
- Recall **past conversations** and what was discussed
- Learn from its own **tool usage** (like web searches or documents it read)
- Get **smarter and more personal** the more you use it

Think of it like giving AlphaAvatar a notebook — every important thing gets written down and read back when needed.

---

## 💡 How Does it Work? (Simple Flow)

```
You say something to AlphaAvatar
            ↓
AlphaAvatar picks out important information
(your name, preferences, facts, decisions)
            ↓
That information gets saved to local storage
            ↓
Next time you start a conversation
            ↓
AlphaAvatar reads its saved memories
            ↓
Responds like it knows you — because it does
```

No setup needed from your side. It works automatically in the background.

---

## ✨ Features

### 🌍 Global Memory (Avatar-wide)
AlphaAvatar maintains memories across your entire experience — not just one chat window.

This includes:
- Things **you** told it (name, preferences, goals)
- Things it learned from **external tools** (web searches, documents, research)
- Things it observed from **its own environment** (what worked, what didn't)

### ⚡ Real-time Context Updates
Memory doesn't just update at the end of a conversation — it updates **while you're talking**. If you mention something new mid-conversation, it gets remembered immediately.

---

## 📦 What Kind of Things Does AlphaAvatar Remember?

| Type | Real Example |
|------|-------------|
| 👤 Personal facts | "My name is Alex and I live in New York" |
| ❤️ Preferences | "I like short, direct answers" |
| 🔍 Research results | Facts found during a DeepResearch session |
| 📄 Document knowledge | Content from files you uploaded via RAG |
| 🗓️ Past conversations | Topics and decisions from previous sessions |
| 🛠️ Tool interactions | Results from MCP tools like Notion or Gmail |

---

## 🔧 Installation

```bash
pip install alpha-avatar-plugins-memory
```

That's it. The plugin is automatically used when you run AlphaAvatar.

---

## 🗄️ How Memories are Stored

AlphaAvatar uses **vector storage** to save memories. This means memories aren't stored as plain text — they're stored in a way that makes them easy to search and retrieve intelligently.

### Supported Backends

| Backend | What it Does |
|---------|-------------|
| **LanceDB** | Saves memories locally on your machine (default) |
| **Qdrant** | A powerful vector database for storage and retrieval |
| **LangChain** | The pipeline that extracts and processes memories |

By default, everything is stored **locally** — your memories never leave your machine unless you configure a cloud backend.

---

## 🔗 How Memory Connects to Other Plugins

The Memory plugin doesn't work alone — it's the foundation that other plugins build on:

```
Memory Plugin
      ├── → Persona Plugin   (builds your user profile from memories)
      ├── → RAG Plugin       (stores document knowledge in memory)
      ├── → Reflection*      (analyzes memories to improve Avatar behavior)
      └── → Planning*        (uses memories to set reminders and goals)

* Coming soon
```

---

## 🙋 Common Questions

**Q: Does memory work across different devices?**
By default, memory is stored locally. Cross-device sync is not yet supported.

**Q: Can I see what AlphaAvatar remembers about me?**
A memory inspection panel is currently in development.

**Q: Can I delete a memory?**
The ability to query, correct, and delete specific memories is coming soon.

**Q: Is my data private?**
Yes — by default everything is stored locally on your machine using LanceDB.

---

## 🚀 Coming Soon

AlphaAvatar's Memory plugin is actively being improved. Here's what's coming:

| Feature | Description |
|---------|-------------|
| 🎤 Voice Memory | Remember things said during voice conversations |
| 👁️ Visual Memory | Extract memories from images, screenshots, and camera frames |
| 😊 Face-based Memory | Remember users by their face using facial recognition |
| 🕸️ Graph Memory | Understand relationships between memories (people, events, goals) |
| 🔒 Memory Privacy Controls | Let users view, edit, export, or delete their memories |
| 👥 Multi-user Memory | Separate memories for multiple users in the same session |

---

## 📚 Related Links

- [Qdrant Documentation](https://qdrant.tech)
- [LangChain Documentation](https://www.langchain.com)
- [AlphaAvatar ROADMAP — Memory Section](https://github.com/AlphaAvatar/AlphaAvatar/blob/main/ROADMAP.md#-memory)
- [Persona Plugin](https://github.com/AlphaAvatar/AlphaAvatar/blob/main/avatar-plugins/avatar-plugins-persona/README.md)
- 

# 📈 **MAIN GOAL**

> **Build a universal assistant** capable of recognizing users through multimodal streaming input.
> It should possess **self-memory**, **autonomous reflection**, and **iterative self-evolution** for real-time interaction.
> The assistant will **seamlessly integrate** with mainstream external tools to solve practical problems efficiently.

---

# Table of contents

- [PLAN OVERVIEW](#plan-overview)
- [Core Function](#core-function)
- [AlphaAvatar Plugins](#alphaavatar-plugins)
    - [CHARACTER](#character-plugin)
    - [MEMORY](#memory-plugin)
    - [PERSONA](#persona-plugin)
- [Tools Plugins](#tools-plugins)
    - [Deep Search](#deepsearch)
- [NEXT STEPS](#next-steps)

---

# 🗓️ PLAN OVERVIEW

| Plugin               | Description                                                                  |   Status   |
| :------------------- | :--------------------------------------------------------------------------- | :--------: |
| 📚 **RAG**           | Retrieval-Augmented Generation for improved reasoning & factual grounding.   | 🧩 Planned |
| ⚙️ **Behavior**      | Controls AlphaAvatar’s behavior logic and process flow.                      | 🧩 Planned |
| 💡 **Reflection**    | Generates metacognitive insights from memory and interaction history.        | 🧩 Planned |
| 🧰 **MCP Tools**     | Modular control & orchestration layer for cross-plugin coordination.         | 🧩 Planned |

---

# Core Function

### ✅ DONE

|  Date    | Task                                                                                                                         |
| :------- | :--------------------------------------------------------------------------------------------------------------------------- |
| 2025-10  | Develop a context manager to route real-time updated interaction information to different plugin models (memory, persona) for corresponding plugin updates. |

### 🧭 TODO

| Priority | Task                                                                                                                         |     Stage     |
| :------- | :--------------------------------------------------------------------------------------------------------------------------- | :-----------: |
| 🔹       | Develop multi-user management features for plugins.  | 🧩 Planned |

---

# AlphaAvatar Plugins

## 😊 CHARACTER

### ✅ DONE

|  Date    | Task                                                                                                                         |
| :------- | :--------------------------------------------------------------------------------------------------------------------------- |
| 2025-12  | Integrating AIRI live2d into AlphaAvatar |

### 🧭 TODO


## 🧠 MEMORY

### ✅ DONE

| Date    | Milestone                            | Notes                                                                                                                                       |
| :------ | :----------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------ |
| 2025-09 | **Automatic Memory Extraction (v1)** | Built on **Memory Client**, enabling memory capture & retrieval across:<br>• Assistant–User<br>• Assistant–Tools<br>• Assistant’s self-memory |

### 🧭 TODO

| Priority | Task                                                                                                                         |     Stage     |
| :------- | :--------------------------------------------------------------------------------------------------------------------------- | :-----------: |
| 🔸       | Design **differentiated prompts** for:<br>– self-memory<br>– shared Assistant–User memory<br>– shared Assistant–Tools memory | ⏳ In Progress |
| 🔸       | Add **multi-user memory isolation** (unique response memory per user).                                                       | ⏳ In Progress |
| 🔹       | Allow users to **query / recall** specific memories on demand.                                                               |   🧩 Planned  |
| 🔹       | Add **event-driven memory updates** for adaptive reflection.                                                                 |   🧩 Planned  |
| 🔹       | Add **omni** memory updates.                                                                                                 |   🧩 Planned  |

## 🧬 PERSONA

### ✅ DONE

| Date    | Milestone                                  | Notes                                                                          |
| :------ | :----------------------------------------- | :----------------------------------------------------------------------------- |
| 2025-10 | **Automatic User Profile Extraction (v1)** | Generates personalized, context-aware responses based on conversation history. |
| 2025-11 | **Speaker Verification**                   | Add speech-based profiling (speaker vector extraction & identification).       |

### 🧭 TODO

| Priority | Task                                                                         |     Stage     |
| :------- | :--------------------------------------------------------------------------- | :-----------: |
| 🔸       | Add **multi-user profile management** for concurrent interactions.           | ⏳ In Progress |
| 🔸       | Enable **real-time profile retrieval** during active conversation.           | ⏳ In Progress |
| 🔹       | Add **face-based profiling** (facial embedding recognition).                 |   🧩 Planned  |
| 🔹       | Integrate **event triggers** for profile updates & reflection cycles.        |   🧩 Planned  |

---

# Tools Plugins

## 🔍 DeepSearch

### ✅ DONE

### 🧭 TODO

---

# NEXT STEPS

| Quarter | Focus                        | Expected Outcome                                  |
| :------ | :--------------------------- | :------------------------------------------------ |
| Q4-2025 | Memory + Persona + Avatar Integration | Unified multimodal identity recognition pipeline. |
| Q1-2026 | DeepSearch Integration    | Give AlphaAvatar the ability to access the network.    |
| Q1-2026 | External Tool Integration    | Seamless task execution via MCP + RAG plugins.    |
| Q2-2026 | Reflection Plugin Alpha      | Enable autonomous self-analysis & evolution.      |

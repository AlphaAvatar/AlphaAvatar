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
    - [Deep Research](#deepresearch)
    - [RAG](#rag)
- [NEXT STEPS](#next-steps)

---

# 🗓️ PLAN OVERVIEW

| Plugin               | Description                                                                  |     Stage     |
| :------------------- | :--------------------------------------------------------------------------- | :-----------: |
| ⚙️ **Behavior**      | Controls AlphaAvatar’s behavior logic and process flow.                      |   🧩 Planned   |
| 💡 **Reflection**    | Generates metacognitive insights from memory and interaction history.        |   🧩 Planned   |
| 🧰 **MCP Tools**     | Modular control & orchestration layer for cross-plugin coordination.         |   🧩 Planned   |

---

# Core Function

### ✅ DONE

|  Date    | Task                                                                                                                         |
| :------- | :--------------------------------------------------------------------------------------------------------------------------- |
| 2025-10  | Develop a context manager to route real-time updated interaction information to different plugin models (memory, persona) for corresponding plugin updates. |

### 🧭 TODO

| Priority | Task                                                                                                                         |     Stage     |
| :------- | :--------------------------------------------------------------------------------------------------------------------------- | :-----------: |
| 🔹       | Develop multi-user management features for plugins.                                                                          |   🧩 Planned   |
| 🔹       | Content uploaded by a user in the current session is first stored in a temporary directory, and then stored in persistent storage after confirmation. The user's upload status and input are identified separately for use in the model.    | 🧩 Planned     |
| 🔹       | The return values ​​of the Deep research download function and the Rag indexing function should include a brief description of the doc/url content (using a decorator) stored in memory for later reference.    | 🧩 Planned     |
| 🔹       | Enrich the logging system.                                                                                                   |   🧩 Planned   |

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

| Date    | Milestone                                     | Notes                                                                                                                                         |
| :------ | :-------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------- |
| 2025-09 | **Automatic Memory Extraction (v1)**          | Built on **Memory Client**, enabling memory capture & retrieval across:<br>• Assistant–User<br>• Assistant–Tools<br>• Assistant’s self-memory |
| 2026-01 | **Automatic Assistant–Tools Extraction (v1)** | Add Assistant–Tools memory in user session for DeepResearch/RAG Plugin.                                                                       |

### 🧭 TODO

| Priority | Task                                                                                                                         |     Stage      |
| :------- | :--------------------------------------------------------------------------------------------------------------------------- | :-----------:  |
| 🔸       | Design **differentiated prompts** for:<br>– self-memory<br>– shared Assistant–User memory<br>– shared Assistant–Tools memory | ⏳ In Progress |
| 🔸       | Add **multi-user memory isolation** (unique response memory per user).                                                       | ⏳ In Progress |
| 🔹       | Allow users to **query / recall** specific memories on demand.                                                               |   🧩 Planned   |
| 🔹       | Add **event-driven memory updates** for adaptive reflection.                                                                 |   🧩 Planned   |
| 🔹       | Add **omni** memory updates.                                                                                                 |   🧩 Planned   |

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
| 🔹       | Add **face-based profiling** (facial embedding recognition).                 |   🧩 Planned   |
| 🔹       | Integrate **event triggers** for profile updates & reflection cycles.        |   🧩 Planned   |

---

# Tools Plugins

## 🔍 DeepResearch

### ✅ DONE

| Date    | Milestone                                  | Notes                                                                          |
| :------ | :----------------------------------------- | :----------------------------------------------------------------------------- |
| 2025-12 | **Integrating the Tavily API into the DeepResearch plugin(v1)** | Supports fast online retrieval or deep search, scraping and page to pdf. |

### 🧭 TODO

| Priority | Task                                                                                                                         |     Stage      |
| :------- | :--------------------------------------------------------------------------------------------------------------------------- | :-----------:  |
| 🔹       | Add intermediate states during deep-research invocation to reduce the user's perceived waiting time.                                  |   🧩 Planned   |
| 🔹       | Allows you to retrieve all accessible webpage links under a specified webpage and store them in a specific folder for use by the RAG plugin. |   🧩 Planned   |
| 🔹       | Add intermediate states during tool invocation to reduce the user's perceived waiting time.                                  |   🧩 Planned   |

## 📖 RAG

### ✅ DONE

| Date    | Milestone                                            | Notes                                                                          |
| :------ | :--------------------------------------------------- | :----------------------------------------------------------------------------- |
| 2026-01 | **Integrating the RAG Anything into the RAG plugin** | Supports query and indexing based on pages from DeepResearch plugin.           |

### 🧭 TODO

| Priority | Task                                                                                                                         |     Stage      |
| :------- | :--------------------------------------------------------------------------------------------------------------------------- | :-----------:  |
| 🔹       | Allow folder index building.                                                                                                 |   🧩 Planned   |
| 🔹       | Allows queries to be performed against **different data sources**.                                                           |   🧩 Planned   |
| 🔹       | Allows the construction of metadata (structured information such as directories) for different data sources, improving retrieval efficiency.  |   🧩 Planned   |
| 🔹       | Build offline indexing and passive retrieval capabilities to automatically retrieve relevant content from the Assistant's internal knowledge base (such as the Reflection module). |   🧩 Planned   |
| 🔹       | Add intermediate states during tool invocation to reduce the user's perceived waiting time.                                  |   🧩 Planned   |

---

# NEXT STEPS

| Quarter | Focus                        | Expected Outcome                                  |
| :------ | :--------------------------- | :------------------------------------------------ |
| Q1-2026 | External Tool Integration    | Seamless task execution via MCP plugins.          |
| Q2-2026 | Reflection Plugin Alpha      | Enable autonomous self-analysis & evolution.      |
| Q2-2026 | World Sandbox Link           | Allows AlphaAvatar to link to external sandbox worlds (code environments, game environments, etc.).      |

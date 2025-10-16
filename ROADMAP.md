# `📈 MAIN GOAL`

Build a universal **assistant** that can automatically recognize users through multimodal streaming input. It should be equipped with self-memory, autonomous reflection, and iterative self-evolution for real-time interaction. The assistant will also integrate seamlessly with mainstream external tools to effectively solve users’ practical problems.

---

# `📅 PLAN`

* **Reflection**: Leverage extracted memory and interactive history to generate metacognitive insights, enabling the Assistant to evolve continuously.
* **Avatar**: Develop a personalized, adaptive representation of the Assistant for richer, context-aware interaction.
* **RAG (Retrieval-Augmented Generation)**: Enhance the Assistant’s reasoning and factual accuracy by integrating retrieval mechanisms.
* **Deep Research**: Equip the Assistant with structured research capabilities for long-horizon, multi-step problem solving.
* **MCP Tools**:

---

# Milestones

## Memory Plugin

### Done ✅

* [2025/09] Released an automatic memory extraction plugin built on **Mem0 Client**, enabling memory capture & retrieval across three dimensions: Assistant–User, Assistant–Tools, and Assistant’s own self-memory.

### TODO 📄

* Design differentiated memory extraction prompts for:

  * the Assistant’s self-memory
  * shared memory between the Assistant and the user
  * shared memory between the Assistant and tools
    to support varied scenarios effectively.
* Support multi-user interactions by extracting and maintaining **separate response memories** for each user.
* Enable users to proactively **query and recall specific memory entries** on demand.
* Add Event

---

## Persona Plugin

### Done ✅

* [2025/10] Implemented automatic user profile extraction based on conversation history, enabling the Assistant to generate more **personalized and context-aware responses**.

### TODO 📄

* Support multi-user interactions
* Real-time retrieval of user profiles based on conversations between users and Assistant.
* Develop a speech-based system to extract speaker vectors and related features, enabling automatic retrieval or identification of speaker profiles without relying on fixed user IDs.
* Develop a face-based system to extract facial embeddings and related features, enabling automatic retrieval or identification of speaker profiles without binding to a specific user ID.
* Add Event

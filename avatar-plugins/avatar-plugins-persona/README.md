# Persona Plugin for AlphaAvatar

Support for **automatic extraction and real-time matching** of user **full-modality personas**, enabling Avatar to recognize, track, and personalize interactions based on multimodal signals.
This plugin provides a unified interface for **profiling** (semantic + vector representation), **speaker identification**, and **face recognition**, abstracting away backend complexity so developers can focus on building adaptive, personalized experiences.

## Features

* **Automatic Persona Extraction:**
  On-the-fly profiling of users based on conversation history, behavioral cues, and multimodal inputs. Persona profiles are represented as vector embeddings for efficient similarity search and personalization.

* **Real-time Persona Matching:**
  Incoming dialogue and multimodal signals are matched against stored persona profiles in real-time, ensuring the Avatar can recall context, traits, and preferences instantly.

## Installation

```bash
pip install alpha-avatar-plugins-persona
```

---

## Supported Modules

### Vector Store
| Module                 | Description                                                                                   | Docs                                                                   |
| ---------------------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| **Qdrant** (default) | Combined framework for persona extraction pipelines and vector storage / retrieval.           | [Qdrant](https://qdrant.tech) |

### Profiler
| Module                 | Description                                                                                   | Docs                                                                   |
| ---------------------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| **LangChain** (default) | Combined framework for persona extraction pipelines and vector storage / retrieval.           | [LangChain](https://www.langchain.com) |

### Speaker
| Module     | Description                                                                               | Docs                                                                 |
| ---------- | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| **ERes2NetV2** (default) | State-of-the-art deep speaker recognition model for speaker embedding and identification. | [3D-Speaker](https://github.com/modelscope/3D-Speaker)     |
| **wav2vec2-large-robust-6-ft-age-gender** (default) | Deep learning model for speaker embedding with additional age and gender recognition capabilities. | [audEERING](https://github.com/audeering/w2v2-age-gender-how-to)     |

### Face Recognizer
| Module  | Description                                                                                   | Docs                                                                 |
| ------- | --------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| **Face ID** (default) | Face embedding + recognition module for identity verification and multimodal persona binding. | (e.g., [InsightFace](https://github.com/deepinsight/insightface))    |

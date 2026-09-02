# Copyright 2026 AlphaAvatar project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import json
import os

import cv2
import numpy as np

from alphaavatar.agents.runtime.inference import InferenceRunner

from ..log import logger
from ..model_files import FACE_MODEL_CONFIG, FaceModelType


class FaceAnalysisRunner(InferenceRunner):
    INFERENCE_METHOD = "alphaavatar.persona.face.analysis"
    MODEL_TYPE: FaceModelType = "buffalo_l"

    def __init__(self):
        super().__init__()

    def initialize(self) -> None:
        import onnxruntime as ort
        from insightface.app import FaceAnalysis

        self._model_config = FACE_MODEL_CONFIG[self.MODEL_TYPE]

        available = ort.get_available_providers()

        if "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            ctx_id = 0
            logger.info("[FaceAnalysisRunner] Running on GPU (CUDA)")
        else:
            providers = ["CPUExecutionProvider"]
            ctx_id = -1
            logger.info("[FaceAnalysisRunner] Running on CPU")

        self._app = FaceAnalysis(
            name=self._model_config.model_name,
            root=os.path.expanduser(self._model_config.root),
            allowed_modules=self._model_config.allowed_modules,
            providers=providers,
        )
        self._app.prepare(
            ctx_id=ctx_id,
            det_thresh=self._model_config.det_thresh,
            det_size=self._model_config.det_size,
        )

        logger.info(
            "[FaceAnalysisRunner] initialized model=%s root=%s det_size=%s det_thresh=%s providers=%s",
            self._model_config.model_name,
            self._model_config.root,
            self._model_config.det_size,
            self._model_config.det_thresh,
            providers,
        )

    def run(self, data: bytes) -> bytes:
        arr = np.frombuffer(data, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            return json.dumps(
                {
                    "image_width": 0,
                    "image_height": 0,
                    "faces": [],
                }
            ).encode()

        image_height, image_width = image.shape[:2]
        faces = self._app.get(image)

        output = []
        for face in faces:
            embedding = getattr(face, "normed_embedding", None)
            if embedding is None:
                embedding = getattr(face, "embedding", None)

            if embedding is not None:
                embedding = np.asarray(embedding, dtype=np.float32)
                norm = float(np.linalg.norm(embedding))

                if norm > 0:
                    embedding = embedding / norm

            bbox = getattr(face, "bbox", None)
            keypoints = getattr(face, "kps", None)
            det_score = getattr(face, "det_score", None)

            gender = getattr(face, "sex", None)
            if gender is None:
                raw_gender = getattr(face, "gender", None)
                if raw_gender is not None:
                    gender = "female" if int(raw_gender) == 0 else "male"

            result = {
                "bbox": (bbox.astype(float).tolist() if bbox is not None else None),
                "kps": (keypoints.astype(float).tolist() if keypoints is not None else None),
                "det_score": (float(det_score) if det_score is not None else 0.0),
                "age": (int(face.age) if getattr(face, "age", None) is not None else None),
                "gender": (str(gender).lower() if gender is not None else None),
            }

            if embedding is not None:
                result["embedding"] = embedding.astype(np.float32).tolist()

            output.append(result)

        return json.dumps(
            {
                "image_width": image_width,
                "image_height": image_height,
                "faces": output,
            }
        ).encode()

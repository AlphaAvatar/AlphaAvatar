# Copyright 2025 AlphaAvatar project
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
import numpy as np
import torch
import torchaudio.compliance.kaldi as Kaldi


class FBank:
    def __init__(self, n_mels, sample_rate, mean_nor: bool = False):
        self.n_mels = n_mels
        self.sample_rate = sample_rate
        self.mean_nor = mean_nor

    def __call__(self, wav: np.ndarray, dither=0) -> np.ndarray:
        sr = self.sample_rate
        assert sr == 16000

        wav_tensor = torch.from_numpy(wav).float()

        if wav_tensor.ndim == 1:
            wav_tensor = wav_tensor.unsqueeze(0)

        if wav_tensor.shape[0] > 1 and wav_tensor.ndim == 2:
            wav_tensor = wav_tensor[0, :].unsqueeze(0)

        if wav_tensor.ndim == 2 and wav_tensor.shape[0] > 1:
            feats = []
            for i in range(wav_tensor.shape[0]):
                f = Kaldi.fbank(
                    wav_tensor[i].unsqueeze(0),
                    num_mel_bins=self.n_mels,
                    sample_frequency=sr,
                    dither=dither,
                )  # [T, N]
                if self.mean_nor:
                    f = f - f.mean(0, keepdim=True)
                feats.append(f)
            feat = torch.nn.utils.rnn.pad_sequence(feats, batch_first=True)  # [B, max_T, N]
        else:
            feat = Kaldi.fbank(
                wav_tensor, num_mel_bins=self.n_mels, sample_frequency=sr, dither=dither
            )  # [T, N]
            if self.mean_nor:
                feat = feat - feat.mean(0, keepdim=True)
            feat = feat.unsqueeze(0)  # [1, T, N]

        return feat.numpy()

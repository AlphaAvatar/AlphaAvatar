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
from torchaudio.compliance import kaldi as Kaldi


class FBank:
    """
    Compute Kaldi-style filter bank (fbank) features for mono or multi-channel waveforms.

    Notes
    -----
    - This class normalizes input arrays to be writable, C-contiguous, and float32 to
      avoid PyTorch warnings about non-writable NumPy arrays when converting to tensors.
    - For multi-channel inputs, fbank is computed per channel independently and padded
      along the time dimension to form a batch.
    - Output shapes:
        * mono input:  [1, T, n_mels]
        * multi input: [C, Tmax, n_mels]  (time-padded across channels)
    """

    def __init__(self, n_mels: int, sample_rate: int, mean_nor: bool = False):
        """
        Parameters
        ----------
        n_mels : int
            Number of mel bins.
        sample_rate : int
            Expected sample rate. This implementation asserts 16 kHz by default.
        mean_nor : bool, optional
            If True, perform zero-mean normalization per feature dimension (cmvn-lite).
        """
        self.n_mels = n_mels
        self.sample_rate = sample_rate
        self.mean_nor = mean_nor

    def __call__(self, wav: np.ndarray, dither: float = 0.0) -> np.ndarray:
        """
        Parameters
        ----------
        wav : np.ndarray
            Waveform array. Shapes supported:
              - [T]              (mono)
              - [C, T] or [T, C] (multi-channel; this method will standardize to [C, T])
        dither : float, optional
            Dithering parameter passed to Kaldi fbank. Default 0.0 (disabled).

        Returns
        -------
        np.ndarray
            FBank feature array with shape:
              - [1, T, n_mels] for mono input
              - [C, Tmax, n_mels] for multi-channel input (padded on time)
        """
        sr = self.sample_rate
        assert sr == 16000, f"FBank currently expects 16 kHz audio, got {sr}"

        # --- 1) Ensure writable, contiguous, and float32 to avoid PyTorch warnings ---
        # ascontiguousarray + dtype conversion only copies when needed.
        wav = np.ascontiguousarray(wav, dtype=np.float32)
        # Explicit copy() guarantees writeable=True for safety on odd sources/slices.
        wav_safe = wav.copy()

        # --- 2) Convert to torch.Tensor without relying on torch.tensor(copy=...) ---
        # (Compatibility with PyTorch < 2.0)
        wav_tensor = torch.from_numpy(wav_safe)  # shape still unknown (1D or 2D)
        # Ensure float dtype
        wav_tensor = wav_tensor.to(dtype=torch.float32)

        # --- 3) Standardize shape to [C, T] ---
        if wav_tensor.ndim == 1:
            # Mono: [T] -> [1, T]
            wav_tensor = wav_tensor.unsqueeze(0)
        elif wav_tensor.ndim == 2:
            # Heuristic: if it's [T, C] (time-by-channel), transpose to [C, T]
            # We treat the longer dimension as time in typical audio (T >> C).
            C, T = wav_tensor.shape
            if C > T:  # likely [T, C]
                wav_tensor = wav_tensor.transpose(0, 1)  # -> [C, T]
        else:
            raise ValueError(
                f"Unexpected wav shape: {tuple(wav_tensor.shape)}; expected [T] or [C, T]/[T, C]."
            )

        # After normalization, wav_tensor is [C, T]
        C, T = wav_tensor.shape

        # --- 4) Compute fbank ---
        if C == 1:
            # Mono path: Kaldi.fbank expects shape [B, T]; here B=1
            feat = Kaldi.fbank(
                wav_tensor, num_mel_bins=self.n_mels, sample_frequency=sr, dither=dither
            )  # [T, n_mels]

            if self.mean_nor:
                feat = feat - feat.mean(0, keepdim=True)  # zero-mean per feature dim

            feat = feat.unsqueeze(0)  # [1, T, n_mels]
        else:
            # Multi-channel: compute per channel, then pad along time
            feats = []
            for i in range(C):
                f = Kaldi.fbank(
                    wav_tensor[i].unsqueeze(0),  # [1, T]
                    num_mel_bins=self.n_mels,
                    sample_frequency=sr,
                    dither=dither,
                )  # [T_i, n_mels]
                if self.mean_nor:
                    f = f - f.mean(0, keepdim=True)
                feats.append(f)

            # Pad along time to the longest frame length across channels
            feat = torch.nn.utils.rnn.pad_sequence(feats, batch_first=True)  # [C, Tmax, n_mels]

        # --- 5) Return numpy on CPU ---
        return feat.cpu().numpy()

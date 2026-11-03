# Adapted from Clips Kitty (https://github.com/ColinGPT9/clips-studio), AGPL-3.0-or-later, Copyright (C) 2026 ColinGPT9. Modified for TeddyClip.
"""PANNs MobileNetV1: an AudioSet sound tagger, used to hear laughter and shouts.

The network is Kong et al.'s MobileNetV1 from "PANNs: Large-Scale Pretrained
Audio Neural Networks for Audio Pattern Recognition" (2020), adapted from
qiuqiangkong/audioset_tagging_cnn, pytorch/models.py:

    Copyright (c) 2018-2020 Qiuqiang Kong. MIT License: permission is hereby
    granted, free of charge, to any person obtaining a copy of this software
    and associated documentation files (the "Software"), to deal in the
    Software without restriction, including without limitation the rights to
    use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions: The above
    copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED
    "AS IS", WITHOUT WARRANTY OF ANY KIND.

Upstream builds its front end on torchlibrosa and librosa, which TeddyClip
doesn't ship. The layers and their names are upstream's, so the published
checkpoint loads as-is; what changed is the front end (torch.stft, and the
mel filterbank the checkpoint carries), and training-only parts (SpecAugment,
mixup, dropout) are gone. The weights (Zenodo record 3987831, CC BY 4.0) and
the AudioSet label list are downloaded once by `ensure_assets`.
"""

from __future__ import annotations

import csv
import hashlib
import urllib.request
from pathlib import Path

import numpy as np

# What the network was trained on; none of these are free parameters.
SAMPLE_RATE = 32000
N_FFT = 1024
HOP = 320
MEL_BINS = 64
CLASSES = 527

WEIGHTS_NAME = "MobileNetV1_mAP=0.389.pth"
WEIGHTS_URL = "https://zenodo.org/records/3987831/files/MobileNetV1_mAP%3D0.389.pth"
WEIGHTS_MD5 = "a419303e1c88aa1b9d2ac3811563d371"  # as Zenodo publishes it
LABELS_NAME = "class_labels_indices.csv"
LABELS_URL = "https://storage.googleapis.com/us_audioset/youtube_corpus/v1/csv/class_labels_indices.csv"

# AudioSet classes pooled into the two people-sound signals. Names must match
# the label list exactly; a name missing from it is skipped.
GROUPS = {
    "laughter": ["Laughter", "Belly laugh", "Giggle", "Chuckle, chortle", "Snicker"],
    "shout": ["Screaming", "Shout", "Yell", "Battle cry"],
}


def _download(url: str, dest: Path) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "teddyclip"})
    with urllib.request.urlopen(req, timeout=600) as r:
        data = r.read()
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return data


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def ensure_assets(models: Path) -> tuple[Path, Path]:
    """Download the checkpoint and the AudioSet label CSV into `models` once.
    Returns (weights, labels). A weights file that fails its checksum is
    fetched again; a download that still fails it is removed and raises."""
    models = Path(models)
    models.mkdir(parents=True, exist_ok=True)
    weights = models / WEIGHTS_NAME
    labels = models / LABELS_NAME
    if not (weights.exists() and _md5(weights) == WEIGHTS_MD5):
        _download(WEIGHTS_URL, weights)
        if _md5(weights) != WEIGHTS_MD5:
            weights.unlink()
            raise RuntimeError("the PANNs weights download does not match the published checksum")
    if not labels.exists():
        _download(LABELS_URL, labels)
    return weights, labels


def _read_labels(labels: Path) -> list[str]:
    """Display names from class_labels_indices.csv (index,mid,display_name), in
    the network's output order."""
    with open(labels, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: int(r["index"]))
    return [r["display_name"] for r in rows]


def _network():
    import torch
    from torch import nn

    def conv_bn(inp, oup, stride):
        return nn.Sequential(nn.Conv2d(inp, oup, 3, 1, 1, bias=False), nn.AvgPool2d(stride),
                             nn.BatchNorm2d(oup), nn.ReLU(inplace=True))

    def conv_dw(inp, oup, stride):
        return nn.Sequential(nn.Conv2d(inp, inp, 3, 1, 1, groups=inp, bias=False), nn.AvgPool2d(stride),
                             nn.BatchNorm2d(inp), nn.ReLU(inplace=True),
                             nn.Conv2d(inp, oup, 1, 1, 0, bias=False), nn.BatchNorm2d(oup),
                             nn.ReLU(inplace=True))

    class MobileNetV1(nn.Module):
        def __init__(self):
            super().__init__()
            self.register_buffer("window", torch.hann_window(N_FFT, periodic=True))
            self.register_buffer("melW", torch.zeros(N_FFT // 2 + 1, MEL_BINS))
            self.bn0 = nn.BatchNorm2d(MEL_BINS)
            self.features = nn.Sequential(
                conv_bn(1, 32, 2), conv_dw(32, 64, 1), conv_dw(64, 128, 2), conv_dw(128, 128, 1),
                conv_dw(128, 256, 2), conv_dw(256, 256, 1), conv_dw(256, 512, 2),
                conv_dw(512, 512, 1), conv_dw(512, 512, 1), conv_dw(512, 512, 1),
                conv_dw(512, 512, 1), conv_dw(512, 512, 1), conv_dw(512, 1024, 2),
                conv_dw(1024, 1024, 1))
            self.fc1 = nn.Linear(1024, 1024, bias=True)
            self.fc_audioset = nn.Linear(1024, CLASSES, bias=True)

        def forward(self, wave):
            """wave: (batch, samples) at 32 kHz -> (batch, 527) probabilities."""
            spec = torch.stft(wave, N_FFT, HOP, N_FFT, self.window, center=True,
                              pad_mode="reflect", return_complex=True)
            power = spec.real ** 2 + spec.imag ** 2                  # (batch, freq, time)
            mel = torch.matmul(power.transpose(1, 2), self.melW)    # (batch, time, mel)
            x = (10.0 * torch.log10(torch.clamp(mel, min=1e-10))).unsqueeze(1)
            x = self.bn0(x.transpose(1, 3)).transpose(1, 3)
            x = self.features(x)
            x = torch.mean(x, dim=3)
            x = torch.max(x, dim=2)[0] + torch.mean(x, dim=2)
            x = torch.relu(self.fc1(x))
            return torch.sigmoid(self.fc_audioset(x))

    return MobileNetV1()


class Tagger:
    """The AudioSet tagger on the CPU. `labels` names the 527 output classes
    in order; `tag` maps (n, samples) 32 kHz float32 audio to (n, 527)
    probabilities."""

    def __init__(self, weights: Path, labels: Path, batch: int = 32):
        import torch

        self.labels = _read_labels(Path(labels))
        self._batch = batch
        state = torch.load(Path(weights), map_location="cpu", weights_only=True)
        state = state.get("model", state)
        model = _network()
        # The checkpoint's STFT is a convolution with the window baked in
        # (torchlibrosa); torch.stft computes the same thing, so only its mel
        # filterbank is kept.
        state = {k: v for k, v in state.items() if not k.startswith("spectrogram_extractor.")}
        state["melW"] = state.pop("logmel_extractor.melW")
        state["window"] = model.window
        model.load_state_dict(state)
        self._model = model.eval()

    def tag(self, windows: np.ndarray) -> np.ndarray:
        import torch

        out = []
        with torch.inference_mode():
            for i in range(0, len(windows), self._batch):
                x = torch.from_numpy(np.ascontiguousarray(windows[i:i + self._batch], dtype=np.float32))
                out.append(self._model(x).float().numpy())
        return np.concatenate(out) if out else np.zeros((0, CLASSES), dtype=np.float32)

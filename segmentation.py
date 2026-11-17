"""Optional PlantSeg U-Net inference for lesion localization.

Install ``segmentation-requirements.txt`` and train a checkpoint with
``python train_unet.py --data data/PlantSeg`` to enable this module.
"""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path

ROOT = Path(__file__).parent
CHECKPOINT = Path(os.getenv("PLANTSEG_MODEL_PATH", ROOT / "models" / "plantseg_unet.pt"))
IMAGE_SIZE = 256

try:
    import torch
    from torch import nn
    import torch.nn.functional as F
    from PIL import Image, ImageDraw
except ImportError:  # The core app works without the optional segmentation stack.
    torch = None
    nn = None
    F = None
    Image = None


if nn is not None:
    class DoubleConv(nn.Module):
        def __init__(self, in_channels: int, out_channels: int):
            super().__init__()
            self.layers = nn.Sequential(
                nn.Conv2d(in_channels, out_channels, 3, padding=1, bias=False),
                nn.BatchNorm2d(out_channels),
                nn.ReLU(inplace=True),
                nn.Conv2d(out_channels, out_channels, 3, padding=1, bias=False),
                nn.BatchNorm2d(out_channels),
                nn.ReLU(inplace=True),
            )

        def forward(self, x):
            return self.layers(x)


    class UNet(nn.Module):
        """Compact binary U-Net; foreground pixels represent disease lesions."""
        def __init__(self, base_channels: int = 16):
            super().__init__()
            widths = [base_channels * (2 ** i) for i in range(5)]
            self.encoders = nn.ModuleList()
            incoming = 3
            for width in widths[:-1]:
                self.encoders.append(DoubleConv(incoming, width))
                incoming = width
            self.bottleneck = DoubleConv(widths[-2], widths[-1])
            self.pool = nn.MaxPool2d(2)
            self.upconvs = nn.ModuleList()
            self.decoders = nn.ModuleList()
            incoming = widths[-1]
            for width in reversed(widths[:-1]):
                self.upconvs.append(nn.ConvTranspose2d(incoming, width, 2, stride=2))
                self.decoders.append(DoubleConv(width * 2, width))
                incoming = width
            self.head = nn.Conv2d(widths[0], 1, kernel_size=1)

        def forward(self, x):
            skips = []
            for encoder in self.encoders:
                x = encoder(x)
                skips.append(x)
                x = self.pool(x)
            x = self.bottleneck(x)
            for up, decoder, skip in zip(self.upconvs, self.decoders, reversed(skips)):
                x = up(x)
                if x.shape[-2:] != skip.shape[-2:]:
                    x = F.interpolate(x, size=skip.shape[-2:], mode="bilinear", align_corners=False)
                x = decoder(torch.cat([skip, x], dim=1))
            return self.head(x)


_model = None
_device = None


def available() -> bool:
    return torch is not None and Image is not None and CHECKPOINT.is_file()


def _load_model():
    global _model, _device
    if not available():
        return None
    if _model is None:
        _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        checkpoint = torch.load(CHECKPOINT, map_location=_device, weights_only=True)
        _model = UNet(base_channels=int(checkpoint.get("base_channels", 16)))
        _model.load_state_dict(checkpoint["model_state"])
        _model.to(_device).eval()
    return _model


def _data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=82, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def predict_overlay(image_bytes: bytes) -> dict | None:
    """Return an annotated preview and lesion coverage, or None when untrained."""
    model = _load_model()
    if model is None:
        return None
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    original_size = image.size
    resized = image.resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR)
    pixels = torch.from_numpy(__import__("numpy").asarray(resized, dtype="float32").copy() / 255.0)
    tensor = pixels.permute(2, 0, 1).unsqueeze(0)
    mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
    with torch.inference_mode():
        probabilities = torch.sigmoid(model(((tensor - mean) / std).to(_device)))[0, 0]
    mask = (probabilities >= 0.5).cpu().numpy()
    preview = image.copy()
    preview.thumbnail((768, 768), Image.Resampling.LANCZOS)
    preview_size = preview.size
    mask_image = Image.fromarray((mask * 255).astype("uint8")).resize(preview_size, Image.Resampling.NEAREST)
    overlay = preview.convert("RGBA")
    tint = Image.new("RGBA", preview_size, (220, 57, 39, 105))
    tint.putalpha(mask_image.point(lambda value: int(value * 0.42)))
    overlay.alpha_composite(tint)
    draw = ImageDraw.Draw(overlay)
    coverage = float(mask.mean() * 100)
    return {
        "preview_data_url": _data_url(overlay.convert("RGB")),
        "lesion_coverage_percent": round(coverage, 1),
        "threshold": 0.5,
        "model": "PlantSeg U-Net",
        "note": "Red shading marks pixels the model identified as lesion-like. This is a visual localization aid, not a disease diagnosis.",
    }

"""Train a binary lesion U-Net on the PlantSeg folder layout.

Expected layout (as provided by the PlantSeg paper):
  data/PlantSeg/images/{train,val,test}/*.jpg
  data/PlantSeg/annotations/{train,val,test}/*.png

PNG masks encode disease classes and background as grayscale indices. This
loader treats each mask's most common value as background (lesions are the
annotated minority region), and learns "lesion pixel or background?".
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset

from segmentation import IMAGE_SIZE, UNet


class PlantSegDataset(Dataset):
    def __init__(self, root: Path, split: str, augment: bool = False):
        self.image_root = root / "images" / split
        self.mask_root = root / "annotations" / split
        if not self.image_root.is_dir() or not self.mask_root.is_dir():
            raise FileNotFoundError(f"Expected {self.image_root} and {self.mask_root}")
        masks = {path.stem: path for path in self.mask_root.rglob("*.png")}
        self.pairs = [(path, masks[path.stem]) for path in self.image_root.rglob("*")
                      if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} and path.stem in masks]
        if not self.pairs:
            raise RuntimeError(f"No matching image and PNG mask pairs found in split '{split}'.")
        self.augment = augment

    def __len__(self):
        return len(self.pairs)

    def __getitem__(self, index):
        image_path, mask_path = self.pairs[index]
        image = Image.open(image_path).convert("RGB").resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR)
        mask = Image.open(mask_path).convert("L").resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.NEAREST)
        image_array = np.asarray(image, dtype=np.float32) / 255.0
        mask_values = np.asarray(mask, dtype=np.uint8)
        background_value = int(np.bincount(mask_values.reshape(-1), minlength=256).argmax())
        mask_array = (mask_values != background_value).astype(np.float32)
        if self.augment and random.random() < 0.5:
            image_array, mask_array = image_array[:, ::-1].copy(), mask_array[:, ::-1].copy()
        if self.augment and random.random() < 0.5:
            image_array, mask_array = image_array[::-1].copy(), mask_array[::-1].copy()
        image_tensor = torch.from_numpy(image_array).permute(2, 0, 1)
        mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
        image_tensor = (image_tensor - mean) / std
        return image_tensor, torch.from_numpy(mask_array).unsqueeze(0)


def dice_score(logits, targets):
    predictions = torch.sigmoid(logits) >= 0.5
    predictions = predictions.float()
    intersection = (predictions * targets).sum(dim=(1, 2, 3))
    total = predictions.sum(dim=(1, 2, 3)) + targets.sum(dim=(1, 2, 3))
    return ((2 * intersection + 1) / (total + 1)).mean()


def loss_fn(logits, targets):
    bce = nn.functional.binary_cross_entropy_with_logits(logits, targets)
    probabilities = torch.sigmoid(logits)
    intersection = (probabilities * targets).sum(dim=(1, 2, 3))
    denominator = probabilities.sum(dim=(1, 2, 3)) + targets.sum(dim=(1, 2, 3))
    dice_loss = 1 - ((2 * intersection + 1) / (denominator + 1)).mean()
    return bce + dice_loss


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/PlantSeg"))
    parser.add_argument("--output", type=Path, default=Path("models/plantseg_unet.pt"))
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--base-channels", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    train_data = PlantSegDataset(args.data, "train", augment=True)
    val_data = PlantSegDataset(args.data, "val")
    train_loader = DataLoader(train_data, batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_data, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = UNet(args.base_channels).to(args.device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    best_dice = -1.0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    print(f"Training on {args.device}: {len(train_data)} train, {len(val_data)} validation images")

    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        for images, masks in train_loader:
            images, masks = images.to(args.device), masks.to(args.device)
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(images), masks)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        model.eval()
        scores = []
        with torch.inference_mode():
            for images, masks in val_loader:
                scores.append(dice_score(model(images.to(args.device)), masks.to(args.device)).item())
        val_dice = float(np.mean(scores))
        print(f"Epoch {epoch:02d}/{args.epochs} | train loss {total_loss / max(1, len(train_loader)):.4f} | val Dice {val_dice:.4f}")
        if val_dice > best_dice:
            best_dice = val_dice
            torch.save({"model_state": model.cpu().state_dict(), "base_channels": args.base_channels,
                        "image_size": IMAGE_SIZE, "best_validation_dice": best_dice,
                        "dataset": "PlantSeg", "background_value": "per-image-majority"}, args.output)
            model.to(args.device)

    print(f"Saved best checkpoint to {args.output} (validation Dice {best_dice:.4f})")


if __name__ == "__main__":
    main()

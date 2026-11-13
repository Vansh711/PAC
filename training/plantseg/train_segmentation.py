"""Train a binary lesion-area segmenter from PlantSeg's image/mask pairs."""
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision.models import ResNet50_Weights
from torchvision.models.segmentation import deeplabv3_resnet50


class PlantSegDataset(Dataset):
    def __init__(self, root: Path, split: str, size: int, augment: bool = False):
        self.root, self.split, self.size, self.augment = root, split, size, augment
        csv_split = {"train": "Training", "val": "Validation", "test": "Test"}[split]
        with (root / "Metadata.csv").open(encoding="utf-8-sig", newline="") as source:
            self.rows = [row for row in csv.DictReader(source) if row["Split"] == csv_split]
        if not self.rows:
            raise ValueError(f"No {split} rows found in {root / 'Metadata.csv'}")

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        image = Image.open(self.root / "images" / self.split / row["Name"]).convert("RGB")
        mask = Image.open(self.root / "annotations" / self.split / row["Label file"]).convert("L")
        if image.size != mask.size:
            raise ValueError(f"Image/mask dimensions differ: {row['Name']} ({image.size} vs {mask.size})")
        if self.augment and random.random() < 0.5:
            image, mask = ImageOps.mirror(image), ImageOps.mirror(mask)
        if self.augment and random.random() < 0.25:
            image, mask = ImageOps.flip(image), ImageOps.flip(mask)
        image = image.resize((self.size, self.size), Image.Resampling.BILINEAR)
        mask = mask.resize((self.size, self.size), Image.Resampling.NEAREST)
        x = np.asarray(image, dtype=np.float32) / 255.0
        x = (x - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array([0.229, 0.224, 0.225], dtype=np.float32)
        y = (np.asarray(mask, dtype=np.uint8) > 0).astype(np.int64)
        return torch.from_numpy(x.transpose(2, 0, 1).copy()), torch.from_numpy(y.copy())


def dice_loss(logits, target):
    probs = torch.softmax(logits, dim=1)[:, 1]
    truth = (target == 1).float()
    dims = (1, 2)
    score = (2 * (probs * truth).sum(dims) + 1) / (probs.sum(dims) + truth.sum(dims) + 1)
    return 1 - score.mean()


@torch.no_grad()
def score(model, loader, device, criterion):
    model.eval()
    loss_sum = intersection = union = dice_intersection = pred_sum = truth_sum = 0.0
    batches = 0
    for images, masks in loader:
        images, masks = images.to(device), masks.to(device)
        logits = model(images)["out"]
        loss = criterion(logits, masks) + dice_loss(logits, masks)
        pred = logits.argmax(1) == 1
        truth = masks == 1
        intersection += (pred & truth).sum().item()
        union += (pred | truth).sum().item()
        dice_intersection += (pred & truth).sum().item()
        pred_sum += pred.sum().item()
        truth_sum += truth.sum().item()
        loss_sum += loss.item()
        batches += 1
    return {"loss": loss_sum / max(1, batches), "iou": intersection / max(1, union), "dice": (2 * dice_intersection) / max(1, pred_sum + truth_sum)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("datasets/PlantSeg/Plantseg"))
    parser.add_argument("--output", type=Path, default=Path("training/plantseg/checkpoints/plantseg_deeplabv3.pth"))
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--image-size", type=int, default=512)
    parser.add_argument("--workers", type=int, default=0, help="Use 0 on Windows for reliable dataloading")
    parser.add_argument("--no-pretrained-backbone", action="store_true", help="Train from scratch instead of fine-tuning ImageNet ResNet-50 weights")
    parser.add_argument("--test-after-training", action="store_true", help="Evaluate the held-out test split once after selecting the best validation checkpoint")
    args = parser.parse_args()

    random.seed(42); np.random.seed(42); torch.manual_seed(42)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Training on {device}; dataset={args.dataset.resolve()}")
    train_data = PlantSegDataset(args.dataset, "train", args.image_size, augment=True)
    val_data = PlantSegDataset(args.dataset, "val", args.image_size)
    train_loader = DataLoader(train_data, batch_size=args.batch_size, shuffle=True, num_workers=args.workers, pin_memory=device.type == "cuda")
    val_loader = DataLoader(val_data, batch_size=args.batch_size, shuffle=False, num_workers=args.workers, pin_memory=device.type == "cuda")

    backbone_weights = None if args.no_pretrained_backbone else ResNet50_Weights.DEFAULT
    model = deeplabv3_resnet50(weights=None, weights_backbone=backbone_weights, num_classes=2).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-4, weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    best_iou = -1.0
    best_epoch = 0
    best_validation = None
    test_metrics = None
    metrics_path = args.output.parent / "training_metrics.csv"
    started = time.time()

    with metrics_path.open("w", newline="", encoding="utf-8") as metrics_file:
        metrics_writer = csv.DictWriter(metrics_file, fieldnames=["epoch", "train_loss", "validation_loss", "validation_iou", "validation_dice"])
        metrics_writer.writeheader()
        metrics_file.flush()
        for epoch in range(1, args.epochs + 1):
            model.train(); running = 0.0
            for images, masks in train_loader:
                images, masks = images.to(device), masks.to(device)
                optimizer.zero_grad(set_to_none=True)
                logits = model(images)["out"]
                loss = criterion(logits, masks) + dice_loss(logits, masks)
                loss.backward(); optimizer.step()
                running += loss.item()
            train_loss = running / max(1, len(train_loader))
            val = score(model, val_loader, device, criterion)
            print(f"epoch {epoch:02d}/{args.epochs} train_loss={train_loss:.4f} val_loss={val['loss']:.4f} val_iou={val['iou']:.4f} val_dice={val['dice']:.4f}")
            metrics_writer.writerow({"epoch": epoch, "train_loss": f"{train_loss:.6f}", "validation_loss": f"{val['loss']:.6f}", "validation_iou": f"{val['iou']:.6f}", "validation_dice": f"{val['dice']:.6f}"})
            metrics_file.flush()
            if val["iou"] > best_iou:
                best_iou = val["iou"]
                best_epoch = epoch
                best_validation = val
                torch.save({"model_state_dict": model.state_dict(), "architecture": "deeplabv3_resnet50", "classes": ["background", "visible_lesion"], "image_size": args.image_size, "best_epoch": epoch, "validation_iou": val["iou"], "validation_dice": val["dice"]}, args.output)
                print(f"  saved best checkpoint: {args.output}")

    if args.test_after_training:
        checkpoint = torch.load(args.output, map_location=device, weights_only=True)
        model.load_state_dict(checkpoint["model_state_dict"])
        test_loader = DataLoader(PlantSegDataset(args.dataset, "test", args.image_size), batch_size=args.batch_size, shuffle=False, num_workers=args.workers)
        test_metrics = score(model, test_loader, device, criterion)
        print("held-out test:", test_metrics)

    summary = {"status": "completed", "architecture": "deeplabv3_resnet50", "fine_tuned_pretrained_backbone": not args.no_pretrained_backbone, "epochs_requested": args.epochs, "best_epoch": best_epoch, "training_samples": len(train_data), "validation_samples": len(val_data), "best_validation": best_validation, "held_out_test": test_metrics, "checkpoint": str(args.output), "checkpoint_bytes": args.output.stat().st_size, "metrics_csv": str(metrics_path), "elapsed_seconds": round(time.time() - started, 1)}
    summary_path = args.output.parent / "training_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Training complete. Verify checkpoint and metrics with: python training/plantseg/verify_training.py")


if __name__ == "__main__":
    main()

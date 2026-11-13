"""Quickly verify that a PlantSeg training run produced a loadable checkpoint."""
import argparse
import json
from pathlib import Path

import torch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=Path("training/plantseg/checkpoints/training_summary.json"))
    args = parser.parse_args()
    if not args.summary.is_file():
        raise SystemExit(f"Training summary not found: {args.summary}. Run train_segmentation.py first.")
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    if summary.get("status") != "completed":
        raise SystemExit("Training summary is not marked completed.")
    checkpoint_path = Path(summary["checkpoint"])
    if not checkpoint_path.is_file():
        raise SystemExit(f"Checkpoint file is missing: {checkpoint_path}")
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    weights = checkpoint.get("model_state_dict")
    if not weights or not all(torch.is_tensor(value) for value in weights.values()):
        raise SystemExit("Checkpoint does not contain valid model weights.")
    val = summary.get("best_validation") or {}
    print("TRAINING CHECK: PASS")
    print(f"Checkpoint loads: {checkpoint_path} ({checkpoint_path.stat().st_size:,} bytes)")
    print(f"Architecture: {summary['architecture']}")
    print(f"Fine-tuned pretrained backbone: {summary['fine_tuned_pretrained_backbone']}")
    print(f"Best epoch: {summary['best_epoch']} / {summary['epochs_requested']}")
    print(f"Samples: train={summary['training_samples']:,}, validation={summary['validation_samples']:,}")
    print(f"Best validation IoU: {val.get('iou', float('nan')):.4f}")
    print(f"Best validation Dice: {val.get('dice', float('nan')):.4f}")
    if summary.get("held_out_test"):
        test = summary["held_out_test"]
        print(f"Held-out test IoU: {test['iou']:.4f}")
        print(f"Held-out test Dice: {test['dice']:.4f}")
    else:
        print("Held-out test: not run; rerun training with --test-after-training for the final check.")
    print(f"Per-epoch metrics: {summary['metrics_csv']}")


if __name__ == "__main__":
    main()

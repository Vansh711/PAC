"""Audit PlantSeg metadata, split manifests, and paired image/mask files."""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
from pathlib import Path


SPLITS = {"Training": "train", "Validation": "val", "Test": "test"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("datasets/PlantSeg/Plantseg"))
    args = parser.parse_args()
    root = args.dataset
    metadata_path = root / "Metadata.csv"
    if not metadata_path.is_file():
        raise SystemExit(f"Metadata.csv not found under {root.resolve()}")

    with metadata_path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    if not rows:
        raise SystemExit("Metadata.csv has no data rows.")

    print(f"Dataset root: {root.resolve()}")
    print(f"Metadata records: {len(rows):,}")
    print(f"Plant hosts: {len({r['Plant'] for r in rows})}")
    print(f"Disease labels: {len({r['Disease'] for r in rows})}")
    print("License metadata:")
    for name, count in collections.Counter(r["License"] for r in rows).most_common():
        print(f"  {name or '(empty)'}: {count:,}")

    overall_ok = True
    for metadata_split, folder_split in SPLITS.items():
        expected_rows = [row for row in rows if row["Split"] == metadata_split]
        expected_images = {row["Name"] for row in expected_rows}
        expected_masks = {row["Label file"] for row in expected_rows}
        image_dir, mask_dir = root / "images" / folder_split, root / "annotations" / folder_split
        if not image_dir.is_dir() or not mask_dir.is_dir():
            raise SystemExit(f"Missing image or annotation directory for split: {folder_split}")
        actual_images = {entry.name for entry in os.scandir(image_dir) if entry.is_file()}
        actual_masks = {entry.name for entry in os.scandir(mask_dir) if entry.is_file()}
        missing_images, extra_images = expected_images - actual_images, actual_images - expected_images
        missing_masks, extra_masks = expected_masks - actual_masks, actual_masks - expected_masks
        ok = not (missing_images or extra_images or missing_masks or extra_masks)
        overall_ok &= ok
        print(f"{folder_split}: {len(expected_rows):,} records; {len(actual_images):,} images; {len(actual_masks):,} masks; {'OK' if ok else 'MISMATCH'}")
        if missing_images: print(f"  Missing images (first 10): {sorted(missing_images)[:10]}")
        if extra_images: print(f"  Unlisted images (first 10): {sorted(extra_images)[:10]}")
        if missing_masks: print(f"  Missing masks (first 10): {sorted(missing_masks)[:10]}")
        if extra_masks: print(f"  Unlisted masks (first 10): {sorted(extra_masks)[:10]}")

        json_path = root / "json" / f"annotation_{folder_split}.json"
        with json_path.open(encoding="utf-8") as source:
            coco = json.load(source)
        json_names = {item["file_name"] for item in coco.get("images", [])}
        image_by_id = {item["id"]: item for item in coco.get("images", [])}
        annotation_image_ids = set(image_by_id)
        annotated_image_ids = {item["image_id"] for item in coco.get("annotations", [])}
        unannotated = annotation_image_ids - annotated_image_ids
        print(f"  COCO JSON: {len(json_names):,} images; {len(coco.get('annotations', [])):,} polygons; {len(unannotated):,} images without a lesion polygon; category records={len(coco.get('categories', []))}")
        for image_id in sorted(unannotated)[:10]:
            name = image_by_id[image_id]["file_name"]
            metadata = next((row for row in expected_rows if row["Name"] == name), {})
            print(f"  Review empty-mask case: {name}; disease={metadata.get('Disease', '?')}; ratio={metadata.get('Mask ratio', '?')}; source={metadata.get('URL', '?')}")

    print("Overall file-pair check:", "PASS" if overall_ok else "FAIL")
    if not overall_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

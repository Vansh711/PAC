# PlantSeg training, in simple steps

This folder contains a small training example for the extracted PlantSeg dataset. It teaches an image model to mark visible lesion/damaged areas in a leaf image. It does **not** fine-tune Gemini or the voice assistant, and it does not identify a disease name.

## Where to run the commands

Open PowerShell (or the VS Code terminal) in the project folder that contains `app.py`, `src`, and `training`. In this workspace that is:

```text
C:\Users\chaud\OneDrive\Desktop\PAC\PAC
```

If your terminal is elsewhere, first run:

```powershell
cd C:\Users\chaud\OneDrive\Desktop\PAC\PAC
```

The commands below assume the dataset is extracted at `datasets/PlantSeg/Plantseg/`.

## 1. Set up the training environment once

Use a separate Python environment so the website's packages remain unchanged. Install a CPU or GPU version of PyTorch from the [official PyTorch installation selector](https://pytorch.org/get-started/locally/), then install the small set of other libraries:

```powershell
py -m venv .venv-plantseg
.\.venv-plantseg\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install torch torchvision Pillow numpy
```

If PowerShell says script execution is disabled, use the direct Python path in the commands below instead of activating the environment.

## 2. Train, then verify

Run these two commands from the project folder above:

```powershell
python training\plantseg\train_segmentation.py --epochs 10 --batch-size 4 --test-after-training
python training\plantseg\verify_training.py
```

If you did not activate the environment, replace `python` with `.\.venv-plantseg\Scripts\python.exe` (for example: `.\.venv-plantseg\Scripts\python.exe training\plantseg\train_segmentation.py --epochs 10 --batch-size 4 --test-after-training`).

Training can take a while and the first run downloads ImageNet backbone weights. If your computer runs out of memory, try `--batch-size 1`; `--epochs 2` is a quicker practice run.

## How to tell whether it worked

The verification command should print `TRAINING CHECK: PASS`. It also checks that the saved model weights can be loaded. You can inspect these files in `training/plantseg/checkpoints/`:

- `plantseg_deeplabv3.pth` — trained model weights.
- `training_summary.json` — best epoch, validation scores and held-out test scores.
- `training_metrics.csv` — loss and validation scores after each epoch; open it in a spreadsheet if you like.

If verification says a summary is missing, training did not finish successfully. If the summary says held-out test was not run, train again with `--test-after-training`.

## What this training means

The script fine-tunes an ImageNet-pretrained ResNet-50 image backbone with a DeepLabV3 segmentation head. It learns two pixel labels: background and visible lesion. IoU and Dice are overlap scores; higher values mean the predicted damaged area overlaps the dataset's mask more closely. These scores do not establish that a diagnosis or treatment is safe in a real field.

The dataset has 11,458 image/mask pairs across 34 plant hosts and 114 disease labels. Its provided masks label visible lesion regions, not disease categories. One test image has no COCO lesion polygon and its source URL may not match its label, so use test scores as an initial check, not as proof of field performance. Dataset sources list mixed rights; review the dataset terms before commercial use or redistribution. Dataset files and trained outputs are ignored by Git.

To check that extraction still matches the dataset metadata, run this optional command from the same project folder:

```powershell
python training\plantseg\audit_dataset.py
```

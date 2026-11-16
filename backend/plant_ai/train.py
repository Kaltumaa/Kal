"""Train EfficientNet-B0 (timm, ImageNet-pretrained) on data/dataset and save plant_ai_model.pth.

    python train.py                       # defaults: 10 epochs, balanced sampling, Apple MPS / CUDA / CPU
    python train.py --epochs 2 --per-class 100 --limit-val 500     # quick smoke run

Class balance: PlantVillage has thousands of lab photos per class, PlantDoc only tens of field photos. Each epoch
draws `--per-class` images per class at random (weighted sampler), and field photos (PlantDoc, file prefix "pd_")
are drawn `--field-boost` times more often, so the model sees real-world backgrounds.

The best epoch is chosen on FIELD-photo validation accuracy (PlantDoc test split): lab accuracy on PlantVillage is
near-perfect and says little about photos taken in a Kenyan shamba. Both are reported and saved in the checkpoint.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader, Subset, WeightedRandomSampler
from torchvision.datasets import ImageFolder

from plant_model import ARCH, DEFAULT_MODEL_PATH, IMG_SIZE, MEAN, STD, build_model, eval_transform, pick_device, \
    train_transform

HERE = Path(__file__).resolve().parent
DEFAULT_DATA = Path(os.environ.get("PLANT_AI_DATASET", Path.home() / "plant_ai_data" / "dataset"))


def is_field(path: str) -> bool:
    return Path(path).name.startswith("pd_")


def make_sampler(ds: ImageFolder, per_class: int, field_boost: float) -> WeightedRandomSampler:
    counts = Counter(ds.targets)
    weights = [(field_boost if is_field(p) else 1.0) / counts[t] for p, t in ds.samples]
    return WeightedRandomSampler(weights, num_samples=per_class * len(ds.classes), replacement=True)


@torch.inference_mode()
def evaluate(model, loader, device, samples) -> dict:
    model.eval()
    correct = total = f_correct = f_total = 0
    loss_sum = 0.0
    crit = nn.CrossEntropyLoss()
    offset = 0
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        out = model(x)
        loss_sum += crit(out, y).item() * len(y)
        hit = (out.argmax(1) == y).cpu()
        field = torch.tensor([is_field(samples[offset + i][0]) for i in range(len(y))])
        offset += len(y)
        correct += int(hit.sum())
        total += len(y)
        f_correct += int(hit[field].sum())
        f_total += int(field.sum())
    return {"val_acc": correct / max(total, 1), "val_loss": loss_sum / max(total, 1),
            "val_acc_field": f_correct / f_total if f_total else None, "val_field_images": f_total,
            "val_images": total}


def main() -> None:
    ap = argparse.ArgumentParser(description="Train the leaf-disease classifier.")
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--out", type=Path, default=DEFAULT_MODEL_PATH)
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--per-class", type=int, default=400, help="images drawn per class per epoch")
    ap.add_argument("--field-boost", type=float, default=4.0, help="how much more often PlantDoc photos are drawn")
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=4e-4)
    ap.add_argument("--weight-decay", type=float, default=0.02)
    ap.add_argument("--img-size", type=int, default=IMG_SIZE)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--limit-val", type=int, default=0, help="evaluate on at most this many val images (0 = all)")
    ap.add_argument("--no-pretrained", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    device = pick_device(args.device)
    train_ds = ImageFolder(args.data / "train", transform=train_transform(args.img_size))
    val_full = ImageFolder(args.data / "val", transform=eval_transform(args.img_size))
    if train_ds.classes != val_full.classes:
        raise SystemExit("train and val have different class folders; re-run prepare_dataset.py")
    val_samples = val_full.samples
    val_ds = val_full
    if args.limit_val and args.limit_val < len(val_full):
        # keep every field photo, then fill with an even spread of lab photos
        field = [i for i, (p, _) in enumerate(val_full.samples) if is_field(p)]
        lab = [i for i, (p, _) in enumerate(val_full.samples) if not is_field(p)]
        step = max(1, len(lab) // max(1, args.limit_val - len(field)))
        keep = sorted(field + lab[::step][: max(0, args.limit_val - len(field))])
        val_ds, val_samples = Subset(val_full, keep), [val_full.samples[i] for i in keep]

    print(f"device={device}  classes={len(train_ds.classes)}  train={len(train_ds)}  val={len(val_samples)}")
    pin = device.type == "cuda"
    train_dl = DataLoader(train_ds, batch_size=args.batch_size, sampler=make_sampler(train_ds, args.per_class,
                                                                                      args.field_boost),
                          num_workers=args.workers, pin_memory=pin, persistent_workers=args.workers > 0)
    val_dl = DataLoader(val_ds, batch_size=args.batch_size * 2, shuffle=False, num_workers=args.workers,
                        pin_memory=pin)

    pretrained = not args.no_pretrained
    try:
        model = build_model(len(train_ds.classes), pretrained=pretrained)
    except Exception as exc:  # noqa: BLE001 - offline: no ImageNet weights to download
        print(f"!! could not load ImageNet weights ({type(exc).__name__}); training from scratch")
        model, pretrained = build_model(len(train_ds.classes), pretrained=False), False
    model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    steps = args.epochs * math.ceil(args.per_class * len(train_ds.classes) / args.batch_size)
    warmup = min(200, steps // 10)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: (s + 1) / warmup if s < warmup else 0.5 * (1 + math.cos(math.pi * (s - warmup) / max(1, steps - warmup))))
    crit = nn.CrossEntropyLoss(label_smoothing=0.1)

    best, history = None, []
    for epoch in range(1, args.epochs + 1):
        model.train()
        t0, seen, loss_sum, correct = time.time(), 0, 0.0, 0
        for x, y in train_dl:
            x, y = x.to(device), y.to(device)
            out = model(x)
            loss = crit(out, y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            sched.step()
            seen += len(y)
            loss_sum += loss.item() * len(y)
            correct += int((out.argmax(1) == y).sum())
        m = evaluate(model, val_dl, device, val_samples)
        m.update(epoch=epoch, train_loss=loss_sum / seen, train_acc=correct / seen, seconds=round(time.time() - t0, 1))
        history.append(m)
        field = f"{m['val_acc_field']:.3f}" if m["val_acc_field"] is not None else "n/a"
        print(f"epoch {epoch:2d}  train_loss {m['train_loss']:.3f}  train_acc {m['train_acc']:.3f}  "
              f"val_acc {m['val_acc']:.3f}  val_acc_field {field}  ({m['seconds']}s)", flush=True)
        score = (m["val_acc_field"] or 0.0, m["val_acc"])
        if best is None or score > best[0]:
            best = (score, epoch)
            torch.save({"arch": ARCH, "classes": train_ds.classes, "img_size": args.img_size, "mean": MEAN,
                        "std": STD, "state_dict": {k: v.cpu() for k, v in model.state_dict().items()},
                        "metrics": m, "history": history, "pretrained_imagenet": pretrained,
                        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "dataset": str(args.data), "args": {k: str(v) for k, v in vars(args).items()}}, args.out)
    report = {"best_epoch": best[1], "best": history[best[1] - 1], "history": history, "model": str(args.out)}
    args.out.with_suffix(".metrics.json").write_text(json.dumps(report, indent=2))
    print(f"saved {args.out} (best epoch {best[1]}: val_acc {report['best']['val_acc']:.3f}, "
          f"field {report['best']['val_acc_field']})")


if __name__ == "__main__":
    main()

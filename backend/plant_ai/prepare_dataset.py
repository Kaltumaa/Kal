"""Merge the crop-disease classes that PlantVillage (raw/color) and PlantDoc (train + test) have in common into one
clean ImageFolder dataset:

    ~/plant_ai_data/dataset/train/<crop>__<condition>/*.jpg
    ~/plant_ai_data/dataset/val/<crop>__<condition>/*.jpg
    ~/plant_ai_data/dataset/classes.json      (class list, source mapping, per-split counts)

The output lives outside the project on purpose: an iCloud-synced Desktop stalls on writing ~40k small files.
Override with --out or PLANT_AI_DATASET.

Rules
* Only classes present in BOTH datasets are kept (see CLASS_MAP), so every class has lab photos (PlantVillage) and
  real field photos (PlantDoc).
* PlantDoc's own split is respected: PlantDoc/train -> train, PlantDoc/test -> val. PlantVillage is split
  deterministically (hash of the file path) with VAL_FRACTION going to val.
* PlantVillage is capped at --max-lab-per-class lab photos per class (default 600, a fixed hash-chosen subset):
  train.py draws 400 images per class per epoch anyway, and every PlantDoc field photo is always kept.
* Every image is opened and verified; unreadable or tiny files are skipped.
* Exact duplicates (same bytes) are kept once. If a duplicate sits in both splits, the val copy wins, so no
  validation image leaks into training.
* Each image is read once (checked, hashed and written from memory) and copied as a real file, so the output does
  not depend on the synced source folder.

Usage:  python prepare_dataset.py [--data-dir ../../data] [--out ~/plant_ai_data/dataset] [--val-fraction 0.15] [--clean]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import time
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, UnidentifiedImageError

HERE = Path(__file__).resolve().parent
DEFAULT_DATA = HERE.parents[1] / "data"
DEFAULT_OUT = Path(os.environ.get("PLANT_AI_DATASET", Path.home() / "plant_ai_data" / "dataset"))
IMAGE_EXT = {".jpg", ".jpeg", ".png"}
MIN_SIDE = 32
SOURCE_TAG = {"plantvillage": "pv", "plantdoc": "pd"}   # file-name prefix: lab (pv) vs field (pd) photo

# clean class name -> (PlantVillage raw/color folder, PlantDoc folder)
CLASS_MAP: dict[str, tuple[str, str]] = {
    "apple__scab": ("Apple___Apple_scab", "Apple Scab Leaf"),
    "apple__cedar_apple_rust": ("Apple___Cedar_apple_rust", "Apple rust leaf"),
    "apple__healthy": ("Apple___healthy", "Apple leaf"),
    "bell_pepper__bacterial_spot": ("Pepper,_bell___Bacterial_spot", "Bell_pepper leaf spot"),
    "bell_pepper__healthy": ("Pepper,_bell___healthy", "Bell_pepper leaf"),
    "blueberry__healthy": ("Blueberry___healthy", "Blueberry leaf"),
    "cherry__healthy": ("Cherry_(including_sour)___healthy", "Cherry leaf"),
    "corn__gray_leaf_spot": ("Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot", "Corn Gray leaf spot"),
    "corn__common_rust": ("Corn_(maize)___Common_rust_", "Corn rust leaf"),
    "corn__northern_leaf_blight": ("Corn_(maize)___Northern_Leaf_Blight", "Corn leaf blight"),
    "grape__black_rot": ("Grape___Black_rot", "grape leaf black rot"),
    "grape__healthy": ("Grape___healthy", "grape leaf"),
    "peach__healthy": ("Peach___healthy", "Peach leaf"),
    "potato__early_blight": ("Potato___Early_blight", "Potato leaf early blight"),
    "potato__late_blight": ("Potato___Late_blight", "Potato leaf late blight"),
    "raspberry__healthy": ("Raspberry___healthy", "Raspberry leaf"),
    "soybean__healthy": ("Soybean___healthy", "Soyabean leaf"),
    "squash__powdery_mildew": ("Squash___Powdery_mildew", "Squash Powdery mildew leaf"),
    "strawberry__healthy": ("Strawberry___healthy", "Strawberry leaf"),
    "tomato__bacterial_spot": ("Tomato___Bacterial_spot", "Tomato leaf bacterial spot"),
    "tomato__early_blight": ("Tomato___Early_blight", "Tomato Early blight leaf"),
    "tomato__late_blight": ("Tomato___Late_blight", "Tomato leaf late blight"),
    "tomato__leaf_mold": ("Tomato___Leaf_Mold", "Tomato mold leaf"),
    "tomato__septoria_leaf_spot": ("Tomato___Septoria_leaf_spot", "Tomato Septoria leaf spot"),
    "tomato__spider_mites": ("Tomato___Spider_mites Two-spotted_spider_mite", "Tomato two spotted spider mites leaf"),
    "tomato__mosaic_virus": ("Tomato___Tomato_mosaic_virus", "Tomato leaf mosaic virus"),
    "tomato__yellow_leaf_curl_virus": ("Tomato___Tomato_Yellow_Leaf_Curl_Virus", "Tomato leaf yellow virus"),
    "tomato__healthy": ("Tomato___healthy", "Tomato leaf"),
}


def _images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXT)


def _valid(raw: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.verify()
        with Image.open(io.BytesIO(raw)) as im:   # verify() leaves the image unusable; reopen to check the size
            return min(im.size) >= MIN_SIDE
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return False


def _pv_split(path: Path, val_fraction: float) -> str:
    bucket = int(hashlib.md5(path.name.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "val" if bucket < val_fraction else "train"


def _place(raw: bytes, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        tmp = dst.with_suffix(dst.suffix + ".part")
        tmp.write_bytes(raw)
        tmp.rename(dst)                            # never leave a half-written image behind


def _cap(paths: list[Path], limit: int) -> list[Path]:
    """A deterministic, evenly spread subset (by file-name hash), so reruns pick the same images."""
    if not limit or len(paths) <= limit:
        return paths
    return sorted(paths, key=lambda p: hashlib.md5(p.name.encode()).hexdigest())[:limit]


def collect(data_dir: Path, val_fraction: float, max_lab: int = 0) -> dict[str, list[tuple[str, str, Path]]]:
    """class -> [(split, source, path)] for every candidate image, before validation and dedupe."""
    pv_root = data_dir / "PlantVillage-Dataset" / "raw" / "color"
    pd_root = data_dir / "PlantDoc-Dataset"
    found: dict[str, list[tuple[str, str, Path]]] = defaultdict(list)
    missing = []
    for cls, (pv, pd) in CLASS_MAP.items():
        pv_imgs, pd_train, pd_test = _images(pv_root / pv), _images(pd_root / "train" / pd), _images(pd_root / "test" / pd)
        if not pv_imgs or not (pd_train or pd_test):
            missing.append(cls)
            continue
        found[cls] += [(_pv_split(p, val_fraction), "plantvillage", p) for p in _cap(pv_imgs, max_lab)]
        found[cls] += [("train", "plantdoc", p) for p in pd_train] + [("val", "plantdoc", p) for p in pd_test]
    if missing:
        print(f"!! skipped (not in both datasets on disk): {', '.join(missing)}")
    return found


def build(data_dir: Path, out: Path, val_fraction: float, max_lab: int = 0) -> dict:
    found = collect(data_dir, val_fraction, max_lab)
    seen: dict[str, tuple[str, str, Path]] = {}       # digest -> (split, class, placed path)
    counts: dict[str, Counter] = {"train": Counter(), "val": Counter()}
    sources: Counter = Counter()
    skipped = Counter()
    # val first, so a duplicate shared by both splits stays in val and is dropped from train
    items = sorted(((s, src, p, c) for c, lst in found.items() for s, src, p in lst), key=lambda t: t[0] != "val")
    started = time.time()
    for n, (split, source, path, cls) in enumerate(items, start=1):
        if n % 2000 == 0:
            rate = n / max(1e-6, time.time() - started)
            print(f"  {n}/{len(items)} images ({rate:.0f}/s, ~{(len(items) - n) / rate / 60:.0f} min left)", flush=True)
        try:
            raw = path.read_bytes()
        except OSError:
            if not path.parent.exists():          # the source folder was moved mid-run: stop, don't half-build
                raise SystemExit(f"!! source folder disappeared ({path.parent}); rerun from the new location")
            skipped["unreadable"] += 1
            continue
        if not _valid(raw):
            skipped["unreadable"] += 1
            continue
        digest = hashlib.sha1(raw).hexdigest()
        if digest in seen:
            skipped["duplicate"] += 1
            continue
        name = f"{SOURCE_TAG[source]}_{digest[:12]}{path.suffix.lower().replace('.jpeg', '.jpg')}"
        dst = out / split / cls / name
        _place(raw, dst)
        seen[digest] = (split, cls, dst)
        counts[split][cls] += 1
        sources[f"{split}:{source}"] += 1
    classes = sorted(found)
    meta = {"classes": classes, "class_map": {c: {"plantvillage": CLASS_MAP[c][0], "plantdoc": CLASS_MAP[c][1]}
                                              for c in classes},
            "counts": {s: dict(sorted(c.items())) for s, c in counts.items()},
            "totals": {s: sum(c.values()) for s, c in counts.items()}, "by_source": dict(sources),
            "skipped": dict(skipped), "val_fraction": val_fraction, "max_lab_per_class": max_lab or None}
    (out / "classes.json").write_text(json.dumps(meta, indent=2))
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--val-fraction", type=float, default=0.15)
    ap.add_argument("--max-lab-per-class", type=int, default=600,
                    help="PlantVillage (lab) photos kept per class, 0 = all. Every PlantDoc (field) photo is kept.")
    ap.add_argument("--clean", action="store_true", help="delete --out first")
    args = ap.parse_args()
    args.out = args.out.expanduser()
    if args.clean and args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True, exist_ok=True)
    meta = build(args.data_dir, args.out, args.val_fraction, args.max_lab_per_class)
    print(f"{len(meta['classes'])} classes -> {args.out}")
    print(f"train {meta['totals']['train']}  val {meta['totals']['val']}  sources {meta['by_source']}  "
          f"skipped {meta['skipped']}")


if __name__ == "__main__":
    main()

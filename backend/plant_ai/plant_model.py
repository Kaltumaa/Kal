"""The leaf-disease model shared by train.py and mcp_server.py: EfficientNet-B0 (timm), its image transforms, and the
checkpoint format of plant_ai_model.pth.

Checkpoint (a dict saved with torch.save):
    arch, classes, img_size, mean, std, state_dict, metrics, trained_at, dataset
"""
from __future__ import annotations

import io
from pathlib import Path

import timm
import torch
from PIL import Image
from torchvision import transforms

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = HERE / "plant_ai_model.pth"
ARCH = "efficientnet_b0"
IMG_SIZE = 224
MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)


def pick_device(name: str = "auto") -> torch.device:
    if name != "auto":
        return torch.device(name)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def build_model(num_classes: int, pretrained: bool = False) -> torch.nn.Module:
    return timm.create_model(ARCH, pretrained=pretrained, num_classes=num_classes)


def train_transform(img_size: int = IMG_SIZE):
    return transforms.Compose([
        transforms.RandomResizedCrop(img_size, scale=(0.55, 1.0)),
        transforms.RandomHorizontalFlip(), transforms.RandomVerticalFlip(p=0.2),
        transforms.RandomRotation(15),
        transforms.ColorJitter(0.3, 0.3, 0.25, 0.03),
        transforms.ToTensor(), transforms.Normalize(MEAN, STD)])


def eval_transform(img_size: int = IMG_SIZE):
    return transforms.Compose([transforms.Resize(int(img_size * 1.14)), transforms.CenterCrop(img_size),
                               transforms.ToTensor(), transforms.Normalize(MEAN, STD)])


class LeafClassifier:
    """Loads plant_ai_model.pth once and classifies leaf photos."""

    def __init__(self, path: Path = DEFAULT_MODEL_PATH, device: str = "auto"):
        if not Path(path).exists():
            raise FileNotFoundError(f"model not found: {path}. Train it with train.py first.")
        ckpt = torch.load(path, map_location="cpu", weights_only=False)
        self.classes: list[str] = ckpt["classes"]
        self.metrics: dict = ckpt.get("metrics", {})
        self.trained_at: str | None = ckpt.get("trained_at")
        self.device = pick_device(device)
        self.model = build_model(len(self.classes))
        self.model.load_state_dict(ckpt["state_dict"])
        self.model.to(self.device).eval()
        self.transform = eval_transform(ckpt.get("img_size", IMG_SIZE))

    @torch.inference_mode()
    def predict(self, image: Image.Image | bytes, top_k: int = 3) -> list[dict]:
        if isinstance(image, (bytes, bytearray)):
            image = Image.open(io.BytesIO(image))
        x = self.transform(image.convert("RGB")).unsqueeze(0).to(self.device)
        probs = torch.softmax(self.model(x).float(), dim=1)[0].cpu()
        conf, idx = probs.topk(min(top_k, len(self.classes)))
        return [{"label": self.classes[i], "crop": self.classes[i].split("__")[0],
                 "condition": self.classes[i].split("__")[1], "confidence": round(float(c), 4)}
                for c, i in zip(conf.tolist(), idx.tolist())]

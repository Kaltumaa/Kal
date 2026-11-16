#!/usr/bin/env bash
# Train plant_ai_model.pth on an AWS EC2 GPU instance (Deep Learning AMI GPU PyTorch, Ubuntu).
# The datasets are downloaded on the instance from GitHub; nothing big is uploaded from your laptop.
#
#   1. From your laptop:  scp -r backend/plant_ai ubuntu@<instance-ip>:~/
#   2. On the instance:   bash ~/plant_ai/aws_train.sh                 (optional: EPOCHS=10 S3_BUCKET=my-bucket)
#   3. From your laptop:  scp ubuntu@<instance-ip>:~/plant_ai/plant_ai_model.pth backend/plant_ai/
#   4. Terminate the instance in the EC2 console (it bills by the hour until you do).
set -euo pipefail

EPOCHS="${EPOCHS:-10}"
WORK="$HOME/plant_ai_work"
CODE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$WORK/data"

echo ">> Python with PyTorch"
if [ -f /opt/pytorch/bin/activate ]; then source /opt/pytorch/bin/activate; fi      # DLAMI PyTorch 2.x
if ! python3 -c "import torch" 2>/dev/null; then
  if command -v conda >/dev/null; then eval "$(conda shell.bash hook)"; conda activate pytorch || true; fi
fi
if ! python3 -c "import torch" 2>/dev/null; then
  # Any Ubuntu image with an NVIDIA driver (e.g. "Deep Learning Base OSS Nvidia Driver GPU AMI"): install PyTorch here.
  sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv git >/dev/null
  python3 -m venv "$WORK/venv" && source "$WORK/venv/bin/activate"
  python3 -m pip install -q --upgrade pip && python3 -m pip install -q torch torchvision
fi
nvidia-smi >/dev/null 2>&1 || echo "!! no NVIDIA driver found: this image or instance has no usable GPU (training will be very slow)"
python3 -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
python3 -m pip install -q timm pillow

echo ">> Datasets (only the folders we need)"
if [ ! -d "$WORK/data/PlantVillage-Dataset/raw/color" ]; then
  git clone --depth 1 --filter=blob:none --sparse https://github.com/spMohanty/PlantVillage-Dataset \
    "$WORK/data/PlantVillage-Dataset"
  git -C "$WORK/data/PlantVillage-Dataset" sparse-checkout set raw/color
fi
if [ ! -d "$WORK/data/PlantDoc-Dataset/train" ]; then
  git clone --depth 1 https://github.com/pratikkayal/PlantDoc-Dataset "$WORK/data/PlantDoc-Dataset"
fi

echo ">> Merge the shared classes"
python3 "$CODE/prepare_dataset.py" --data-dir "$WORK/data" --out "$WORK/dataset" --clean

echo ">> Train ($EPOCHS epochs)"
cd "$CODE"
python3 train.py --data "$WORK/dataset" --epochs "$EPOCHS" --batch-size 64 --workers 6

if [ -n "${S3_BUCKET:-}" ]; then
  echo ">> Upload to s3://$S3_BUCKET/plant_ai/"
  aws s3 cp plant_ai_model.pth "s3://$S3_BUCKET/plant_ai/plant_ai_model.pth"
  aws s3 cp plant_ai_model.metrics.json "s3://$S3_BUCKET/plant_ai/plant_ai_model.metrics.json"
fi
echo ">> Done: $CODE/plant_ai_model.pth"
python3 -c "import json; b=json.load(open('plant_ai_model.metrics.json'))['best']; \
print(f\"val_acc {b['val_acc']:.3f}  field-photo val_acc {b['val_acc_field']}\")"

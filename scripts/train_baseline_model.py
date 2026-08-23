"""Train the CIFAR-10 ResNet-18 checkpoints SERA's pipeline relies on.

Produces two checkpoints:
  - resnet18_cifar10        : trained to convergence, the "correct" model.
  - resnet18_cifar10_stale  : same architecture, stopped after 1 epoch,
                               used to simulate F5 (wrong checkpoint loaded).

Usage:
    python scripts/train_baseline_model.py --epochs 12
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch
import torch.nn as nn
import torch.optim as optim
import torchvision
import torchvision.transforms as T

from sera.config import CIFAR10_MEAN, CIFAR10_STD, DATA_DIR
from sera.model import make_resnet18_cifar, save_checkpoint


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=0.1)
    parser.add_argument("--train-subset", type=int, default=0, help="0 = full 50k training set")
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"training on {device}")

    train_tf = T.Compose(
        [
            T.RandomCrop(32, padding=4),
            T.RandomHorizontalFlip(),
            T.ToTensor(),
            T.Normalize(CIFAR10_MEAN, CIFAR10_STD),
        ]
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    train_set = torchvision.datasets.CIFAR10(
        root=str(DATA_DIR), train=True, download=True, transform=train_tf
    )
    if args.train_subset:
        train_set = torch.utils.data.Subset(train_set, range(args.train_subset))
    train_loader = torch.utils.data.DataLoader(
        train_set, batch_size=args.batch_size, shuffle=True, num_workers=0
    )

    test_tf = T.Compose([T.ToTensor(), T.Normalize(CIFAR10_MEAN, CIFAR10_STD)])
    test_set = torchvision.datasets.CIFAR10(
        root=str(DATA_DIR), train=False, download=True, transform=test_tf
    )
    test_loader = torch.utils.data.DataLoader(test_set, batch_size=512, shuffle=False)

    model = make_resnet18_cifar(num_classes=10).to(device)
    optimizer = optim.SGD(model.parameters(), lr=args.lr, momentum=0.9, weight_decay=5e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    criterion = nn.CrossEntropyLoss()

    def evaluate():
        model.eval()
        correct = total = 0
        with torch.no_grad():
            for x, y in test_loader:
                x, y = x.to(device), y.to(device)
                pred = model(x).argmax(dim=1)
                correct += (pred == y).sum().item()
                total += y.size(0)
        model.train()
        return correct / total

    model.train()
    for epoch in range(args.epochs):
        t0 = time.time()
        running_loss = 0.0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad()
            loss = criterion(model(x), y)
            loss.backward()
            optimizer.step()
            running_loss += loss.item() * x.size(0)
        scheduler.step()
        train_loss = running_loss / len(train_set)
        acc = evaluate()
        print(
            f"epoch {epoch + 1}/{args.epochs}  loss={train_loss:.4f}  "
            f"test_acc={acc:.4f}  ({time.time() - t0:.1f}s)"
        )
        if epoch == 0:
            save_checkpoint(model, "resnet18_cifar10_stale")
            print("  saved resnet18_cifar10_stale (epoch 1 snapshot)")

    final_acc = evaluate()
    save_checkpoint(model, "resnet18_cifar10")
    print(f"saved resnet18_cifar10, final test_acc={final_acc:.4f}")


if __name__ == "__main__":
    main()

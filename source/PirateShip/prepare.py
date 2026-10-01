"""Render the pinned PirateShip model with explicit proof compatibility edits."""

import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    metadata = json.loads((root / "upstream.json").read_text())
    raw = (root / "upstream/pirateship.tla").read_bytes()
    if hashlib.sha256(raw).hexdigest() != metadata["files"]["upstream/pirateship.tla"]["sha256"]:
        raise SystemExit("The imported source differs from its pinned hash.")
    text = raw.decode()
    for index, rule in enumerate(json.loads((root / metadata["proof_model"]["rules"]).read_text()), 1):
        if text.count(rule["before"]) != 1:
            raise SystemExit(f"Compatibility rule {index} must match exactly once.")
        text = text.replace(rule["before"], rule["after"])
    rendered = text.encode()
    if hashlib.sha256(rendered).hexdigest() != metadata["proof_model"]["sha256"]:
        raise SystemExit("The rendered model differs from its recorded hash.")
    target = root / metadata["proof_model"]["file"]
    if args.check:
        if target.read_bytes() != rendered:
            raise SystemExit("The committed model differs from its rendering.")
        print("PirateShip compatibility rendering matches.")
    else:
        target.write_bytes(rendered)


if __name__ == "__main__":
    main()

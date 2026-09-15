"""Reproduce the TLAPS-compatible SSI model from the pinned source."""

import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the rendering without writing it")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    metadata = json.loads((root / "upstream.json").read_text())
    original = root / "serializableSnapshotIsolation.tla"
    raw = original.read_bytes()
    expected = metadata["files"][original.name]["import_sha256"]
    if hashlib.sha256(raw).hexdigest() != expected:
        raise SystemExit("The imported source does not match its pinned hash.")
    text = raw.decode("utf-8").replace("\r\n", "\n")
    rules = json.loads((root / metadata["proof_model"]["rules"]).read_text())
    for index, rule in enumerate(rules, 1):
        if text.count(rule["before"]) != 1:
            raise SystemExit(f"Compatibility rule {index} must match exactly once.")
        text = text.replace(rule["before"], rule["after"])
    rendered = text.encode("utf-8")
    if hashlib.sha256(rendered).hexdigest() != metadata["proof_model"]["sha256"]:
        raise SystemExit("The rendered model does not match its recorded hash.")
    target = root / metadata["proof_model"]["file"]
    if args.check:
        if target.read_bytes() != rendered:
            raise SystemExit("The committed proof model differs from its rendering.")
        print("SSI compatibility rendering matches.")
    else:
        target.write_bytes(rendered)
        print(f"Wrote {target.name}")


if __name__ == "__main__":
    main()

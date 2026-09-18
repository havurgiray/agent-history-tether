#!/usr/bin/env python3
"""Point the package-manager manifests at a published release.

  update_manifests.py <version> <SHA256SUMS.txt> [--cask Casks/aht.rb]
                                                 [--scoop bucket/aht.json]

Edits the manifests IN PLACE (only the version, the download URLs and the
checksums change), so hand edits to caveats, notes and metadata survive.
SHA256SUMS.txt is the file attached to the GitHub release.
"""
import argparse
import json
import re
import sys

REPO = "https://github.com/havurgiray/agent-history-tether"


def checksums(path: str) -> dict:
    out = {}
    for line in open(path, encoding="utf-8"):
        if line.strip():
            digest, name = line.split()
            out[name.lstrip("*")] = digest
    return out


def need(sums: dict, name: str) -> str:
    if name not in sums:
        sys.exit(f"{name} is not listed in the checksum file")
    return sums[name]


def update_cask(path: str, version: str, sums: dict) -> None:
    digest = need(sums, f"aht-{version}-macos-universal.zip")
    text = open(path, encoding="utf-8").read()
    text, n1 = re.subn(r'^(\s*version\s+")[^"]+(")', rf"\g<1>{version}\g<2>",
                       text, count=1, flags=re.M)
    text, n2 = re.subn(r'^(\s*sha256\s+")[0-9a-f]{64}(")', rf"\g<1>{digest}\g<2>",
                       text, count=1, flags=re.M)
    if (n1, n2) != (1, 1):
        sys.exit(f"{path}: version/sha256 stanzas not found")
    open(path, "w", encoding="utf-8").write(text)
    print(f"cask  -> {version}  {digest[:12]}…")


def update_scoop(path: str, version: str, sums: dict) -> None:
    data = json.load(open(path, encoding="utf-8"))
    data["version"] = version
    for arch, tag in (("64bit", "x64"), ("arm64", "arm64")):
        name = f"aht-{version}-windows-{tag}.zip"
        data["architecture"][arch] = {
            "url": f"{REPO}/releases/download/v{version}/{name}",
            "hash": need(sums, name)}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=4)
        fh.write("\n")
    print(f"scoop -> {version}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("version")
    ap.add_argument("sums")
    ap.add_argument("--cask")
    ap.add_argument("--scoop")
    a = ap.parse_args()
    sums = checksums(a.sums)
    if a.cask:
        update_cask(a.cask, a.version, sums)
    if a.scoop:
        update_scoop(a.scoop, a.version, sums)
    if not (a.cask or a.scoop):
        sys.exit("nothing to do: pass --cask and/or --scoop")


if __name__ == "__main__":
    main()

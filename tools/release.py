"""Package and publish a PopTracker pack release for auto-update.

PopTracker reads manifest.json -> versions_url -> versions.json, treats the top
entry as latest, and offers it when its package_version is newer than the
installed one, downloading download_url and verifying sha256.

Build only (safe; no git/network), e.g. to inspect the zip:
    py -3.12 tools/release.py --changelog "First line" "Second line"

Full publish (bumps version, builds, releases, commits, pushes):
    py -3.12 tools/release.py --version 0.2.0 --changelog "..." --publish

--publish performs, in order: build zip + hash, update versions.json, commit
manifest.json + versions.json, push, then `gh release create v<ver>` with the
zip as an asset (so download_url resolves). Requires git and the gh CLI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
REPO = "Kryen112/HP2PC_AP_Poptracker"

# Runtime pack content shipped in the release zip (manifest.json at the zip
# root). Dev tooling, VCS, build output, and metadata are excluded.
INCLUDE = ["manifest.json", "README.md", "images", "items",
           "layouts", "locations", "maps", "scripts"]


def set_manifest_version(version: str) -> None:
    path = PACK / "manifest.json"
    text = path.read_text(encoding="utf-8")
    new = re.sub(r'("package_version"\s*:\s*")[^"]*(")',
                 rf'\g<1>{version}\g<2>', text)
    if new == text:
        sys.exit("error: could not find package_version in manifest.json")
    path.write_text(new, encoding="utf-8")


def manifest_version() -> str:
    return json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))["package_version"]


def build_zip(version: str) -> Path:
    dist = PACK / "dist"
    dist.mkdir(exist_ok=True)
    zip_path = dist / f"HP2PC_AP_Poptracker_v{version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in INCLUDE:
            p = PACK / name
            if p.is_file():
                z.write(p, name)
            elif p.is_dir():
                for root, dirs, files in os.walk(p):
                    dirs[:] = [d for d in dirs if d != "__pycache__"]
                    for f in files:
                        fp = Path(root) / f
                        z.write(fp, str(fp.relative_to(PACK)))
    return zip_path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def update_versions(version: str, zip_name: str, digest: str,
                    changelog: list[str]) -> Path:
    vfile = PACK / "versions.json"
    data = {"versions": []}
    if vfile.exists():
        data = json.loads(vfile.read_text(encoding="utf-8"))
    entry = {
        "package_version": version,
        "download_url": f"https://github.com/{REPO}/releases/download/v{version}/{zip_name}",
        "sha256": digest,
        "changelog": changelog or [],
    }
    # Newest first; replace any existing entry for this version.
    data["versions"] = [v for v in data["versions"]
                        if v.get("package_version") != version]
    data["versions"].insert(0, entry)
    vfile.write_text(json.dumps(data, indent="\t") + "\n", encoding="utf-8")
    return vfile


def run(*cmd: str) -> None:
    print("  $", " ".join(cmd))
    subprocess.run(cmd, cwd=PACK, check=True)


def publish(version: str, zip_path: Path, changelog: list[str]) -> None:
    if shutil.which("git") is None or shutil.which("gh") is None:
        sys.exit("error: --publish needs both git and the gh CLI on PATH")
    tag = f"v{version}"
    notes = "\n".join(changelog) if changelog else f"Release {tag}"
    run("git", "commit", "manifest.json", "versions.json", "-m", f"Release {tag}")
    run("git", "push")
    # Creates the tag at the pushed HEAD, the release, and uploads the asset.
    run("gh", "release", "create", tag, str(zip_path),
        "--repo", REPO, "--title", tag, "--notes", notes)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", help="set package_version in manifest.json first")
    ap.add_argument("--changelog", nargs="*", default=[],
                    help="changelog lines for this version")
    ap.add_argument("--publish", action="store_true",
                    help="commit, push, and create the GitHub release (needs git + gh)")
    args = ap.parse_args()

    if args.version:
        set_manifest_version(args.version)
    version = manifest_version()

    zip_path = build_zip(version)
    digest = sha256(zip_path)
    update_versions(version, zip_path.name, digest, args.changelog)

    print(f"Built  {zip_path}  ({zip_path.stat().st_size // 1024} KB)")
    print(f"sha256 {digest}")
    print(f"Wrote  versions.json (latest = {version})")

    if args.publish:
        print(f"\nPublishing v{version}:")
        publish(version, zip_path, args.changelog)
        print(f"\nPublished v{version}.")
    else:
        print(f"\nDry run (no --publish). To publish v{version}:")
        print("  re-run with --publish (commits manifest+versions.json, pushes,")
        print(f"  and creates GitHub release {('v' + version)!r} with the zip asset).")


if __name__ == "__main__":
    main()

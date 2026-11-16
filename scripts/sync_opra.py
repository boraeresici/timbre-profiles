#!/usr/bin/env python3
"""Mirror the OPRA dataset into this repository.

Exit codes:
  0  mirror updated or already current
  2  upstream unreachable or snapshot invalid (mirror left untouched)
  3  deletion guard tripped (mirror left untouched; needs a human)
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

UPSTREAM = "https://github.com/opra-project/OPRA.git"
# Same paths as upstream, so the app can swap hosts without changing paths.
MIRRORED = ["database", "dist/database_v1.jsonl", "LICENSE.md", "THIRD_PARTY_LICENSES.md", "README.md"]
ROOT = pathlib.Path(__file__).resolve().parent.parent
DEST = ROOT / "opra"
MANIFEST = ROOT / "manifest.json"
REPORT = ROOT / ".sync-report.md"


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def files_under(base: pathlib.Path):
    out = set()
    for rel in MIRRORED:
        p = base / rel
        if p.is_file():
            out.add(rel)
        elif p.is_dir():
            out.update(str(f.relative_to(base)) for f in p.rglob("*") if f.is_file())
    return out


def sha256(path: pathlib.Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def validate(base: pathlib.Path):
    """Reject a snapshot that would replace good data with broken data."""
    problems = []
    infos = list((base / "database").rglob("info.json"))
    if not infos:
        problems.append("database/ contains no info.json files")
    for f in infos:
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            problems.append(f"{f.relative_to(base)}: {e}")
    dist = base / "dist/database_v1.jsonl"
    if dist.is_file():
        for n, line in enumerate(dist.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                try:
                    json.loads(line)
                except Exception as e:  # noqa: BLE001
                    problems.append(f"dist/database_v1.jsonl:{n}: {e}")
                    break
    else:
        problems.append("dist/database_v1.jsonl missing")
    return problems[:20]


def stats(base: pathlib.Path):
    vendors = [d for d in (base / "database/vendors").iterdir() if d.is_dir()]
    products = [p for v in vendors for p in (v / "products").glob("*") if p.is_dir()]
    presets = [e for p in products for e in (p / "eq").glob("*") if e.is_dir()]
    return {"vendors": len(vendors), "products": len(products), "presets": len(presets)}


def report(title, lines):
    REPORT.write_text(f"## {title}\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print(REPORT.read_text())
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(REPORT.read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-deletions", action="store_true", help="accept a large deletion after review")
    ap.add_argument("--max-deleted-files", type=int, default=25)
    ap.add_argument("--max-deleted-ratio", type=float, default=0.02)
    ap.add_argument("--stale-days", type=int, default=180)
    args = ap.parse_args()

    old = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else None
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / "OPRA"
        try:
            git("clone", "--depth", "1", "--quiet", UPSTREAM, str(src))
        except subprocess.CalledProcessError as e:
            report("OPRA upstream unreachable", [f"`git clone {UPSTREAM}` failed:", "```", e.stderr.strip()[-2000:], "```",
                                                 "The mirror was not touched."])
            return 2
        revision = git("rev-parse", "HEAD", cwd=src)
        committed = git("log", "-1", "--format=%cI", cwd=src)
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(committed)).days
        stale = [f"⚠️ Upstream has had no commits for {age} days."] if age > args.stale_days else []

        if old and old.get("sourceRevision") == revision and DEST.exists():
            report("OPRA unchanged", [f"Upstream `{revision[:12]}` ({committed}) is already mirrored."] + stale)
            return 0

        problems = validate(src)
        if problems:
            report("OPRA snapshot rejected", [f"Upstream `{revision[:12]}` failed validation:"] + [f"- {p}" for p in problems]
                   + ["The mirror was not touched."])
            return 2

        before, after = files_under(DEST), files_under(src)
        removed, added = sorted(before - after), sorted(after - before)
        limit = max(args.max_deleted_files, int(len(before) * args.max_deleted_ratio))
        if before and len(removed) > limit and not args.allow_deletions:
            report("OPRA deletion guard tripped",
                   [f"Upstream `{revision[:12]}` removes **{len(removed)}** of {len(before)} mirrored files (limit {limit}).",
                    "The mirror was not touched. If this is intended, rerun the workflow with `allow_deletions`.", "",
                    "<details><summary>Removed files</summary>", ""] + [f"- `{r}`" for r in removed[:500]] + ["", "</details>"])
            return 3

        if DEST.exists():
            shutil.rmtree(DEST)
        for rel in MIRRORED:
            s, d = src / rel, DEST / rel
            d.parent.mkdir(parents=True, exist_ok=True)
            (shutil.copytree if s.is_dir() else shutil.copy2)(s, d)

        manifest = {
            "schemaVersion": 1,
            "source": "opra-project/OPRA",
            "sourceURL": "https://github.com/opra-project/OPRA",
            "sourceRevision": revision,
            "sourceCommittedAt": committed,
            "license": "CC-BY-SA-4.0 (dataset); AutoEQ-derived data MIT, see opra/THIRD_PARTY_LICENSES.md",
            "syncedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "files": len(after),
            "distSHA256": sha256(DEST / "dist/database_v1.jsonl"),
            **stats(DEST),
        }
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        prev = old["sourceRevision"][:12] if old else "none"
        report("OPRA mirror updated",
               [f"`{prev}` → `{revision[:12]}` ({committed})",
                f"Files: {len(after)} (+{len(added)} / −{len(removed)}); products {manifest['products']}, presets {manifest['presets']}"]
               + ([f"Removed (recoverable from git history): " + ", ".join(f"`{r}`" for r in removed[:20])] if removed else [])
               + stale)
        return 0


if __name__ == "__main__":
    sys.exit(main())

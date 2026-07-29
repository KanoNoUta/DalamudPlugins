import json
import os
import subprocess
from pathlib import Path
from zipfile import ZipFile


REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "KanoNoUta/DalamudPlugins")
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
PLUGINS_ROOT = Path("plugins")
OUTPUT = Path("pluginmaster.json")

TRIMMED_KEYS = [
    "Author",
    "Name",
    "Punchline",
    "Description",
    "Tags",
    "CategoryTags",
    "InternalName",
    "RepoUrl",
    "Changelog",
    "AssemblyVersion",
    "ApplicableVersion",
    "DalamudApiLevel",
    "TestingAssemblyVersion",
    "TestingDalamudApiLevel",
    "IconUrl",
    "ImageUrls",
    "AcceptsFeedback",
]


def load_manifest(zip_path: Path, plugin_name: str) -> dict:
    manifest_name = f"{plugin_name}.json"
    with ZipFile(zip_path) as archive:
        names = [name.replace("\\", "/") for name in archive.namelist()]
        if manifest_name not in names:
            raise RuntimeError(f"{zip_path} 缺少根目录清单 {manifest_name}")
        manifest = json.loads(archive.read(manifest_name).decode("utf-8-sig"))

    if manifest.get("InternalName") != plugin_name:
        raise RuntimeError(
            f"{zip_path}: InternalName={manifest.get('InternalName')!r}，应为 {plugin_name!r}"
        )
    if not manifest.get("AssemblyVersion"):
        raise RuntimeError(f"{zip_path}: 缺少 AssemblyVersion")
    if not isinstance(manifest.get("DalamudApiLevel"), int):
        raise RuntimeError(f"{zip_path}: DalamudApiLevel 必须是整数")
    return manifest


def trim_manifest(manifest: dict) -> dict:
    return {key: manifest[key] for key in TRIMMED_KEYS if key in manifest}


def download_url(plugin_name: str, subfolder: str | None = None) -> str:
    suffix = f"/{subfolder}" if subfolder else ""
    return (
        f"https://raw.githubusercontent.com/{REPOSITORY}/{BRANCH}/"
        f"plugins/{plugin_name}{suffix}/latest.zip"
    )


def last_update(zip_path: Path) -> str:
    """Return a stable per-plugin update time instead of checkout mtime."""
    repository_path = zip_path.as_posix()
    try:
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", repository_path],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if not dirty:
            committed = subprocess.run(
                ["git", "log", "-1", "--format=%ct", "--", repository_path],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if committed.isdigit():
                return committed
    except (OSError, subprocess.CalledProcessError):
        pass

    # New or locally replaced packages have no matching commit yet. Their file
    # time is stable for this generation; CI resolves it to the commit time
    # after the package commit is pushed.
    return str(int(zip_path.stat().st_mtime))


def build_entry(zip_path: Path, plugin_name: str, subfolder: str | None = None) -> dict:
    manifest = trim_manifest(load_manifest(zip_path, plugin_name))
    if subfolder:
        manifest["Name"] = f"{manifest['Name']} ({subfolder})"

    url = download_url(plugin_name, subfolder)
    manifest["DownloadLinkInstall"] = url
    manifest["DownloadLinkUpdate"] = url
    manifest["DownloadCount"] = 0
    manifest["LastUpdate"] = last_update(zip_path)
    return manifest


def extract_manifests() -> list[dict]:
    manifests: list[dict] = []
    if not PLUGINS_ROOT.is_dir():
        return manifests

    for plugin_dir in sorted(path for path in PLUGINS_ROOT.iterdir() if path.is_dir()):
        plugin_name = plugin_dir.name
        base_zip = plugin_dir / "latest.zip"
        if not base_zip.is_file():
            continue

        base_entry = build_entry(base_zip, plugin_name)
        testing_zip = plugin_dir / "testing" / "latest.zip"
        if testing_zip.is_file():
            testing_manifest = load_manifest(testing_zip, plugin_name)
            base_entry["TestingAssemblyVersion"] = testing_manifest["AssemblyVersion"]
            base_entry["TestingDalamudApiLevel"] = testing_manifest["DalamudApiLevel"]
            base_entry["DownloadLinkTesting"] = download_url(plugin_name, "testing")
        manifests.append(base_entry)

        for subfolder in sorted(path for path in plugin_dir.iterdir() if path.is_dir()):
            if subfolder.name == "testing":
                continue
            variant_zip = subfolder / "latest.zip"
            if variant_zip.is_file():
                manifests.append(build_entry(variant_zip, plugin_name, subfolder.name))

    return manifests


def main() -> None:
    manifests = extract_manifests()
    OUTPUT.write_text(
        json.dumps(manifests, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Generated {OUTPUT} with {len(manifests)} plugin entr{'y' if len(manifests) == 1 else 'ies'}.")


if __name__ == "__main__":
    main()

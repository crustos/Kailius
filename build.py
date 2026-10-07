#!/usr/bin/env python3
"""Kailius build tool: package the game's assets and generate mini ports.

Usage (stdlib only, Python 3.8+):

    python build.py                      # same as `all`
    python build.py package              # engine-neutral asset bundle -> dist/
    python build.py mini unity           # small Unity project -> $TMPDIR/kailius-mini-unity
    python build.py mini unity --build   # ...and build a player if a Unity editor is found
    python build.py mini prowl2d         # C# game for Prowl2D -> $TMPDIR/kailius-mini-prowl2d
    python build.py mini prowl2d --build --prowl2d ../Prowl2D
                                         # ...translate to C, build a native player with no .NET,
                                         #    run it and compare with the .NET run
    python build.py mini stride2d --build --stride2d ../stride2D
                                         # same game with a window, keyboard and drawing (Stride2D)
    python build.py all                   # package + every mini port (without --build)

`package` produces dist/kailius-assets/ (and .zip) containing:

    manifest.json   every image/audio/font with hashes, sizes and import settings
                    (pixels-per-unit, filter mode, sprite slices and pivots)
    media/          the raw png/gif/wav/mp3/ttf files, original folder layout kept
    source/         Unity scenes, prefabs, C# scripts and animations, kept as
                    reference material for converting levels and behaviour to
                    other engines

`mini <engine>` generates a small playable slice of the game for one engine. Each
engine is a function registered in MINI_TARGETS, with its hand-written template
files under ports/<engine>/. Adding an engine means adding a template folder and
one function. ports/common/mini_level.json is the engine-neutral level; values such
as speeds, damage and collider sizes are read from the Unity prefabs themselves.

`mini prowl2d` targets Prowl2D (https://github.com/crustos/Prowl2D): the game is C#
in the subset Prowl2D translates to C, so the shipped player is a native executable
with no .NET in it. Prowl2D has no input, audio, textures or window yet, so the
game is a headless bot-driven run. `mini stride2d` is the same game on Stride2D
(https://github.com/crustos/stride2D), which adds a renderer and a keyboard.

Unity's Library/, obj/, Logs/, .vs/ and the ~3000 generated tile .asset files are
deliberately ignored: they are editor caches, not game content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "Assets"
PORTS = ROOT / "ports"
DEFAULT_DIST = ROOT / "dist"
DEFAULT_UNITY_OUT = Path(tempfile.gettempdir()) / "kailius-mini-unity"
DEFAULT_PROWL2D_OUT = Path(tempfile.gettempdir()) / "kailius-mini-prowl2d"
DEFAULT_STRIDE2D_OUT = Path(tempfile.gettempdir()) / "kailius-mini-stride2d"
BUNDLE_NAME = "kailius-assets"

# Dropped into every directory build.py creates, so a rerun may safely replace it
# but never deletes a directory it did not make.
GENERATED_MARKER = ".kailius-build-output"

# --------------------------------------------------------------------------- #
# What counts as game content
# --------------------------------------------------------------------------- #

# Top-level Assets/ folders that are Unity packages or mobile-UI plugins, not game content.
SKIP_TOP_LEVEL = {"TextMesh Pro", "Joystick Pack", "Plugins"}

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif"}
AUDIO_EXT = {".wav", ".mp3", ".ogg"}
FONT_EXT = {".ttf", ".otf"}

# Unity-native files kept verbatim for reference by future converters.
SOURCE_DIRS = {"Scenes", "Prefabs", "Scripts", "Animations", "Materials"}
SOURCE_EXT = {".unity", ".prefab", ".cs", ".anim", ".controller", ".overrideController", ".mat"}

# Unity sprite alignment enum -> normalized pivot (9 = custom pivot stored in the meta).
ALIGNMENT_PIVOTS = {
    0: (0.5, 0.5), 1: (0.0, 1.0), 2: (0.5, 1.0), 3: (1.0, 1.0), 4: (0.0, 0.5),
    5: (1.0, 0.5), 6: (0.0, 0.0), 7: (0.5, 0.0), 8: (1.0, 0.0),
}
FILTER_MODES = {0: "point", 1: "bilinear", 2: "trilinear"}
SPRITE_MODES = {0: "none", 1: "single", 2: "multiple"}

# Audio above this size is treated as streamed music rather than a one-shot effect.
MUSIC_MIN_BYTES = 1_000_000

NUM = r"-?[\d.eE+-]+"
SLICE_RE = re.compile(
    r"-\s+serializedVersion:\s*\d+\s+name:\s*(?P<name>[^\n]+?)\s+"
    r"rect:\s+serializedVersion:\s*\d+\s+"
    rf"x:\s*(?P<x>{NUM})\s+y:\s*(?P<y>{NUM})\s+width:\s*(?P<w>{NUM})\s+height:\s*(?P<h>{NUM})\s+"
    r"alignment:\s*(?P<align>\d+)\s+"
    rf"pivot:\s*\{{x:\s*(?P<px>{NUM}),\s*y:\s*(?P<py>{NUM})\}}"
)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str) -> "None":
    sys.exit(f"error: {message}")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_size(path: Path) -> Optional[Tuple[int, int]]:
    """Pixel size of a PNG or GIF read from its header (no imaging library needed)."""
    with path.open("rb") as handle:
        head = handle.read(32)
    if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
        width, height = struct.unpack(">II", head[16:24])
        return width, height
    if head[:6] in (b"GIF87a", b"GIF89a"):
        width, height = struct.unpack("<HH", head[6:10])
        return width, height
    return None


def reset_output_dir(path: Path) -> None:
    """Empty `path` for a fresh build, but only if build.py created it (or it is empty)."""
    if path.exists():
        if (path / GENERATED_MARKER).exists():
            shutil.rmtree(path)
        elif any(path.iterdir()):
            fail(f"{path} exists and was not created by build.py; refusing to overwrite it "
                 "(delete it or choose another output directory)")
    path.mkdir(parents=True, exist_ok=True)
    (path / GENERATED_MARKER).write_text("created by build.py - safe to delete\n")


def git_commit() -> Optional[str]:
    try:
        result = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


# --------------------------------------------------------------------------- #
# Reading Unity metadata
# --------------------------------------------------------------------------- #

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def read_unity_project() -> Dict[str, object]:
    """Editor version, product name and the scene build order of the source project."""
    info: Dict[str, object] = {"editorVersion": None, "editorRevision": None,
                               "productName": "Kailius", "scenes": []}

    version_file = ROOT / "ProjectSettings" / "ProjectVersion.txt"
    if version_file.exists():
        for line in read_text(version_file).splitlines():
            if line.startswith("m_EditorVersionWithRevision:"):
                info["editorRevision"] = line.split(":", 1)[1].strip()
            elif line.startswith("m_EditorVersion:"):
                info["editorVersion"] = line.split(":", 1)[1].strip()

    settings_file = ROOT / "ProjectSettings" / "ProjectSettings.asset"
    if settings_file.exists():
        match = re.search(r"^\s*productName:\s*(.+?)\s*$", read_text(settings_file), re.M)
        if match:
            info["productName"] = match.group(1)

    build_file = ROOT / "ProjectSettings" / "EditorBuildSettings.asset"
    if build_file.exists():
        scenes = re.findall(r"-\s+enabled:\s*(\d)\s+path:\s*(.+?)\s+guid:\s*([0-9a-f]+)",
                            read_text(build_file))
        info["scenes"] = [{"index": i, "path": path, "guid": guid, "enabledInBuild": enabled == "1"}
                          for i, (enabled, path, guid) in enumerate(scenes)]
    return info


def meta_value(text: str, key: str, cast=int):
    match = re.search(rf"^\s*{key}:\s*({NUM})\s*$", text, re.M)
    return cast(float(match.group(1))) if match else None


def parse_import_settings(asset: Path) -> Dict[str, object]:
    """guid plus, for textures, the import settings a port needs to reproduce the look."""
    meta = asset.with_name(asset.name + ".meta")
    if not meta.exists():
        return {}
    text = read_text(meta)
    result: Dict[str, object] = {}

    guid = re.search(r"^guid:\s*([0-9a-f]{32})", text, re.M)
    if guid:
        result["guid"] = guid.group(1)

    if "TextureImporter:" not in text:
        return result

    result["filter"] = FILTER_MODES.get(meta_value(text, "filterMode"), "bilinear")
    mode = meta_value(text, "spriteMode") or 0
    result["spriteMode"] = SPRITE_MODES.get(mode, "none")
    ppu = meta_value(text, "spritePixelsToUnits", float)
    if ppu is not None:
        result["pixelsPerUnit"] = ppu

    if mode == 1:
        pivot = re.search(rf"spritePivot:\s*\{{x:\s*({NUM}),\s*y:\s*({NUM})\}}", text)
        if pivot:
            result["pivot"] = [float(pivot.group(1)), float(pivot.group(2))]
    elif mode == 2:
        slices = []
        for m in SLICE_RE.finditer(text):
            align = int(m.group("align"))
            pivot = ALIGNMENT_PIVOTS.get(align, (float(m.group("px")), float(m.group("py"))))
            slices.append({
                "name": m.group("name").strip(),
                "x": float(m.group("x")), "y": float(m.group("y")),
                "width": float(m.group("w")), "height": float(m.group("h")),
                "pivot": list(pivot),
            })
        result["slices"] = slices
    return result


# --------------------------------------------------------------------------- #
# package: engine-neutral asset bundle
# --------------------------------------------------------------------------- #

def iter_game_files() -> Iterable[Tuple[Path, Path]]:
    for path in sorted(ASSETS.rglob("*")):
        if not path.is_file() or path.suffix == ".meta":
            continue
        rel = path.relative_to(ASSETS)
        if rel.parts[0] in SKIP_TOP_LEVEL:
            continue
        yield path, rel


def package(dist: Path) -> Path:
    if not ASSETS.is_dir():
        fail(f"{ASSETS} not found; run build.py from a Kailius checkout")

    bundle = dist / BUNDLE_NAME
    reset_output_dir(bundle)

    project = read_unity_project()
    images: List[dict] = []
    audio: List[dict] = []
    fonts: List[dict] = []
    sources: List[dict] = []

    for path, rel in iter_game_files():
        ext = path.suffix.lower()
        top = rel.parts[0]

        if ext in IMAGE_EXT or ext in AUDIO_EXT or ext in FONT_EXT:
            dest_rel = Path("media") / rel
        elif top in SOURCE_DIRS and path.suffix in SOURCE_EXT:
            dest_rel = Path("source") / rel
        else:
            continue  # generated .asset tiles, prefabs inside Sprites/, zips, etc.

        dest = bundle / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)

        entry = {
            "path": dest_rel.as_posix(),
            "assetPath": f"Assets/{rel.as_posix()}",
            "bytes": path.stat().st_size,
            "sha256": sha256_of(path),
        }
        entry.update(parse_import_settings(path))

        if ext in IMAGE_EXT:
            size = image_size(path)
            if size:
                entry["width"], entry["height"] = size
            images.append(entry)
        elif ext in AUDIO_EXT:
            entry["kind"] = "music" if entry["bytes"] >= MUSIC_MIN_BYTES else "sfx"
            audio.append(entry)
        elif ext in FONT_EXT:
            fonts.append(entry)
        else:
            sources.append(entry)

    scenes = []
    for scene in project["scenes"]:
        name = Path(scene["path"]).stem
        scenes.append({**scene, "name": name, "source": f"source/{scene['path'][len('Assets/'):]}"})

    manifest = {
        "schema": 1,
        "game": project["productName"],
        "gitCommit": git_commit(),
        "sourceEngine": {"name": "Unity", "version": project["editorVersion"]},
        "conventions": {
            "imageSliceOrigin": "bottom-left",
            "pivot": "normalized 0..1 within the sprite rect, origin bottom-left",
            "pixelsPerUnit": "world units = pixels / pixelsPerUnit (32 for nearly every sprite)",
        },
        "scenes": scenes,
        "images": images,
        "audio": audio,
        "fonts": fonts,
        "sourceFiles": sources,
        "skipped": {
            "topLevelFolders": sorted(SKIP_TOP_LEVEL),
            "reason": "Unity packages / mobile joystick plugin, not game content",
        },
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    zip_path = dist / f"{BUNDLE_NAME}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(bundle.rglob("*")):
            if file.is_file() and file.name != GENERATED_MARKER:
                archive.write(file, file.relative_to(dist).as_posix())

    verify_bundle(bundle, manifest, zip_path)

    sliced = sum(1 for i in images if i.get("slices"))
    log(f"packaged {len(images)} images ({sliced} sliced sheets), {len(audio)} audio, "
        f"{len(fonts)} fonts, {len(sources)} source files, {len(scenes)} scenes")
    log(f"  bundle: {bundle}")
    log(f"  zip:    {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)")
    return bundle


def verify_bundle(bundle: Path, manifest: dict, zip_path: Path) -> None:
    for group in ("images", "audio", "fonts", "sourceFiles"):
        for entry in manifest[group]:
            if not (bundle / entry["path"]).is_file():
                fail(f"manifest lists {entry['path']} but it is missing from the bundle")
    for scene in manifest["scenes"]:
        if not (bundle / scene["source"]).is_file():
            fail(f"scene {scene['name']} listed in build settings but {scene['source']} is missing")
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        if bad:
            fail(f"corrupt entry in {zip_path}: {bad}")


# --------------------------------------------------------------------------- #
# mini unity: a small playable slice, generated from ports/unity + original assets
# --------------------------------------------------------------------------- #

# (glob relative to Assets/, folder under Assets/Resources/Kailius/, optional new file stem).
# Folders are loaded whole by the runtime scripts, so each holds exactly one animation.
UNITY_MINI_ASSETS = [
    # sprites are baked into Resources/Kailius/atlas.png (see unity_write_data); only sounds and the sky are copied
    ("Sprites/Background/Sky BG 1.png", "Sprites/Background", "sky"),
    ("Sounds/Item.mp3", "Sounds", "coin"),
    ("Sounds/Swish.wav", "Sounds", "jump"),
    ("Sounds/DeathSlime.wav", "Sounds", "slime_death"),
]

UNITY_MINI_PACKAGES = {
    "com.unity.modules.audio": "1.0.0",
    "com.unity.modules.imgui": "1.0.0",
    "com.unity.modules.physics2d": "1.0.0",
}

UNITY_GITIGNORE = """\
[Ll]ibrary/
[Tt]emp/
[Oo]bj/
[Bb]uild/
[Bb]uilds/
[Ll]ogs/
[Uu]serSettings/
.vs/
*.csproj
*.sln
"""


def copy_unity_asset(source: Path, dest_dir: Path, new_stem: Optional[str]) -> Path:
    """Copy an asset and its .meta (keeping import settings and guid), optionally renamed."""
    stem = new_stem or source.stem
    dest = dest_dir / f"{stem}{source.suffix}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)

    meta = source.with_name(source.name + ".meta")
    if meta.exists():
        text = read_text(meta)
        if new_stem:
            text = text.replace(source.stem, new_stem)
        dest.with_name(dest.name + ".meta").write_text(text, encoding="utf-8", newline="\n")
    return dest


def find_unity_editor(version: Optional[str], explicit: Optional[str]) -> Optional[Path]:
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("UNITY_EDITOR"):
        candidates.append(Path(os.environ["UNITY_EDITOR"]))
    for name in ("unity-editor", "Unity", "unity"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    if version:
        system = platform.system()
        home = Path.home()
        if system == "Linux":
            candidates.append(home / "Unity" / "Hub" / "Editor" / version / "Editor" / "Unity")
        elif system == "Darwin":
            candidates.append(Path("/Applications/Unity/Hub/Editor") / version / "Unity.app/Contents/MacOS/Unity")
        elif system == "Windows":
            candidates.append(Path("C:/Program Files/Unity/Hub/Editor") / version / "Editor" / "Unity.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def default_build_target() -> str:
    return {"Windows": "win64", "Darwin": "osx"}.get(platform.system(), "linux64")


def write_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    """RGBA bytes to a PNG file (stdlib only)."""
    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(pixels[y * width * 4:(y + 1) * width * 4]) for y in range(height))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


ATLAS_META = """fileFormatVersion: 2
guid: {guid}
TextureImporter:
  serializedVersion: 10
  mipmaps:
    enableMipMap: 0
  sRGBTexture: 1
  alphaIsTransparency: 1
  isReadable: 1
  textureFormat: 4
  maxTextureSize: 2048
  textureSettings:
    filterMode: 0
    wrapU: 1
    wrapV: 1
  nPOTScale: 0
  spriteMode: 0
  textureType: 0
  platformSettings:
  - serializedVersion: 3
    buildTarget: DefaultTexturePlatform
    maxTextureSize: 2048
    textureFormat: -1
    textureCompression: 0
    compressionQuality: 50
"""


def unity_level_json(data: dict, atlas: dict, tuning: List[Tuple[str, object, str]]) -> dict:
    """Resources/Kailius/level.json: everything MiniGame builds the level from (JsonUtility-friendly: lists of objects)."""
    groups, kinds = atlas["groups"], []
    for d in data["kinds"]:
        first, count = groups.get("enemy:" + d["kind"], (0, 0))
        kinds.append({"name": d["kind"], "boss": d["behaviour"] == "boss", "speed": d["speed"], "health": d["health"],
                      "width": d["width"], "height": d["height"], "gravityScale": d["gravityScale"],
                      "attackDamage": d["attackDamage"], "attackRange": d["attackRange"],
                      "weaponRange": d["weaponRange"], "frame0": first, "frameCount": count, "fps": d["fps"]})
    torch = torch_info()
    boss_sense = source_constant(ASSETS / "Scripts" / "Enemies" / "BossRun.cs",
                                 r"Distance\(player\.position, rb\.position\)\s*<=\s*(\d+)")
    one_way = data.get("oneWay") or [False] * len(data["solids"])
    tuning_all = [(n, float(v)) for n, v, _ in tuning + PROWL2D_EXTRAS]
    tuning_all += [("TrapDamage", float(data["trapDamage"])), ("BossSense", float(boss_sense)),
                   ("TorchStickX", torch["stick"]["x"]), ("TorchStickY", torch["stick"]["y"]),
                   ("TorchFlameX", torch["flame"]["x"]), ("TorchFlameY", torch["flame"]["y"]),
                   ("TorchFps", float(torch["fps"]))]
    rect = lambda r: {"x": r[0], "y": r[1], "w": r[2], "h": r[3]}
    return {
        "spawnX": data["spawn"][0], "spawnY": data["spawn"][1], "portalX": data["portal"][0], "portalY": data["portal"][1],
        "respawnX": data["respawn"][0], "respawnY": data["respawn"][1],
        "solids": [dict(rect(r), oneWay=bool(o)) for r, o in zip(data["solids"], one_way)],
        "hazards": [rect(r) for r in data["hazards"]],
        "tiles": [{"x": x, "y": y, "frame": groups.get(f"trap:{ref[0]}:{ref[1]}", (0, 0))[0]}
                  for x, y, ref in data["hazardTiles"]],
        "coins": [{"x": x, "y": y} for x, y in data["coins"]],
        "enemies": [{"x": x, "y": y, "kind": k} for x, y, k in data["enemies"]],
        "torches": [{"x": x, "y": y} for x, y in data["torches"]],
        "kinds": kinds,
        "tuning": [{"name": n, "value": v} for n, v in tuning_all],
        "sprites": atlas["sprites"],
        "groups": [{"key": k, "first": f, "count": c} for k, (f, c) in sorted(groups.items())],
        "atlasWidth": atlas["width"], "atlasHeight": atlas["height"],
    }


def unity_write_data(resources: Path, scene: Optional[str]) -> dict:
    tuning = read_tuning()
    level_file = PORTS / "common" / "mini_level.json"
    data = scene_level_data(scene) if scene else expand_level(json.loads(level_file.read_text(encoding="utf-8")))
    atlas = build_atlas(data)
    resources.mkdir(parents=True, exist_ok=True)
    write_png(resources / "atlas.png", atlas["width"], atlas["height"], atlas["pixels"])
    guid = hashlib.md5(b"kailius-mini-atlas").hexdigest()
    (resources / "atlas.png.meta").write_text(ATLAS_META.format(guid=guid), encoding="utf-8", newline="\n")
    (resources / "level.json").write_text(json.dumps(unity_level_json(data, atlas, tuning), indent=1) + "\n",
                                          encoding="utf-8", newline="\n")
    if data["skipped"]:
        log(f"  not ported yet (ranged attackers): {', '.join(data['skipped'])}")
    log(f"  level: {len(data['solids'])} solids, {len(data['coins'])} coins, {len(data['enemies'])} enemies of "
        f"{len(data['kinds'])} kinds, {len(data['hazards'])} trap strips, {len(data['torches'])} torches; "
        f"atlas {atlas['width']}x{atlas['height']}")
    return data


SCRIPT_META = """fileFormatVersion: 2
guid: {guid}
MonoImporter:
  externalObjects: {{}}
  serializedVersion: 2
  defaultReferences: []
  executionOrder: 0
  icon: {{instanceID: 0}}
  userData:
  assetBundleName:
  assetBundleVariant:
"""


def write_script_metas(folder: Path) -> None:
    """A .meta for every script, with a guid derived from its path, so tools that read the project without opening it in
    Unity (which would write them) see every script, and Unity keeps the same guids from run to run."""
    for script in sorted(folder.rglob("*.cs")):
        meta = script.with_name(script.name + ".meta")
        if not meta.exists():
            guid = hashlib.md5(("kailius-mini/" + script.relative_to(folder).as_posix()).encode()).hexdigest()
            meta.write_text(SCRIPT_META.format(guid=guid), encoding="utf-8", newline="\n")


def build_unity_mini(out: Path, unity_version: Optional[str], build: bool,
                     editor: Optional[str], build_target: str, scene: Optional[str] = None) -> Path:
    template = PORTS / "unity"
    if not template.is_dir():
        fail(f"missing template folder {template}")

    project = read_unity_project()
    version = unity_version or project["editorVersion"] or "2020.1.1f1"

    reset_output_dir(out)
    shutil.copytree(template, out, dirs_exist_ok=True)
    (out / "README.md").write_text(read_text(template / "README.md"), encoding="utf-8", newline="\n")

    (out / "Packages").mkdir(exist_ok=True)
    (out / "Packages" / "manifest.json").write_text(
        json.dumps({"dependencies": UNITY_MINI_PACKAGES}, indent=2) + "\n", encoding="utf-8")

    (out / "ProjectSettings").mkdir(exist_ok=True)
    version_lines = [f"m_EditorVersion: {version}"]
    if version == project["editorVersion"] and project["editorRevision"]:
        version_lines.append(f"m_EditorVersionWithRevision: {project['editorRevision']}")
    (out / "ProjectSettings" / "ProjectVersion.txt").write_text("\n".join(version_lines) + "\n")

    (out / ".gitignore").write_text(UNITY_GITIGNORE)

    resources = out / "Assets" / "Resources" / "Kailius"
    copied = 0
    for pattern, dest_folder, new_stem in UNITY_MINI_ASSETS:
        matches = sorted(p for p in ASSETS.glob(pattern) if p.suffix != ".meta")
        if not matches:
            fail(f"mini profile needs Assets/{pattern} but nothing matches it")
        if new_stem and len(matches) != 1:
            fail(f"Assets/{pattern} matched {len(matches)} files but is renamed to a single name")
        for match in matches:
            copy_unity_asset(match, resources / dest_folder, new_stem)
            copied += 1

    unity_write_data(resources, scene)
    write_script_metas(out / "Assets" / "KailiusMini")
    scripts = sorted((out / "Assets" / "KailiusMini").rglob("*.cs"))
    log(f"generated Unity project ({version}): {copied} assets, {len(scripts)} scripts")
    log(f"  project: {out}")
    log("  open it in Unity Hub (Add > Add project from disk), then open "
        "Assets/Scenes/KailiusMini.unity and press Play")

    if build:
        run_unity_build(out, version, editor, build_target)
    return out


def run_unity_build(project_dir: Path, version: str, editor: Optional[str], target: str) -> None:
    unity = find_unity_editor(version, editor)
    if unity is None:
        log("  --build skipped: no Unity editor found. Pass --unity-editor PATH or set UNITY_EDITOR.")
        return
    builds = project_dir / "Builds"
    command = [
        str(unity), "-batchmode", "-nographics", "-quit",
        "-projectPath", str(project_dir),
        "-buildTarget", target,
        "-executeMethod", "KailiusMini.EditorTools.MiniBuilder.Build",
        "-kailiusOut", str(builds),
        "-logFile", str(project_dir / "build.log"),
    ]
    log(f"  building with {unity} ...")
    result = subprocess.run(command)
    if result.returncode != 0:
        fail(f"Unity exited with {result.returncode}; see {project_dir / 'build.log'}")
    log(f"  player: {builds}")


# --------------------------------------------------------------------------- #
# Reading the game's own tuning out of the Unity project
# --------------------------------------------------------------------------- #
# Prefabs and scenes are one text format: a stream of "--- !u!<class> &<fileId>" objects, each a
# component. Class ids used here: 4 Transform, 50 Rigidbody2D, 61 BoxCollider2D, 114 MonoBehaviour.

UNITY_OBJECT_RE = re.compile(r"^--- !u!(\d+) &(-?\d+)(?: stripped)?[ \t]*$", re.M)


def load_unity_objects(path: Path) -> Dict[int, Tuple[int, str]]:
    """file id -> (class id, body text) for every object in a prefab or scene."""
    parts = UNITY_OBJECT_RE.split(read_text(path))
    return {int(parts[i + 1]): (int(parts[i]), parts[i + 2]) for i in range(1, len(parts) - 2, 3)}


def yaml_number(body: str, key: str) -> Optional[float]:
    match = re.search(rf"^  {key}:\s*({NUM})\s*$", body, re.M)
    return float(match.group(1)) if match else None


def yaml_vec2(body: str, key: str) -> Optional[Tuple[float, float]]:
    match = re.search(rf"^  {key}:\s*\{{x:\s*({NUM}),\s*y:\s*({NUM})", body, re.M)
    return (float(match.group(1)), float(match.group(2))) if match else None


def yaml_ref(body: str, key: str) -> Optional[int]:
    match = re.search(rf"^  {key}:\s*\{{fileID:\s*(-?\d+)", body, re.M)
    return int(match.group(1)) if match else None


def script_class_by_guid() -> Dict[str, str]:
    """Unity refers to scripts by guid; map each guid to its C# class (the file name)."""
    classes: Dict[str, str] = {}
    for meta in sorted((ASSETS / "Scripts").rglob("*.cs.meta")):
        match = re.search(r"^guid:\s*([0-9a-f]{32})", read_text(meta), re.M)
        if match:
            classes[match.group(1)] = meta.name[: -len(".cs.meta")]
    return classes


def script_fields(objects: Dict[int, Tuple[int, str]], classes: Dict[str, str],
                  class_name: str) -> Dict[str, float]:
    """The numeric inspector fields of the component running `class_name` in this prefab."""
    fields: Dict[str, float] = {}
    for class_id, body in objects.values():
        if class_id != 114:
            continue
        guid = re.search(r"m_Script:.*?guid:\s*([0-9a-f]{32})", body)
        if not guid or classes.get(guid.group(1)) != class_name:
            continue
        for key, value in re.findall(rf"^  ([A-Za-z]\w*):\s*({NUM})\s*$", body, re.M):
            if not key.startswith("m_"):
                fields[key] = float(value)
    return fields


def physics_body(objects: Dict[int, Tuple[int, str]]) -> Dict[str, float]:
    """Gravity scale, drag and collider size (world units) of the object that owns the Rigidbody2D."""
    for class_id, body in objects.values():
        if class_id != 50:
            continue
        owner = yaml_ref(body, "m_GameObject")
        scale = (1.0, 1.0)
        size = None
        for other_class, other_body in objects.values():
            if yaml_ref(other_body, "m_GameObject") != owner:
                continue
            if other_class == 4:
                scale = yaml_vec2(other_body, "m_LocalScale") or scale
            elif other_class in (61, 70):   # BoxCollider2D, CapsuleCollider2D: both store m_Size
                size = yaml_vec2(other_body, "m_Size")
        if size is None:
            fail("the prefab's Rigidbody2D object has no box or capsule collider")
        return {
            "gravityScale": yaml_number(body, "m_GravityScale") or 0.0,
            "linearDrag": yaml_number(body, "m_LinearDrag") or 0.0,
            "width": size[0] * scale[0],
            "height": size[1] * scale[1],
        }
    fail("the prefab has no Rigidbody2D")


def source_constant(path: Path, pattern: str, group: int = 1) -> float:
    """A number the game hard-codes in a script (not exposed in the inspector)."""
    match = re.search(pattern, read_text(path))
    if not match:
        fail(f"could not find /{pattern}/ in {path.relative_to(ROOT)}")
    return float(match.group(group))


def read_tuning() -> List[Tuple[str, object, str]]:
    """(name, value, where it came from) for everything the mini game takes from Kailius itself."""
    classes = script_class_by_guid()
    player = load_unity_objects(ASSETS / "Prefabs" / "Player" / "Player.prefab")
    slime = load_unity_objects(ASSETS / "Prefabs" / "Enemies" / "Slime.prefab")
    coin = load_unity_objects(ASSETS / "Prefabs" / "Scores" / "Coins.prefab")

    controller = script_fields(player, classes, "PlayerController")
    stats = script_fields(player, classes, "Stats")
    patrol = script_fields(slime, classes, "Patrol")
    coin_fields = script_fields(coin, classes, "Coin")
    for label, fields, keys in (("PlayerController", controller, ("moveSpeed", "jumpHeight", "damagePatrols")),
                                ("Stats", stats, ("health",)),
                                ("Patrol", patrol, ("speed", "distance")),
                                ("Coin", coin_fields, ("scoreValue",))):
        missing = [k for k in keys if k not in fields]
        if missing:
            fail(f"prefab data for {label} is missing {missing}")

    player_body = physics_body(player)
    slime_body = physics_body(slime)
    gravity = yaml_vec2(read_text(ROOT / "ProjectSettings" / "Physics2DSettings.asset"), "m_Gravity")
    if gravity is None:
        fail("ProjectSettings/Physics2DSettings.asset has no m_Gravity")

    controller_cs = ASSETS / "Scripts" / "Player" / "PlayerController.cs"
    enemy_cs = ASSETS / "Scripts" / "Enemies" / "Enemy.cs"
    knock_x = source_constant(controller_cs, r"AddForce\(new Vector2\((\d+), (\d+)\) \* (\d+)", 1) \
        * source_constant(controller_cs, r"AddForce\(new Vector2\((\d+), (\d+)\) \* (\d+)", 3)
    knock_y = source_constant(controller_cs, r"AddForce\(new Vector2\((\d+), (\d+)\) \* (\d+)", 2) \
        * source_constant(controller_cs, r"AddForce\(new Vector2\((\d+), (\d+)\) \* (\d+)", 3)

    return [
        ("Gravity", gravity[1], "Physics2DSettings m_Gravity"),
        ("MoveSpeed", controller["moveSpeed"], "Player.prefab PlayerController.moveSpeed"),
        ("JumpSpeed", controller["jumpHeight"], "Player.prefab PlayerController.jumpHeight (a velocity)"),
        ("ContactDamage", int(controller["damagePatrols"]), "Player.prefab PlayerController.damagePatrols"),
        ("DamageCooldown", source_constant(controller_cs, r"attactRate\s*=\s*([\d.]+)f"),
         "PlayerController.cs attactRate"),
        ("KnockbackSpeed", knock_x, "PlayerController.cs AddForce on touching a patrol"),
        ("KnockbackLift", knock_y, "PlayerController.cs AddForce on touching a patrol"),
        ("MaxHealth", int(stats["health"]), "Player.prefab Stats.health"),
        ("PlayerGravityScale", player_body["gravityScale"], "Player.prefab Rigidbody2D"),
        ("PlayerDrag", player_body["linearDrag"], "Player.prefab Rigidbody2D"),
        ("PlayerW", player_body["width"], "Player.prefab capsule collider size x scale"),
        ("PlayerH", player_body["height"], "Player.prefab capsule collider size x scale"),
        ("SlimeSpeed", patrol["speed"], "Slime.prefab Patrol.speed"),
        ("LedgeProbe", patrol["distance"], "Slime.prefab Patrol.distance"),
        ("SlimeGravityScale", slime_body["gravityScale"], "Slime.prefab Rigidbody2D"),
        ("SlimeW", slime_body["width"], "Slime.prefab capsule collider size x scale"),
        ("SlimeH", slime_body["height"], "Slime.prefab capsule collider size x scale"),
        ("CoinScore", int(coin_fields["scoreValue"]), "Coins.prefab Coin.scoreValue"),
        ("EnemyScore", int(source_constant(enemy_cs, r"ChangeScore\((\d+)\)")), "Enemy.cs Die()"),
    ]


# --------------------------------------------------------------------------- #
# Exporting a Unity scene to engine-neutral level data
# --------------------------------------------------------------------------- #
# A Kailius level is a few Tilemaps (cells on a 1x1 grid; solid when the tile asset says so and the
# tilemap has a TilemapCollider2D) plus prefab instances (player, coins, enemies, the portal) placed by
# m_LocalPosition overrides. The output is plain data every port can read.

CLASS_TRANSFORM = 4
CLASS_PREFAB_INSTANCE = 1001
CLASS_TILEMAP = 1839735485
CLASS_TILEMAP_COLLIDER = 19719996

# Prefab name -> what it is in a level. Anything not listed is UI, audio or camera plumbing and is ignored.
ENTITY_KINDS = {
    "Player": "player", "Respawn": "respawn", "Portal": "portal",
    "Coins": "coin", "Coins Variant": "coin", "Gems": "gem", "Gems Variant": "gem", "Stars": "star",
    "Heart": "heart", "Heart Variant": "heart", "Shield": "shield", "Sword": "sword", "Chest": "chest",
    "Chest_Scene2 Variant": "chest",
    "Slime": "enemy", "Tru": "enemy", "Knight": "enemy", "Bee": "enemy", "Crab": "enemy", "Ghost": "enemy",
    "Ghoul": "enemy", "Hellcat": "enemy", "Piranha": "enemy", "Skeleton": "enemy", "Slug": "enemy",
    "Vampire": "enemy", "WizzardNormal": "enemy", "WizardBoss": "enemy", "GhostHalo": "enemy",
    "Flame1": "torch",
}


def yaml_block(body: str, key: str) -> str:
    """The text under a top-level (2-space) key, up to the next top-level key."""
    start = re.search(rf"^  {key}:[^\n]*\n?", body, re.M)
    if not start:
        return ""
    rest = body[start.end():]
    end = re.search(r"^  [A-Za-z_]", rest, re.M)
    return rest[: end.start()] if end else rest


def yaml_list(block: str) -> List[str]:
    """Items of a block list written at the same indent as its key ('  - ...')."""
    return [item for item in re.split(r"^  - ", block, flags=re.M)[1:]]


def guid_index() -> Dict[str, Path]:
    """guid -> asset path for everything under Assets/ (one pass over the .meta files)."""
    index: Dict[str, Path] = {}
    for meta in ASSETS.rglob("*.meta"):
        match = re.search(r"^guid:\s*([0-9a-f]{32})", read_text(meta), re.M)
        if match:
            index[match.group(1)] = meta.with_suffix("")
    return index


def tilemap_cells(body: str) -> List[Tuple[int, int, Optional[str]]]:
    """(x, y, tile asset guid) for every painted cell of a Tilemap object."""
    assets = []
    for entry in yaml_list(yaml_block(body, "m_TileAssetArray")):
        guid = re.search(r"guid:\s*([0-9a-f]{32})", entry)
        assets.append(guid.group(1) if guid else None)
    cells = []
    for entry in yaml_list(yaml_block(body, "m_Tiles")):
        pos = re.search(r"first:\s*\{x:\s*(-?\d+),\s*y:\s*(-?\d+)", entry)
        index = re.search(r"m_TileIndex:\s*(-?\d+)", entry)
        if pos and index:
            i = int(index.group(1))
            cells.append((int(pos.group(1)), int(pos.group(2)), assets[i] if 0 <= i < len(assets) else None))
    return cells


def merge_cells(cells: Iterable[Tuple[int, int]]) -> List[Tuple[int, int, int, int]]:
    """Greedy merge of unit cells into (x, y, width, height) rectangles: horizontal runs first, then
    runs of identical width stacked vertically. Fewer, larger colliders than one per cell."""
    rows: Dict[int, List[int]] = {}
    for x, y in sorted(set(cells)):
        rows.setdefault(y, []).append(x)
    runs: Dict[int, List[List[int]]] = {}
    for y, xs in rows.items():
        run = [xs[0], xs[0]]
        runs[y] = []
        for x in xs[1:]:
            if x == run[1] + 1:
                run[1] = x
            else:
                runs[y].append(run)
                run = [x, x]
        runs[y].append(run)
    rects: List[Tuple[int, int, int, int]] = []
    open_rects: Dict[Tuple[int, int], List[int]] = {}   # (x0, x1) -> [x, y, w, h] still growing upward
    for y in sorted(runs):
        seen = set()
        for x0, x1 in runs[y]:
            key = (x0, x1)
            seen.add(key)
            current = open_rects.get(key)
            if current and current[1] + current[3] == y:
                current[3] += 1
            else:
                if current:
                    rects.append(tuple(current))
                open_rects[key] = [x0, y, x1 - x0 + 1, 1]
        for key in [k for k in open_rects if k not in seen]:
            rects.append(tuple(open_rects.pop(key)))
    rects.extend(tuple(r) for r in open_rects.values())
    return sorted(rects, key=lambda r: (r[1], r[0]))


def prefab_root_transform(prefab_path: Path) -> Tuple[int, Tuple[float, float]]:
    """(file id, local position) of a prefab's root Transform."""
    for fid, (class_id, body) in load_unity_objects(prefab_path).items():
        if class_id == CLASS_TRANSFORM and yaml_ref(body, "m_Father") == 0:
            return fid, yaml_vec2(body, "m_LocalPosition") or (0.0, 0.0)
    fail(f"{prefab_path.name} has no root Transform")


def scene_world_position(objects: Dict[int, Tuple[int, str]], transform_id: int) -> Tuple[float, float]:
    """Sum of local positions up the parent chain (rotation and scale of parents are assumed identity)."""
    x = y = 0.0
    seen = set()
    while transform_id and transform_id in objects and transform_id not in seen:
        seen.add(transform_id)
        body = objects[transform_id][1]
        local = yaml_vec2(body, "m_LocalPosition") or (0.0, 0.0)
        x, y = x + local[0], y + local[1]
        transform_id = yaml_ref(body, "m_Father") or 0
    return x, y


def tile_world_size(tile_asset: Path, cache: Dict[Path, Tuple[float, float]]) -> Tuple[float, float]:
    """Width and height in world units of a tile's sprite, when every slice of its texture has the same
    size (true for Kailius's tile sets: 64 px at 32 px/unit is a 2x2 tile on a 1x1 grid); else 1x1."""
    if tile_asset in cache:
        return cache[tile_asset]
    size = (1.0, 1.0)
    sprite = re.search(r"m_Sprite:.*?guid:\s*([0-9a-f]{32})", read_text(tile_asset), re.S)
    texture = guid_index().get(sprite.group(1)) if sprite else None
    meta = texture.with_name(texture.name + ".meta") if texture else None
    if meta and meta.is_file():
        text = read_text(meta)
        ppu = yaml_number(text, "spritePixelsToUnits") or 100.0
        sizes = set(re.findall(r"rect:\s*serializedVersion: 2\s*x:\s*[-\d.]+\s*y:\s*[-\d.]+\s*"
                               r"width:\s*([\d.]+)\s*height:\s*([\d.]+)", text))
        if len(sizes) == 1:
            w, h = next(iter(sizes))
            size = (float(w) / ppu, float(h) / ppu)
    cache[tile_asset] = size
    return size


def export_scene(scene: str) -> Dict[str, object]:
    """Engine-neutral level data for one scene: solid and hazard tile rectangles, and placed entities."""
    path = ASSETS / "Scenes" / f"{scene}.unity"
    if not path.is_file():
        fail(f"no scene {scene} (looked for {path.relative_to(ROOT)})")
    objects = load_unity_objects(path)
    guids = guid_index()
    classes = script_class_by_guid()

    def game_object_name(go_id: int) -> str:
        match = re.search(r"m_Name:\s*(.*)", objects[go_id][1])
        return match.group(1).strip() if match else ""

    tilemaps = []
    size_cache: Dict[Path, Tuple[float, float]] = {}
    for fid, (class_id, body) in objects.items():
        if class_id != CLASS_TILEMAP:
            continue
        owner = yaml_ref(body, "m_GameObject")
        collider = next((b for c, b in objects.values()
                         if c == CLASS_TILEMAP_COLLIDER and yaml_ref(b, "m_GameObject") == owner), None)
        solid_cells, other_cells, tiles = [], 0, 0
        trap = next((b for c, b in objects.values() if c == 114 and yaml_ref(b, "m_GameObject") == owner
                     and classes.get((re.search(r"m_Script:.*?guid:\s*([0-9a-f]{32})", b) or [None, ""])[1]) == "Traps"),
                    None)
        trap_tiles = []
        for x, y, tile in tilemap_cells(body):
            asset = guids.get(tile) if tile else None
            if trap is not None and asset and asset.suffix == ".asset":
                sprite = re.search(r"m_Sprite:\s*\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-f]{32})", read_text(asset))
                if sprite:
                    trap_tiles.append([x, y, sprite.group(2), int(sprite.group(1))])
            collides = False
            if asset and asset.suffix == ".asset":
                kind = re.search(r"m_ColliderType:\s*(\d+)", read_text(asset))
                collides = bool(kind and int(kind.group(1)) != 0)
            if collider is not None and collides:
                # the sprite is centred on its cell and may be bigger than it: cover it in half-unit steps
                w, h = tile_world_size(asset, size_cache)
                x0, y0 = round((x + 0.5 - w / 2) * 2), round((y + 0.5 - h / 2) * 2)
                solid_cells += [(x0 + i, y0 + j) for i in range(round(w * 2)) for j in range(round(h * 2))]
                tiles += 1
            else:
                other_cells += 1
        if collider is None and not solid_cells:
            continue
        tilemaps.append({
            "name": game_object_name(owner),
            "trigger": bool(collider is not None and yaml_number(collider, "m_IsTrigger")),
            "rects": [[r[0] / 2, r[1] / 2, r[2] / 2, r[3] / 2] for r in merge_cells(solid_cells)],
            "cells": tiles,
            "damage": int(yaml_number(trap, "damage") or 0) if trap is not None else None,
            "tiles": trap_tiles,
        })

    entities = []
    prefab_cache: Dict[str, Tuple[int, Tuple[float, float]]] = {}
    for fid, (class_id, body) in objects.items():
        if class_id != CLASS_PREFAB_INSTANCE:
            continue
        source = re.search(r"m_SourcePrefab:.*?guid:\s*([0-9a-f]{32})", body)
        prefab_path = guids.get(source.group(1)) if source else None
        if not prefab_path or prefab_path.suffix != ".prefab":
            continue
        name = prefab_path.stem
        kind = ENTITY_KINDS.get(name)
        if kind is None:
            continue
        if source.group(1) not in prefab_cache:
            prefab_cache[source.group(1)] = prefab_root_transform(prefab_path)
        root_id, default = prefab_cache[source.group(1)]
        position = {"x": default[0], "y": default[1]}
        for target, prop, value in re.findall(
                r"target:\s*\{fileID:\s*(-?\d+),[^}]*\}\s*propertyPath:\s*(m_LocalPosition\.[xy])\s*value:\s*([^\n]*)",
                body):
            if int(target) == root_id:
                position[prop[-1]] = float(value)
        parent = re.search(r"m_TransformParent:\s*\{fileID:\s*(-?\d+)", body)
        offset = scene_world_position(objects, int(parent.group(1))) if parent else (0.0, 0.0)
        entities.append({"prefab": name, "kind": kind,
                         "x": round(position["x"] + offset[0], 4), "y": round(position["y"] + offset[1], 4)})
    entities.sort(key=lambda e: (e["kind"], e["prefab"], e["x"], e["y"]))

    return {"schema": 1, "scene": scene, "cellSize": 1.0, "tilemaps": tilemaps, "entities": entities}


# --------------------------------------------------------------------------- #
# mini prowl2d: a game in the C# subset that Prowl2D translates to C (no .NET at run time)
# --------------------------------------------------------------------------- #

# Values the mini game needs that Kailius does not define (it has no fixed-step headless loop,
# kill plane or portal trigger of its own).
PROWL2D_EXTRAS = [
    ("Dt", 0.01, "fixed step of the headless loop"),
    ("KillPlaneY", -20.0, "below this the player respawns"),
    ("CoinRadius", 0.42, "trigger radius of a coin"),
    ("PortalW", 1.5, "portal trigger width"),
    ("PortalH", 4.0, "portal trigger height"),
    ("StompDamage", 100.0, "what landing on an enemy does (the mini has no sword); a slime has 100 health"),
    ("BossWindup", 0.4, "seconds from a boss starting its attack to the hit"),
    ("BossCooldown", 1.0, "seconds between a boss's attacks"),
    ("BossInvulnerable", 0.5, "seconds a boss cannot be stomped again"),
]
PORTAL_H = 4.0


def cs_float(value: float) -> str:
    text = f"{value:.6g}"
    if not any(c in text for c in ".e") and "inf" not in text:
        text += ".0"
    return text + "f"


def prowl2d_cfg_source(tuning: List[Tuple[str, object, str]]) -> str:
    lines = ["// GENERATED by build.py from the Kailius Unity project: do not edit",
             "static class Cfg", "{"]
    for name, value, note in tuning + PROWL2D_EXTRAS:
        literal = str(value) if isinstance(value, int) else cs_float(float(value))
        kind = "int" if isinstance(value, int) else "float"
        lines.append(f"    public const {kind} {name} = {literal};   // {note}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def expand_level(level: dict) -> dict:
    """ports/common/mini_level.json as the same kind of data a real scene gives (see scene_level_data)."""
    solids = []
    for x0, x1, top in level["ground"]:
        solids.append((x0, top - level["groundThickness"], x1 - x0, level["groundThickness"]))
    for x0, x1, top in level["platforms"]:
        solids.append((x0, top - level["platformThickness"], x1 - x0, level["platformThickness"]))
    one_way = [False] * len(level["ground"]) + [True] * len(level["platforms"])
    coins = []
    for row in level["coinRows"]:
        coins += [(row["x"] + i * row["spacing"], row["y"]) for i in range(row["count"])]
    for arc in level["coinArcs"]:
        n = arc["count"]
        coins += [(arc["x"] + i * arc["spacing"],
                   arc["y"] + arc["amplitude"] * math.sin(i / (n - 1) * math.pi)) for i in range(n)]
    spawn = tuple(level["spawn"])
    return {"solids": solids, "oneWay": one_way, "coins": coins, "hazards": [], "hazardTiles": [], "trapDamage": 0,
            "kinds": [enemy_def("Slime")], "enemies": [(s[0], s[1], 0) for s in level["slimes"]], "torches": [],
            "spawn": spawn, "respawn": spawn, "portal": (level["portal"][0], level["portal"][1] + PORTAL_H / 2),
            "skipped": []}


def scene_level_data(scene: str) -> dict:
    """A real scene shaped like the mini level: solids, traps, pickups, enemies of every supported kind,
    torches, spawn, respawn point and portal."""
    export = export_scene(scene)
    found = lambda *kinds: [e for e in export["entities"] if e["kind"] in kinds]
    player, portal, respawn = found("player"), found("portal"), found("respawn")
    if not player or not portal:
        fail(f"{scene} has no player or no portal entity")
    kinds, index, skipped = [], {}, []
    for name in sorted({e["prefab"] for e in found("enemy")}):
        definition = enemy_def(name)
        if definition["behaviour"] == "unsupported":
            skipped.append(name)
            continue
        index[name] = len(kinds)
        kinds.append(definition)
    flat = [t for t in export["tilemaps"] if not t["trigger"]]
    traps = [t for t in flat if t.get("damage")]
    return {
        "solids": [tuple(r) for t in flat if not t.get("damage") for r in t["rects"]],
        "hazards": [tuple(r) for t in traps for r in t["rects"]],
        "hazardTiles": [(x + 0.5, y + 0.5, (guid, ident)) for t in traps for x, y, guid, ident in t["tiles"]],
        "trapDamage": max([t["damage"] for t in traps] or [0]),
        "coins": [(e["x"], e["y"]) for e in found("coin", "gem")],
        "kinds": kinds,
        "enemies": [(e["x"], e["y"], index[e["prefab"]]) for e in found("enemy") if e["prefab"] in index],
        "torches": [(e["x"], e["y"]) for e in found("torch")],
        "spawn": (player[0]["x"], player[0]["y"]), "portal": (portal[0]["x"], portal[0]["y"]),
        "respawn": (respawn[0]["x"], respawn[0]["y"]) if respawn else (player[0]["x"], player[0]["y"]),
        "skipped": skipped,
    }


def prowl2d_level_source(data: dict, groups: Optional[dict] = None) -> str:
    """Level.cs: the level as tables the game builds itself from. `groups` (from the atlas) says where each
    enemy's and trap tile's frames are; without an atlas those are 0."""
    groups = groups or {}
    kind_fields = ["behaviour", "speed", "health", "width", "height", "gravityScale", "attackDamage",
                   "attackRange", "weaponRange", "frame0", "frameCount", "fps"]
    kind_rows = []
    for definition in data["kinds"]:
        first, count = groups.get("enemy:" + definition["kind"], (0, 0))
        kind_rows.append([0.0 if definition["behaviour"] == "patrol" else 1.0, definition["speed"], definition["health"],
                          definition["width"], definition["height"], definition["gravityScale"],
                          definition["attackDamage"], definition["attackRange"], definition["weaponRange"],
                          float(first), float(count), definition["fps"]])
    tiles = [(x, y, float(groups.get(f"trap:{ref[0]}:{ref[1]}", (0, 0))[0])) for x, y, ref in data["hazardTiles"]]
    tables = [("solids", "Solid", 4, data["solids"]), ("coins", "Coin", 2, data["coins"]),
              ("enemies", "Enemy", 3, data["enemies"]), ("hazards", "Hazard", 4, data["hazards"]),
              ("tiles", "HazardTile", 3, tiles), ("torches", "Torch", 2, data["torches"]),
              ("kinds", "Kind", len(kind_fields), kind_rows)]

    lines = ["// GENERATED by build.py from the Kailius project: do not edit", "static class Level", "{",
             "    static float spawnX, spawnY, portalX, portalY, respawnX, respawnY;",
             "    public static float SpawnX() { return spawnX; }", "    public static float SpawnY() { return spawnY; }",
             "    public static float PortalX() { return portalX; }", "    public static float PortalY() { return portalY; }",
             "    public static float RespawnX() { return respawnX; }", "    public static float RespawnY() { return respawnY; }",
             "    // Kind(k, field): one row per enemy kind"]
    for i, field in enumerate(kind_fields):
        lines.append(f"    public const int K{field[0].upper()}{field[1:]} = {i};")
    for field, accessor, width, rows in tables:
        lines += [f"    static float[] {field};", f"    public static int {accessor}Count;",
                  f"    public static float {accessor}(int i, int k) {{ return At({field}, i * {width} + k); }}"]
    lines += ["    static float At(float[] a, int i) { return a[i]; }",
              "    static void Put(float[] a, int i, float v) { a[i] = v; }", "",
              "    public static void Init()", "    {",
              f"        spawnX = {cs_float(data['spawn'][0])}; spawnY = {cs_float(data['spawn'][1])};",
              f"        portalX = {cs_float(data['portal'][0])}; portalY = {cs_float(data['portal'][1])};",
              f"        respawnX = {cs_float(data['respawn'][0])}; respawnY = {cs_float(data['respawn'][1])};"]
    for field, accessor, width, rows in tables:
        lines.append(f"        {field} = new float[{max(1, len(rows) * width)}]; {accessor}Count = {len(rows)};")
        for i, row in enumerate(rows):
            for k, value in enumerate(row):
                lines.append(f"        Put({field}, {i * width + k}, {cs_float(float(value))});")
    lines += ["    }", "}"]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# sprites, animation clips, enemy prefabs: what the ports need to draw and run the other characters
# --------------------------------------------------------------------------- #

_PNG_CACHE: Dict[Path, Picture] = {}
_ANIM_BY_GUID: Dict[str, Path] = {}


def texture_slices(texture: Path) -> Dict[int, Tuple[int, int, int, int]]:
    """Unity sprite id (the fileID a prefab or clip refers to) -> (x, y, w, h) of that slice, y measured from the
    TOP of the image. A single-sprite texture has the one id 21300000 and covers the whole image."""
    meta = read_text(texture.with_name(texture.name + ".meta"))
    if texture not in _PNG_CACHE:
        _PNG_CACHE[texture] = Picture(*read_png(texture))
    picture = _PNG_CACHE[texture]
    out: Dict[int, Tuple[int, int, int, int]] = {21300000: (0, 0, picture.width, picture.height)}
    by_name: Dict[str, Tuple[int, int, int, int]] = {}
    for block in re.split(r"\n\s+- serializedVersion: 2\n\s+name: ", meta)[1:]:
        name = block.split("\n", 1)[0].strip()
        rect = re.search(rf"x:\s*({NUM})\s+y:\s*({NUM})\s+width:\s*({NUM})\s+height:\s*({NUM})", block)
        if rect:
            x, y, w, h = (int(float(v)) for v in rect.groups())
            by_name[name] = (x, picture.height - y - h, w, h)
    # a prefab or clip refers to a slice by the id in the importer's name table, not by its position in the sheet
    for ident, name in re.findall(r"213:\s*(-?\d+)\s+second:\s*(\S+)", meta):
        if name in by_name:
            out[int(ident)] = by_name[name]
    return out


def sprite_picture(guid: str, file_id: int) -> Tuple[Picture, float]:
    """The pixels of one sprite and its pixels-per-unit."""
    texture = guid_index().get(guid)
    if texture is None or texture.suffix.lower() != ".png":
        fail(f"sprite {guid} is not a PNG in Assets")
    slices = texture_slices(texture)
    if file_id not in slices:
        fail(f"{texture.name} has no sprite with id {file_id}")
    x, y, w, h = slices[file_id]
    ppu = meta_value(read_text(texture.with_name(texture.name + ".meta")), "spritePixelsToUnits", float) or 100.0
    return _PNG_CACHE[texture].crop(x, y, w, h), ppu


def clip_frames(clip_guid: str) -> Tuple[List[Tuple[str, int]], float]:
    """(sprite guid, id) for each frame of an animation clip, and its frames per second."""
    if not _ANIM_BY_GUID:
        for meta in ASSETS.rglob("*.anim.meta"):
            found = re.search(r"^guid:\s*([0-9a-f]{32})", read_text(meta), re.M)
            if found:
                _ANIM_BY_GUID[found.group(1)] = meta.with_suffix("")
    path = _ANIM_BY_GUID.get(clip_guid)
    if path is None:
        return [], 0.0
    text = read_text(path)
    frames, times = [], []
    for time, file_id, guid in re.findall(
            r"- time:\s*(" + NUM + r")\s+value:\s*\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-f]{32})", text):
        frames.append((guid, int(file_id)))
        times.append(float(time))
    fps = 1.0 / (times[1] - times[0]) if len(times) > 1 and times[1] > times[0] else 0.0
    return frames, fps


def controller_clips(controller_guid: str) -> Tuple[Dict[str, str], str]:
    """state name -> clip guid for an Animator controller, and the name of its default state."""
    path = guid_index().get(controller_guid)
    if path is None:
        return {}, ""
    text = read_text(path)
    states: Dict[str, str] = {}
    ids: Dict[str, str] = {}
    for ident, name, motion in re.findall(
            r"--- !u!1102 &(-?\d+)\nAnimatorState:.*?m_Name:\s*(\S+).*?m_Motion:\s*\{fileID:\s*\d+,\s*guid:\s*([0-9a-f]{32})",
            text, re.S):
        states[name] = motion
        ids[ident] = name
    default = re.search(r"m_DefaultState:\s*\{fileID:\s*(-?\d+)\}", text)
    return states, ids.get(default.group(1), "") if default else ""


def controller_behaviour(controller_guid: str, behaviour: str) -> Dict[str, float]:
    """The numeric fields of a StateMachineBehaviour (e.g. BossRun) in a controller."""
    path = guid_index().get(controller_guid)
    if path is None:
        return {}
    classes = script_class_by_guid()
    for body in re.split(r"--- !u!114 &-?\d+\n", read_text(path))[1:]:
        guid = re.search(r"m_Script:.*?guid:\s*([0-9a-f]{32})", body)
        if guid and classes.get(guid.group(1)) == behaviour:
            return {key: float(value) for key, value in re.findall(rf"^  ([A-Za-z]\w*):\s*({NUM})\s*$", body, re.M)}
    return {}


def prefab_path(name: str) -> Path:
    found = sorted(ASSETS.glob(f"Prefabs/**/{name}.prefab"))
    if not found:
        fail(f"no prefab named {name}")
    return found[0]


def prefab_scale_of(objects: Dict[int, Tuple[int, str]], game_object: int) -> float:
    """Product of the x scales from a game object up to its root (the sprite's size multiplier)."""
    scale = 1.0
    transform = next((fid for fid, (c, b) in objects.items() if c == 4 and yaml_ref(b, "m_GameObject") == game_object), None)
    while transform is not None:
        body = objects[transform][1]
        scale *= (yaml_vec2(body, "m_LocalScale") or (1.0, 1.0))[0]
        parent = yaml_ref(body, "m_Father")
        transform = parent if parent and parent in objects else None
    return scale


def prefab_clip(objects: Dict[int, Tuple[int, str]]) -> Tuple[List[Tuple[str, int]], float, str]:
    """The animation a prefab plays while moving: (frames, fps, state name), from its Animator controller."""
    animator = next((b for c, b in objects.values() if c == 95), "")
    controller = re.search(r"m_Controller:\s*\{fileID:\s*\d+,\s*guid:\s*([0-9a-f]{32})", animator)
    states, default = controller_clips(controller.group(1)) if controller else ({}, "")
    calm = [n for n in states if not re.search("die|dead|death|hurt|attack|appear", n, re.I)]
    pick = next((n for n in calm if re.search("run|walk|move|fly", n, re.I)),
                default if default in calm else (calm[0] if calm else ""))
    if not pick:
        return [], 0.0, ""
    frames, fps = clip_frames(states[pick])
    return frames, fps, pick


def enemy_def(kind: str) -> Dict[str, object]:
    """Behaviour numbers, collider and animation of one enemy prefab, read from the Unity project."""
    objects = load_unity_objects(prefab_path(kind))
    classes = script_class_by_guid()
    patrol = script_fields(objects, classes, "Patrol")
    enemy = script_fields(objects, classes, "Enemy")
    weapon = script_fields(objects, classes, "BossWeapon")
    has_boss = any(c == 114 and classes.get(
        (re.search(r"m_Script:.*?guid:\s*([0-9a-f]{32})", b) or [None, ""])[1]) == "Boss" for c, b in objects.values())
    chaser = has_boss and not script_fields(objects, classes, "MageWeapon") and "attackDamage" in weapon
    body = physics_body(objects)
    animator = next((b for c, b in objects.values() if c == 95), "")
    controller = re.search(r"m_Controller:\s*\{fileID:\s*\d+,\s*guid:\s*([0-9a-f]{32})", animator)
    run = controller_behaviour(controller.group(1), "BossRun") if controller else {}
    frames, fps, pick = prefab_clip(objects)
    renderer = next((b for c, b in objects.values() if c == 212), "")
    sprite_owner = yaml_ref(renderer, "m_GameObject") if renderer else None
    if not frames and renderer:
        found = re.search(r"m_Sprite:\s*\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-f]{32})", renderer)
        frames = [(found.group(2), int(found.group(1)))] if found else []
    return {
        "kind": kind, "behaviour": "boss" if chaser else "patrol" if patrol else "unsupported",
        "speed": run.get("speed", patrol.get("speed", 1.5)), "health": enemy.get("health", 100.0),
        "width": body["width"], "height": body["height"], "gravityScale": body["gravityScale"],
        "attackDamage": weapon.get("attackDamage", 0.0), "weaponRange": weapon.get("attackRange", 1.0),
        "attackRange": run.get("attackRange", weapon.get("attackRange", 1.0)),
        "frames": frames, "fps": fps or 6.0,
        "spriteScale": prefab_scale_of(objects, sprite_owner) if sprite_owner else 1.0,
        "clip": pick,
    }


def torch_info() -> Dict[str, object]:
    """Flame1.prefab: a torch is a stick and an animated flame, each offset from the prefab root."""
    objects = load_unity_objects(prefab_path("Flame1"))
    parts: Dict[str, Dict[str, object]] = {}
    for _, (class_id, body) in objects.items():
        if class_id != 212:
            continue
        owner = yaml_ref(body, "m_GameObject")
        name = re.search(r"m_Name:\s*(.*)", objects[owner][1]).group(1).strip()
        x = y = 0.0
        scale = 1.0
        transform = next(f for f, (c, b) in objects.items() if c == 4 and yaml_ref(b, "m_GameObject") == owner)
        chain = []
        while transform in objects:
            chain.append(objects[transform][1])
            parent = yaml_ref(objects[transform][1], "m_Father")
            transform = parent if parent else None
        for link in reversed(chain[:-1]):          # the last link is the root: offsets are relative to it
            lx, ly = yaml_vec2(link, "m_LocalPosition") or (0.0, 0.0)
            x, y = x + lx * scale, y + ly * scale
            scale *= (yaml_vec2(link, "m_LocalScale") or (1.0, 1.0))[0]
        sprite = re.search(r"m_Sprite:\s*\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-f]{32})", body)
        parts[name] = {"x": x, "y": y, "scale": scale,
                       "sprite": (sprite.group(2), int(sprite.group(1))) if sprite else None}
    frames, fps, _ = prefab_clip(objects)
    stick = parts.get("Stick")
    flame = next((p for n, p in parts.items() if n != "Stick" and p["sprite"]), None)
    if stick is None or flame is None or not frames:
        fail("Flame1.prefab no longer looks like a stick and a flame")
    return {"stick": stick, "flame": flame, "frames": frames, "fps": fps or 8.0}


# --------------------------------------------------------------------------- #
# texture atlas: the Kailius art the C# ports draw with (stdlib only: PNG reading, cropping, packing, RLE)
# --------------------------------------------------------------------------- #

def read_png(path: Path, max_rows: Optional[int] = None) -> Tuple[int, int, bytearray]:
    """Decode an 8-bit, non-interlaced PNG to (width, height, RGBA bytes). max_rows stops early."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        fail(f"{path.name} is not a PNG")
    pos, idat, palette, trns, header = 8, [], b"", b"", None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    width, height, depth, ctype, _, _, interlace = header
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if depth != 8 or interlace or channels is None:
        fail(f"{path.name}: only 8-bit non-interlaced PNGs are supported (depth {depth}, type {ctype})")
    raw = zlib.decompress(b"".join(idat))
    stride = width * channels
    rows = height if max_rows is None else min(height, max_rows)
    out = bytearray(width * rows * 4)
    prev = bytearray(stride)
    for y in range(rows):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if f == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 255
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        o = y * width * 4
        for x in range(width):
            if ctype == 6:
                out[o + x * 4:o + x * 4 + 4] = line[x * 4:x * 4 + 4]
            elif ctype == 2:
                out[o + x * 4:o + x * 4 + 4] = line[x * 3:x * 3 + 3] + b"\xff"
            elif ctype == 3:
                i = line[x]
                out[o + x * 4:o + x * 4 + 3] = palette[i * 3:i * 3 + 3]
                out[o + x * 4 + 3] = trns[i] if i < len(trns) else 255
            elif ctype == 0:
                out[o + x * 4:o + x * 4 + 4] = bytes((line[x],) * 3 + (255,))
            else:
                out[o + x * 4:o + x * 4 + 4] = bytes((line[x * 2],) * 3 + (line[x * 2 + 1],))
    return width, rows, out


class Picture:
    """RGBA pixels with the few operations the atlas needs."""

    def __init__(self, width: int, height: int, pixels: Optional[bytearray] = None) -> None:
        self.width, self.height = width, height
        self.pixels = pixels if pixels is not None else bytearray(width * height * 4)

    def crop(self, x: int, y: int, w: int, h: int) -> "Picture":
        out = Picture(w, h)
        for row in range(h):
            src = ((y + row) * self.width + x) * 4
            out.pixels[row * w * 4:(row + 1) * w * 4] = self.pixels[src:src + w * 4]
        return out

    def centred(self, w: int, h: int) -> "Picture":
        """The same pixels on a transparent w x h canvas, centred (how Unity places a sprite by its centre pivot)."""
        out = Picture(w, h)
        ox, oy = (w - self.width) // 2, (h - self.height) // 2
        for row in range(self.height):
            dst = ((oy + row) * w + ox) * 4
            out.pixels[dst:dst + self.width * 4] = self.pixels[row * self.width * 4:(row + 1) * self.width * 4]
        return out

    def opaque_box(self) -> Optional[Tuple[int, int, int, int]]:
        """(x0, y0, x1, y1) of the pixels with any alpha, x1/y1 exclusive."""
        xs, ys = [], []
        for y in range(self.height):
            row = self.pixels[y * self.width * 4 + 3:(y + 1) * self.width * 4:4]
            if any(row):
                ys.append(y)
                first = next(i for i, a in enumerate(row) if a)
                last = len(row) - 1 - next(i for i, a in enumerate(reversed(row)) if a)
                xs += [first, last]
        return (min(xs), min(ys), max(xs) + 1, max(ys) + 1) if xs else None

    def scaled(self, w: int, h: int) -> "Picture":
        """Box-filter resize (premultiplied, so transparent edges do not bleed dark)."""
        out = Picture(w, h)
        for y in range(h):
            y0, y1 = y * self.height // h, max((y + 1) * self.height // h, y * self.height // h + 1)
            for x in range(w):
                x0, x1 = x * self.width // w, max((x + 1) * self.width // w, x * self.width // w + 1)
                r = g = b = a = n = 0
                for sy in range(y0, y1):
                    base = (sy * self.width + x0) * 4
                    for sx in range(x1 - x0):
                        pr, pg, pb, pa = self.pixels[base + sx * 4:base + sx * 4 + 4]
                        r += pr * pa; g += pg * pa; b += pb * pa; a += pa; n += 1
                o = (y * w + x) * 4
                if a:
                    out.pixels[o:o + 4] = bytes((r // a, g // a, b // a, a // n))
        return out


def union_box(pictures: List[Picture]) -> Tuple[int, int, int, int]:
    boxes = [p.opaque_box() for p in pictures if p.opaque_box()]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def png_picture(relative: str, max_rows: Optional[int] = None) -> Picture:
    width, height, pixels = read_png(ASSETS / relative, max_rows)
    return Picture(width, height, pixels)


def meta_ppu(relative: str) -> float:
    return meta_value(read_text(ASSETS / (relative + ".meta")), "spritePixelsToUnits", float) or 100.0


# The atlas keeps one entry per frame; `scale` is the Unity transform scale
# the sprite is drawn with, so a frame's world size is pixels / pixels-per-unit * scale.
ATLAS_PPU = 32.0


def build_atlas(data: Optional[dict] = None) -> Dict[str, object]:
    """Pack the art the mini port draws into one texture. Returns {width, height, pixels, sprites: [...]}, each sprite
    {name, x, y, w, h, scale} with x/y the top-left pixel of the frame in the atlas."""
    frames: List[Tuple[str, Picture, float]] = []
    groups: Dict[str, Tuple[int, int]] = {}       # key -> (index of its first frame, number of frames)

    # ground: the 240 px grass block of the tile set cut into nine 32 px tiles (corners, edges, plain fill)
    groups["tiles"] = (len(frames), 9)
    tileset = png_picture("Sprites/Otros suelos/TileSet.png", max_rows=640)
    block = tileset.crop(400, 400, 240, 240)
    for row, y0 in enumerate((0, 104, 208)):
        for col, x0 in enumerate((0, 104, 208)):
            frames.append((f"tile{row * 3 + col}", block.crop(x0, y0, 32, 32), 1.0))

    def group(prefix: str, pictures: List[Picture], scale: float) -> None:
        x0, y0, x1, y1 = union_box(pictures)
        for i, picture in enumerate(pictures):
            frames.append((f"{prefix}{i}", picture.crop(x0, y0, x1 - x0, y1 - y0), scale))

    base = "Sprites/Character/Animations/"
    group("player_idle", [png_picture(base + "Idle/adventurer-idle-2-03.png")], 2.0)
    walk = [png_picture(base + f"Walk/adventurer-walk-{i:02d}.png") for i in range(6)]
    jump = [png_picture(base + f"Jump/adventurer-jump-{i:02d}.png") for i in range(4)]
    # one crop for idle, walk and jump so the feet stay on the same line
    boxed = union_box([png_picture(base + "Idle/adventurer-idle-2-03.png")] + walk + jump)
    frames = [f for f in frames if not f[0].startswith("player_idle")]
    for name, pictures in (("player_idle", [png_picture(base + "Idle/adventurer-idle-2-03.png")]),
                           ("player_walk", walk), ("player_jump", jump)):
        groups[name] = (len(frames), len(pictures))
        for i, picture in enumerate(pictures):
            frames.append((f"{name}{i}", picture.crop(boxed[0], boxed[1], boxed[2] - boxed[0], boxed[3] - boxed[1]), 2.0))

    sheet = png_picture("Sprites/Enemies/Slime/slime-Sheet.png")
    group("slime", [sheet.crop(col * 32, 0, 32, 25) for col in range(4)], 2.0)

    coins = [png_picture(f"Sprites/Scores/Coin/coin_{i:02d}.png") for i in range(1, 9)]
    canvas_w, canvas_h = max(c.width for c in coins), max(c.height for c in coins)   # frames are trimmed to different widths
    groups["coin"] = (len(frames), len(coins))
    group("coin", [c.centred(canvas_w, canvas_h) for c in coins], 0.5)

    portal_files = sorted((ASSETS / "Sprites" / "Portal").glob("kisspng-portal-*.png"))
    portal_rel = str(portal_files[0].relative_to(ASSETS))
    sheet_picture = png_picture(portal_rel)
    # the first four slices of the sheet are the animation frames (Unity slices measure y from the bottom)
    slices = [sl for sl in parse_import_settings(portal_files[0]).get("slices", []) if sl["height"] > 100][:4]
    cells = [sheet_picture.crop(int(sl["x"]), sheet_picture.height - int(sl["y"] + sl["height"]),
                                int(sl["width"]), int(sl["height"])) for sl in slices]
    if len(cells) != 4:
        fail("the portal sheet no longer has four frame slices")
    px0, py0, px1, py1 = union_box(cells)
    factor = ATLAS_PPU / meta_ppu(portal_rel) * 0.8      # the prefab draws it at scale 0.8
    out_w, out_h = max(1, round((px1 - px0) * factor)), max(1, round((py1 - py0) * factor))
    groups["portal"] = (len(frames), len(cells))
    for i, c in enumerate(cells):
        frames.append((f"portal{i}", c.crop(px0, py0, px1 - px0, py1 - py0).scaled(out_w, out_h), 1.0))

    def add_animation(key: str, name: str, refs: List[Tuple[str, int]], scale: float) -> None:
        """Frames given as Unity sprite refs: centred on one canvas, cropped to their union, scaled to 32 px/unit."""
        pictures, ppu = [], 100.0
        for guid, ident in refs:
            picture, ppu = sprite_picture(guid, ident)
            pictures.append(picture)
        canvas_w, canvas_h = max(p.width for p in pictures), max(p.height for p in pictures)
        pictures = [p.centred(canvas_w, canvas_h) for p in pictures]
        x0, y0, x1, y1 = union_box(pictures)
        groups[key] = (len(frames), len(pictures))
        for i, picture in enumerate(pictures):
            frames.append((f"{name}{i}", picture.crop(x0, y0, x1 - x0, y1 - y0), scale * ATLAS_PPU / ppu))

    kinds = (data or {}).get("kinds", [])
    for definition in kinds:
        add_animation("enemy:" + definition["kind"], "enemy_" + definition["kind"].lower(),
                      definition["frames"], definition["spriteScale"])
    torch = torch_info()                              # a few small sprites; drawn whenever the level has torches
    add_animation("torch_stick", "torch_stick", [torch["stick"]["sprite"]], torch["stick"]["scale"])
    add_animation("torch_flame", "torch_flame", torch["frames"], torch["flame"]["scale"])
    seen: Dict[Tuple[str, int], int] = {}
    for _, _, ref in (data or {}).get("hazardTiles", []):
        if ref not in seen:
            seen[ref] = len(seen)
            add_animation(f"trap:{ref[0]}:{ref[1]}", f"trap{seen[ref]}_", [ref], 1.0)

    # shelf packing, tallest first, into a fixed-width sheet
    atlas_w = 512
    order = sorted(range(len(frames)), key=lambda i: -frames[i][1].height)
    positions: Dict[int, Tuple[int, int]] = {}
    x = y = shelf = 0
    for i in order:
        pic = frames[i][1]
        if x + pic.width + 1 > atlas_w:
            x, y, shelf = 0, y + shelf + 1, 0
        positions[i] = (x, y)
        x += pic.width + 1
        shelf = max(shelf, pic.height)
    atlas_h = 1
    while atlas_h < y + shelf:
        atlas_h *= 2
    atlas = Picture(atlas_w, atlas_h)
    sprites = []
    for i, (name, pic, scale) in enumerate(frames):
        px, py = positions[i]
        for row in range(pic.height):
            dst = ((py + row) * atlas_w + px) * 4
            atlas.pixels[dst:dst + pic.width * 4] = pic.pixels[row * pic.width * 4:(row + 1) * pic.width * 4]
        sprites.append({"name": name, "x": px, "y": py, "w": pic.width, "h": pic.height, "scale": scale})
    return {"width": atlas_w, "height": atlas_h, "pixels": atlas.pixels, "sprites": sprites, "groups": groups}


def atlas_csharp(atlas: Dict[str, object]) -> str:
    """Atlas.cs: the texture as run-length data (the C# subset has no array or string data literals) and a table
    with each sprite's texture coordinates, size in pixels and draw scale."""
    width, height, pixels, sprites = atlas["width"], atlas["height"], atlas["pixels"], atlas["sprites"]
    runs: List[Tuple[int, int]] = []
    previous, count = None, 0
    for i in range(0, len(pixels), 4):
        r, g, b, a = pixels[i:i + 4]
        argb = 0 if a == 0 else (a << 24) | (r << 16) | (g << 8) | b
        if argb >= 1 << 31:
            argb -= 1 << 32
        if argb == previous:
            count += 1
        else:
            if previous is not None:
                runs.append((count, previous))
            previous, count = argb, 1
    runs.append((count, previous))

    def pascal(name: str) -> str:
        return "".join(part[:1].upper() + part[1:] for part in name.split("_"))

    lines = ["// GENERATED by build.py from the Kailius art: do not edit", "static class Atlas", "{",
             f"    public const int Width = {width};", f"    public const int Height = {height};",
             f"    public const int Count = {len(sprites)};"]
    for index, sprite in enumerate(sprites):
        lines.append(f"    public const int {pascal(sprite['name'])} = {index};")
    lines.append(f"    public const int TorchFlameCount = {atlas['groups']['torch_flame'][1]};")
    lines += ["", "    static float[] info;", "    static int cursor;",
              "    // k: 0 u0, 1 v0, 2 u1, 3 v1 (top of the picture is v0), 4 width px, 5 height px, 6 draw scale",
              "    public static float Info(int id, int k) { return At(info, id * 8 + k); }",
              "    static float At(float[] a, int i) { return a[i]; }",
              "    static void Set(float[] a, int i, float v) { a[i] = v; }", "",
              "    static void Run(byte[] px, int count, int argb)",
              "    {",
              "        byte b0 = (byte)((argb >> 16) & 255);", "        byte b1 = (byte)((argb >> 8) & 255);",
              "        byte b2 = (byte)(argb & 255);", "        byte b3 = (byte)((argb >> 24) & 255);",
              "        for (int i = 0; i < count; i++)", "        {",
              "            px[cursor] = b0; px[cursor + 1] = b1; px[cursor + 2] = b2; px[cursor + 3] = b3;",
              "            cursor += 4;", "        }", "    }", "",
              "    static void Runs(byte[] px, int c0, int v0, int c1, int v1, int c2, int v2, int c3, int v3,",
              "                     int c4, int v4, int c5, int v5, int c6, int v6, int c7, int v7)",
              "    {",
              "        Run(px, c0, v0); Run(px, c1, v1); Run(px, c2, v2); Run(px, c3, v3);",
              "        Run(px, c4, v4); Run(px, c5, v5); Run(px, c6, v6); Run(px, c7, v7);", "    }", ""]
    lines += ["    public static void Init()", "    {", f"        info = new float[{len(sprites) * 8}];"]
    inset = 0.02
    for index, sp in enumerate(sprites):
        values = [(sp["x"] + inset) / width, (sp["y"] + inset) / height,
                  (sp["x"] + sp["w"] - inset) / width, (sp["y"] + sp["h"] - inset) / height,
                  sp["w"], sp["h"], sp["scale"], 0.0]
        for k, value in enumerate(values):
            lines.append(f"        Set(info, {index * 8 + k}, {cs_float(value)});")
    lines += ["    }", ""]
    padded = runs + [(0, 0)] * (-len(runs) % 8)
    chunk = 8 * 64
    parts = [padded[i:i + chunk] for i in range(0, len(padded), chunk)]
    for n, part in enumerate(parts):
        lines.append(f"    static void Part{n}(byte[] px)")
        lines.append("    {")
        for i in range(0, len(part), 8):
            args = ", ".join(f"{c}, {v}" for c, v in part[i:i + 8])
            lines.append(f"        Runs(px, {args});")
        lines.append("    }")
        lines.append("")
    lines += ["    // The whole texture, RGBA, row by row from the top.", "    public static byte[] Pixels()", "    {",
              f"        byte[] px = new byte[{width * height * 4}];", "        cursor = 0;"]
    lines += [f"        Part{n}(px);" for n in range(len(parts))]
    lines += ["        return px;", "    }", "}"]
    return "\n".join(lines) + "\n"


# The two engines that take the C# subset. Their scene API is the same; the namespaces, the run commands and
# what the engine can do (Stride2D has a renderer and a keyboard) differ.
CSHARP_ENGINES = {
    "prowl2d": {
        "title": "Prowl2D", "env": "PROWL2D", "siblings": ["Prowl2D", "Prowl"], "marker": "Prowl.Core2D",
        "swap": {}, "template": None, "output": "Build/Player",
    },
    "stride2d": {
        "title": "Stride2D", "env": "STRIDE2D", "siblings": ["stride2D", "Stride2D"], "marker": "src/core",
        "swap": {"Prowl.Core2D": "Stride2D", "Prowl.Native.Box2D": "Stride2D.Native.Box2D"},
        "template": "stride2d", "output": "build/player",
    },
}
# Files of ports/prowl2d that every C# engine shares (the rest of that folder is Prowl2D's own front end).
SHARED_CSHARP = ["Layers.cs", "Shared.cs", "Player.cs", "Enemy.cs", "Pickups.cs", "Bot.cs", "World.cs"]


def find_csharp_engine(engine: str, explicit: Optional[str]) -> Optional[Path]:
    info = CSHARP_ENGINES[engine]
    candidates = [explicit, os.environ.get(info["env"])] + [ROOT.parent / name for name in info["siblings"]]
    for candidate in candidates:
        if candidate and (Path(candidate) / "build.py").is_file() and (Path(candidate) / info["marker"]).is_dir():
            return Path(candidate).resolve()
    return None


def build_csharp_mini(engine: str, out: Path, checkout: Optional[str], build: bool,
                      scene: Optional[str] = None) -> Path:
    info = CSHARP_ENGINES[engine]
    shared = PORTS / "prowl2d"
    own = PORTS / info["template"] if info["template"] else shared
    level_file = PORTS / "common" / "mini_level.json"
    if not own.is_dir() or not level_file.is_file():
        fail(f"missing {own} or {level_file}")

    tuning = read_tuning()
    data = scene_level_data(scene) if scene else expand_level(json.loads(level_file.read_text(encoding="utf-8")))
    if len(data["solids"]) + len(data["hazards"]) > 200:
        log(f"  warning: {len(data['solids'])} solids is near the {info['title']} 256 collider cap")
    if data["skipped"]:
        log(f"  not ported yet (ranged attackers): {', '.join(data['skipped'])}")
    torch = torch_info()
    boss_sense = source_constant(ASSETS / "Scripts" / "Enemies" / "BossRun.cs",
                                 r"Distance\(player\.position, rb\.position\)\s*<=\s*(\d+)")
    extras = [("TrapDamage", int(data["trapDamage"]), "Traps.cs damage on the scene's trap tilemap"),
              ("BossSense", boss_sense, "BossRun.cs: a boss chases within this distance")]
    extras += [("TorchStickX", torch["stick"]["x"], "Flame1.prefab"), ("TorchStickY", torch["stick"]["y"], "Flame1.prefab"),
               ("TorchFlameX", torch["flame"]["x"], "Flame1.prefab"), ("TorchFlameY", torch["flame"]["y"], "Flame1.prefab"),
               ("TorchFps", torch["fps"], "Flame1.anim")]

    reset_output_dir(out)
    game = out / "KailiusMini2D"
    game.mkdir()

    def put(source: Path, name: str) -> None:
        text = read_text(source)
        for old, new in info["swap"].items():
            text = text.replace(old, new)
        (game / name).write_text(text, encoding="utf-8", newline="\n")

    if info["template"]:
        for name in SHARED_CSHARP:
            put(shared / name, name)
        for source in sorted(own.glob("*.cs")):
            put(source, source.name)
    else:
        for source in sorted(shared.glob("*.cs")):
            put(source, source.name)
    atlas = None
    if info["template"]:
        atlas = build_atlas(data)
        (game / "Atlas.cs").write_text(atlas_csharp(atlas), encoding="utf-8")
        log(f"  atlas: {atlas['width']}x{atlas['height']} px, {len(atlas['sprites'])} sprites from the Kailius art")
    (game / "Cfg.cs").write_text(prowl2d_cfg_source(tuning + extras), encoding="utf-8")
    (game / "Level.cs").write_text(prowl2d_level_source(data, atlas["groups"] if atlas else None), encoding="utf-8")
    (out / "README.md").write_text(read_text(own / "README.md"), encoding="utf-8", newline="\n")

    log(f"generated {info['title']} game: {len(list(game.glob('*.cs')))} C# files, {len(tuning)} values read from "
        f"the Unity project, {len(data['solids'])} solids, {len(data['hazards'])} trap strips, "
        f"{len(data['coins'])} coins, {len(data['enemies'])} enemies of {len(data['kinds'])} kinds "
        f"({', '.join(k['kind'] for k in data['kinds'])}), {len(data['torches'])} torches")
    log(f"  game: {game}")

    if build:
        run_csharp_build(engine, game, checkout)
    else:
        log(f"  build it with:  python3 build.py mini {engine} --build --{engine} PATH_TO_{info['title']}")
    return out


def run_csharp_build(engine: str, game: Path, checkout: Optional[str]) -> None:
    info = CSHARP_ENGINES[engine]
    root = find_csharp_engine(engine, checkout)
    if root is None:
        log(f"  --build skipped: no {info['title']} checkout found. Pass --{engine} PATH, set {info['env']}, "
            f"or clone it next to this repository.")
        return
    command = [sys.executable, str(root / "build.py"), "player", str(game), "--verify", "--run"]
    log(f"  translating to C and building with {root} ...")
    result = subprocess.run(command, cwd=root)
    if result.returncode != 0:
        fail(f"{info['title']} build exited with {result.returncode} (needs the .NET SDK once for the translator, "
             f"a C compiler, and its `python3 build.py native` run in {root}; a game that did not reach the "
             f"portal also exits with 1)")
    log(f"  native player: {root / info['output'] / game.name / (engine + '-player')}")


# --------------------------------------------------------------------------- #
# Unity authored-scene export: the level as real GameObjects
# --------------------------------------------------------------------------- #

SPRITE_META = """fileFormatVersion: 2
guid: {guid}
TextureImporter:
  serializedVersion: 10
  mipmaps:
    enableMipMap: 0
  sRGBTexture: 1
  alphaIsTransparency: 1
  isReadable: 0
  textureFormat: 4
  maxTextureSize: 2048
  textureSettings:
    filterMode: 0
    wrapU: 1
    wrapV: 1
  nPOTScale: 0
  spriteMode: 1
  spriteExtrude: 1
  spriteMeshType: 1
  alignment: 0
  spritePivot: {{x: 0.5, y: 0.5}}
  spritePixelsToUnits: {ppu}
  textureType: 8
  platformSettings:
  - serializedVersion: 3
    buildTarget: DefaultTexturePlatform
    maxTextureSize: 2048
    textureFormat: -1
    textureCompression: 0
    compressionQuality: 50
"""

TAG_MANAGER = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!78 &1
TagManager:
  serializedVersion: 2
  tags:
{tags}
  layers:
{layers}
  m_SortingLayers:
  - name: Default
    uniqueID: 0
    locked: 0
"""

AUTHORED_TAGS = ["Ground", "Enemy", "Coin", "Hazard"]
AUTHORED_SCENE_CAMERA = """--- !u!1 &{go}
GameObject:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {{fileID: 0}}
  m_PrefabInstance: {{fileID: 0}}
  m_PrefabAsset: {{fileID: 0}}
  serializedVersion: 6
  m_Component:
  - component: {{fileID: {tf}}}
  - component: {{fileID: {cam}}}
  - component: {{fileID: {mb}}}
  m_Layer: 0
  m_Name: Main Camera
  m_TagString: MainCamera
  m_Icon: {{fileID: 0}}
  m_NavMeshLayer: 0
  m_StaticEditorFlags: 0
  m_IsActive: 1
--- !u!4 &{tf}
Transform:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {{fileID: 0}}
  m_PrefabInstance: {{fileID: 0}}
  m_PrefabAsset: {{fileID: 0}}
  m_GameObject: {{fileID: {go}}}
  m_LocalRotation: {{x: 0, y: 0, z: 0, w: 1}}
  m_LocalPosition: {{x: 0, y: 3, z: -10}}
  m_LocalScale: {{x: 1, y: 1, z: 1}}
  m_Children: []
  m_Father: {{fileID: 0}}
  m_RootOrder: 0
  m_LocalEulerAnglesHint: {{x: 0, y: 0, z: 0}}
--- !u!20 &{cam}
Camera:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {{fileID: 0}}
  m_PrefabInstance: {{fileID: 0}}
  m_PrefabAsset: {{fileID: 0}}
  m_GameObject: {{fileID: {go}}}
  m_Enabled: 1
  serializedVersion: 2
  m_ClearFlags: 2
  m_BackGroundColor: {{r: 0.45, g: 0.7, b: 0.95, a: 0}}
  m_projectionMatrixMode: 1
  m_GateFitMode: 2
  m_FOVAxisMode: 0
  m_SensorSize: {{x: 36, y: 24}}
  m_LensShift: {{x: 0, y: 0}}
  m_FocalLength: 50
  m_NormalizedViewPortRect:
    serializedVersion: 2
    x: 0
    y: 0
    width: 1
    height: 1
  near clip plane: 0.3
  far clip plane: 1000
  field of view: 60
  orthographic: 1
  orthographic size: 8
  m_Depth: -1
  m_CullingMask:
    serializedVersion: 2
    m_Bits: 4294967295
  m_RenderingPath: -1
  m_TargetTexture: {{fileID: 0}}
  m_TargetDisplay: 0
  m_TargetEye: 3
  m_HDR: 1
  m_AllowMSAA: 1
  m_AllowDynamicResolution: 0
  m_ForceIntoRT: 0
  m_OcclusionCulling: 1
  m_StereoConvergence: 10
  m_StereoSeparation: 0.022
--- !u!114 &{mb}
MonoBehaviour:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {{fileID: 0}}
  m_PrefabInstance: {{fileID: 0}}
  m_PrefabAsset: {{fileID: 0}}
  m_GameObject: {{fileID: {go}}}
  m_Enabled: 1
  m_EditorHideFlags: 0
  m_Script: {{fileID: 11500000, guid: {script}, type: 3}}
  m_Name:
  m_EditorClassIdentifier:
  target: {{fileID: {target}}}
  offsetY: 3
"""



ANIM_CLIP = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!74 &7400000
AnimationClip:
  m_ObjectHideFlags: 0
  m_Name: {name}
  serializedVersion: 6
  m_Legacy: 0
  m_Compressed: 0
  m_UseHighQualityCurve: 1
  m_RotationCurves: []
  m_CompressedRotationCurves: []
  m_EulerCurves: []
  m_PositionCurves: []
  m_ScaleCurves: []
  m_FloatCurves: []
  m_PPtrCurves:
  - serializedVersion: 2
    curve:
{keys}    attribute: m_Sprite
    path:
    classID: 212
    script: {{fileID: 0}}
  m_SampleRate: 60
  m_WrapMode: 0
  m_AnimationClipSettings:
    serializedVersion: 2
    m_StartTime: 0
    m_StopTime: {stop}
    m_LoopTime: 1
  m_Events: []
"""

ANIM_CONTROLLER = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!91 &9100000
AnimatorController:
  m_Name: {name}
  m_AnimatorParameters: []
  m_AnimatorLayers:
  - serializedVersion: 5
    m_Name: Base Layer
    m_StateMachine: {{fileID: 1107000}}
    m_Mask: {{fileID: 0}}
    m_BlendingMode: 0
    m_SyncedLayerIndex: -1
    m_DefaultWeight: 0
--- !u!1107 &1107000
AnimatorStateMachine:
  m_Name: Base Layer
  m_ChildStates:
  - serializedVersion: 1
    m_State: {{fileID: 1102001}}
  m_ChildStateMachines: []
  m_AnyStateTransitions: []
  m_EntryTransitions: []
  m_DefaultState: {{fileID: 1102001}}
--- !u!1102 &1102001
AnimatorState:
  m_Name: {name}
  m_Speed: 1
  m_CycleOffset: 0
  m_Transitions: []
  m_Motion: {{fileID: 7400000, guid: {clip}, type: 2}}
"""

ASSET_META = "fileFormatVersion: 2\nguid: {guid}\n"


def write_animation(folder: Path, name: str, frames: List[str], fps: float, sprite_guid) -> str:
    """A looping sprite-swap clip and a one-state controller that plays it; returns the controller's guid."""
    folder.mkdir(parents=True, exist_ok=True)
    clip_guid = hashlib.md5(f"kailius-authored/clip/{name}".encode()).hexdigest()
    ctrl_guid = hashlib.md5(f"kailius-authored/controller/{name}".encode()).hexdigest()
    step = 1.0 / max(fps, 1.0)
    keys = "".join(f"    - time: {i * step:.5f}\n      value: {{fileID: 21300000, guid: {sprite_guid(f)}, type: 3}}\n"
                   for i, f in enumerate(frames))
    for file, text, guid in ((f"{name}.anim", ANIM_CLIP.format(name=name, keys=keys, stop=f"{len(frames) * step:.5f}"), clip_guid),
                             (f"{name}.controller", ANIM_CONTROLLER.format(name=name, clip=clip_guid), ctrl_guid)):
        (folder / file).write_text(text, encoding="utf-8", newline="\n")
        (folder / (file + ".meta")).write_text(ASSET_META.format(guid=guid), encoding="utf-8", newline="\n")
    return ctrl_guid


class SceneWriter:
    """Collects the YAML of an authored scene: one GameObject per call, each with a Transform and any components."""

    def __init__(self, guid_of_sprite, script_guid) -> None:
        self.parts: List[str] = []
        self.next_id = 1000
        self.sprite_guid, self.script_guid = guid_of_sprite, script_guid
        self.roots = 0

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def game_object(self, name: str, x: float, y: float, sx: float = 1.0, sy: float = 1.0, tag: str = "Untagged",
                    sprite: Optional[str] = None, order: int = 0, body: Optional[dict] = None,
                    box: Optional[Tuple[float, float]] = None, circle: Optional[float] = None, trigger: bool = False,
                    script: Optional[str] = None, fields: Optional[dict] = None,
                    controller: Optional[str] = None) -> int:
        go, tf = self._id(), self._id()
        comps = [tf]
        extra: List[str] = []

        def add(kind: int, name_: str, body_text: str) -> int:
            fid = self._id()
            comps.append(fid)
            extra.append(f"--- !u!{kind} &{fid}\n{name_}:\n  m_ObjectHideFlags: 0\n  m_GameObject: {{fileID: {go}}}\n"
                         + body_text)
            return fid

        if sprite:
            add(212, "SpriteRenderer",
                "  m_Enabled: 1\n  m_Color: {r: 1, g: 1, b: 1, a: 1}\n  m_FlipX: 0\n  m_FlipY: 0\n"
                f"  m_SortingOrder: {order}\n  m_Sprite: {{fileID: 21300000, guid: {self.sprite_guid(sprite)}, type: 3}}\n")
        if controller:
            add(95, "Animator", f"  m_Enabled: 1\n  m_Controller: {{fileID: 9100000, guid: {controller}, type: 2}}\n")
        if body:
            add(50, "Rigidbody2D",
                f"  m_BodyType: 0\n  m_Simulated: 1\n  m_Mass: 1\n  m_LinearDrag: {body.get('drag', 0)}\n"
                f"  m_AngularDrag: 0.05\n  m_GravityScale: {body['gravity']}\n  m_Material: {{fileID: 0}}\n"
                "  m_Interpolate: 0\n  m_SleepingMode: 1\n  m_CollisionDetection: 0\n  m_Constraints: 4\n")
        if box:
            add(61, "BoxCollider2D",
                f"  m_Enabled: 1\n  m_IsTrigger: {int(trigger)}\n  m_Offset: {{x: 0, y: 0}}\n"
                f"  m_Size: {{x: {box[0]:.5f}, y: {box[1]:.5f}}}\n")
        if circle:
            add(58, "CircleCollider2D",
                f"  m_Enabled: 1\n  m_IsTrigger: {int(trigger)}\n  m_Offset: {{x: 0, y: 0}}\n  m_Radius: {circle}\n")
        if script:
            lines = "".join(f"  {k}: {v}\n" for k, v in (fields or {}).items())
            add(114, "MonoBehaviour",
                "  m_Enabled: 1\n  m_EditorHideFlags: 0\n"
                f"  m_Script: {{fileID: 11500000, guid: {self.script_guid(script)}, type: 3}}\n"
                "  m_Name:\n  m_EditorClassIdentifier:\n" + lines)
        head = (f"--- !u!1 &{go}\nGameObject:\n  m_ObjectHideFlags: 0\n  m_CorrespondingSourceObject: {{fileID: 0}}\n"
                "  m_PrefabInstance: {fileID: 0}\n  m_PrefabAsset: {fileID: 0}\n  serializedVersion: 6\n  m_Component:\n"
                + "".join(f"  - component: {{fileID: {c}}}\n" for c in comps)
                + f"  m_Layer: 0\n  m_Name: {name}\n  m_TagString: {tag}\n  m_Icon: {{fileID: 0}}\n"
                "  m_NavMeshLayer: 0\n  m_StaticEditorFlags: 0\n  m_IsActive: 1\n"
                f"--- !u!4 &{tf}\nTransform:\n  m_ObjectHideFlags: 0\n  m_CorrespondingSourceObject: {{fileID: 0}}\n"
                f"  m_PrefabInstance: {{fileID: 0}}\n  m_PrefabAsset: {{fileID: 0}}\n  m_GameObject: {{fileID: {go}}}\n"
                "  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}\n"
                f"  m_LocalPosition: {{x: {x:.5f}, y: {y:.5f}, z: 0}}\n  m_LocalScale: {{x: {sx:.5f}, y: {sy:.5f}, z: 1}}\n"
                f"  m_Children: []\n  m_Father: {{fileID: 0}}\n  m_RootOrder: {self.roots + 1}\n"
                "  m_LocalEulerAnglesHint: {x: 0, y: 0, z: 0}\n")
        self.roots += 1
        self.parts.append(head + "".join(extra))
        self.last_transform = tf
        return tf


def build_unity_authored(out: Path, unity_version: Optional[str], scene: Optional[str] = None) -> Path:
    """A Unity project whose scene holds the whole level as authored GameObjects (SpriteRenderer, Rigidbody2D,
    BoxCollider2D/CircleCollider2D, a few tiny scripts), one PNG per sprite. Nothing is built at run time, so tools
    that pack the authored scene (tools/unity_pack.py) see everything that is drawn."""
    template = PORTS / "unity_authored"
    if not template.is_dir():
        fail(f"missing template folder {template}")
    project = read_unity_project()
    version = unity_version or project["editorVersion"] or "2020.1.1f1"
    reset_output_dir(out)
    shutil.copytree(template, out, dirs_exist_ok=True)
    (out / "Packages").mkdir(exist_ok=True)
    (out / "Packages" / "manifest.json").write_text(
        json.dumps({"dependencies": UNITY_MINI_PACKAGES}, indent=2) + "\n", encoding="utf-8")
    (out / "ProjectSettings").mkdir(exist_ok=True)
    (out / "ProjectSettings" / "ProjectVersion.txt").write_text(f"m_EditorVersion: {version}\n")
    (out / "ProjectSettings" / "TagManager.asset").write_text(TAG_MANAGER.format(
        tags="\n".join(f"  - {t}" for t in AUTHORED_TAGS), layers="\n".join("  -" for _ in range(32))),
        encoding="utf-8", newline="\n")
    (out / ".gitignore").write_text(UNITY_GITIGNORE)

    tuning = {n: float(v) for n, v, _ in read_tuning()}
    level_file = PORTS / "common" / "mini_level.json"
    data = scene_level_data(scene) if scene else expand_level(json.loads(level_file.read_text(encoding="utf-8")))
    atlas = build_atlas(data)
    groups = atlas["groups"]

    # one PNG per sprite, cut from the atlas, with an import meta that sets pixels-per-unit from its draw scale
    sprite_dir = out / "Assets" / "KailiusAuthored" / "Sprites"
    sprite_dir.mkdir(parents=True, exist_ok=True)
    width = atlas["width"]
    guids: Dict[str, str] = {}
    for spr in atlas["sprites"]:
        rows = b"".join(bytes(atlas["pixels"][((spr["y"] + r) * width + spr["x"]) * 4:
                                              ((spr["y"] + r) * width + spr["x"] + spr["w"]) * 4])
                        for r in range(spr["h"]))
        write_png(sprite_dir / (spr["name"] + ".png"), spr["w"], spr["h"], rows)
        guids[spr["name"]] = hashlib.md5(("kailius-authored/" + spr["name"]).encode()).hexdigest()
        ppu = 32.0 / spr["scale"]
        (sprite_dir / (spr["name"] + ".png.meta")).write_text(
            SPRITE_META.format(guid=guids[spr["name"]], ppu=f"{ppu:g}"), encoding="utf-8", newline="\n")
    write_script_metas(out / "Assets" / "KailiusAuthored")
    frame = lambda key, i=0: atlas["sprites"][groups[key][0] + i]["name"]
    anim_dir = out / "Assets" / "KailiusAuthored" / "Animations"
    sprite_guid = lambda n: guids[n]

    def animation(key: str, fps: float) -> str:
        first, count = groups[key]
        names = [atlas["sprites"][first + i]["name"] for i in range(count)]
        return write_animation(anim_dir, key.replace(":", "_"), names, fps, sprite_guid)

    # script guids follow write_script_metas(folder): the path relative to the folder it was given
    w = SceneWriter(lambda n: guids[n], lambda n: hashlib.md5(f"kailius-mini/Scripts/{n}.cs".encode()).hexdigest())

    solids = data["solids"]
    one_way = data.get("oneWay") or [False] * len(solids)
    for (x, y, sw, sh), flat in zip(solids, [not o for o in one_way]):
        w.game_object("Ground" if flat else "Platform", x + sw / 2, y + sh / 2, sw, sh, tag="Ground",
                      sprite=frame("tiles", 4), box=(1, 1))
        w.game_object("Grass", x + sw / 2, y + sh - 0.5, sw, 1, sprite=frame("tiles", 1), order=1)
    ctrl_coin = animation("coin", 10.0)
    for cx, cy in data["coins"]:
        w.game_object("Coin", cx, cy, tag="Coin", sprite=frame("coin"), controller=ctrl_coin, circle=0.4, trigger=True)
    for x, y, kind in data["enemies"]:
        d = data["kinds"][kind]
        under = [s for s in solids if s[0] <= x <= s[0] + s[2] and s[1] + s[3] <= y + 0.5]
        floor = max(under, key=lambda s: s[1] + s[3]) if under else (x - 3, 0, 6, 0)
        w.game_object("Enemy_" + d["kind"], x, y, tag="Enemy", sprite=frame("enemy:" + d["kind"]), order=2, controller=animation("enemy:" + d["kind"], d["fps"]),
                      body={"gravity": d["gravityScale"]}, box=(d["width"], d["height"]),
                      script="AuthoredEnemy",
                      fields={"speed": d["speed"], "minX": f"{floor[0] + 0.8:.3f}",
                              "maxX": f"{floor[0] + floor[2] - 0.8:.3f}", "direction": 1})
    for hx, hy, hw, hh in data["hazards"]:
        w.game_object("Hazard", hx + hw / 2, hy + hh / 2, tag="Hazard", box=(hw, hh), trigger=True)
    for tx, ty, ref in data["hazardTiles"]:
        w.game_object("Trap", tx, ty, sprite=frame(f"trap:{ref[0]}:{ref[1]}"), order=1)
    for tx, ty in data["torches"]:
        w.game_object("TorchStick", tx + tuning.get("TorchStickX", 0), ty + tuning.get("TorchStickY", 0),
                      sprite=frame("torch_stick"), order=1)
        w.game_object("TorchFlame", tx + tuning.get("TorchFlameX", 0), ty + tuning.get("TorchFlameY", 0),
                      sprite=frame("torch_flame"), order=2, controller=animation("torch_flame", tuning.get("TorchFps", 8.0)))
    px, py = data["portal"]
    w.game_object("Portal", px, py, tag="Finish", sprite=frame("portal"), order=1, controller=animation("portal", 8.0), box=(2, 3), trigger=True)
    sx, sy = data["spawn"]
    player = w.game_object(
        "Player", sx, sy, tag="Player", sprite=frame("player_idle"), order=3,
        body={"gravity": tuning["PlayerGravityScale"], "drag": tuning["PlayerDrag"]},
        box=(tuning["PlayerW"], tuning["PlayerH"]), script="AuthoredPlayer",
        fields={"speed": tuning["MoveSpeed"], "jumpSpeed": tuning["JumpSpeed"], "spawnX": sx, "spawnY": sy,
                "jumpsLeft": 2, "score": 0, "respawnBelow": -12})
    camera = AUTHORED_SCENE_CAMERA.format(go=900, tf=901, cam=902, mb=903, script=w.script_guid("AuthoredCamera"),
                                          target=player)
    scene_dir = out / "Assets" / "Scenes"
    scene_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "KailiusAuthored.unity").write_text(
        "%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n" + camera + "".join(w.parts), encoding="utf-8", newline="\n")
    log(f"generated authored Unity project ({version}): {w.roots} GameObjects, {len(atlas['sprites'])} sprites")
    log(f"  project: {out}")
    return out


def mini_unity(args: argparse.Namespace) -> Path:
    if getattr(args, 'authored', False):
        return build_unity_authored(args.out or DEFAULT_UNITY_OUT.with_name(DEFAULT_UNITY_OUT.name + '-authored'),
                                    args.unity_version, getattr(args, 'scene', None))
    return build_unity_mini(args.out or DEFAULT_UNITY_OUT, args.unity_version, args.build,
                            args.unity_editor, args.build_target, getattr(args, 'scene', None))


def mini_prowl2d(args: argparse.Namespace) -> Path:
    return build_csharp_mini("prowl2d", args.out or DEFAULT_PROWL2D_OUT, args.prowl2d, args.build,
                             getattr(args, "scene", None))


def mini_stride2d(args: argparse.Namespace) -> Path:
    return build_csharp_mini("stride2d", args.out or DEFAULT_STRIDE2D_OUT, args.stride2d, args.build,
                             getattr(args, "scene", None))


MINI_TARGETS = {"unity": mini_unity, "prowl2d": mini_prowl2d, "stride2d": mini_stride2d}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def add_mini_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--build", action="store_true",
                        help="also build a runnable player: Unity batch mode for `unity`, Prowl2D's "
                             "C translation for `prowl2d`")
    parser.add_argument("--unity-version", help="Unity editor version to write into the project "
                        "(default: the version the fork uses)")
    parser.add_argument("--unity-editor", help="path to the Unity executable (or set UNITY_EDITOR)")
    parser.add_argument("--build-target", default=default_build_target(),
                        choices=["linux64", "win64", "osx"], help="player platform for unity --build")
    parser.add_argument("--authored", action="store_true", help="unity: write the level as authored GameObjects "
                        "in the scene (SpriteRenderer, Rigidbody2D, colliders) instead of building it at run time")
    parser.add_argument("--scene", help="build this Unity scene (e.g. Scene_1) instead of the "
                        "hand-made mini level")
    parser.add_argument("--prowl2d", help="path to a Prowl2D checkout for prowl2d --build "
                        "(or set PROWL2D; default: ../Prowl2D)")
    parser.add_argument("--stride2d", help="path to a Stride2D checkout for stride2d --build "
                        "(or set STRIDE2D; default: ../stride2D)")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    package_cmd = commands.add_parser("package", help="build the engine-neutral asset bundle")
    package_cmd.add_argument("--dist", type=Path, default=DEFAULT_DIST,
                             help=f"output directory (default: {DEFAULT_DIST})")

    mini_cmd = commands.add_parser("mini", help="generate a small playable port")
    mini_cmd.add_argument("engine", choices=sorted(MINI_TARGETS))
    mini_cmd.add_argument("--out", type=Path, help="where to generate it (default: kailius-mini-<engine> "
                          "in the system temp directory)")
    add_mini_arguments(mini_cmd)

    all_cmd = commands.add_parser("all", help="package, then generate every mini port")
    all_cmd.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    add_mini_arguments(all_cmd)
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    args = make_parser().parse_args(argv if argv is not None else (sys.argv[1:] or ["all"]))

    if args.command == "package":
        package(args.dist)
    elif args.command == "mini":
        MINI_TARGETS[args.engine](args)
    else:
        package(args.dist)
        args.out = None   # every port goes to its default directory
        for engine in sorted(MINI_TARGETS):
            MINI_TARGETS[engine](args)


if __name__ == "__main__":
    main()

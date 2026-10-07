![caption](images/kailiusDemo.gif)

# Kailius
In Kailius, players embark on an exhilarating adventure through a captivating 2D platforming world. Developed using Unity, this engrossing game is available for Android, Windows, and Linux platforms, allowing gamers to immerse themselves in its enchanting universe on their preferred devices.

Set in a realm brimming with excitement and challenges, Kailius offers a test of skill for players of all levels. With its diverse range of levels, the game keeps you engaged as the difficulty steadily increases, ensuring a thrilling experience from start to finish. Each level presents unique obstacles and puzzles that demand precise timing, nimble movements, and quick thinking to overcome.

Drawing inspiration from the pixelated aesthetics of classic 8-bit RPGs, Kailius presents a nostalgic visual style that resonates with fans of retro gaming. The carefully crafted PixelArt graphics breathe life into the game's characters, environments, and enemies, transporting players back to the golden era of gaming while still offering a fresh and modern experience.

Whether you're a seasoned platforming enthusiast or a newcomer to the genre, Kailius promises hours of entertainment, challenges, and triumphs. Are you ready to embark on this epic journey and become a legend in the realm of Kailius? The fate of this captivating world lies in your hands.

## :hammer_and_wrench: Build tool and ports

`build.py` (repo root, Python 3, standard library only) packages the game's content so other engines can use it, and
generates small playable ports of Kailius from the Unity project itself. Nothing is copied by hand: the level layout,
enemy stats, trap damage, player physics and the art are all read from the prefabs, scenes, scripts and sprites in
`Assets/`, so the ports follow the game when it changes.

    python3 build.py package                 # engine-neutral asset bundle in dist/ (manifest, hashes, import settings)
    python3 build.py mini <target>           # generate one playable mini port
    python3 build.py all                     # package, then every mini port

It also needs the `ports/` folder, which holds the engine front ends and the hand-made mini level that `build.py`
copies from. The generated projects themselves are build output and are not committed.

### Targets

| Target | What it is | Run it |
|---|---|---|
| `unity` | A small Unity project (editor 2020.1.1f1, the fork's version) with the mini level, the real art, patrol and boss enemies, traps, torches, HUD, sound. | Unity Hub > Add project from disk, open `Assets/Scenes/KailiusMini.unity`, press Play. `--build` makes a player in batch mode (needs `--unity-editor` or `UNITY_EDITOR`). |
| `stride2d` | The same game on [Stride2D](https://github.com/crustos/stride2D): a native window, keyboard, atlas art, text. | `python3 build.py mini stride2d --build --stride2d PATH_TO_Stride2D` |
| `prowl2d` | The same game headless on [Prowl2D](https://github.com/crustos/Prowl2D): a dotnet-free C# to C translation, driven by a bot, with no window. | `python3 build.py mini prowl2d --build --prowl2d PATH_TO_Prowl2D` |

Add `--out DIR` to choose where a port is generated (default: `kailius-mini-<target>` in the temp directory) and
`--scene Scene_1` to build from a real Kailius scene instead of the mini level. Controls in the playable ports:
A/D or arrows to move, Space to jump (once more in the air), land on enemies to hurt them, R to restart.

The mini ports cover movement, double jump, platforms, coins, patrol and boss enemies, traps, torches, score and
health, and the portal. Not yet ported: ranged attackers (wizards), hearts, swords, shields, chests, enemy drops,
parallax backgrounds. Per-target details are in `ports/<target>/README.md`.

## :warning: Requirements
* Android 5.0+
* Snapdragon 625+
* 2GB RAM

## :iphone: [Play Store](https://play.google.com/store/apps/details?id=com.waniapps.Kailius.game.android)

![setup-screenshot](images/1.jpg)
![setup-screenshot](images/2.jpg)
![setup-screenshot](images/3.jpg)
![setup-screenshot](images/4.jpg)

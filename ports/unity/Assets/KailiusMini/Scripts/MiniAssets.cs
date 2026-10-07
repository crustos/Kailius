using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using UnityEngine;

namespace KailiusMini
{
    // Plain data classes JsonUtility fills from Resources/Kailius/level.json (written by build.py).
    [Serializable] public class SolidData { public float x, y, w, h; public bool oneWay; }
    [Serializable] public class RectData { public float x, y, w, h; }
    [Serializable] public class PointData { public float x, y; }
    [Serializable] public class TileData { public float x, y; public int frame; }
    [Serializable] public class EnemyData { public float x, y; public int kind; }
    [Serializable] public class TuningData { public string name; public float value; }
    [Serializable] public class SpriteData { public string name; public int x, y, w, h; public float scale; }
    [Serializable] public class GroupData { public string key; public int first, count; }

    [Serializable]
    public class KindData
    {
        public string name;
        public bool boss;
        public float speed, health, width, height, gravityScale;
        public float attackDamage, attackRange, weaponRange;
        public int frame0, frameCount;
        public float fps;
    }

    [Serializable]
    public class LevelData
    {
        public float spawnX, spawnY, portalX, portalY, respawnX, respawnY;
        public List<SolidData> solids;
        public List<RectData> hazards;
        public List<TileData> tiles;
        public List<PointData> coins;
        public List<EnemyData> enemies;
        public List<PointData> torches;
        public List<KindData> kinds;
        public List<TuningData> tuning;
        public List<SpriteData> sprites;
        public List<GroupData> groups;
        public int atlasWidth, atlasHeight;
    }

    /// <summary>
    /// Loads what build.py put in Assets/Resources/Kailius: level.json (the level, the numbers read from the
    /// Kailius prefabs and scripts, where each sprite is in the atlas), atlas.png, and the sounds.
    /// The atlas holds the real Kailius art cropped and scaled to 32 pixels per unit; sprites are cut from it at runtime.
    /// </summary>
    public static class MiniAssets
    {
        const string Root = "Kailius/";
        const float Ppu = 32f;
        static readonly Regex TrailingNumber = new Regex(@"^(.*?)(\d+)$");

        public static LevelData Level { get; private set; }
        static Texture2D atlas;
        static Dictionary<string, float> tuning;
        static Dictionary<string, GroupData> groups;
        static Dictionary<long, Sprite> cache;

        public static void Load()
        {
            TextAsset json = Resources.Load<TextAsset>(Root + "level");
            atlas = Resources.Load<Texture2D>(Root + "atlas");
            if (json == null || atlas == null)
                throw new InvalidOperationException("KailiusMini: Resources/Kailius/level.json or atlas.png is missing; run build.py mini unity");
            Level = JsonUtility.FromJson<LevelData>(json.text);
            atlas.filterMode = FilterMode.Point;
            atlas.wrapMode = TextureWrapMode.Clamp;

            tuning = new Dictionary<string, float>();
            foreach (TuningData t in Level.tuning) tuning[t.name] = t.value;
            groups = new Dictionary<string, GroupData>();
            foreach (GroupData g in Level.groups) groups[g.key] = g;
            cache = new Dictionary<long, Sprite>();
        }

        /// <summary>A number read from the Kailius project (Cfg in the other ports).</summary>
        public static float Tune(string name)
        {
            float value;
            if (!tuning.TryGetValue(name, out value))
                throw new KeyNotFoundException("KailiusMini: no value '" + name + "' in level.json");
            return value;
        }

        public static int GroupFirst(string key) { return groups[key].first; }
        public static int GroupCount(string key) { return groups[key].count; }

        /// <summary>One atlas frame. Characters stand on the bottom of the frame, so their pivot is bottom centre.</summary>
        public static Sprite Frame(int index, bool centred)
        {
            long key = index * 2L + (centred ? 1 : 0);
            Sprite sprite;
            if (cache.TryGetValue(key, out sprite)) return sprite;

            SpriteData d = Level.sprites[index];
            Rect rect = new Rect(d.x, atlas.height - d.y - d.h, d.w, d.h);     // the atlas lists y from the top
            Vector2 pivot = centred ? new Vector2(0.5f, 0.5f) : new Vector2(0.5f, 0f);
            sprite = Sprite.Create(atlas, rect, pivot, Ppu / d.scale, 0, SpriteMeshType.FullRect);
            sprite.name = d.name;
            cache[key] = sprite;
            return sprite;
        }

        public static Sprite[] Frames(string group, bool centred)
        {
            GroupData g = groups[group];
            Sprite[] frames = new Sprite[g.count];
            for (int i = 0; i < g.count; i++) frames[i] = Frame(g.first + i, centred);
            return frames;
        }

        public static Sprite[] Frames(int first, int count, bool centred)
        {
            Sprite[] frames = new Sprite[count];
            for (int i = 0; i < count; i++) frames[i] = Frame(first + i, centred);
            return frames;
        }

        /// <summary>The top-left pixelsWide x pixelsHigh part of ground tile 0..8 (row from the top times 3, plus column).</summary>
        public static Sprite TilePart(int tile, int pixelsWide, int pixelsHigh)
        {
            long key = -1 - ((tile * 64L + pixelsWide) * 64L + pixelsHigh);
            Sprite sprite;
            if (cache.TryGetValue(key, out sprite)) return sprite;

            SpriteData d = Level.sprites[GroupFirst("tiles") + tile];
            Rect rect = new Rect(d.x, atlas.height - d.y - pixelsHigh, pixelsWide, pixelsHigh);
            sprite = Sprite.Create(atlas, rect, new Vector2(0.5f, 0.5f), Ppu, 0, SpriteMeshType.FullRect);
            cache[key] = sprite;
            return sprite;
        }

        /// <summary>Every sprite at a Resources/Kailius path (used for the sky), in natural name order.</summary>
        public static Sprite LoadSprite(string path)
        {
            Sprite[] all = Resources.LoadAll<Sprite>(Root + path);
            if (all.Length == 0)
            {
                Debug.LogWarning("KailiusMini: no sprites found at Resources/" + Root + path);
                return null;
            }
            Array.Sort(all, (a, b) => NaturalCompare(a.name, b.name));
            return all[0];
        }

        public static AudioClip LoadClip(string name)
        {
            return Resources.Load<AudioClip>(Root + "Sounds/" + name);
        }

        static int NaturalCompare(string a, string b)
        {
            Match ma = TrailingNumber.Match(a);
            Match mb = TrailingNumber.Match(b);
            if (ma.Success && mb.Success && ma.Groups[1].Value == mb.Groups[1].Value)
                return int.Parse(ma.Groups[2].Value).CompareTo(int.Parse(mb.Groups[2].Value));
            return string.CompareOrdinal(a, b);
        }
    }
}

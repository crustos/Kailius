using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace KailiusMini
{
    /// <summary>
    /// Builds the whole mini level at runtime from Resources/Kailius/level.json, so the scene file only needs this one
    /// component. The same level data and numbers drive the Prowl2D and Stride2D ports.
    /// Sizes are world units; the art in the atlas is already scaled to 32 pixels per unit.
    /// </summary>
    public class MiniGame : MonoBehaviour
    {
        public static MiniGame Instance { get; private set; }

        public int Score { get; private set; }
        public int Coins { get; private set; }
        public int TotalCoins { get; private set; }
        public int Kills { get; private set; }
        public int TotalEnemies { get; private set; }
        public int Deaths { get; private set; }
        public int TrapHits { get; set; }
        public bool LevelComplete { get; private set; }
        public MiniPlayer Player { get; private set; }

        readonly Dictionary<string, AudioClip> clips = new Dictionary<string, AudioClip>();

        Camera cam;
        AudioSource audioSource;
        Sprite whiteSprite;
        SpriteRenderer sky;
        Vector3 cameraVelocity;
        GUIStyle labelStyle;
        GUIStyle bigStyle;
        float deathBannerUntil;
        int coinScore;
        int enemyScore;

        void Awake()
        {
            Instance = this;
            Time.timeScale = 1f;

            MiniAssets.Load();
            Physics2D.gravity = new Vector2(0f, MiniAssets.Tune("Gravity"));
            coinScore = (int)MiniAssets.Tune("CoinScore");
            enemyScore = (int)MiniAssets.Tune("EnemyScore");

            audioSource = gameObject.AddComponent<AudioSource>();
            whiteSprite = CreateWhiteSprite();

            SetupCamera();
            BuildLevel();
        }

        void OnDestroy()
        {
            if (Instance == this) Instance = null;
        }

        // ------------------------------------------------------------------ level

        void BuildLevel()
        {
            LevelData level = MiniAssets.Level;

            foreach (SolidData s in level.solids) BuildSolid(s);
            foreach (RectData h in level.hazards) BuildHazard(h);
            foreach (TileData t in level.tiles) BuildDecor("Trap", t.x, t.y, MiniAssets.Frame(t.frame, true), 3);
            foreach (PointData t in level.torches) BuildTorch(t.x, t.y);
            BuildPortal(level.portalX, level.portalY);
            for (int i = 0; i < level.coins.Count; i++) BuildCoin(level.coins[i].x, level.coins[i].y, i);
            foreach (EnemyData e in level.enemies) BuildEnemy(e);
            Player = BuildPlayer(new Vector3(level.spawnX, level.spawnY, 0f));
        }

        // The ground is drawn as the nine tiles of the grass block: corners, edges and a plain fill, tiled to size.
        // Columns and rows are [first cell, middle, last cell]; a shorter span shows only the first cell.
        static List<Vector3> Split(float total)
        {
            List<Vector3> parts = new List<Vector3>();       // x = tile index 0..2, y = offset from the start, z = size
            if (total < 2f)
            {
                parts.Add(new Vector3(0f, 0f, total));
                return parts;
            }
            parts.Add(new Vector3(0f, 0f, 1f));
            if (total - 2f > 0.001f) parts.Add(new Vector3(1f, 1f, total - 2f));
            parts.Add(new Vector3(2f, total - 1f, 1f));
            return parts;
        }

        void BuildSolid(SolidData s)
        {
            GameObject go = new GameObject(s.oneWay ? "Platform" : "Ground");
            go.transform.position = new Vector3(s.x + s.w * 0.5f, s.y + s.h * 0.5f, 0f);

            BoxCollider2D col = go.AddComponent<BoxCollider2D>();
            col.size = new Vector2(s.w, s.h);
            if (s.oneWay)
            {
                // One-way: the player can jump up through a platform and walk underneath it.
                col.usedByEffector = true;
                PlatformEffector2D effector = go.AddComponent<PlatformEffector2D>();
                effector.useOneWay = true;
                effector.useSideFriction = false;
                effector.useSideBounce = false;
                effector.surfaceArc = 170f;
            }

            foreach (Vector3 column in Split(s.w))
                foreach (Vector3 row in Split(s.h))
                {
                    float sw = column.z, sh = row.z;
                    int pw = Mathf.Clamp(Mathf.RoundToInt(sw * 32f), 1, 32);
                    int ph = Mathf.Clamp(Mathf.RoundToInt(sh * 32f), 1, 32);

                    GameObject cell = new GameObject("Tile");
                    cell.transform.SetParent(go.transform, false);
                    cell.transform.localPosition = new Vector3(-s.w * 0.5f + column.y + sw * 0.5f,
                                                               s.h * 0.5f - row.y - sh * 0.5f, 0f);
                    SpriteRenderer sr = cell.AddComponent<SpriteRenderer>();
                    sr.sprite = MiniAssets.TilePart((int)row.x * 3 + (int)column.x, pw, ph);
                    sr.drawMode = SpriteDrawMode.Tiled;
                    sr.tileMode = SpriteTileMode.Continuous;
                    sr.size = new Vector2(sw, sh);
                    sr.sortingOrder = 0;
                }
        }

        void BuildHazard(RectData h)
        {
            GameObject go = new GameObject("Trap");
            go.transform.position = new Vector3(h.x + h.w * 0.5f, h.y + h.h * 0.5f, 0f);
            BoxCollider2D col = go.AddComponent<BoxCollider2D>();
            col.size = new Vector2(h.w, h.h);
            go.AddComponent<MiniHazard>();
        }

        GameObject BuildDecor(string objectName, float x, float y, Sprite sprite, int order)
        {
            GameObject go = new GameObject(objectName);
            go.transform.position = new Vector3(x, y, 0f);
            SpriteRenderer sr = go.AddComponent<SpriteRenderer>();
            sr.sprite = sprite;
            sr.sortingOrder = order;
            return go;
        }

        // Flame1.prefab: a stick and an animated flame, each offset from the prefab's position.
        void BuildTorch(float x, float y)
        {
            BuildDecor("TorchStick", x + MiniAssets.Tune("TorchStickX"), y + MiniAssets.Tune("TorchStickY"),
                       MiniAssets.Frame(MiniAssets.GroupFirst("torch_stick"), true), 2);
            GameObject flame = BuildDecor("TorchFlame", x + MiniAssets.Tune("TorchFlameX"), y + MiniAssets.Tune("TorchFlameY"),
                                          MiniAssets.Frame(MiniAssets.GroupFirst("torch_flame"), true), 3);
            flame.AddComponent<SpriteAnimator>().Play(MiniAssets.Frames("torch_flame", true), MiniAssets.Tune("TorchFps"));
        }

        void BuildCoin(float x, float y, int index)
        {
            GameObject go = new GameObject("Coin");
            go.transform.position = new Vector3(x, y, 0f);

            CircleCollider2D col = go.AddComponent<CircleCollider2D>();
            col.isTrigger = true;
            col.radius = MiniAssets.Tune("CoinRadius");

            GameObject art = new GameObject("Art");
            art.transform.SetParent(go.transform, false);
            art.transform.localPosition = new Vector3(0f, -0.36f, 0f);
            SpriteRenderer sr = art.AddComponent<SpriteRenderer>();
            sr.sortingOrder = 4;
            Sprite[] frames = MiniAssets.Frames("coin", false);
            sr.sprite = frames[index % frames.Length];
            art.AddComponent<SpriteAnimator>().Play(frames, 10f);

            go.AddComponent<MiniPickup>();
            TotalCoins++;
        }

        void BuildPortal(float x, float y)
        {
            GameObject go = new GameObject("Portal");
            go.transform.position = new Vector3(x, y, 0f);

            BoxCollider2D col = go.AddComponent<BoxCollider2D>();
            col.isTrigger = true;
            col.size = new Vector2(MiniAssets.Tune("PortalW"), MiniAssets.Tune("PortalH"));

            GameObject art = new GameObject("Art");
            art.transform.SetParent(go.transform, false);
            art.transform.localPosition = new Vector3(0f, -MiniAssets.Tune("PortalH") * 0.5f, 0f);
            SpriteRenderer sr = art.AddComponent<SpriteRenderer>();
            sr.sortingOrder = 2;
            Sprite[] frames = MiniAssets.Frames("portal", false);
            sr.sprite = frames[0];
            art.AddComponent<SpriteAnimator>().Play(frames, 6f);

            go.AddComponent<MiniPortal>();
        }

        void BuildEnemy(EnemyData e)
        {
            KindData kind = MiniAssets.Level.kinds[e.kind];

            GameObject go = new GameObject(kind.name);
            go.transform.position = new Vector3(e.x, e.y, 0f);

            Rigidbody2D body = go.AddComponent<Rigidbody2D>();
            body.freezeRotation = true;
            body.sharedMaterial = NoFriction();

            BoxCollider2D col = go.AddComponent<BoxCollider2D>();
            col.size = new Vector2(kind.width, kind.height);

            GameObject art = new GameObject("Art");
            art.transform.SetParent(go.transform, false);
            art.transform.localPosition = new Vector3(0f, -kind.height * 0.5f, 0f);
            SpriteRenderer sr = art.AddComponent<SpriteRenderer>();
            sr.sortingOrder = 5;
            Sprite[] frames = MiniAssets.Frames(kind.frame0, kind.frameCount, false);
            sr.sprite = frames[0];
            art.AddComponent<SpriteAnimator>().Play(frames, kind.fps);

            go.AddComponent<MiniEnemy>().Init(kind, sr, whiteSprite);
            TotalEnemies++;
        }

        MiniPlayer BuildPlayer(Vector3 position)
        {
            float w = MiniAssets.Tune("PlayerW");
            float h = MiniAssets.Tune("PlayerH");

            GameObject go = new GameObject("Player");
            go.transform.position = position;

            Rigidbody2D body = go.AddComponent<Rigidbody2D>();
            body.gravityScale = MiniAssets.Tune("PlayerGravityScale");
            body.drag = MiniAssets.Tune("PlayerDrag");
            body.freezeRotation = true;
            body.collisionDetectionMode = CollisionDetectionMode2D.Continuous;
            body.sharedMaterial = NoFriction();

            BoxCollider2D col = go.AddComponent<BoxCollider2D>();
            col.size = new Vector2(w, h);

            GameObject art = new GameObject("Art");
            art.transform.SetParent(go.transform, false);
            art.transform.localPosition = new Vector3(0f, -h * 0.5f, 0f);
            art.AddComponent<SpriteRenderer>().sortingOrder = 10;
            art.AddComponent<SpriteAnimator>();

            return go.AddComponent<MiniPlayer>();      // last: its Awake reads the art child
        }

        // ------------------------------------------------------------------ camera and sky

        void SetupCamera()
        {
            cam = Camera.main;
            if (cam == null)
            {
                GameObject go = new GameObject("Main Camera");
                go.tag = "MainCamera";
                cam = go.AddComponent<Camera>();
                go.AddComponent<AudioListener>();
            }
            cam.orthographic = true;
            cam.orthographicSize = 8f;
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.45f, 0.70f, 0.95f);
            cam.transform.position = new Vector3(MiniAssets.Level.spawnX, MiniAssets.Level.spawnY, -10f);

            Sprite skySprite = MiniAssets.LoadSprite("Sprites/Background");
            if (skySprite != null)
            {
                GameObject go = new GameObject("Sky");
                go.transform.SetParent(cam.transform, false);
                go.transform.localPosition = new Vector3(0f, 0f, 20f);
                sky = go.AddComponent<SpriteRenderer>();
                sky.sprite = skySprite;
                sky.sortingOrder = -100;
            }
        }

        void LateUpdate()
        {
            if (cam == null) return;

            if (Player != null)
            {
                Vector3 target = new Vector3(Player.transform.position.x,
                                             Mathf.Max(Player.transform.position.y + 1f, 3f), -10f);
                cam.transform.position = Vector3.SmoothDamp(cam.transform.position, target,
                                                            ref cameraVelocity, 0.15f);
            }

            // Keep the sky covering the view whatever the window shape.
            if (sky != null)
            {
                Vector2 size = sky.sprite.bounds.size;
                float viewHeight = cam.orthographicSize * 2f;
                float viewWidth = viewHeight * cam.aspect;
                float scale = Mathf.Max(viewHeight / size.y, viewWidth / size.x) * 1.05f;
                sky.transform.localScale = new Vector3(scale, scale, 1f);
            }
        }

        // ------------------------------------------------------------------ score and audio

        public void CollectCoin()
        {
            Coins++;
            Score += coinScore;
            Play("coin");
        }

        public void EnemyKilled()
        {
            Kills++;
            Score += enemyScore;
        }

        public void PlayerDied()
        {
            Deaths++;
            deathBannerUntil = Time.time + 1.7f;
        }

        public void Complete()
        {
            LevelComplete = true;
        }

        public void Play(string clipName)
        {
            AudioClip clip;
            if (!clips.TryGetValue(clipName, out clip))
            {
                clip = MiniAssets.LoadClip(clipName);
                clips[clipName] = clip;
            }
            if (clip != null) audioSource.PlayOneShot(clip);
        }

        void Update()
        {
            if (Input.GetKeyDown(KeyCode.R))
                SceneManager.LoadScene(SceneManager.GetActiveScene().buildIndex);
        }

        // ------------------------------------------------------------------ HUD

        void OnGUI()
        {
            if (labelStyle == null)
            {
                labelStyle = new GUIStyle(GUI.skin.label) { fontSize = 22, fontStyle = FontStyle.Bold };
                labelStyle.normal.textColor = Color.white;
                bigStyle = new GUIStyle(labelStyle) { fontSize = 52, alignment = TextAnchor.MiddleCenter };
            }

            int health = Player != null ? Mathf.Max(0, Player.Health) : 0;
            int maxHealth = Player != null ? Player.maxHealth : 1;
            float fraction = Mathf.Clamp01(health / (float)maxHealth);

            GUI.color = new Color(0f, 0f, 0f, 0.6f);
            GUI.DrawTexture(new Rect(16f, 10f, 224f, 22f), Texture2D.whiteTexture);
            GUI.color = Color.Lerp(Color.red, Color.green, fraction);
            GUI.DrawTexture(new Rect(18f, 12f, 220f * fraction, 18f), Texture2D.whiteTexture);
            GUI.color = Color.white;
            GUI.Label(new Rect(252f, 6f, 300f, 32f), "HP " + health + "/" + maxHealth, labelStyle);

            GUI.Label(new Rect(16f, 40f, 900f, 32f),
                      "Score " + Score + "     Coins " + Coins + "/" + TotalCoins +
                      "     Kills " + Kills + "/" + TotalEnemies, labelStyle);

            GUI.Label(new Rect(16f, Screen.height - 36f, 1000f, 30f),
                      "A/D move   Space jump (twice in the air)   Land on enemies to hurt them   R restart",
                      labelStyle);

            GUIStyle centred = new GUIStyle(labelStyle) { alignment = TextAnchor.MiddleCenter };
            if (LevelComplete)
            {
                GUI.Label(new Rect(0f, Screen.height * 0.3f, Screen.width, 80f), "LEVEL COMPLETE", bigStyle);
                GUI.Label(new Rect(0f, Screen.height * 0.3f + 80f, Screen.width, 40f),
                          "Score " + Score + "   -   press R to play again", centred);
            }
            else if (Time.time < deathBannerUntil)
            {
                GUI.Label(new Rect(0f, Screen.height * 0.3f, Screen.width, 80f), "YOU DIED", bigStyle);
            }
        }

        // ------------------------------------------------------------------ helpers

        static Sprite CreateWhiteSprite()
        {
            Texture2D texture = new Texture2D(1, 1);
            texture.SetPixel(0, 0, Color.white);
            texture.Apply();
            texture.filterMode = FilterMode.Point;
            return Sprite.Create(texture, new Rect(0f, 0f, 1f, 1f), new Vector2(0.5f, 0.5f), 1f);
        }

        static PhysicsMaterial2D NoFriction()
        {
            PhysicsMaterial2D material = new PhysicsMaterial2D("NoFriction");
            material.friction = 0f;
            material.bounciness = 0f;
            return material;
        }
    }
}

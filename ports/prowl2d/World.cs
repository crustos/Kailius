using System;
using Prowl.Core2D;
using Prowl.Native.Box2D;

// Builds the level into a scene from the generated Level and Cfg: ground, coins, enemies, portal and the player.
// Shared by every front end (headless bot run, window); they only differ in what drives the input and what is drawn.
static class World
{
    static Collider2D MakeCollider(Scene2D scene, Node n, float w, float h, bool trigger)
    {
        Collider2D c = scene.NewBoxCollider(n, w, h);
        c.Friction = 0f;
        c.IsTrigger = trigger;
        scene.Finish(c.Self);
        return c;
    }

    // Kailius uses capsule colliders (so a character does not catch on a seam); the runtime has box, circle
    // and convex polygon (8 points at most). This is a capsule as an octagon with the capsule's exact width
    // and height: the long side is straight and each end is chamfered. Taller than wide stands up, wider
    // than tall lies down.
    static Collider2D MakeCapsule(Scene2D scene, Node n, float w, float h)
    {
        bool upright = h >= w;
        float r = (upright ? w : h) * 0.5f;                      // end radius
        float c = (upright ? h : w) * 0.5f - r;                  // half the straight part
        float[] xy = new float[16];
        // along the long axis a = +-c (sides) and +-(c + r) (ends); across it b = +-r (sides) and +-r/2 (ends)
        float[] a = new float[8];
        float[] b = new float[8];
        a[0] = c; b[0] = r;
        a[1] = c + r; b[1] = r * 0.5f;
        a[2] = c + r; b[2] = -r * 0.5f;
        a[3] = c; b[3] = -r;
        a[4] = -c; b[4] = -r;
        a[5] = -c - r; b[5] = -r * 0.5f;
        a[6] = -c - r; b[6] = r * 0.5f;
        a[7] = -c; b[7] = r;
        for (int i = 0; i < 8; i++)
        {
            if (upright) { xy[i * 2] = b[i]; xy[i * 2 + 1] = a[i]; }
            else { xy[i * 2] = a[i]; xy[i * 2 + 1] = b[i]; }
        }
        Collider2D col = scene.NewPolygonCollider(n, xy, 8);
        col.Friction = 0f;
        scene.Finish(col.Self);
        return col;
    }

    static Node MakeBox(Scene2D scene, float x, float y, float w, float h, int layer, int tag, bool trigger)
    {
        Node n = scene.NewNode(null);
        n.SetPosition(x, y);
        n.Layer = layer;
        n.Tag = tag;
        MakeCollider(scene, n, w, h, trigger);
        return n;
    }

    // Returns the player's node. withBot adds BotScript, which plays the level through InputState.
    public static Node Build(Scene2D scene, bool withBot)
    {
        scene.FixedDeltaTime = Cfg.Dt;
        scene.SetGravity(0f, Cfg.Gravity);
        Level.Init();

        // ground and platforms: x, y, w, h with the origin at the bottom left
        for (int i = 0; i < Level.SolidCount; i++)
            MakeBox(scene, Level.Solid(i, 0) + Level.Solid(i, 2) * 0.5f, Level.Solid(i, 1) + Level.Solid(i, 3) * 0.5f,
                    Level.Solid(i, 2), Level.Solid(i, 3), Layers.Ground, Shared.TagGround, false);

        Shared.InitCoins(Level.CoinCount);
        for (int i = 0; i < Level.CoinCount; i++)
        {
            Node n = scene.NewNode(null);
            n.SetPosition(Level.Coin(i, 0), Level.Coin(i, 1));
            n.Layer = Layers.Pickup;
            n.Tag = Shared.TagCoin;
            Collider2D cc = scene.NewCircleCollider(n, Cfg.CoinRadius);
            cc.IsTrigger = true;
            scene.Finish(cc.Self);
            CoinScript cs = Scripts.AddCoinScript(n);
            cs.Index = i;
            Shared.RegisterCoin(i, n);
        }

        Shared.InitEnemies(Level.EnemyCount);
        for (int i = 0; i < Level.EnemyCount; i++)
        {
            int kind = (int)Level.Enemy(i, 2);
            Node en = scene.NewNode(null);
            en.SetPosition(Level.Enemy(i, 0), Level.Enemy(i, 1));
            en.Layer = Layers.Enemy;
            en.Tag = Shared.TagEnemyBase + i;
            Rigidbody2D erb = scene.NewRigidbody(en, PB2.BodyDynamic);
            erb.GravityScale = Level.Kind(kind, Level.KGravityScale);
            erb.LinearDamping = 0f;
            erb.FreezeRotation = true;
            erb.CanSleep = false;
            scene.Finish(erb.Self);
            MakeCapsule(scene, en, Level.Kind(kind, Level.KWidth), Level.Kind(kind, Level.KHeight));
            EnemyScript es = Scripts.AddEnemyScript(en);
            es.Index = i;
            Shared.RegisterEnemy(i, en, kind);
        }

        // the scene's trap tiles: solid to stand against, and Traps.cs hurts and respawns whoever touches them
        for (int i = 0; i < Level.HazardCount; i++)
            MakeBox(scene, Level.Hazard(i, 0) + Level.Hazard(i, 2) * 0.5f, Level.Hazard(i, 1) + Level.Hazard(i, 3) * 0.5f,
                    Level.Hazard(i, 2), Level.Hazard(i, 3), Layers.Ground, Shared.TagHazard, false);

        Node portal = MakeBox(scene, Level.PortalX(), Level.PortalY(), Cfg.PortalW, Cfg.PortalH, Layers.Goal, Shared.TagPortal, true);
        Scripts.AddPortalScript(portal);

        Node player = scene.NewNode(null);
        player.SetPosition(Level.SpawnX(), Level.SpawnY());
        player.Layer = Layers.Player;
        player.Tag = Shared.TagPlayer;
        Rigidbody2D rb = scene.NewRigidbody(player, PB2.BodyDynamic);
        rb.GravityScale = Cfg.PlayerGravityScale;
        rb.LinearDamping = Cfg.PlayerDrag;
        rb.FreezeRotation = true;
        rb.IsBullet = true;
        rb.CanSleep = false;
        scene.Finish(rb.Self);
        MakeCapsule(scene, player, Cfg.PlayerW, Cfg.PlayerH);
        Scripts.AddPlayerScript(player);
        if (withBot) Scripts.AddBotScript(player);
        return player;
    }
}

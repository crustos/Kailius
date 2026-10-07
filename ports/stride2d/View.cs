using System;
using Stride2D;
using Stride2D.Native.Gfx2D;

// Draws the world: the Kailius art from the atlas as textured quads (ground cut into 32 px tiles, the adventurer, slimes,
// coins and the portal, animated by a frame counter), a sky gradient behind, and the health bar and coin count on top.
static class View
{
    const float ViewHalfHeight = 7f;
    const float Pixel = 1f / 32f;                 // the art is 32 pixels per unit
    const int MaxQuads = 4096;

    static float[] quads;                         // atlas quads: 6 vertices each
    static float[] sky;
    static float[] hud;
    static float[] lastX;                         // each enemy's x last frame, to know which way it faces
    static float[] facing;
    static int vertexCount;
    static int hudCount;
    static int texture;
    static int tick;
    static int deathsSeen;
    static int deathBanner;
    static float playerFacing;
    static float viewLeft;
    static float viewRight;
    static float viewBottom;
    static float viewTop;

    public static void Init()
    {
        Atlas.Init();
        byte[] pixels = Atlas.Pixels();
        texture = GFX.Texture(Atlas.Width, Atlas.Height, GFX.FilterNearest, pixels);
        quads = new float[MaxQuads * 6 * GFX.MeshVertexFloats];
        sky = new float[6 * GFX.MeshVertexFloats];
        hud = new float[(Level.EnemyCount * 2 + 64) * GFX.SpriteFloats];
        lastX = new float[Level.EnemyCount + 1];
        facing = new float[Level.EnemyCount + 1];
        playerFacing = 1f;
        deathsSeen = 0;
        Text.Init();
    }

    static void Vert(float[] a, int n, float x, float y, float u, float v, float r, float g, float b, float al)
    {
        int o = n * GFX.MeshVertexFloats;
        a[o] = x; a[o + 1] = y; a[o + 2] = u; a[o + 3] = v;
        a[o + 4] = r; a[o + 5] = g; a[o + 6] = b; a[o + 7] = al;
    }

    static void Set(float[] a, int i, float v) { a[i] = v; }
    static float Get(float[] a, int i) { return a[i]; }

    // One textured rectangle: world corners (x0, y0) bottom left to (x1, y1) top right; u0,v0 is the picture's top left.
    static void Quad(float x0, float y0, float x1, float y1, float u0, float v0, float u1, float v1)
    {
        if (vertexCount + 6 > MaxQuads * 6) return;
        if (x1 < viewLeft || x0 > viewRight || y1 < viewBottom || y0 > viewTop) return;
        int n = vertexCount;
        Vert(quads, n, x0, y0, u0, v1, 1f, 1f, 1f, 1f);
        Vert(quads, n + 1, x1, y0, u1, v1, 1f, 1f, 1f, 1f);
        Vert(quads, n + 2, x1, y1, u1, v0, 1f, 1f, 1f, 1f);
        Vert(quads, n + 3, x0, y0, u0, v1, 1f, 1f, 1f, 1f);
        Vert(quads, n + 4, x1, y1, u1, v0, 1f, 1f, 1f, 1f);
        Vert(quads, n + 5, x0, y1, u0, v0, 1f, 1f, 1f, 1f);
        vertexCount += 6;
    }

    // A whole sprite frame, its bottom centre at (x, bottom); mirrored when flip.
    static void Frame(int id, float x, float bottom, bool flip)
    {
        float w = Atlas.Info(id, 4) * Pixel * Atlas.Info(id, 6);
        float h = Atlas.Info(id, 5) * Pixel * Atlas.Info(id, 6);
        float u0 = Atlas.Info(id, 0);
        float u1 = Atlas.Info(id, 2);
        if (flip)
        {
            float t = u0;
            u0 = u1;
            u1 = t;
        }
        Quad(x - w * 0.5f, bottom, x + w * 0.5f, bottom + h, u0, Atlas.Info(id, 1), u1, Atlas.Info(id, 3));
    }

    // A whole sprite frame centred on (cx, cy): how Unity places a sprite with its pivot in the middle.
    static void Centred(int id, float cx, float cy)
    {
        float w = Atlas.Info(id, 4) * Pixel * Atlas.Info(id, 6);
        float h = Atlas.Info(id, 5) * Pixel * Atlas.Info(id, 6);
        Quad(cx - w * 0.5f, cy - h * 0.5f, cx + w * 0.5f, cy + h * 0.5f, Atlas.Info(id, 0), Atlas.Info(id, 1), Atlas.Info(id, 2), Atlas.Info(id, 3));
    }

    // One ground tile (0..8: row from the top times three plus column), maybe only its left part and bottom part when the cell is cut short.
    static void Tile(int index, float x, float y, float w, float h)
    {
        int id = Atlas.Tile0 + index;
        float u0 = Atlas.Info(id, 0);
        float v0 = Atlas.Info(id, 1);
        float u1 = Atlas.Info(id, 2);
        float v1 = Atlas.Info(id, 3);
        // a cell shorter than a unit shows the top of the tile, a narrower one its left part
        u1 = u0 + (u1 - u0) * w;
        v1 = v0 + (v1 - v0) * h;
        Quad(x, y + 1f - h, x + w, y + 1f, u0, v0, u1, v1);
    }

    static void Ground(float rx, float ry, float rw, float rh)
    {
        if (rx > viewRight || rx + rw < viewLeft || ry > viewTop || ry + rh < viewBottom) return;
        int cols = (int)MathF.Ceiling(rw - 0.001f);
        int rows = (int)MathF.Ceiling(rh - 0.001f);
        int c0 = (int)MathF.Floor(viewLeft - rx);
        if (c0 < 0) c0 = 0;
        int r0 = (int)MathF.Floor(ry + rh - viewTop);      // rows count down from the top edge
        if (r0 < 0) r0 = 0;
        for (int r = r0; r < rows; r++)
        {
            float top = ry + rh - r;                       // row r counts down from the top edge
            if (top - 1f > viewTop) continue;
            if (top < viewBottom) break;
            float h = 1f;
            if (top - ry < 1f) h = top - ry;
            if (h < 0.001f) continue;
            // rows from the top: 0 is the grass; a one-row platform is all grass top
            int tr = 1;
            if (rows <= 1) tr = 0;
            else if (r == rows - 1) tr = 2;
            else if (r == 0) tr = 0;
            for (int c = c0; c < cols; c++)
            {
                float x = rx + c;
                if (x > viewRight) break;
                float w = 1f;
                if (rx + rw - x < 1f) w = rx + rw - x;
                int tc = 1;
                if (cols > 1)
                {
                    if (c == 0) tc = 0;
                    else if (c == cols - 1) tc = 2;
                }
                Tile(tr * 3 + tc, x, top - 1f + (1f - h), w, h);
            }
        }
    }

    // One frame centred on the player; returns what GFX.End returns (0 once the window is closed).
    public static int Draw(Node player)
    {
        tick++;
        float cx = player.WorldX();
        float cy = player.WorldY() + 1.5f;
        float halfW = ViewHalfHeight * 16f / 9f;
        GFX.Camera(cx, cy, ViewHalfHeight, 0.45f, 0.70f, 0.92f);
        viewLeft = cx - halfW - 1f;
        viewRight = cx + halfW + 1f;
        viewBottom = cy - ViewHalfHeight - 1f;
        viewTop = cy + ViewHalfHeight + 1f;
        vertexCount = 0;

        // sky: a gradient over the whole view
        Vert(sky, 0, cx - halfW, cy - ViewHalfHeight, 0f, 0f, 0.80f, 0.91f, 1f, 1f);
        Vert(sky, 1, cx + halfW, cy - ViewHalfHeight, 0f, 0f, 0.80f, 0.91f, 1f, 1f);
        Vert(sky, 2, cx + halfW, cy + ViewHalfHeight, 0f, 0f, 0.36f, 0.62f, 0.95f, 1f);
        Vert(sky, 3, cx - halfW, cy - ViewHalfHeight, 0f, 0f, 0.80f, 0.91f, 1f, 1f);
        Vert(sky, 4, cx + halfW, cy + ViewHalfHeight, 0f, 0f, 0.36f, 0.62f, 0.95f, 1f);
        Vert(sky, 5, cx - halfW, cy + ViewHalfHeight, 0f, 0f, 0.36f, 0.62f, 0.95f, 1f);

        for (int i = 0; i < Level.SolidCount; i++)
            Ground(Level.Solid(i, 0), Level.Solid(i, 1), Level.Solid(i, 2), Level.Solid(i, 3));

        for (int i = 0; i < Level.HazardTileCount; i++)
            Centred((int)Level.HazardTile(i, 2), Level.HazardTile(i, 0), Level.HazardTile(i, 1));

        for (int i = 0; i < Level.TorchCount; i++)
        {
            float tx = Level.Torch(i, 0);
            float ty = Level.Torch(i, 1);
            Centred(Atlas.TorchStick0, tx + Cfg.TorchStickX, ty + Cfg.TorchStickY);
            int flicker = (int)((float)tick * Cfg.TorchFps / 60f) + i * 3;
            Centred(Atlas.TorchFlame0 + flicker % Atlas.TorchFlameCount, tx + Cfg.TorchFlameX, ty + Cfg.TorchFlameY);
        }

        Frame(Atlas.Portal0 + (tick / 10) % 4, Level.PortalX(), Level.PortalY() - Cfg.PortalH * 0.5f, false);

        for (int i = 0; i < Level.CoinCount; i++)
            if (!Shared.CoinTaken(i))
                Frame(Atlas.Coin0 + ((tick / 6) + i) % 8, Level.Coin(i, 0), Level.Coin(i, 1) - 0.36f, false);

        hudCount = 0;
        for (int i = 0; i < Shared.EnemyTotal(); i++)
            if (Shared.EnemyAlive(i))
            {
                Node en = Shared.EnemyNode(i);
                int kind = Shared.EnemyKind(i);
                float ex = en.WorldX();
                float dx = ex - Get(lastX, i);
                if (dx > 0.002f) Set(facing, i, 1f);
                else if (dx < -0.002f) Set(facing, i, -1f);
                Set(lastX, i, ex);
                int first = (int)Level.Kind(kind, Level.KFrame0);
                int frames = (int)Level.Kind(kind, Level.KFrameCount);
                int step = (int)((float)tick * Level.Kind(kind, Level.KFps) / 60f);
                float height = Level.Kind(kind, Level.KHeight);
                bool flip = Get(facing, i) < 0f;
                // a boss turns to face the player (Boss.LookAtPlayer); its art looks left, the patrols' look right
                if (Shared.EnemyIsBoss(i)) flip = player.WorldX() > ex;
                Frame(first + step % frames, ex, en.WorldY() - height * 0.5f, flip);

                float maxHealth = Level.Kind(kind, Level.KHealth);
                float left01 = Shared.EnemyHealth(i) / maxHealth;
                if (left01 < 1f)
                {
                    float barY = en.WorldY() + height * 0.5f + 0.35f;
                    Bar(ex, barY, 0.6f, 0.07f, 0.12f, 0.12f, 0.12f, 0.85f, GFX.ShapeBox, 1);
                    Bar(ex - 0.6f + 0.6f * left01, barY, 0.6f * left01, 0.07f, 0.85f, 0.2f, 0.2f, 1f, GFX.ShapeBox, 2);
                }
            }

        float px = player.WorldX();
        float py = player.WorldY();
        if (InputState.Move > 0.1f) playerFacing = 1f;
        else if (InputState.Move < -0.1f) playerFacing = -1f;
        int pose = Atlas.PlayerIdle0;
        if (!Shared.PlayerGrounded)
        {
            float vy = Shared.PlayerVy;
            int k = 3;
            if (vy > 3f) k = 0;
            else if (vy > 0f) k = 1;
            else if (vy > -3f) k = 2;
            pose = Atlas.PlayerJump0 + k;
        }
        else if (InputState.Move > 0.1f || InputState.Move < -0.1f)
        {
            pose = Atlas.PlayerWalk0 + (tick / 5) % 6;
        }
        Frame(pose, px, py - Cfg.PlayerH * 0.5f, playerFacing < 0f);

        // health bar pinned to the top left of the view (flat shapes through the sprite batch)
        float left = cx - halfW + 0.4f;
        float top = cy + ViewHalfHeight - 0.5f;
        float full = 4f;
        float frac = (float)Shared.PlayerHealth / (float)Cfg.MaxHealth;
        if (frac < 0f) frac = 0f;
        Bar(left + full * 0.5f, top, full * 0.5f, 0.2f, 0.12f, 0.12f, 0.12f, 0.8f, GFX.ShapeBox, 1);
        Bar(left + full * frac * 0.5f, top, full * frac * 0.5f, 0.2f, 0.85f, 0.2f, 0.2f, 1f, GFX.ShapeBox, 2);

        // text
        Text.Begin(cx, cy, halfW, ViewHalfHeight, Game.Width, Game.Height);
        Text.Print("HP " + Shared.PlayerHealth + "/" + Cfg.MaxHealth, 180f, 25f, false, 1f, 1f, 1f);
        Text.Print("Score " + Shared.Score + "    Coins " + Shared.Coins + "/" + Shared.CoinTotal() + "    Kills " + Shared.Kills + "/" + Shared.EnemyTotal(), 12f, 56f, false, 1f, 0.9f, 0.4f);
        if (Shared.Deaths > deathsSeen)
        {
            deathsSeen = Shared.Deaths;
            deathBanner = 100;
        }
        if (deathBanner > 0)
        {
            deathBanner--;
            Text.PrintCentred("You died", 150f, true, 1f, 0.35f, 0.3f);
        }
        if (Shared.Won)
        {
            Text.PrintCentred("You reached the portal!", 240f, true, 1f, 1f, 1f);
            Text.PrintCentred("Score " + Shared.Score + "     Esc to quit", 290f, false, 1f, 0.9f, 0.4f);
        }
        else if (!InputState.Human)
        {
            Text.PrintCentred("The bot is playing. Press Left/Right or A/D to take over.", (float)Game.Height - 24f, false, 1f, 1f, 1f);
        }

        GFX.Begin();
        GFX.Triangles(sky, 6, 0);
        GFX.Triangles(quads, vertexCount, texture);
        GFX.Sprites(hud, hudCount);
        Text.Draw();
        return GFX.End();
    }

    static void Bar(float x, float y, float hw, float hh, float r, float g, float b, float a, int shape, int layer)
    {
        int o = hudCount * GFX.SpriteFloats;
        hud[o] = x; hud[o + 1] = y; hud[o + 2] = hw; hud[o + 3] = hh; hud[o + 4] = 0f;
        hud[o + 5] = r; hud[o + 6] = g; hud[o + 7] = b; hud[o + 8] = a;
        hud[o + 9] = (float)shape; hud[o + 10] = (float)layer; hud[o + 11] = 0f;
        hudCount++;
    }
}

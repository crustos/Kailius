using System;
using Stride2D;
using Stride2D.Native.Gfx2D;

// Kailius mini on Stride2D: a window with the keyboard and the sprite renderer. The bot plays until a key is pressed.
// With no display the renderer draws offscreen (software), the bot plays, and the run ends at the portal or after MaxSteps.
static class Game
{
    public const int Width = 960;
    public const int Height = 540;
    const int MaxSteps = 6000;           // headless limit, in fixed steps
    static Scene2D scene;
    static Node player;
    static float pending;                // time not yet simulated
    static int steps;

    static int Milli(float v) { return (int)(v * 1000f); }

    // Called once. Returns 0 when it is ready.
    public static int Init()
    {
        if (GFX.Init(Width, Height) == 0) return 1;
        Scripts.Init();
        scene = new Scene2D();
        player = World.Build(scene, true);
        View.Init();
        InputState.Init();
        return 0;
    }

    // One drawn frame (1/60 s of game time). Returns 0 when the game should stop.
    public static int Step()
    {
        InputState.Poll();
        pending += 1f / 60f;
        while (pending >= Cfg.Dt - 0.0001f)
        {
            if (!Shared.Won) Scripts.Tick(scene, Cfg.Dt);        // the portal ends the run: the world stops
            pending -= Cfg.Dt;
            steps++;
        }
        int open = View.Draw(player);
        if (InputState.Quit) return 0;
        return open;
    }

    public static int Main()
    {
        if (Init() != 0)
        {
            Console.WriteLine("no renderer");
            return 1;
        }
        Console.WriteLine("backend " + GFX.Backend());
        int frame = 0;
        // a bot run ends at the portal; a person's keeps the window up (and the banner) until Esc
        while (Step() != 0 && (!Shared.Won || InputState.Human) && steps < MaxSteps)
        {
            if (frame % 60 == 0)
                Console.WriteLine("t=" + (frame / 60) + "s x*1000=" + Milli(player.WorldX()) + " y*1000=" + Milli(player.WorldY()) + " score=" + Shared.Score + " hp=" + Shared.PlayerHealth);
            frame++;
        }
        int won = 0;
        if (Shared.Won) won = 1;
        Console.WriteLine("won=" + won + " steps=" + steps + " deaths=" + Shared.Deaths + " coins=" + Shared.Coins + "/" + Shared.CoinTotal() + " score=" + Shared.Score + " kills=" + Shared.Kills + "/" + Shared.EnemyTotal());
        Console.WriteLine("frame hash " + GFX.FrameHash());
        GFX.Shutdown();
        return won == 1 ? 0 : 1;
    }
}

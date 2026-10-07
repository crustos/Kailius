using System;
using Prowl.Core2D;
using Prowl.Native.Box2D;

// Builds the mini level from the generated Level and Cfg and runs it headless, driven by BotScript.
// Prints a line a second and a summary; the exit code is 0 when the portal was reached.
static class Game
{
    const int MaxFrames = 6000;

    static int Milli(float v) { return (int)(v * 1000f); }

    public static int Main()
    {
        Scripts.Init();
        Scene2D scene = new Scene2D();
        Node player = World.Build(scene, true);

        int wonFrame = -1;
        float maxX = Level.SpawnX();
        for (int frame = 0; frame < MaxFrames && !Shared.Won; frame++)
        {
            Scripts.Tick(scene, Cfg.Dt);
            float px = player.WorldX();
            float py = player.WorldY();
            if (px > maxX) maxX = px;
            if (frame % 100 == 0)
                Console.WriteLine("t=" + (frame / 100) + "s x*1000=" + Milli(px) + " y*1000=" + Milli(py) + " score=" + Shared.Score + " hp=" + Shared.PlayerHealth);
            if (Shared.Won) wonFrame = frame;
        }
        int won = 0;
        if (Shared.Won) won = 1;
        Console.WriteLine("won=" + won + " frame=" + wonFrame + " deaths=" + Shared.Deaths + " coins=" + Shared.Coins + "/" + Shared.CoinTotal() + " score=" + Shared.Score + " kills=" + Shared.Kills + "/" + Shared.EnemyTotal() + " hp=" + Shared.PlayerHealth);
        Console.WriteLine("max x*1000=" + Milli(maxX) + " end x*1000=" + Milli(player.WorldX()) + " y*1000=" + Milli(player.WorldY()));
        return won == 1 ? 0 : 1;
    }
}

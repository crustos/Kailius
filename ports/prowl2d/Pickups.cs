using System;
using Prowl.Core2D;

// Coin: port of Coin.OnTriggerEnter2D.
[Script, MaxInstances(64)]
class CoinScript
{
    public Component Self;
    public int Index;
    public void OnTriggerEnter2D(Collider2D other)
    {
        if (other.Self.Node.Tag != Shared.TagPlayer) return;
        Shared.CollectCoin(Index);
    }
}

// Portal: port of Portal.OnTriggerEnter2D. The original loads the next scene; here reaching it wins.
[Script, MaxInstances(1)]
class PortalScript
{
    public Component Self;
    public void OnTriggerEnter2D(Collider2D other)
    {
        if (other.Self.Node.Tag == Shared.TagPlayer) Shared.Won = true;
    }
}

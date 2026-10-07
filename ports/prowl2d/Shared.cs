using System;
using Prowl.Core2D;

// State the scripts share. It never names a script type, so the translator has no dependency
// cycle to order, and the static arrays are only touched through helpers that take the array as a
// parameter (the C# subset cannot subscript a static array field directly).
static class Shared
{
    public const int TagPlayer = 1;
    public const int TagGround = 2;
    public const int TagCoin = 3;
    public const int TagPortal = 4;
    public const int TagHazard = 5;
    public const int TagEnemyBase = 100;       // enemy i has Tag TagEnemyBase + i

    public static bool Won;
    public static int Deaths;
    public static int Score;
    public static int Coins;
    public static int Kills;
    public static int PlayerHealth;
    public static int TrapHits;
    public static bool PlayerGrounded;         // published by PlayerScript for the bot
    public static float PlayerVy;
    public static Node PlayerNode;

    // a hit from an enemy's weapon, applied by PlayerScript on its next step
    public static int PendingDamage;
    public static float PendingFromX;

    static Node[] coinNodes;
    static bool[] coinTaken;
    static int coinCount;
    static Node[] enemyNodes;
    static bool[] enemyAlive;
    static float[] enemyHealth;
    static float[] enemyInvulnerableUntil;
    static int[] enemyKind;
    static int enemyCount;

    static void SetB(bool[] a, int i, bool v) { a[i] = v; }
    static bool GetB(bool[] a, int i) { return a[i]; }
    static void SetN(Node[] a, int i, Node v) { a[i] = v; }
    static Node GetN(Node[] a, int i) { return a[i]; }
    static void SetF(float[] a, int i, float v) { a[i] = v; }
    static float GetF(float[] a, int i) { return a[i]; }
    static void SetI(int[] a, int i, int v) { a[i] = v; }
    static int GetI(int[] a, int i) { return a[i]; }

    // ---- coins ----
    public static void InitCoins(int count)
    {
        coinCount = count;
        coinNodes = new Node[count + 1];
        coinTaken = new bool[count + 1];
    }

    public static void RegisterCoin(int i, Node n) { SetN(coinNodes, i, n); }
    public static int CoinTotal() { return coinCount; }
    public static bool CoinTaken(int i) { return GetB(coinTaken, i); }

    // Port of Coin.OnTriggerEnter2D: +10 score, +1 coin, and the coin goes away.
    public static void CollectCoin(int i)
    {
        if (GetB(coinTaken, i)) return;
        SetB(coinTaken, i, true);
        Coins++;
        Score += Cfg.CoinScore;
        Scene2D.Current.Destroy(GetN(coinNodes, i));
    }

    // ---- enemies ----
    public static void InitEnemies(int count)
    {
        enemyCount = count;
        enemyNodes = new Node[count + 1];
        enemyAlive = new bool[count + 1];
        enemyHealth = new float[count + 1];
        enemyInvulnerableUntil = new float[count + 1];
        enemyKind = new int[count + 1];
    }

    public static void RegisterEnemy(int i, Node n, int kind)
    {
        SetN(enemyNodes, i, n);
        SetB(enemyAlive, i, true);
        SetI(enemyKind, i, kind);
        SetF(enemyHealth, i, Level.Kind(kind, Level.KHealth));
    }

    public static int EnemyTotal() { return enemyCount; }
    public static bool EnemyAlive(int i) { return GetB(enemyAlive, i); }
    public static Node EnemyNode(int i) { return GetN(enemyNodes, i); }
    public static int EnemyKind(int i) { return GetI(enemyKind, i); }
    public static float EnemyHealth(int i) { return GetF(enemyHealth, i); }
    public static bool EnemyIsBoss(int i) { return Level.Kind(GetI(enemyKind, i), Level.KBehaviour) > 0.5f; }

    // Port of Enemy.Die: the enemy is removed. (The score is added by whoever killed it.)
    public static void KillEnemy(int i)
    {
        if (!GetB(enemyAlive, i)) return;
        SetB(enemyAlive, i, false);
        Scene2D.Current.Destroy(GetN(enemyNodes, i));
    }

    // Port of Enemy.TakeDamage for the one attack the mini has (landing on it). A hit is ignored while the
    // enemy is still recovering from the last one. Returns true when this hit killed it.
    public static bool StompEnemy(int i, float now)
    {
        if (!GetB(enemyAlive, i)) return false;
        if (now < GetF(enemyInvulnerableUntil, i)) return false;
        SetF(enemyInvulnerableUntil, i, now + Cfg.BossInvulnerable);
        float left = GetF(enemyHealth, i) - Cfg.StompDamage;
        SetF(enemyHealth, i, left);
        if (left > 0f) return false;
        KillEnemy(i);
        return true;
    }

    // A weapon hit on the player (Stats.takeDamage); PlayerScript applies it on its next step.
    public static void HurtPlayer(int damage, float fromX)
    {
        PendingDamage += damage;
        PendingFromX = fromX;
    }

    // Is a living enemy within `range` ahead of (x, y) in direction dir, at about the same height?
    public static bool EnemyNear(float x, float y, float dir, float range)
    {
        for (int i = 0; i < enemyCount; i++)
        {
            if (!GetB(enemyAlive, i)) continue;
            Node n = GetN(enemyNodes, i);
            float dx = (n.WorldX() - x) * dir;
            float dy = n.WorldY() - y;
            if (dx > 0f && dx < range && dy > -1.2f && dy < 1.2f) return true;
        }
        return false;
    }
}

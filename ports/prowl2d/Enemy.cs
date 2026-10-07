using System;
using Prowl.Core2D;
using Prowl.Native.Box2D;

// Every enemy of the game, from the numbers in its prefab (Level.Kind): speed, health, collider, and which of the
// two behaviours it has.
//  patrol  Patrol.cs: walk, and turn around at a ledge or a wall (the original raycasts down from a groundDetection
//          child; here the same idea is two small probes in front of the body).
//  boss    Boss.cs + BossRun.cs + BossWeapon.cs: face the player, run at them along the ground while they are within
//          BossSense, stop in attack range, and after a wind-up hit them if still in weapon range, then cool down.
[Script(Order = 5), MaxInstances(32)]
class EnemyScript
{
    public Component Self;
    public int Index;
    float dir;
    Rigidbody2D body;
    Node node;
    Scene2D scene;
    uint groundMask;
    bool ready;
    bool boss;
    float speed;
    float halfW;
    float halfH;
    float attackRange;
    float weaponRange;
    int damage;
    float attackStart;
    float nextAttack;

    public void Start()
    {
        scene = Scene2D.Current;
        node = Self.Node;
        body = scene.Find(node, ComponentKind.Rigidbody2D).Body;
        groundMask = 1u << Layers.Ground;
        dir = 1f;
        attackStart = -1f;
    }

    bool Probe(float cx, float cy, float halfW2, float halfH2)
    {
        return scene.Physics.Sim.OverlapBox(cx, cy, halfW2, halfH2, 0f, groundMask, false) > 0;
    }

    // Index is set after the script is added, so the kind is read on the first step.
    void Setup()
    {
        int kind = Shared.EnemyKind(Index);
        boss = Shared.EnemyIsBoss(Index);
        speed = Level.Kind(kind, Level.KSpeed);
        halfW = Level.Kind(kind, Level.KWidth) * 0.5f;
        halfH = Level.Kind(kind, Level.KHeight) * 0.5f;
        attackRange = Level.Kind(kind, Level.KAttackRange);
        weaponRange = Level.Kind(kind, Level.KWeaponRange);
        damage = (int)Level.Kind(kind, Level.KAttackDamage);
        ready = true;
    }

    public void FixedUpdate()
    {
        if (!Shared.EnemyAlive(Index)) return;
        if (!ready) Setup();
        if (boss) Chase();
        else Patrol();
    }

    void Patrol()
    {
        float x = node.WorldX();
        float y = node.WorldY();
        // only decide to turn while standing, so an enemy still falling into place does not flip every step
        bool onGround = Probe(x, y - halfH - 0.05f, halfW * 0.8f, 0.05f);
        if (onGround)
        {
            float probeH = Cfg.LedgeProbe * 0.5f;
            bool groundAhead = Probe(x + dir * (halfW + 0.1f), y - halfH - probeH, 0.05f, probeH);
            bool wallAhead = Probe(x + dir * (halfW + 0.08f), y, 0.05f, halfH * 0.8f);
            if (!groundAhead || wallAhead) dir = -dir;
        }
        body.SetVelocity(dir * speed, body.VelocityY());
    }

    void Chase()
    {
        Node pn = Shared.PlayerNode;
        if (pn == null) return;
        float now = scene.FixedIndex * Cfg.Dt;
        float x = node.WorldX();
        float dx = pn.WorldX() - x;
        float dy = pn.WorldY() - node.WorldY();
        float dist = MathF.Sqrt(dx * dx + dy * dy);
        if (dx > 0.05f) dir = 1f;
        else if (dx < -0.05f) dir = -1f;

        float vx = 0f;
        if (dist <= Cfg.BossSense && dist > attackRange) vx = dir * speed;

        if (attackStart < 0f && dist <= attackRange && now >= nextAttack) attackStart = now;
        if (attackStart >= 0f)
        {
            vx = 0f;
            if (now >= attackStart + Cfg.BossWindup)
            {
                // the weapon hits whoever is within its range when the swing lands
                if (dist <= weaponRange + Cfg.PlayerW * 0.5f) Shared.HurtPlayer(damage, x);
                attackStart = -1f;
                nextAttack = now + Cfg.BossCooldown;
            }
        }
        body.SetVelocity(vx, body.VelocityY());
    }
}

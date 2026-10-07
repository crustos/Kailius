using System;
using Prowl.Core2D;
using Prowl.Native.Box2D;

// Port of Kailius PlayerController: move, jump, one extra jump in the air, contact damage from a
// patrol with a cooldown, and respawn. The numbers come from Cfg (read from Player.prefab).
// Added for the mini version: landing on an enemy hurts it (a slime dies at once, a boss takes five), where the original uses a melee attack.
[Script(Order = 10), MaxInstances(1)]
class PlayerScript
{
    public Component Self;
    public int Health;
    bool grounded;
    bool canDoubleJump;
    float damageReadyAt;
    float knockbackUntil;
    float knockbackVx;
    Rigidbody2D body;
    Node node;
    Scene2D scene;
    uint groundMask;

    public void Start()
    {
        scene = Scene2D.Current;
        node = Self.Node;
        Shared.PlayerNode = node;
        body = scene.Find(node, ComponentKind.Rigidbody2D).Body;
        groundMask = 1u << Layers.Ground;
        Health = Cfg.MaxHealth;
        Shared.PlayerHealth = Health;
        canDoubleJump = true;
    }

    public void FixedUpdate()
    {
        float now = scene.FixedIndex * Cfg.Dt;
        float x = node.WorldX();
        float y = node.WorldY();
        if (y < Cfg.KillPlaneY)
        {
            Respawn();
            return;
        }

        if (Shared.PendingDamage > 0)
        {
            // a boss's weapon landed (Stats.takeDamage): no cooldown of ours, the attacker has its own
            Health -= Shared.PendingDamage;
            Shared.PendingDamage = 0;
            float awayFrom = 1f;
            if (x < Shared.PendingFromX) awayFrom = -1f;
            knockbackVx = awayFrom * Cfg.KnockbackSpeed;
            knockbackUntil = now + 0.2f;
            body.SetVelocity(knockbackVx, Cfg.KnockbackLift);
            Shared.PlayerHealth = Health;
            if (Health <= 0)
            {
                Respawn();
                return;
            }
        }

        float halfW = Cfg.PlayerW * 0.5f;
        float halfH = Cfg.PlayerH * 0.5f;
        float vy = body.VelocityY();

        // standing on something: a thin probe just under the feet (the physics reports no ground flag)
        grounded = scene.Physics.Sim.OverlapBox(x, y - halfH - 0.05f, halfW * 0.9f, 0.05f, 0f, groundMask, false) > 0;
        bool landed = grounded && vy <= 0.5f;
        if (landed) canDoubleJump = true;

        float vx = InputState.Move * Cfg.MoveSpeed;
        if (now < knockbackUntil) vx = knockbackVx;

        if (InputState.JumpPressed)
        {
            InputState.JumpPressed = false;
            if (landed)
            {
                vy = Cfg.JumpSpeed;
            }
            else if (canDoubleJump)
            {
                canDoubleJump = false;
                vy = Cfg.JumpSpeed;
            }
        }

        body.SetVelocity(vx, vy);
        Shared.PlayerGrounded = landed;
        Shared.PlayerVy = vy;
        Shared.PlayerHealth = Health;
    }

    public void OnCollisionBegin2D(Collision2D hit)
    {
        Node other = hit.Other.Self.Node;
        int tag = other.Tag;
        if (tag == Shared.TagHazard)
        {
            // Traps.OnCollisionEnter2D: true damage, then back to the respawn point if still alive
            Shared.TrapHits++;
            Health -= Cfg.TrapDamage;
            Shared.PlayerHealth = Health;
            if (Health <= 0)
            {
                Respawn();
                return;
            }
            node.SetPosition(Level.RespawnX(), Level.RespawnY());
            body.SetVelocity(0f, 0f);
            return;
        }
        if (tag < Shared.TagEnemyBase) return;
        int index = tag - Shared.TagEnemyBase;
        if (!Shared.EnemyAlive(index)) return;
        float now = scene.FixedIndex * Cfg.Dt;

        // feet above the enemy's middle means we came down on it
        bool stomp = node.WorldY() - Cfg.PlayerH * 0.5f >= other.WorldY();
        if (stomp)
        {
            bool killed = Shared.StompEnemy(index, now);
            if (killed)
            {
                Shared.Score += Cfg.EnemyScore;
                Shared.Kills++;
            }
            canDoubleJump = true;
            body.SetVelocity(body.VelocityX(), Cfg.JumpSpeed * 0.75f);
            return;
        }

        // only the "Patrols" hurt by touch; a boss hurts with its weapon
        if (Shared.EnemyIsBoss(index)) return;
        if (now < damageReadyAt) return;
        damageReadyAt = now + Cfg.DamageCooldown;
        Health -= Cfg.ContactDamage;
        float away = 1f;
        if (node.WorldX() < other.WorldX()) away = -1f;
        knockbackVx = away * Cfg.KnockbackSpeed;
        knockbackUntil = now + 0.2f;
        body.SetVelocity(knockbackVx, Cfg.KnockbackLift);
        if (Health <= 0) Respawn();
    }

    void Respawn()
    {
        Shared.Deaths++;
        Console.WriteLine("death " + Shared.Deaths + " step=" + scene.FixedIndex + " x*1000=" + (int)(node.WorldX() * 1000f) + " y*1000=" + (int)(node.WorldY() * 1000f));
        Health = Cfg.MaxHealth;
        node.SetPosition(Level.SpawnX(), Level.SpawnY());
        body.SetVelocity(0f, 0f);
        knockbackUntil = 0f;
        canDoubleJump = true;
    }
}

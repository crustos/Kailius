using System;
using Prowl.Core2D;

// Stands in for a keyboard until the engine has input: runs toward the portal and jumps walls,
// gaps and enemies using the same kind of probes the player does. Runs before PlayerScript.
[Script(Order = 0), MaxInstances(1)]
class BotScript
{
    public Component Self;
    Scene2D scene;
    uint groundMask;

    public void Start()
    {
        scene = Scene2D.Current;
        groundMask = 1u << Layers.Ground;
    }

    bool Probe(float cx, float cy, float halfW, float halfH)
    {
        return scene.Physics.Sim.OverlapBox(cx, cy, halfW, halfH, 0f, groundMask, false) > 0;
    }

    public void FixedUpdate()
    {
        if (InputState.Human) return;
        Node pn = Shared.PlayerNode;
        if (pn == null) return;
        float x = pn.WorldX();
        float y = pn.WorldY();
        float halfW = Cfg.PlayerW * 0.5f;
        float halfH = Cfg.PlayerH * 0.5f;

        float dir = 1f;
        if (Level.PortalX() - x < -0.3f) dir = -1f;

        bool jump = false;
        if (Shared.PlayerGrounded)
        {
            bool wallAhead = Probe(x + dir * (halfW + 0.3f), y, 0.2f, halfH * 0.95f);
            bool floorAhead = Probe(x + dir * (halfW + 0.5f), y - halfH - 0.25f, 0.2f, 0.2f);
            if (wallAhead || !floorAhead || Shared.EnemyNear(x, y, dir, 3f)) jump = true;
        }
        else if (Shared.PlayerVy < 0f)
        {
            // coming down with nothing under us: spend the extra jump
            bool floorBelow = Probe(x, y - halfH - 0.8f, halfW, 0.8f);
            if (!floorBelow) jump = true;
        }
        InputState.Move = dir;
        InputState.JumpPressed = jump;
    }
}

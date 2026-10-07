using System;
using Stride2D.Native.Gfx2D;

// The input seam, driven by the window's keyboard. Until a key is pressed the bot plays (so a headless run, which has no
// keys, plays itself); the first movement key hands the game to the person. Arrows or A/D move, Up, W or Space jump,
// Escape quits.
static class InputState
{
    public static float Move;          // -1 .. 1
    public static bool JumpPressed;    // a jump was pressed; PlayerScript clears it
    public static bool Human;          // a person has taken over: BotScript stops writing
    public static bool Quit;

    static int[] ev;
    static bool left;
    static bool right;

    static int Next(int[] a) { return GFX.PollEvent(a); }
    static int At(int[] a, int i) { return a[i]; }

    public static void Init() { ev = new int[5]; }

    // Drains the window's events; call once a frame.
    public static void Poll()
    {
        while (Next(ev) != 0)
        {
            int type = At(ev, 0);
            int key = At(ev, 1);
            bool down = type == 5;
            if (type == 9) Quit = true;
            if (type != 5 && type != 6) continue;
            if (key == 256 && down) Quit = true;
            if (key == 263 || key == 65) left = down;
            else if (key == 262 || key == 68) right = down;
            else if ((key == 265 || key == 87 || key == 32) && down && At(ev, 2) == 0) { JumpPressed = true; Human = true; }
            if (down && (key == 263 || key == 65 || key == 262 || key == 68)) Human = true;
        }
        if (Human)
        {
            float m = 0f;
            if (left) m -= 1f;
            if (right) m += 1f;
            Move = m;
        }
    }
}

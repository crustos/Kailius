// The input seam. Prowl2D has no input yet, so a bot (BotScript) writes these once per fixed step,
// before PlayerScript reads them. When the engine gains a keyboard, only the writer changes.
static class InputState
{
    public static float Move;          // -1 .. 1
    public static bool JumpPressed;    // a jump was pressed this step; PlayerScript clears it
    public static bool Human;          // a person has taken over: BotScript stops writing
}

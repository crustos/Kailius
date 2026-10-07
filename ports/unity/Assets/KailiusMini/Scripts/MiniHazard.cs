using UnityEngine;

namespace KailiusMini
{
    /// <summary>
    /// A trap strip (the scene's trap tilemap). Port of Traps.cs: touching it is true damage, and the player goes
    /// back to the respawn point if still alive. MiniPlayer reads this when it collides with it.
    /// </summary>
    public class MiniHazard : MonoBehaviour
    {
    }
}

using UnityEngine;

namespace KailiusMini
{
    /// <summary>End-of-level portal. Port of Portal.cs, which loads the next scene; the mini game just ends the level.</summary>
    public class MiniPortal : MonoBehaviour
    {
        void OnTriggerEnter2D(Collider2D other)
        {
            if (other.GetComponent<MiniPlayer>() == null) return;
            if (MiniGame.Instance != null) MiniGame.Instance.Complete();
        }
    }
}

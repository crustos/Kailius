using UnityEngine;

namespace KailiusMini
{
    /// <summary>Coin pickup. Port of Coin.cs: +10 score and +1 coin, with a sound.</summary>
    public class MiniPickup : MonoBehaviour
    {
        void OnTriggerEnter2D(Collider2D other)
        {
            if (other.GetComponent<MiniPlayer>() == null) return;
            if (MiniGame.Instance != null) MiniGame.Instance.CollectCoin();
            Destroy(gameObject);
        }
    }
}

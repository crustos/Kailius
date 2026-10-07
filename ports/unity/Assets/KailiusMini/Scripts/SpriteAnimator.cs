using UnityEngine;

namespace KailiusMini
{
    /// <summary>Plays a looping array of sprites on this object's SpriteRenderer.</summary>
    [RequireComponent(typeof(SpriteRenderer))]
    public class SpriteAnimator : MonoBehaviour
    {
        SpriteRenderer sr;
        Sprite[] frames;
        float fps = 10f;
        float time;

        void Awake()
        {
            sr = GetComponent<SpriteRenderer>();
        }

        /// <summary>Start looping these frames. Calling again with the same array keeps the animation running.</summary>
        public void Play(Sprite[] newFrames, float framesPerSecond)
        {
            if (newFrames == frames) return;
            frames = newFrames;
            fps = framesPerSecond;
            time = 0f;
            Apply(0);
        }

        /// <summary>Stop animating and show one sprite.</summary>
        public void Hold(Sprite sprite)
        {
            frames = null;
            if (sprite != null) sr.sprite = sprite;
        }

        void Update()
        {
            if (frames == null || frames.Length < 2) return;
            time += Time.deltaTime * fps;
            Apply((int)time % frames.Length);
        }

        void Apply(int index)
        {
            if (frames != null && frames.Length > 0)
                sr.sprite = frames[Mathf.Clamp(index, 0, frames.Length - 1)];
        }
    }
}

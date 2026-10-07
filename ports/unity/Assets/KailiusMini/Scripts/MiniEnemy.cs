using UnityEngine;

namespace KailiusMini
{
    /// <summary>
    /// Every enemy of the game, from the numbers in its prefab (KindData): speed, health, collider, and which of the
    /// two behaviours it has.
    ///   patrol  Patrol.cs: walk, and turn around at a ledge or a wall.
    ///   boss    Boss.cs + BossRun.cs + BossWeapon.cs: face the player, run at them while they are within BossSense,
    ///           stop in attack range, and after a wind-up hit them if still in weapon range, then cool down.
    /// Added for the mini: landing on an enemy hurts it (a slime dies at once, a boss takes five), where the original
    /// uses a melee attack.
    /// </summary>
    [RequireComponent(typeof(Rigidbody2D), typeof(BoxCollider2D))]
    public class MiniEnemy : MonoBehaviour
    {
        public KindData Kind { get; private set; }
        public bool Dead { get; private set; }
        public bool IsBoss { get { return Kind != null && Kind.boss; } }

        Rigidbody2D body;
        BoxCollider2D box;
        SpriteRenderer art;
        Transform barBack;
        Transform barFill;
        float health;
        float invulnerableUntil;
        float attackStart = -1f;
        float nextAttack;
        int direction = 1;

        void Awake()
        {
            body = GetComponent<Rigidbody2D>();
            box = GetComponent<BoxCollider2D>();
        }

        public void Init(KindData kind, SpriteRenderer artRenderer, Sprite whiteSprite)
        {
            Kind = kind;
            health = kind.health;
            art = artRenderer;
            body.gravityScale = kind.gravityScale;

            barBack = MakeBar(whiteSprite, new Color(0.12f, 0.12f, 0.12f, 0.85f), 20);
            barFill = MakeBar(whiteSprite, new Color(0.85f, 0.2f, 0.2f, 1f), 21);
            barBack.gameObject.SetActive(false);
            barFill.gameObject.SetActive(false);
        }

        Transform MakeBar(Sprite white, Color color, int order)
        {
            GameObject go = new GameObject("Bar");
            go.transform.SetParent(transform, false);
            SpriteRenderer sr = go.AddComponent<SpriteRenderer>();
            sr.sprite = white;
            sr.color = color;
            sr.sortingOrder = order;
            return go.transform;
        }

        void FixedUpdate()
        {
            if (Dead || Kind == null) return;
            if (Kind.boss) Chase();
            else Patrol();
        }

        void LateUpdate()
        {
            if (Dead || Kind == null) return;
            float left = Mathf.Clamp01(health / Kind.health);
            bool show = left < 1f;
            barBack.gameObject.SetActive(show);
            barFill.gameObject.SetActive(show);
            if (!show) return;

            float y = Kind.height * 0.5f + 0.35f;
            barBack.localPosition = new Vector3(0f, y, 0f);
            barBack.localScale = new Vector3(1.2f, 0.14f, 1f);
            barFill.localPosition = new Vector3(-0.6f + 0.6f * left, y, 0f);
            barFill.localScale = new Vector3(1.2f * left, 0.14f, 1f);
        }

        // ------------------------------------------------------------------ behaviours

        void Patrol()
        {
            float halfW = Kind.width * 0.5f;
            float halfH = Kind.height * 0.5f;
            Vector2 p = transform.position;

            // only decide to turn while standing, so an enemy still falling into place does not flip every step
            bool onGround = Solid(new Vector2(p.x, p.y - halfH - 0.05f), new Vector2(halfW * 0.8f, 0.05f));
            if (onGround)
            {
                float probe = MiniAssets.Tune("LedgeProbe") * 0.5f;
                bool groundAhead = Solid(new Vector2(p.x + direction * (halfW + 0.1f), p.y - halfH - probe),
                                         new Vector2(0.05f, probe));
                bool wallAhead = Solid(new Vector2(p.x + direction * (halfW + 0.08f), p.y),
                                       new Vector2(0.05f, halfH * 0.8f));
                if (!groundAhead || wallAhead) direction = -direction;
            }
            art.flipX = direction < 0;
            body.velocity = new Vector2(direction * Kind.speed, body.velocity.y);
        }

        void Chase()
        {
            MiniPlayer player = MiniGame.Instance != null ? MiniGame.Instance.Player : null;
            if (player == null) return;

            float now = Time.time;
            Vector2 p = transform.position;
            float dx = player.transform.position.x - p.x;
            float dy = player.transform.position.y - p.y;
            float dist = Mathf.Sqrt(dx * dx + dy * dy);
            if (dx > 0.05f) direction = 1;
            else if (dx < -0.05f) direction = -1;
            art.flipX = player.transform.position.x > p.x;      // a boss's art looks left, the patrols' look right

            float vx = 0f;
            if (dist <= MiniAssets.Tune("BossSense") && dist > Kind.attackRange) vx = direction * Kind.speed;

            if (attackStart < 0f && dist <= Kind.attackRange && now >= nextAttack) attackStart = now;
            if (attackStart >= 0f)
            {
                vx = 0f;
                if (now >= attackStart + MiniAssets.Tune("BossWindup"))
                {
                    // the weapon hits whoever is within its range when the swing lands
                    if (dist <= Kind.weaponRange + MiniAssets.Tune("PlayerW") * 0.5f)
                        player.TakeHit((int)Kind.attackDamage, p.x);
                    attackStart = -1f;
                    nextAttack = now + MiniAssets.Tune("BossCooldown");
                }
            }
            body.velocity = new Vector2(vx, body.velocity.y);
        }

        bool Solid(Vector2 center, Vector2 half)
        {
            Collider2D[] hits = Physics2D.OverlapBoxAll(center, half * 2f, 0f);
            for (int i = 0; i < hits.Length; i++)
            {
                Collider2D hit = hits[i];
                if (hit.isTrigger || hit.gameObject == gameObject) continue;
                if (hit.GetComponent<MiniPlayer>() != null || hit.GetComponent<MiniEnemy>() != null) continue;
                return true;
            }
            return false;
        }

        // ------------------------------------------------------------------ being hit

        /// <summary>Port of Enemy.TakeDamage for the one attack the mini has. Ignored while recovering from the last hit.</summary>
        public bool Stomp()
        {
            if (Dead || Time.time < invulnerableUntil) return false;
            invulnerableUntil = Time.time + MiniAssets.Tune("BossInvulnerable");
            health -= MiniAssets.Tune("StompDamage");
            if (health > 0f) return false;

            Dead = true;
            body.simulated = false;
            if (MiniGame.Instance != null) MiniGame.Instance.Play("slime_death");
            Destroy(gameObject);
            return true;
        }
    }
}

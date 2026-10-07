using UnityEngine;

namespace KailiusMini
{
    /// <summary>
    /// Port of Kailius PlayerController: A/D (or arrows) to move, Space to jump, one extra jump in the air,
    /// contact damage with a cooldown from patrols, true damage from traps, a boss's weapon hit.
    /// Every number comes from level.json (read from Player.prefab, PlayerController.cs and Stats.cs by build.py).
    /// Added for the mini version: landing on an enemy hurts it (the original uses a melee attack).
    /// </summary>
    [RequireComponent(typeof(Rigidbody2D), typeof(BoxCollider2D))]
    public class MiniPlayer : MonoBehaviour
    {
        public int maxHealth;
        public int Health { get; private set; }

        float moveSpeed, jumpSpeed, damageCooldown, knockbackSpeed, knockbackLift, killPlaneY;
        int contactDamage, trapDamage;

        Rigidbody2D body;
        BoxCollider2D box;
        SpriteRenderer sr;
        SpriteAnimator anim;
        Sprite[] idle, walk, jump;
        Vector3 spawn;

        bool grounded;
        bool canDoubleJump;
        bool jumpQueued;
        float moveInput;
        float nextDamageTime;
        float knockbackUntil;
        float knockbackVx;

        void Awake()
        {
            body = GetComponent<Rigidbody2D>();
            box = GetComponent<BoxCollider2D>();
            sr = GetComponentInChildren<SpriteRenderer>();
            anim = GetComponentInChildren<SpriteAnimator>();

            moveSpeed = MiniAssets.Tune("MoveSpeed");
            jumpSpeed = MiniAssets.Tune("JumpSpeed");
            damageCooldown = MiniAssets.Tune("DamageCooldown");
            knockbackSpeed = MiniAssets.Tune("KnockbackSpeed");
            knockbackLift = MiniAssets.Tune("KnockbackLift");
            killPlaneY = MiniAssets.Tune("KillPlaneY");
            contactDamage = (int)MiniAssets.Tune("ContactDamage");
            trapDamage = (int)MiniAssets.Tune("TrapDamage");
            maxHealth = (int)MiniAssets.Tune("MaxHealth");

            idle = MiniAssets.Frames("player_idle", false);
            walk = MiniAssets.Frames("player_walk", false);
            jump = MiniAssets.Frames("player_jump", false);

            spawn = transform.position;
            Health = maxHealth;
            sr.sprite = idle[0];
        }

        void Update()
        {
            moveInput = 0f;
            bool frozen = MiniGame.Instance != null && MiniGame.Instance.LevelComplete;
            if (!frozen)
            {
                if (Input.GetKey(KeyCode.A) || Input.GetKey(KeyCode.LeftArrow)) moveInput -= 1f;
                if (Input.GetKey(KeyCode.D) || Input.GetKey(KeyCode.RightArrow)) moveInput += 1f;
                if (Input.GetKeyDown(KeyCode.Space) || Input.GetKeyDown(KeyCode.W) || Input.GetKeyDown(KeyCode.UpArrow))
                    jumpQueued = true;
            }

            if (moveInput != 0f) sr.flipX = moveInput < 0f;
            if (transform.position.y < killPlaneY) Respawn();
            UpdateAnimation();
        }

        void FixedUpdate()
        {
            grounded = CheckGrounded();
            if (grounded) canDoubleJump = true;

            if (Time.time >= knockbackUntil)
                body.velocity = new Vector2(moveInput * moveSpeed, body.velocity.y);

            if (jumpQueued)
            {
                jumpQueued = false;
                if (grounded)
                {
                    Jump();
                }
                else if (canDoubleJump)
                {
                    canDoubleJump = false;
                    Jump();
                }
            }
        }

        void Jump()
        {
            body.velocity = new Vector2(body.velocity.x, jumpSpeed);
            grounded = false;
            if (MiniGame.Instance != null) MiniGame.Instance.Play("jump");
        }

        bool CheckGrounded()
        {
            if (body.velocity.y > 0.5f) return false;

            Bounds b = box.bounds;
            Vector2 center = new Vector2(b.center.x, b.min.y - 0.05f);
            Vector2 size = new Vector2(b.size.x * 0.9f, 0.1f);
            Collider2D[] hits = Physics2D.OverlapBoxAll(center, size, 0f);
            for (int i = 0; i < hits.Length; i++)
            {
                Collider2D hit = hits[i];
                if (hit.isTrigger || hit.attachedRigidbody == body) continue;
                if (hit.GetComponent<MiniEnemy>() != null) continue;
                return true;
            }
            return false;
        }

        void UpdateAnimation()
        {
            if (!grounded)
            {
                float vy = body.velocity.y;
                int index = vy > 4f ? 0 : (vy > -4f ? 1 : 2);
                anim.Hold(jump[Mathf.Min(index, jump.Length - 1)]);
            }
            else if (Mathf.Abs(moveInput) > 0.01f)
            {
                anim.Play(walk, 12f);
            }
            else
            {
                anim.Hold(idle[0]);
            }
        }

        void OnCollisionEnter2D(Collision2D collision)
        {
            if (collision.collider.GetComponent<MiniHazard>() != null) HitTrap();
            else HandleContact(collision);
        }

        void OnCollisionStay2D(Collision2D collision)
        {
            if (collision.collider.GetComponent<MiniHazard>() == null) HandleContact(collision);
        }

        // Traps.OnCollisionEnter2D: true damage, then back to the respawn point if still alive.
        void HitTrap()
        {
            Health -= trapDamage;
            if (MiniGame.Instance != null) MiniGame.Instance.TrapHits++;
            if (Health <= 0)
            {
                Respawn();
                return;
            }
            transform.position = new Vector3(MiniAssets.Level.respawnX, MiniAssets.Level.respawnY, 0f);
            body.velocity = Vector2.zero;
        }

        void HandleContact(Collision2D collision)
        {
            MiniEnemy enemy = collision.collider.GetComponent<MiniEnemy>();
            if (enemy == null || enemy.Dead) return;

            // Feet above the enemy's middle means we landed on it.
            bool stomp = box.bounds.min.y >= collision.collider.bounds.center.y;
            if (stomp)
            {
                if (enemy.Stomp() && MiniGame.Instance != null) MiniGame.Instance.EnemyKilled();
                body.velocity = new Vector2(body.velocity.x, jumpSpeed * 0.75f);
                canDoubleJump = true;
                return;
            }

            // only the patrols hurt by touch; a boss hurts with its weapon (TakeHit)
            if (enemy.IsBoss) return;
            if (Time.time < nextDamageTime) return;
            nextDamageTime = Time.time + damageCooldown;
            Health -= contactDamage;
            Knock(enemy.transform.position.x);
            if (Health <= 0) Respawn();
        }

        /// <summary>A boss's weapon landed (Stats.takeDamage): no cooldown of ours, the attacker has its own.</summary>
        public void TakeHit(int damage, float fromX)
        {
            Health -= damage;
            Knock(fromX);
            if (Health <= 0) Respawn();
        }

        void Knock(float fromX)
        {
            float away = transform.position.x >= fromX ? 1f : -1f;
            knockbackVx = away * knockbackSpeed;
            body.velocity = new Vector2(knockbackVx, knockbackLift);
            knockbackUntil = Time.time + 0.2f;
        }

        public void Respawn()
        {
            if (MiniGame.Instance != null) MiniGame.Instance.PlayerDied();
            transform.position = spawn;
            body.velocity = Vector2.zero;
            Health = maxHealth;
        }
    }
}

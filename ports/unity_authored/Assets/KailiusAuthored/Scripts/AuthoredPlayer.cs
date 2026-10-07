using UnityEngine;

// Authored-scene player: every value is a public field the generator writes into the scene, so the script needs no
// level data, no AddComponent and no helper classes.
public class AuthoredPlayer : MonoBehaviour
{
    public float speed = 10f;
    public float jumpSpeed = 22f;
    public float spawnX = 0f;
    public float spawnY = 3f;
    public int jumpsLeft = 2;
    public int score = 0;
    public float respawnBelow = -12f;
    Rigidbody2D body;

    void Awake()
    {
        body = GetComponent<Rigidbody2D>();
    }

    void Update()
    {
        Vector2 v = body.velocity;
        v.x = Input.GetAxis("Horizontal") * speed;
        if (Input.GetButtonDown("Jump") && jumpsLeft > 0)
        {
            v.y = jumpSpeed;
            jumpsLeft = jumpsLeft - 1;
        }
        body.velocity = v;
        if (transform.position.y < respawnBelow)
        {
            Respawn();
        }
    }

    void Respawn()
    {
        transform.position = new Vector3(spawnX, spawnY, 0f);
        body.velocity = new Vector2(0f, 0f);
    }

    void OnCollisionEnter2D(Collision2D other)
    {
        if (other.gameObject.CompareTag("Ground"))
        {
            jumpsLeft = 2;
        }
        if (other.gameObject.CompareTag("Enemy"))
        {
            ContactPoint2D contact = other.GetContact(0);
            if (contact.normal.y > 0.5f)
            {
                Destroy(other.gameObject);
                score = score + 100;
                Vector2 v = body.velocity;
                v.y = jumpSpeed * 0.6f;
                body.velocity = v;
            }
            else
            {
                Respawn();
            }
        }
    }

    void OnTriggerEnter2D(Collider2D other)
    {
        if (other.CompareTag("Coin"))
        {
            Destroy(other.gameObject);
            score = score + 10;
            Debug.Log("score " + score);
        }
        if (other.CompareTag("Hazard"))
        {
            Respawn();
        }
        if (other.CompareTag("Finish"))
        {
            Debug.Log("level complete, score " + score);
        }
    }
}

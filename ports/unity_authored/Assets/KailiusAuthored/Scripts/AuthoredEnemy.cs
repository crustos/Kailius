using UnityEngine;

// Patrols between two x values the generator computes from the ground under the enemy.
public class AuthoredEnemy : MonoBehaviour
{
    public float speed = 1.5f;
    public float minX = 0f;
    public float maxX = 1f;
    public float direction = 1f;
    Rigidbody2D body;

    void Awake()
    {
        body = GetComponent<Rigidbody2D>();
    }

    void FixedUpdate()
    {
        float x = transform.position.x;
        if (x > maxX)
        {
            direction = -1f;
        }
        if (x < minX)
        {
            direction = 1f;
        }
        Vector2 v = body.velocity;
        v.x = direction * speed;
        body.velocity = v;
    }
}

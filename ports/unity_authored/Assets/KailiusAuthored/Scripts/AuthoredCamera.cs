using UnityEngine;

// Keeps the camera on the player.
public class AuthoredCamera : MonoBehaviour
{
    public Transform target;
    public float offsetY = 3f;

    void LateUpdate()
    {
        float x = target.position.x;
        float y = target.position.y + offsetY;
        transform.position = new Vector3(x, y, -10f);
    }
}

using UnityEngine;

// Physical stand-in of a traffic car near the player (pooled by TrafficSystem): forwards its collisions.
public class TrafficProxy : MonoBehaviour
{
    [System.NonSerialized] public TrafficSystem system;
    [System.NonSerialized] public int index;

    void OnCollisionEnter(Collision c)
    {
        if (system) system.OnProxyHit(index, c);
    }

    void OnCollisionStay(Collision c)
    {
        if (system) system.Touch(index, c);
    }
}

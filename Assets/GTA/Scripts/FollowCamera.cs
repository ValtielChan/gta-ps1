using UnityEngine;

// Chase camera: trails the target's flattened forward, smoothed (frame-rate independent).
public class FollowCamera : MonoBehaviour
{
    public Transform target;
    public float distance = 5.2f, height = 1.9f, lookHeight = 1.0f;
    public float followSharpness = 6f, lookSharpness = 10f;

    void LateUpdate()
    {
        if (!target) return;
        Vector3 fwd = Vector3.ProjectOnPlane(target.forward, Vector3.up).normalized;
        Vector3 want = target.position - fwd * distance + Vector3.up * height;
        transform.position = Vector3.Lerp(transform.position, want, 1 - Mathf.Exp(-followSharpness * Time.deltaTime));
        var look = Quaternion.LookRotation(target.position + Vector3.up * lookHeight - transform.position);
        transform.rotation = Quaternion.Slerp(transform.rotation, look, 1 - Mathf.Exp(-lookSharpness * Time.deltaTime));
    }
}

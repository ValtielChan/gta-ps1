using UnityEngine;

// On the hips and spine of a pooled ragdoll (added by CrowdSystem): when the thrown body slams into the ground, a
// wall or a car, a dull thud and a blood splat (spray + stain on what it hit), at most every 0.35 s per body
// (`root` shares the timers); while it slides on the ground, a smear every 0.7 m.
public class RagdollThud : MonoBehaviour
{
    public RagdollThud root;
    float last = -1f;
    Vector3 lastSmear;
    Rigidbody rb;

    void Awake() => rb = GetComponent<Rigidbody>();

    void OnCollisionEnter(Collision c)
    {
        var r = root ? root : this;
        float v = c.relativeVelocity.magnitude;
        if (v < 3.5f || Time.time - r.last < 0.35f) return;
        r.last = Time.time;
        var p = c.GetContact(0);
        if (GameAudio.I) GameAudio.Play(GameAudio.I.bodyLand, p.point, Mathf.InverseLerp(3f, 14f, v) * 0.7f + 0.3f, 0, 1, 0.03f);
        if (BloodFX.I) BloodFX.I.Splat(p.point, p.normal, c.relativeVelocity, !c.rigidbody);
        r.lastSmear = p.point;
    }

    void OnCollisionStay(Collision c)
    {
        var r = root ? root : this;
        if (c.rigidbody || !BloodFX.I || rb.linearVelocity.sqrMagnitude < 4f) return;
        var p = c.GetContact(0);
        if ((p.point - r.lastSmear).sqrMagnitude < 0.7f * 0.7f) return;
        r.lastSmear = p.point;
        BloodFX.I.Smear(p.point, p.normal, rb.linearVelocity);
    }
}

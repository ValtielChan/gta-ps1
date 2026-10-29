using UnityEngine;

// Simple damage of a traffic car proxy (added by TrafficSystem to every pooled proxy; the player's car has none, it
// is indestructible). An impact dents the body mesh around the contact (vertices pushed toward the car's centre,
// smooth falloff, a little per-vertex crumple, grime darkens the vertex colors) and adds to `damage`; past SmokeAt
// the engine smokes, light grey then thick and black. Repair() puts the shared mesh back when the proxy is reused.
public class CarDamage : MonoBehaviour
{
    public static Material smokeMaterial;   // M_Smoke (TrafficSystem.smoke)
    const float MinSpeed = 2f;              // m/s along the contact normal below which nothing happens
    const float MaxDent = 0.8f;             // m a vertex can move from its rest position
    const float SmokeAt = 1f, BlackAt = 2.5f;

    public float damage;
    MeshFilter filter;
    Rigidbody rb;
    Mesh shared, mesh;
    Vector3[] rest, verts;
    Color[] restColors, colors;
    Vector3 center, engine;   // body space
    float puff;
    static ParticleSystem smoke;
    static readonly ContactPoint[] contacts = new ContactPoint[8];

    void Awake()
    {
        filter = transform.Find("Body").GetComponent<MeshFilter>();
        rb = GetComponent<Rigidbody>();
        shared = filter.sharedMesh;
        var b = shared.bounds;
        center = b.center;
        engine = new Vector3(b.center.x, Mathf.Lerp(b.min.y, b.max.y, 0.6f), b.max.z - 0.15f * b.size.z);   // hood (front = +Z)
    }

    public void Repair()
    {
        damage = 0;
        if (!mesh) return;
        System.Array.Copy(rest, verts, rest.Length);
        mesh.vertices = verts;
        if (colors != null) { System.Array.Copy(restColors, colors, colors.Length); mesh.colors = colors; }
        mesh.RecalculateNormals();
        mesh.RecalculateBounds();
        filter.sharedMesh = shared;
    }

    void OnCollisionEnter(Collision c)
    {
        if (c.rigidbody && !c.rigidbody.GetComponent<SimpleCar>() && !c.rigidbody.GetComponent<TrafficProxy>()) return;   // ragdoll limbs
        int n = c.GetContacts(contacts);
        if (n == 0) return;
        Vector3 point = Vector3.zero, normal = Vector3.zero;
        for (int i = 0; i < n; i++) { point += contacts[i].point; normal += contacts[i].normal; }
        float speed = Mathf.Abs(Vector3.Dot(c.relativeVelocity, normal.normalized));
        if (speed > MinSpeed) Dent(point / n, speed);
    }

    void Dent(Vector3 world, float speed)
    {
        if (!mesh)
        {
            mesh = Instantiate(shared);
            rest = shared.vertices;
            verts = mesh.vertices;
            restColors = shared.colors;
            if (restColors.Length == rest.Length) colors = mesh.colors; else restColors = null;
        }
        filter.sharedMesh = mesh;
        var p = filter.transform.InverseTransformPoint(world);
        var dir = (center - p).normalized;
        float depth = Mathf.Min(0.7f, speed * 0.045f), radius = 0.8f + speed * 0.06f;   // 15 m/s: 0.67 m deep, 1.7 m wide
        for (int i = 0; i < verts.Length; i++)
        {
            float d = (verts[i] - p).magnitude;
            if (d >= radius) continue;
            float w = 1 - d / radius;
            w *= w;
            // crumple: a stable factor per rest position (split vertices at one spot move together, no cracks)
            float h = Vector3.Dot(rest[i], new Vector3(12.9898f, 78.233f, 37.719f));
            float k = 0.3f + 1.2f * Mathf.Repeat(Mathf.Sin(h) * 43758.545f, 1f);
            var crumple = new Vector3(Mathf.Repeat(Mathf.Sin(h * 1.7f) * 24634.63f, 1f) - 0.5f, Mathf.Repeat(Mathf.Sin(h * 2.3f) * 31245.7f, 1f) - 0.5f, 0) * 0.5f;
            verts[i] = rest[i] + Vector3.ClampMagnitude(verts[i] + (dir + crumple) * (depth * w * k) - rest[i], MaxDent);
            if (colors != null) colors[i] = Color.Lerp(colors[i], colors[i] * 0.55f, w * Mathf.Min(1, speed / 12f));
        }
        mesh.vertices = verts;
        if (colors != null) mesh.colors = colors;
        mesh.RecalculateNormals();
        mesh.RecalculateBounds();
        damage += speed / 10f;
    }

    void Update()
    {
        if (damage < SmokeAt || !smokeMaterial) return;
        var cam = Camera.main;
        if (cam && (cam.transform.position - transform.position).sqrMagnitude > 150 * 150) return;
        float heavy = Mathf.InverseLerp(SmokeAt, BlackAt, damage);
        puff += Time.deltaTime * Mathf.Lerp(4f, 14f, heavy);
        if (puff < 1) return;
        if (!smoke) smoke = MakeSmoke();
        var e = new ParticleSystem.EmitParams();
        var at = filter.transform.TransformPoint(engine);
        var v = rb ? rb.linearVelocity * 0.3f : Vector3.zero;
        for (; puff >= 1; puff--)
        {
            e.position = at + Random.insideUnitSphere * 0.25f;
            e.velocity = v + Vector3.up * Random.Range(1f, 2f) + Random.insideUnitSphere * 0.4f;
            e.startSize = Random.Range(0.5f, 0.9f) * Mathf.Lerp(1f, 1.4f, heavy);
            e.startLifetime = Random.Range(1.8f, 3f);
            e.rotation = Random.Range(0f, 360f);
            float g = Mathf.Lerp(0.75f, 0.18f, heavy) + Random.Range(-0.05f, 0.05f);
            e.startColor = new Color(g, g, g, Mathf.Lerp(0.55f, 0.9f, heavy));
            smoke.Emit(e, 1);
        }
    }

    // one world-space system shared by every smoking car
    static ParticleSystem MakeSmoke()
    {
        var ps = new GameObject("CarSmoke").AddComponent<ParticleSystem>();
        ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
        var main = ps.main;
        main.loop = true;
        main.playOnAwake = false;
        main.simulationSpace = ParticleSystemSimulationSpace.World;
        main.startSpeed = 0;
        main.gravityModifier = -0.05f;
        main.maxParticles = 1500;
        var emission = ps.emission;
        emission.enabled = false;
        var shape = ps.shape;
        shape.enabled = false;
        var size = ps.sizeOverLifetime;
        size.enabled = true;
        size.size = new ParticleSystem.MinMaxCurve(1f, AnimationCurve.Linear(0, 1, 1, 3.5f));
        var col = ps.colorOverLifetime;
        col.enabled = true;
        var fade = new Gradient();
        fade.SetKeys(new[] { new GradientColorKey(Color.white, 0), new GradientColorKey(Color.white, 1) },
                     new[] { new GradientAlphaKey(0, 0), new GradientAlphaKey(1, 0.1f), new GradientAlphaKey(0.6f, 0.5f), new GradientAlphaKey(0, 1) });
        col.color = fade;
        var vel = ps.limitVelocityOverLifetime;   // the car's speed carried at birth fades out: a trail behind it
        vel.enabled = true;
        vel.dampen = 0.08f;
        vel.limit = 0.5f;
        var r = ps.GetComponent<ParticleSystemRenderer>();
        r.sharedMaterial = smokeMaterial;
        r.renderMode = ParticleSystemRenderMode.Billboard;
        r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
        ps.Play();
        return ps;
    }
}

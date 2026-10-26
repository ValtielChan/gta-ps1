using System.Collections.Generic;
using UnityEngine;

// Blood when people are run over, GTA style (added by CrowdSystem):
// - sprays: one world-space ParticleSystem of small dark-red droplets under gravity, thrown from the impact and from
//   bodies slamming into things; a droplet dies where it lands and leaves a drop stain now and then;
// - stains: quads showing a cell of the T_Blood atlas (Kind order, the drawing points to +V = the way the blood
//   flew) laid on static colliders only (cars and bodies move), PS1Lit with alpha clip, drawn instanced, the oldest
//   recycled: a splash under the impact, splats where the body lands or hits a wall, smears where it slides, a pool
//   spreading under it once it lies still.
public class BloodFX : MonoBehaviour
{
    public enum Kind { Pool, Splash, Smear, Spatter }

    public static BloodFX I { get; private set; }
    public int maxStains = 512;

    struct Stain { public Vector3 pos; public Quaternion rot; public float size, target, grow; public int cell; }

    Material stainMat;
    Stain[] stains;
    int next, count;
    Mesh[] quads;
    Matrix4x4[][] mats;
    int[] batch;
    ParticleSystem ps;
    readonly RaycastHit[] hits = new RaycastHit[8];
    readonly List<ParticleCollisionEvent> events = new List<ParticleCollisionEvent>();
    static readonly Color32 Dark = new Color32(70, 0, 0, 255), Bright = new Color32(150, 8, 8, 255);

    public void Init(Material stain, Material spray)
    {
        I = this;
        stainMat = stain;
        stains = new Stain[maxStains];
        quads = new Mesh[4];
        mats = new Matrix4x4[4][];
        batch = new int[4];
        for (int c = 0; c < 4; c++)
        {
            float u = c % 2 * 0.5f, v = c < 2 ? 0.5f : 0f;   // cells 0 1 on the top row of the image
            quads[c] = new Mesh
            {
                vertices = new[] { new Vector3(-0.5f, 0, -0.5f), new Vector3(-0.5f, 0, 0.5f), new Vector3(0.5f, 0, 0.5f), new Vector3(0.5f, 0, -0.5f) },
                uv = new[] { new Vector2(u, v), new Vector2(u, v + 0.5f), new Vector2(u + 0.5f, v + 0.5f), new Vector2(u + 0.5f, v) },
                normals = new[] { Vector3.up, Vector3.up, Vector3.up, Vector3.up },
                colors = new[] { Color.white, Color.white, Color.white, Color.white },
                triangles = new[] { 0, 1, 2, 0, 2, 3 },
            };
            mats[c] = new Matrix4x4[maxStains];
        }

        ps = gameObject.AddComponent<ParticleSystem>();
        ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
        var main = ps.main;
        main.loop = true;
        main.playOnAwake = false;
        main.simulationSpace = ParticleSystemSimulationSpace.World;
        main.startSpeed = 0;
        main.gravityModifier = 1.2f;
        main.maxParticles = 3000;
        var emission = ps.emission;
        emission.enabled = false;
        var shape = ps.shape;
        shape.enabled = false;
        var col = ps.collision;
        col.enabled = true;
        col.type = ParticleSystemCollisionType.World;
        col.mode = ParticleSystemCollisionMode.Collision3D;
        col.quality = ParticleSystemCollisionQuality.Low;
        col.collidesWith = ~(1 << 2);   // not the ragdolls (Ignore Raycast): the droplets leave the body
        col.lifetimeLoss = 1;
        col.sendCollisionMessages = true;
        var r = GetComponent<ParticleSystemRenderer>();
        r.sharedMaterial = spray;
        r.renderMode = ParticleSystemRenderMode.Billboard;
        r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
        ps.Play();
    }

    // ---- what the game calls ----

    // a pedestrian hit at `pos` and thrown at `v`: a spray along the throw, a splash on the ground under the impact
    // and a spatter a few meters ahead when fast
    public void Hit(Vector3 pos, Vector3 v)
    {
        float speed = v.magnitude;
        Spray(pos, v * 0.6f, 2f + 0.15f * speed, Mathf.Clamp((int)(25 + speed * 4), 25, 110));
        var flat = new Vector3(v.x, 0, v.z);
        if (Surface(pos + Vector3.up, Vector3.down, 4f, out var h)) Lay(h.point, h.normal, flat, Random.Range(1.3f, 2f), Kind.Splash);
        if (speed > 8f && Surface(pos + flat * Random.Range(0.15f, 0.3f) + Vector3.up, Vector3.down, 5f, out h))
            Lay(h.point, h.normal, flat, Random.Range(1f, 1.6f), Kind.Spatter);
    }

    // a thrown body slamming into something at `v` (relative speed)
    public void Splat(Vector3 point, Vector3 normal, Vector3 v, bool onStatic)
    {
        float speed = v.magnitude;
        Spray(point + normal * 0.1f, Vector3.Reflect(-v, normal) * 0.25f + normal * 1.5f, 1.5f + 0.1f * speed, Mathf.Clamp((int)(speed * 3), 8, 45));
        if (onStatic) Lay(point, normal, -v, Mathf.Lerp(0.8f, 1.6f, Mathf.InverseLerp(3f, 15f, speed)), speed > 8f ? Kind.Spatter : Kind.Splash);
    }

    public void Smear(Vector3 point, Vector3 normal, Vector3 v) => Lay(point, normal, v, Random.Range(0.8f, 1.1f), Kind.Smear);

    // the body lies still: a pool spreads under it
    public void Pool(Vector3 hips)
    {
        if (Surface(hips + Vector3.up * 0.3f, Vector3.down, 2f, out var h))
            Lay(h.point, h.normal, Random.onUnitSphere, Random.Range(1.4f, 2f), Kind.Pool, 0.12f);
    }

    // ---- internals ----

    void Spray(Vector3 pos, Vector3 v, float spread, int n)
    {
        var e = new ParticleSystem.EmitParams();
        for (int i = 0; i < n; i++)
        {
            e.position = pos + Random.insideUnitSphere * 0.25f;
            e.velocity = v * Random.Range(0.4f, 1.2f) + Random.insideUnitSphere * spread + Vector3.up * Random.Range(0.5f, 2.5f);
            e.startSize = Random.Range(0.05f, 0.14f);
            e.startColor = Color32.Lerp(Dark, Bright, Random.value);
            e.startLifetime = Random.Range(0.8f, 1.6f);
            ps.Emit(e, 1);
        }
    }

    // the nearest static collider along the ray (ragdolls are on Ignore Raycast)
    bool Surface(Vector3 from, Vector3 dir, float dist, out RaycastHit best)
    {
        best = default;
        int n = Physics.RaycastNonAlloc(from, dir, hits, dist, Physics.DefaultRaycastLayers, QueryTriggerInteraction.Ignore);
        float d = float.MaxValue;
        for (int i = 0; i < n; i++)
            if (!hits[i].rigidbody && hits[i].distance < d) { d = hits[i].distance; best = hits[i]; }
        return d < float.MaxValue;
    }

    void Lay(Vector3 point, Vector3 normal, Vector3 dir, float size, Kind kind, float grow = 0)
    {
        dir = Vector3.ProjectOnPlane(dir, normal);
        if (dir.sqrMagnitude < 1e-4f) dir = Vector3.ProjectOnPlane(Random.onUnitSphere, normal);
        // lifted off the surface, a little more for each newer stain so overlapping ones do not fight
        stains[next] = new Stain
        {
            pos = point + normal * (0.012f + next % 16 * 0.0015f),
            rot = Quaternion.LookRotation(dir, normal),
            size = grow > 0 ? size * 0.2f : size, target = size, grow = grow * size, cell = (int)kind,
        };
        next = (next + 1) % stains.Length;
        count = Mathf.Min(count + 1, stains.Length);
    }

    // droplets that land leave drops (one event in three)
    void OnParticleCollision(GameObject other)
    {
        if (other.GetComponentInParent<Rigidbody>()) return;   // cars move: no stain on them
        int n = ps.GetCollisionEvents(other, events);
        for (int i = 0; i < n; i += 3)
            Lay(events[i].intersection, events[i].normal, events[i].velocity, Random.Range(0.25f, 0.45f), Kind.Spatter);
    }

    void Update()
    {
        if (stains == null) return;
        System.Array.Clear(batch, 0, 4);
        float dt = Time.deltaTime;
        for (int i = 0; i < count; i++)
        {
            ref var s = ref stains[i];
            if (s.size < s.target) s.size = Mathf.Min(s.target, s.size + s.grow * dt);
            mats[s.cell][batch[s.cell]++] = Matrix4x4.TRS(s.pos, s.rot, new Vector3(s.size, 1, s.size));
        }
        for (int c = 0; c < 4; c++)
            if (batch[c] > 0)
                Graphics.DrawMeshInstanced(quads[c], 0, stainMat, mats[c], batch[c], null, UnityEngine.Rendering.ShadowCastingMode.Off, true);
    }
}

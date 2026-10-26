using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Animations;
using UnityEngine.Playables;
using UnityEngine.Rendering;

// The city's population: thousands of pedestrians for a few draw calls, WebGL friendly (no compute, no GameObject
// per pedestrian).
// - Pedestrians are plain structs simulated here and drawn with GPU instancing (GTA/PS1Crowd: vertex animation
//   texture + outfit Texture2DArray, see CrowdCharacter), up to drawDistance, frustum culled; only those within
//   shadowDistance cast shadows.
// - Everywhere in the city: `walkers` spread over the pedestrian graph exported by the road generator
//   (<City>_peds.json: middle line of every sidewalk, junction corners, crosswalks). They walk along it keeping to
//   their right (`lane`), pick a way at each junction, cross at the crosswalks now and then (crossChance), stop for a
//   few seconds sometimes, wait when the car blocks their way. Far from the camera (fullSimDistance) a quarter of
//   them is stepped per frame. People also sit on the benches and bus stop seats (`spots`, from the scene's props),
//   wait at bus stops and chat in small groups where the paved lots are wide (sidewalk bitmap, `talkingGroups`).
// - Physical existence: a pedestrian touched by the car (SimpleCar box) above minHitSpeed, or by a flying body,
//   is swapped on the spot for a pooled ragdoll (skinned model + rigidbodies) posed on the same animation frame
//   and thrown with the impact velocity; a new walker appears somewhere out of sight.
public class CrowdSystem : MonoBehaviour
{
    public enum Clip { Idle, Walk, Sit, SitTalk, Talk }   // VAT clips, order of NpcPrefabs.Clips

    [System.Serializable]
    public struct Spot { public Vector3 pos; public float yaw; public bool seat; }   // bench seat, or standing spot at a bus stop

    public CrowdCharacter[] characters;
    public TextAsset walkMap;     // sidewalk bitmap (GTA > Setup Crowd In Open Scene): where groups can stand
    public TextAsset pedGraph;    // Assets/GTA/City/<City>_peds.json (Tools/citygen: city_demo.export_peds)
    public Spot[] spots;
    public int walkers = 2000;
    public int talkingGroups = 160;
    [Range(0, 1)] public float crossChance = 0.3f;   // at a crosswalk, share of pedestrians who cross
    [Range(0, 1)] public float seatOccupancy = 0.6f, standOccupancy = 0.5f;
    public float drawDistance = 250f, fullSimDistance = 120f, shadowDistance = 30f;
    public float walkSpeed = 1.35f;          // m/s, matches the walk clip
    public float minHitSpeed = 3f;           // m/s
    public int ragdollsPerCharacter = 8;
    public float bodyLifetime = 45f;

    const int MaxBatch = 1023;
    const float TurnRate = 5f;

    struct Ped
    {
        public Vector2 pos;
        public float y, yaw, anim, timer, speed;
        public float lane;              // walkers: offset to the right of the graph line
        public int ch, skin, from, to;  // walkers: graph link being walked
        public Clip clip;
        public bool still, crossing;    // still: seated / waiting / chatting, never walks
    }

    [System.Serializable] class Graph { public float[] points; public int[] links; }

    class Body
    {
        public GameObject go;
        public Animator anim;
        public Rigidbody[] rbs;
        public Rigidbody hips;
        public SkinnedMeshRenderer smr;
        public float time;
    }

    Ped[] peds;
    Vector2[] gp;                       // graph points (x, z); y is the sidewalk height everywhere
    int[] adjStart, adj;                // neighbours of point i: adj[adjStart[i] .. adjStart[i + 1]]
    bool[] adjCross;
    int[] linkA, linkB;
    float[] linkCum;                    // cumulated link lengths: walkers spread evenly along the sidewalks
    float minX, minZ, cell, groundY;
    int w, h;
    byte[] bits;
    Matrix4x4[][] mats;
    Vector4[][] data;
    int[] batch;
    MaterialPropertyBlock mpb;
    readonly Plane[] planes = new Plane[6];
    Vector3 camPos;
    Rigidbody carRb;
    TrafficSystem traffic;
    Vector3 carHalf, carCenter;
    Matrix4x4 carInv;
    Vector2 carPos;
    float carSpeed;
    Body[][] pools;
    readonly List<Body> flying = new List<Body>();
    public readonly List<Vector2> Crossing = new List<Vector2>();   // pedestrians on a crosswalk this frame (traffic brakes for them)

    void Start()
    {
        var b = walkMap.bytes;
        minX = System.BitConverter.ToSingle(b, 0);
        minZ = System.BitConverter.ToSingle(b, 4);
        cell = System.BitConverter.ToSingle(b, 8);
        groundY = System.BitConverter.ToSingle(b, 12);   // ponytail: sidewalks are flat (0.15 m); store heights when they are not
        w = System.BitConverter.ToInt32(b, 16);
        h = System.BitConverter.ToInt32(b, 20);
        bits = new byte[b.Length - 24];
        System.Buffer.BlockCopy(b, 24, bits, 0, bits.Length);
        LoadGraph();

        int k = characters.Length * 2;
        mats = new Matrix4x4[k][];
        data = new Vector4[k][];
        batch = new int[k];
        for (int i = 0; i < k; i++) { mats[i] = new Matrix4x4[MaxBatch]; data[i] = new Vector4[MaxBatch]; }
        mpb = new MaterialPropertyBlock();

        traffic = FindAnyObjectByType<TrafficSystem>();
        var car = FindAnyObjectByType<SimpleCar>();
        if (car)
        {
            carRb = car.GetComponent<Rigidbody>();
            var box = car.GetComponent<BoxCollider>();
            carCenter = box.center;
            carHalf = box.size * 0.5f;
        }

        pools = new Body[characters.Length][];
        for (int c = 0; c < characters.Length; c++)
        {
            pools[c] = new Body[ragdollsPerCharacter];
            for (int i = 0; i < ragdollsPerCharacter; i++)
            {
                var go = Instantiate(characters[c].ragdoll, transform);
                go.SetActive(false);
                var rbs = go.GetComponentsInChildren<Rigidbody>(true);
                pools[c][i] = new Body { go = go, anim = go.GetComponent<Animator>(), rbs = rbs, hips = rbs[0], smr = go.GetComponentInChildren<SkinnedMeshRenderer>(true), time = -1e9f };
            }
        }
        Populate();
    }

    void LoadGraph()
    {
        var g = JsonUtility.FromJson<Graph>(pedGraph.text);
        int n = g.points.Length / 3, m = g.links.Length / 3;
        gp = new Vector2[n];
        for (int i = 0; i < n; i++) gp[i] = new Vector2(g.points[i * 3], g.points[i * 3 + 2]);
        adjStart = new int[n + 1];
        for (int k = 0; k < m; k++) { adjStart[g.links[k * 3] + 1]++; adjStart[g.links[k * 3 + 1] + 1]++; }
        for (int i = 0; i < n; i++) adjStart[i + 1] += adjStart[i];
        adj = new int[m * 2];
        adjCross = new bool[m * 2];
        var fill = (int[])adjStart.Clone();
        linkA = new int[m];
        linkB = new int[m];
        linkCum = new float[m];
        float total = 0;
        for (int k = 0; k < m; k++)
        {
            int a = g.links[k * 3], c = g.links[k * 3 + 1];
            bool x = g.links[k * 3 + 2] != 0;
            adj[fill[a]] = c; adjCross[fill[a]++] = x;
            adj[fill[c]] = a; adjCross[fill[c]++] = x;
            linkA[k] = a;
            linkB[k] = c;
            linkCum[k] = total += (gp[c] - gp[a]).magnitude;
        }
    }

    void Populate()
    {
        UpdateCar();   // nobody spawns inside the car
        camPos = Camera.main.transform.position;
        var list = new List<Ped>();
        // seated on benches / bus stop seats, waiting at bus stops
        if (spots != null)
            foreach (var s in spots)
                if (Random.value < (s.seat ? seatOccupancy : standOccupancy))
                    list.Add(NewPed(new Vector2(s.pos.x, s.pos.z), s.pos.y, s.yaw * Mathf.Deg2Rad,
                        s.seat ? (Random.value < 0.35f ? Clip.SitTalk : Clip.Sit) : Clip.Idle, true));
        // small groups chatting where the sidewalk is wide; their cells leave the bitmap so walkers go around them
        for (int g = 0, tries = 0; g < talkingGroups && tries < talkingGroups * 50; tries++)
        {
            if (!RandomCell(out var c) || !Roomy(c)) continue;
            int n = Random.value < 0.3f ? 3 : 2;
            float a0 = Random.value * Mathf.PI * 2, r = n == 2 ? 0.55f : 0.65f;
            for (int m = 0; m < n; m++)
            {
                float a = a0 + m * Mathf.PI * 2 / n;
                list.Add(NewPed(c + Dir(a) * r, groundY, a + Mathf.PI, Clip.Talk, true));
            }
            g++;
        }
        for (int i = 0; i < walkers; i++)
        {
            var p = NewPed(default, groundY, 0, Clip.Walk, false);
            if (PlaceWalker(ref p, false)) list.Add(p);
        }
        peds = list.ToArray();
    }

    Ped NewPed(Vector2 pos, float y, float yaw, Clip clip, bool still)
    {
        int ch = Random.Range(0, characters.Length);
        return new Ped
        {
            pos = pos, y = y, yaw = yaw, clip = clip, still = still,
            timer = Random.Range(2f, 10f),
            ch = ch, skin = Random.Range(0, characters[ch].skins.Length), lane = Random.Range(0.25f, 0.9f),
            speed = walkSpeed * Random.Range(0.85f, 1.15f), anim = Random.value * 10,
        };
    }

    void Update()
    {
        var cam = Camera.main;
        if (!cam) return;
        float dt = Mathf.Min(Time.deltaTime, 0.1f);
        camPos = cam.transform.position;
        var center = new Vector2(camPos.x, camPos.z);
        GeometryUtility.CalculateFrustumPlanes(cam, planes);
        UpdateCar();
        UpdateBodies();
        float near2 = fullSimDistance * fullSimDistance;
        int frame = Time.frameCount;
        Crossing.Clear();
        for (int i = 0; i < peds.Length; i++)
        {
            ref var p = ref peds[i];
            p.anim += p.clip == Clip.Walk ? dt * p.speed / walkSpeed : dt;
            if (p.crossing && !p.still) Crossing.Add(p.pos);
            if (!p.still)
            {
                if ((p.pos - center).sqrMagnitude < near2) Step(ref p, dt);
                else if (((i + frame) & 3) == 0) Step(ref p, dt * 4);   // far away: a quarter of them per frame
            }
            if (Hit(ref p, out var v))
            {
                Kill(ref p, v);
                var w = NewPed(default, groundY, 0, Clip.Walk, false);
                if (PlaceWalker(ref w, true)) p = w;
            }
            else if (!p.still && InCar(p.pos, 0.05f)) PushOut(ref p);
        }
        Draw();
    }

    public int Count => peds?.Length ?? 0;

    public Vector3 Feet(int i, out float yawDeg)
    {
        yawDeg = peds[i].yaw * Mathf.Rad2Deg;
        return new Vector3(peds[i].pos.x, peds[i].y, peds[i].pos.y);
    }

    // ---- walking ----

    static Vector2 Dir(float yaw) => new Vector2(Mathf.Sin(yaw), Mathf.Cos(yaw));

    bool Walkable(Vector2 q)
    {
        int i = (int)((q.x - minX) / cell), j = (int)((q.y - minZ) / cell);
        if ((uint)i >= (uint)w || (uint)j >= (uint)h) return false;
        int k = j * w + i;
        return (bits[k >> 3] & (1 << (k & 7))) != 0;
    }

    // room for a group and for walkers to pass: paved all around within 1.6 m
    bool Roomy(Vector2 c)
    {
        for (int a = 0; a < 8; a++) if (!Walkable(c + Dir(a * Mathf.PI / 4) * 1.6f)) return false;
        return true;
    }

    // a random paved cell anywhere in the city (talking groups)
    bool RandomCell(out Vector2 q)
    {
        for (int t = 0; t < 400; t++)
        {
            q = new Vector2(minX + Random.value * w * cell, minZ + Random.value * h * cell);
            if (Walkable(q) && !InCar(q, 0.5f)) return true;
        }
        q = default;
        return false;
    }

    static Vector2 Right(Vector2 d) => new Vector2(d.y, -d.x);

    // a random point of the graph, evenly along the sidewalks; hidden: out of sight (not in view, or far)
    bool PlaceWalker(ref Ped p, bool hidden)
    {
        float total = linkCum[linkCum.Length - 1];
        for (int t = 0; t < 60; t++)
        {
            int k = System.Array.BinarySearch(linkCum, Random.value * total);
            if (k < 0) k = ~k;
            k = Mathf.Min(k, linkCum.Length - 1);
            bool fwd = Random.value < 0.5f;
            int a = fwd ? linkA[k] : linkB[k], c = fwd ? linkB[k] : linkA[k];
            var d = (gp[c] - gp[a]).normalized;
            var q = Vector2.Lerp(gp[a], gp[c], Random.value) + Right(d) * p.lane;
            if (InCar(q, 0.5f)) continue;
            if (hidden)
            {
                var f = new Vector3(q.x, groundY, q.y);
                float d2 = (f - camPos).sqrMagnitude;
                if (d2 < 3600 || (d2 < drawDistance * drawDistance && Visible(f))) continue;
            }
            p.pos = q;
            p.from = a;
            p.to = c;
            p.yaw = Mathf.Atan2(d.x, d.y);
            p.crossing = IsCrossing(a, c);
            return true;
        }
        return false;
    }

    bool IsCrossing(int a, int c)
    {
        for (int k = adjStart[a]; k < adjStart[a + 1]; k++) if (adj[k] == c) return adjCross[k];
        return false;
    }

    // at a graph point: carry on along the sidewalk, turn the corner, or cross (crossChance); never straight back
    // unless it is a dead end
    void Next(ref Ped p)
    {
        int at = p.to, prev = p.from;
        float cw = crossChance / Mathf.Max(0.01f, 1 - crossChance), total = 0;
        for (int k = adjStart[at]; k < adjStart[at + 1]; k++) if (adj[k] != prev) total += adjCross[k] ? cw : 1;
        int next = prev;
        bool cross = p.crossing;
        float r = Random.value * total;
        for (int k = adjStart[at]; k < adjStart[at + 1] && total > 0; k++)
        {
            if (adj[k] == prev) continue;
            r -= adjCross[k] ? cw : 1;
            next = adj[k];
            cross = adjCross[k];
            if (r <= 0) break;
        }
        p.from = at;
        p.to = next;
        p.crossing = cross;
    }

    void Step(ref Ped p, float dt)
    {
        p.timer -= dt;
        if (p.clip == Clip.Idle)
        {
            if (p.timer <= 0) { p.clip = Clip.Walk; p.timer = Random.Range(8f, 20f); }
            return;
        }
        if (p.timer <= 0 && !p.crossing)
        {
            p.timer = Random.Range(8f, 20f);
            if (Random.value < 0.15f) { p.clip = Clip.Idle; p.timer = Random.Range(2f, 6f); return; }   // window shopping
        }
        // at the curb, a crosswalk ahead: wait for a gap in the traffic (cars yield to the ones already crossing)
        if (p.crossing && traffic && (p.pos - gp[p.from]).sqrMagnitude < 2.25f && !traffic.CanCross(gp[p.from], gp[p.to]))
        {
            p.clip = Clip.Idle;
            p.timer = 0.5f;
            return;
        }
        // head for the end of the current link, kept `lane` m to the right of the line
        var target = gp[p.to] + Right((gp[p.to] - gp[p.from]).normalized) * p.lane;
        var to = target - p.pos;
        float dist = to.magnitude;
        if (dist < 0.5f) { Next(ref p); return; }
        var dir = to / dist;
        float want = Mathf.Atan2(dir.x, dir.y);
        float d = Mathf.DeltaAngle(p.yaw * Mathf.Rad2Deg, want * Mathf.Rad2Deg) * Mathf.Deg2Rad;
        p.yaw += Mathf.Clamp(d, -TurnRate * dt, TurnRate * dt);
        var next = p.pos + dir * Mathf.Min(dist, p.speed * dt);
        if (!InCar(next, 0.45f)) p.pos = next;   // the car is in the way: wait
    }

    // ---- car, impacts, ragdolls ----

    void UpdateCar()
    {
        carSpeed = 0;
        if (!carRb) return;
        var t = carRb.transform;
        carInv = t.worldToLocalMatrix;
        carPos = new Vector2(t.position.x, t.position.z);
        carSpeed = carRb.linearVelocity.magnitude;
    }

    bool InCar(Vector2 q, float margin)
    {
        if (!carRb || (q - carPos).sqrMagnitude > 36) return false;
        var l = carInv.MultiplyPoint3x4(new Vector3(q.x, carRb.position.y, q.y)) - carCenter;
        return Mathf.Abs(l.x) < carHalf.x + margin && Mathf.Abs(l.z) < carHalf.z + margin;
    }

    // a slow car nudges people aside instead of driving through them
    void PushOut(ref Ped p)
    {
        var l = carInv.MultiplyPoint3x4(new Vector3(p.pos.x, carRb.position.y, p.pos.y)) - carCenter;
        l.x = Mathf.Sign(l.x) * (carHalf.x + 0.1f);
        var q = carRb.transform.TransformPoint(l + carCenter);
        p.pos = new Vector2(q.x, q.z);
    }

    bool Hit(ref Ped p, out Vector3 v)
    {
        v = default;
        // the car: its box, grown by the distance it covers this frame
        if (carSpeed > minHitSpeed && InCar(p.pos, 0.3f + carSpeed * Time.deltaTime))
        {
            // thrown a bit faster than the car and off its line (the side of the bumper that hit), else the car
            // catches the body again and pushes it along
            var cv = carRb.linearVelocity;
            var right = carRb.transform.right;
            float side = Mathf.Sign(Vector3.Dot(new Vector3(p.pos.x - carPos.x, 0, p.pos.y - carPos.y), right) + Random.Range(-0.3f, 0.3f));
            v = cv * 1.3f + right * (side * 0.3f * carSpeed) + Vector3.up * (2f + 0.12f * carSpeed);
            carRb.linearVelocity *= 0.97f;   // 70 kg against 1.4 t
            return true;
        }
        // a flying body knocks the ones it lands on
        foreach (var b in flying)
        {
            var hp = b.hips.position;
            if (hp.y - p.y < 1.6f && (new Vector2(hp.x, hp.z) - p.pos).sqrMagnitude < 0.5f) { v = b.hips.linearVelocity * 0.8f + Vector3.up; return true; }
        }
        return false;
    }

    void Kill(ref Ped p, Vector3 v)
    {
        var ch = characters[p.ch];
        var pool = pools[p.ch];
        Body b = pool[0];
        foreach (var x in pool) if (!x.go.activeSelf || x.time < b.time) { b = x; if (!x.go.activeSelf) break; }

        b.go.transform.SetPositionAndRotation(new Vector3(p.pos.x, p.y, p.pos.y), Quaternion.Euler(0, p.yaw * Mathf.Rad2Deg, 0));
        b.smr.sharedMaterial = ch.skins[p.skin];
        foreach (var rb in b.rbs) rb.isKinematic = true;
        b.go.SetActive(true);

        // same pose as the instanced pedestrian: evaluate its clip at the frame it was showing
        int clip = (int)p.clip;
        float t = (int)(p.anim * ch.fps) % ch.clipFrames[clip] / ch.fps;
        b.anim.enabled = true;
        var g = PlayableGraph.Create("pose");
        var output = AnimationPlayableOutput.Create(g, "pose", b.anim);
        var cp = AnimationClipPlayable.Create(g, ch.clips[clip]);
        output.SetSourcePlayable(cp);
        cp.SetTime(t);
        g.Evaluate();
        g.Destroy();
        b.anim.enabled = false;
        Physics.SyncTransforms();

        // the legs take the bumper first: they leave faster than the torso, the body tumbles
        foreach (var rb in b.rbs)
        {
            rb.isKinematic = false;
            rb.linearVelocity = v * (rb.position.y - p.y < 0.9f ? 1.1f : 0.9f);
            rb.angularVelocity = Random.insideUnitSphere * 4f;
        }
        b.time = Time.time;
    }

    void UpdateBodies()
    {
        flying.Clear();
        foreach (var pool in pools)
            foreach (var b in pool)
            {
                if (!b.go.activeSelf) continue;
                float age = Time.time - b.time;
                if (age > bodyLifetime) b.go.SetActive(false);
                else if (age < 4f && b.hips.linearVelocity.sqrMagnitude > 9) flying.Add(b);
            }
    }

    // ---- drawing ----

    bool Visible(Vector3 feet)
    {
        var c = feet + new Vector3(0, 0.9f, 0);
        foreach (var pl in planes) if (pl.GetDistanceToPoint(c) < -1.1f) return false;
        return true;
    }

    void Draw()
    {
        float sh2 = shadowDistance * shadowDistance, draw2 = drawDistance * drawDistance;
        System.Array.Clear(batch, 0, batch.Length);
        for (int i = 0; i < peds.Length; i++)
        {
            ref var p = ref peds[i];
            float dx = p.pos.x - camPos.x, dz = p.pos.y - camPos.z, d2 = dx * dx + dz * dz;
            if (d2 > draw2) continue;
            var feet = new Vector3(p.pos.x, p.y, p.pos.y);
            if (!Visible(feet)) continue;
            int k = p.ch * 2 + (d2 < sh2 ? 1 : 0);
            int n = batch[k];
            if (n == MaxBatch) continue;   // ponytail: one draw per batch caps a batch at 1023 visible, split if that is ever reached
            var ch = characters[p.ch];
            int clip = (int)p.clip;
            int row = ch.clipStart[clip] + (int)(p.anim * ch.fps) % ch.clipFrames[clip];
            mats[k][n] = Matrix4x4.TRS(feet, Quaternion.Euler(0, p.yaw * Mathf.Rad2Deg, 0), Vector3.one);
            data[k][n] = new Vector4(p.skin, row, 0, 0);
            batch[k] = n + 1;
        }
        for (int k = 0; k < batch.Length; k++)
        {
            if (batch[k] == 0) continue;
            var ch = characters[k / 2];
            mpb.SetVectorArray("_Crowd", data[k]);
            Graphics.DrawMeshInstanced(ch.mesh, 0, ch.material, mats[k], batch[k], mpb,
                k % 2 == 1 ? ShadowCastingMode.On : ShadowCastingMode.Off, true, gameObject.layer);
        }
    }
}

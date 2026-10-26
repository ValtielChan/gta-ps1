using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

// City traffic: hundreds of cars on the lane graph exported by the road generator (<City>_traffic.json, see
// Tools/citygen/roadnet.py traffic_graph), simulated as plain structs and drawn with GPU instancing (same design
// as CrowdSystem: WebGL friendly, no GameObject per car).
// - A lane is a polyline in travel order; a car keeps its lane and picks a successor at its end (weighted by turn).
// - Car following (gap to the car ahead, across lane ends), speed limits, slowing before curves and junctions.
// - Junctions: signals cycle two groups (E-W / N-S) per junction; stop signs = full stop then first come first
//   served; yield (roundabout, merges) and left turns on green: a car enters a connector only when no car is on a
//   conflicting one (polylines crossing, or merging into the same lane) or about to enter it.
// - Obstacles ahead in the lane (the player's car, wrecked cars, crossing pedestrians): brake.
// - Physical existence: the cars nearest to the player get a pooled rigidbody proxy (TrafficProxy: box collider +
//   the real model, driven by velocity so masses count in collisions); a hit above crashSpeed turns the proxy into
//   a free wreck (gravity, pushed around, an obstacle for the others) and the traffic car respawns out of sight.
// - Parked cars: static instances on the parking spots of the graph (street parking lanes, parking-lot stalls),
//   `parkedOccupancy` of them taken; within parkRadius of the player they become free rigidbodies at rest (pushed,
//   rammed, thrown), and keep the pose they were left in; a parked car pushed off its spot is an obstacle for traffic.
public class TrafficSystem : MonoBehaviour
{
    public TrafficCar[] cars;
    public TextAsset laneGraph;           // Assets/GTA/City/<City>_traffic.json
    public int count = 700;
    public float drawDistance = 300f, physicsDistance = 45f;
    public int proxies = 14;
    [Range(0, 1)] public float parkedOccupancy = 0.7f;
    public float parkRadius = 35f;
    public int parkedProxies = 30;
    public float crashSpeed = 2.5f;       // m/s relative speed that frees a proxy
    public float wreckLifetime = 60f;
    public float accel = 3f, brake = 4f, hardBrake = 8f, headway = 1.0f, minGap = 1.8f;
    public float greenTime = 9f, yellowTime = 2.5f, allRed = 1f;
    public float maxShift = 3.8f;         // m a car moves aside to pass a still obstacle (wreck, pushed car, stopped player)
    public float jamTime = 30f;           // s stopped before an unseen car is moved elsewhere
    // GTA-style population: the simulation is global, but cars live within liveRadius of the player; an unseen car
    // farther than recycleDistance comes back somewhere around him (unseen), at most laneSpacing m of lane per car
    public float liveRadius = 450f, recycleDistance = 520f, laneSpacing = 45f;
    int recycleLeft;
    [System.NonSerialized] public int jamRespawns;

    const int MaxBatch = 1023;
    const float Look = 60f, CarLength = 4.6f, HalfLength = 2.3f, HalfWidth = 0.9f, StopLine = 7.5f;

    [System.Serializable] class LaneJson { public float[] pts; public float speed; public int junction, turn, arm; public int[] next; }
    [System.Serializable] class JunctionJson { public int control; public float x, z; }
    [System.Serializable] class Graph { public LaneJson[] lanes; public JunctionJson[] junctions; public float[] parked; }   // parked: x, y, z, fwd x, fwd z

    struct Parked { public Vector3 pos; public Quaternion rot; public Matrix4x4 m; public int model, paint, proxy; public bool moved; }
    Parked[] parked;
    float[] parkedRaw;
    int[] parkCellStart, parkItems;
    Proxy[] parkPool;
    readonly List<int> movedParked = new List<int>();

    class Lane
    {
        public Vector3[] pts;
        public float[] cum;
        public float length, speed, stopAt;   // stopAt: s of the car centre at the stop line
        public int junction, turn, arm;       // turn: 0 straight, 1 right, 2 left, 3 ring, 5 exit, 6 merge
        public int[] next, prev, conflicts;
        public float[] conflictPast;          // s on the conflicting lane past which its car has cleared our path
        public int stopJunction = -1;         // junction entered at the end of this lane
    }

    struct Car
    {
        public int lane, next, model, paint, proxy;
        public float s, speed, spin, stopped, steer;
        public byte why;                       // what limits the speed (Why[]), for the dev checks
        public float off, offTarget;           // lateral offset from the lane centre (passing a still obstacle), + = right
        public Vector3 pos, fwd;
    }

    struct Obstacle { public Vector3 pos, fwd, right, vel; public float halfL, halfW; public byte kind; public int car; }   // car: traffic car index + 1 (0 = none)   // kind: 3 player, 4 wreck, 5 pedestrian (Why[])
    static readonly string[] Why = { "free", "lane end", "car ahead", "player", "wreck", "pedestrian", "box full", "red", "yellow", "busy", "stop sign", "yield", "car passing" };
    byte stopWhy;

    class Proxy
    {
        public GameObject go;
        public Rigidbody rb;
        public BoxCollider box;
        public MeshRenderer body;
        public Transform[] wheels;
        public int car = -1, model;
        public bool wreck;
        public float lastHit = -1e9f;   // time of the last collision (an offset without a hit is a frame hitch, not a crash)
        public float time;
    }

    Lane[] lanes;
    int[] control;
    float[] phaseOffset;
    float[] laneCum;                     // cumulated road lane lengths (spawning spread evenly)
    int[] roadLanes;
    Car[] carsSim;
    int[] bucketStart, bucket;           // cars per lane: bucket[bucketStart[l] .. bucketStart[l + 1]]
    int[] laneStamp;                     // frame a car entered the lane (same-frame conflict checks)
    Obstacle[] obstacles = new Obstacle[64];
    int obstacleCount;
    int[] cellStart, cellItems, cellFill;   // obstacles by 50 m cell: a car only looks at the 3 x 3 cells around it
    int[] fill;
    const float Cell = 50f, GridMin = -1200f;
    const int Cells = 48;                   // ponytail: 2.4 km square map; make the grid follow the city bounds past that
    Matrix4x4[][] bodyMats;              // [model * paints + paint][instance]
    Matrix4x4[][][] wheelMats;           // [model][wheel][instance]
    int[] bodyCount, wheelCount;
    readonly Plane[] planes = new Plane[6];
    Vector3 camPos, playerPos;
    Rigidbody playerRb;
    readonly System.Diagnostics.Stopwatch watch = new System.Diagnostics.Stopwatch();
    public float simMs;                  // last frame's cost (simulation + draw submission)
    Proxy[] pool;
    CrowdSystem crowd;
    float cycle;

    void Start()
    {
        LoadGraph();
        var player = FindAnyObjectByType<SimpleCar>();
        if (player) playerRb = player.GetComponent<Rigidbody>();
        crowd = FindAnyObjectByType<CrowdSystem>();
        cycle = 2 * (greenTime + yellowTime + allRed);

        int nb = 0;
        foreach (var c in cars) nb += c.paints;
        bodyMats = new Matrix4x4[nb][];
        bodyCount = new int[nb];
        for (int i = 0; i < nb; i++) bodyMats[i] = new Matrix4x4[MaxBatch];
        wheelMats = new Matrix4x4[cars.Length][][];
        wheelCount = new int[cars.Length];
        for (int m = 0; m < cars.Length; m++)
        {
            wheelMats[m] = new Matrix4x4[4][];
            for (int w = 0; w < 4; w++) wheelMats[m][w] = new Matrix4x4[MaxBatch];
        }

        pool = new Proxy[proxies];
        for (int i = 0; i < proxies; i++) pool[i] = MakeProxy("Proxy" + i, i, i % cars.Length);
        parkPool = new Proxy[parkedProxies * cars.Length];
        for (int i = 0; i < parkPool.Length; i++) parkPool[i] = MakeProxy("Parked" + i, ParkedIndex + i, i % cars.Length);
        var spots = new List<Parked>();
        for (int k = 0; k + 4 < parkedRaw.Length; k += 5)
        {
            if (Random.value >= parkedOccupancy) continue;
            int m = Random.Range(0, cars.Length);
            var pos = new Vector3(parkedRaw[k], parkedRaw[k + 1], parkedRaw[k + 2]);
            var rot = Quaternion.LookRotation(new Vector3(parkedRaw[k + 3], 0, parkedRaw[k + 4]));
            spots.Add(new Parked { pos = pos, rot = rot, m = Matrix4x4.TRS(pos, rot, Vector3.one), model = m, paint = Random.Range(0, cars[m].paints), proxy = -1 });
        }
        parked = spots.ToArray();
        BuildParkGrid();

        camPos = Camera.main ? Camera.main.transform.position : Vector3.zero;
        UpdatePlayer();
        carsSim = new Car[count];
        laneStamp = new int[lanes.Length];
        BuildBuckets();
        int placed = 0;
        for (int i = 0; i < count; i++)
        {
            var c = NewCar();
            if (Place(ref c, false)) { carsSim[placed++] = c; BuildBuckets(); }
        }
        System.Array.Resize(ref carsSim, placed);
    }

    const int ParkedIndex = 1000;   // TrafficProxy.index of the parked cars' proxies

    Proxy MakeProxy(string name, int index, int model)
    {
        var go = Instantiate(cars[model].proxy, transform);
        go.name = name;
        go.SetActive(false);
        var tp = go.GetComponent<TrafficProxy>();
        tp.system = this;
        tp.index = index;
        return new Proxy
        {
            go = go, rb = go.GetComponent<Rigidbody>(), box = go.GetComponent<BoxCollider>(), model = model,
            body = go.transform.Find("Body").GetComponent<MeshRenderer>(),
            wheels = new[] { go.transform.Find("Wheel0"), go.transform.Find("Wheel1"), go.transform.Find("Wheel2"), go.transform.Find("Wheel3") },
        };
    }

    // ---- graph ----

    void LoadGraph()
    {
        var g = JsonUtility.FromJson<Graph>(laneGraph.text);
        parkedRaw = g.parked ?? new float[0];
        lanes = new Lane[g.lanes.Length];
        for (int i = 0; i < lanes.Length; i++)
        {
            var j = g.lanes[i];
            int n = j.pts.Length / 3;
            var l = new Lane { pts = new Vector3[n], cum = new float[n], speed = j.speed, junction = j.junction, turn = j.turn, arm = j.arm, next = j.next };
            for (int k = 0; k < n; k++)
            {
                l.pts[k] = new Vector3(j.pts[k * 3], j.pts[k * 3 + 1], j.pts[k * 3 + 2]);
                l.cum[k] = k == 0 ? 0 : l.cum[k - 1] + (l.pts[k] - l.pts[k - 1]).magnitude;
            }
            l.length = l.cum[n - 1];
            lanes[i] = l;
        }
        control = new int[g.junctions.Length];
        phaseOffset = new float[g.junctions.Length];
        for (int j = 0; j < control.Length; j++) { control[j] = g.junctions[j].control; phaseOffset[j] = Random.value * 100; }

        var prev = new List<int>[lanes.Length];
        for (int i = 0; i < lanes.Length; i++) prev[i] = new List<int>();
        for (int i = 0; i < lanes.Length; i++) foreach (int n in lanes[i].next) prev[n].Add(i);
        var conf = new List<int>[lanes.Length];
        var past = new List<float>[lanes.Length];
        for (int i = 0; i < lanes.Length; i++)
        {
            var l = lanes[i];
            l.prev = prev[i].ToArray();
            conf[i] = new List<int>();
            past[i] = new List<float>();
            if (l.junction < 0 && l.next.Length > 0 && lanes[l.next[0]].junction >= 0) l.stopJunction = lanes[l.next[0]].junction;
            bool controlled = l.stopJunction >= 0 && control[l.stopJunction] != 0;
            // where a yielding car waits: connectors converge on the lane they join (6 m back), a merge lane
            // runs onto the main lane over its last 24 m (wait before that), else 3 m before the end
            if (l.junction >= 0) l.stopAt = Mathf.Max(l.length * 0.5f, l.length - 6f);
            else if (l.turn == 6) l.stopAt = l.length - Mathf.Min(24f, 0.6f * l.length);
            else l.stopAt = l.length - (controlled ? StopLine : 3f);
        }
        // conflicts: connectors of one junction whose polylines cross (merges are checked from the lane's prev list)
        var byJunction = new Dictionary<int, List<int>>();
        for (int i = 0; i < lanes.Length; i++)
            if (lanes[i].junction >= 0)
            {
                if (!byJunction.TryGetValue(lanes[i].junction, out var list)) byJunction[lanes[i].junction] = list = new List<int>();
                list.Add(i);
            }
        foreach (var list in byJunction.Values)
            for (int a = 0; a < list.Count; a++)
                for (int b = a + 1; b < list.Count; b++)
                {
                    Lane la = lanes[list[a]], lb = lanes[list[b]];
                    if ((la.pts[0] - lb.pts[0]).sqrMagnitude < 0.1f || System.Array.IndexOf(la.next, list[b]) >= 0 || System.Array.IndexOf(lb.next, list[a]) >= 0) continue;
                    if (Crosses(la, lb, out float sa, out float sb))
                    {
                        conf[list[a]].Add(list[b]); past[list[a]].Add(sb + HalfLength + 1f);
                        conf[list[b]].Add(list[a]); past[list[b]].Add(sa + HalfLength + 1f);
                    }
                }
        float total = 0;
        var road = new List<int>();
        var cum = new List<float>();
        for (int i = 0; i < lanes.Length; i++)
        {
            lanes[i].conflicts = conf[i].ToArray();
            lanes[i].conflictPast = past[i].ToArray();
            if (lanes[i].junction >= 0 || lanes[i].length < 12) continue;
            road.Add(i);
            cum.Add(total += lanes[i].length);
        }
        roadLanes = road.ToArray();
        laneCum = cum.ToArray();
    }

    // do the polylines cross? sa / sb: distance along a / b of the last crossing
    static bool Crosses(Lane a, Lane b, out float sa, out float sb)
    {
        bool hit = false;
        sa = sb = 0;
        for (int i = 1; i < a.pts.Length; i++)
            for (int j = 1; j < b.pts.Length; j++)
            {
                Vector2 p = new Vector2(a.pts[i - 1].x, a.pts[i - 1].z), r = new Vector2(a.pts[i].x, a.pts[i].z) - p;
                Vector2 q = new Vector2(b.pts[j - 1].x, b.pts[j - 1].z), s = new Vector2(b.pts[j].x, b.pts[j].z) - q;
                float den = r.x * s.y - r.y * s.x;
                if (Mathf.Abs(den) < 1e-6f) continue;
                var qp = q - p;
                float t = (qp.x * s.y - qp.y * s.x) / den, u = (qp.x * r.y - qp.y * r.x) / den;
                if (t > 0.02f && t < 0.98f && u > 0.02f && u < 0.98f)
                {
                    hit = true;
                    sa = Mathf.Max(sa, a.cum[i - 1] + t * (a.cum[i] - a.cum[i - 1]));
                    sb = Mathf.Max(sb, b.cum[j - 1] + u * (b.cum[j] - b.cum[j - 1]));
                }
            }
        return hit;
    }

    Vector3 At(Lane l, float s, out Vector3 fwd)
    {
        int k = System.Array.BinarySearch(l.cum, s);
        if (k < 0) k = ~k - 1;
        k = Mathf.Clamp(k, 0, l.pts.Length - 2);
        var d = l.pts[k + 1] - l.pts[k];
        float seg = Mathf.Max(l.cum[k + 1] - l.cum[k], 1e-4f);
        fwd = d / seg;
        return l.pts[k] + d * Mathf.Clamp01((s - l.cum[k]) / seg);
    }

    // ---- population ----

    Car NewCar()
    {
        int m = Random.Range(0, cars.Length);
        return new Car { model = m, paint = Random.Range(0, cars[m].paints), proxy = -1, next = -1 };
    }

    // a random spot on a road lane, evenly by length, away from the other cars; hidden: out of sight
    bool Place(ref Car c, bool hidden)
    {
        float total = laneCum[laneCum.Length - 1];
        for (int t = 0; t < 60; t++)
        {
            int k = System.Array.BinarySearch(laneCum, Random.value * total);
            if (k < 0) k = ~k;
            int li = roadLanes[Mathf.Min(k, roadLanes.Length - 1)];
            var l = lanes[li];
            float s = Random.Range(3f, l.length - 10f);
            int n = bucketStart[li + 1] - bucketStart[li];
            if ((n + 1) * laneSpacing > l.length) continue;   // density cap per lane
            bool free = true;
            for (int b = bucketStart[li]; b < bucketStart[li + 1] && free; b++) free = Mathf.Abs(carsSim[bucket[b]].s - s) > 14f;
            if (!free) continue;
            var p = At(l, s, out var fwd);
            float d2 = (p - playerPos).sqrMagnitude;
            if (d2 < 900 || d2 > liveRadius * liveRadius) continue;   // the population lives around the player
            if (hidden && (p - camPos).sqrMagnitude < drawDistance * drawDistance && Visible(p)) continue;
            c.lane = li;
            c.s = s;
            c.speed = l.speed * 0.6f;
            c.next = Pick(li);
            c.stopped = 0;
            c.pos = p;
            c.fwd = fwd;
            return true;
        }
        return false;
    }

    static readonly float[] TurnWeight = { 2f, 1.5f, 1f, 1.5f, 1f, 0.5f, 1f };   // straight, right, left, ring, -, exit, merge

    int Pick(int lane)
    {
        var nx = lanes[lane].next;
        if (nx.Length == 0) return -1;
        float total = 0;
        foreach (int n in nx) total += TurnWeight[lanes[n].turn];
        float r = Random.value * total;
        foreach (int n in nx) { r -= TurnWeight[lanes[n].turn]; if (r <= 0) return n; }
        return nx[nx.Length - 1];
    }

    int[] carCellStart, carItems, carFill;

    void BuildCarGrid()
    {
        if (carCellStart == null) { carCellStart = new int[Cells * Cells + 1]; carFill = new int[Cells * Cells]; carItems = new int[count]; }
        System.Array.Clear(carCellStart, 0, carCellStart.Length);
        System.Array.Clear(carFill, 0, carFill.Length);
        for (int i = 0; i < carsSim.Length; i++) carCellStart[CellOf(carsSim[i].pos) + 1]++;
        for (int c = 0; c < Cells * Cells; c++) carCellStart[c + 1] += carCellStart[c];
        for (int i = 0; i < carsSim.Length; i++) { int c = CellOf(carsSim[i].pos); carItems[carCellStart[c] + carFill[c]++] = i; }
    }

    // nobody in the corridor `shift` m to the side, from 12 m behind to 60 m ahead (oncoming cars included)
    bool SideClear(int i, Vector3 pos, Vector3 fwd, Vector3 right, float shift)
    {
        int cell = CellOf(pos), ci = cell % Cells, cj = cell / Cells;
        for (int j = Mathf.Max(0, cj - 1); j <= Mathf.Min(Cells - 1, cj + 1); j++)
            for (int ii = Mathf.Max(0, ci - 1); ii <= Mathf.Min(Cells - 1, ci + 1); ii++)
                for (int n = carCellStart[j * Cells + ii]; n < carCellStart[j * Cells + ii + 1]; n++)
                {
                    int k = carItems[n];
                    if (k == i) continue;
                    var rel = carsSim[k].pos - pos;
                    float along = Vector3.Dot(rel, fwd);
                    if (along < -12f || along > 60f) continue;
                    if (Mathf.Abs(Vector3.Dot(rel, right) - shift) < 2.4f) return false;
                }
        return true;
    }

    void BuildBuckets()
    {
        int n = carsSim?.Length ?? 0;
        if (bucketStart == null) { bucketStart = new int[lanes.Length + 1]; bucket = new int[count]; fill = new int[lanes.Length]; }
        System.Array.Clear(bucketStart, 0, bucketStart.Length);
        System.Array.Clear(fill, 0, fill.Length);
        for (int i = 0; i < n; i++) bucketStart[carsSim[i].lane + 1]++;
        for (int l = 0; l < lanes.Length; l++) bucketStart[l + 1] += bucketStart[l];
        for (int i = 0; i < n; i++) { int l = carsSim[i].lane; bucket[bucketStart[l] + fill[l]++] = i; }
    }

    // ---- simulation ----

    void Update()
    {
        var cam = Camera.main;
        if (!cam || carsSim == null) return;
        float dt = Mathf.Min(Time.deltaTime, 0.1f);
        watch.Restart();
        camPos = cam.transform.position;
        GeometryUtility.CalculateFrustumPlanes(cam, planes);
        UpdatePlayer();
        BuildObstacles();
        BuildBuckets();
        BuildCarGrid();
        recycleLeft = 6;
        for (int i = 0; i < carsSim.Length; i++) Step(i, dt);
        UpdateProxies();
        UpdateParked();
        Draw();
        simMs = (float)watch.Elapsed.TotalMilliseconds;
    }

    void UpdatePlayer()
    {
        if (playerRb) playerPos = playerRb.position;
    }

    void AddObstacle(Obstacle o)
    {
        if (obstacleCount == obstacles.Length) System.Array.Resize(ref obstacles, obstacleCount * 2);
        obstacles[obstacleCount++] = o;
    }

    static int CellOf(Vector3 p)
    {
        int i = Mathf.Clamp((int)((p.x - GridMin) / Cell), 0, Cells - 1), j = Mathf.Clamp((int)((p.z - GridMin) / Cell), 0, Cells - 1);
        return j * Cells + i;
    }

    void BuildObstacles()
    {
        obstacleCount = 0;
        if (playerRb)
        {
            var t = playerRb.transform;
            AddObstacle(new Obstacle { pos = playerRb.position, fwd = Flat(t.forward), right = Flat(t.right), vel = playerRb.linearVelocity, halfL = HalfLength, halfW = HalfWidth, kind = 3 });
        }
        foreach (var p in pool)
            if (p.wreck && p.go.activeSelf)
                AddObstacle(new Obstacle { pos = p.rb.position, fwd = Flat(p.go.transform.forward), right = Flat(p.go.transform.right), vel = p.rb.linearVelocity, halfL = HalfLength, halfW = HalfWidth, kind = 4 });
        foreach (var p in parkPool)
            if (p.go.activeSelf && (parked[p.car].moved || !p.rb.IsSleeping()))
                AddObstacle(new Obstacle { pos = p.rb.position, fwd = Flat(p.go.transform.forward), right = Flat(p.go.transform.right), vel = p.rb.linearVelocity, halfL = HalfLength, halfW = HalfWidth, kind = 4 });
        foreach (int k in movedParked)
            if (parked[k].proxy < 0)
                AddObstacle(new Obstacle { pos = parked[k].pos, fwd = Flat(parked[k].rot * Vector3.forward), right = Flat(parked[k].rot * Vector3.right), halfL = HalfLength, halfW = HalfWidth, kind = 4 });
        for (int i = 0; i < (carsSim?.Length ?? 0); i++)
            if (Mathf.Abs(carsSim[i].off) > 0.6f)
                AddObstacle(new Obstacle { pos = carsSim[i].pos, fwd = carsSim[i].fwd, right = new Vector3(carsSim[i].fwd.z, 0, -carsSim[i].fwd.x), vel = carsSim[i].fwd * carsSim[i].speed, halfL = HalfLength, halfW = HalfWidth, kind = 12, car = i + 1 });
        if (crowd)
            foreach (var q in crowd.Crossing)
                AddObstacle(new Obstacle { pos = new Vector3(q.x, 0, q.y), fwd = Vector3.forward, right = Vector3.right, halfL = 0.4f, halfW = 0.4f, kind = 5 });
        if (cellStart == null) { cellStart = new int[Cells * Cells + 1]; cellFill = new int[Cells * Cells]; }
        if (cellItems == null || cellItems.Length < obstacleCount) cellItems = new int[obstacles.Length];
        System.Array.Clear(cellStart, 0, cellStart.Length);
        System.Array.Clear(cellFill, 0, cellFill.Length);
        for (int k = 0; k < obstacleCount; k++) cellStart[CellOf(obstacles[k].pos) + 1]++;
        for (int c = 0; c < Cells * Cells; c++) cellStart[c + 1] += cellStart[c];
        for (int k = 0; k < obstacleCount; k++) { int c = CellOf(obstacles[k].pos); cellItems[cellStart[c] + cellFill[c]++] = k; }
    }

    static Vector3 Flat(Vector3 v) { v.y = 0; return v.sqrMagnitude > 1e-6f ? v.normalized : Vector3.forward; }

    float SafeV(float vEnd, float dist) => dist <= 0 ? vEnd : Mathf.Sqrt(vEnd * vEnd + 2 * brake * dist);

    // speed that keeps a time headway and can brake down to the leader's speed over the free gap
    float Follow(float gap, float vAhead)
    {
        float free = gap - minGap;
        if (free <= 0) return 0;
        return Mathf.Min(Mathf.Sqrt(vAhead * vAhead + 2 * brake * free), free / headway);
    }

    void Step(int i, float dt)
    {
        ref var c = ref carsSim[i];
        var lane = lanes[c.lane];
        float distEnd = lane.length - c.s;
        float vMax = lane.speed, v;
        byte why = 0;
        if ((v = SafeV(c.next >= 0 ? lanes[c.next].speed : 0, distEnd)) < vMax) { vMax = v; why = 1; }
        float gap = Ahead(i, ref c, out float vAhead);
        if (gap < Look && (v = Follow(gap, vAhead)) < vMax) { vMax = v; why = 2; }
        var right = new Vector3(c.fwd.z, 0, -c.fwd.x);
        float stillAlong = 1e9f, stillShift = 0;   // nearest still obstacle on the lane centre, shift that passes it
        int cell = CellOf(c.pos), ci = cell % Cells, cj = cell / Cells;
        for (int j = Mathf.Max(0, cj - 1); j <= Mathf.Min(Cells - 1, cj + 1); j++)
            for (int ii = Mathf.Max(0, ci - 1); ii <= Mathf.Min(Cells - 1, ci + 1); ii++)
            {
                int cc = j * Cells + ii;
                for (int k = cellStart[cc]; k < cellStart[cc + 1]; k++)
                {
                    ref var o = ref obstacles[cellItems[k]];
                    if (o.car == i + 1) continue;
                    var rel = o.pos - c.pos;
                    float along = Vector3.Dot(rel, c.fwd);
                    if (along < -7 || along > 45) continue;
                    float half = Mathf.Abs(Vector3.Dot(right, o.fwd)) * o.halfL + Mathf.Abs(Vector3.Dot(right, o.right)) * o.halfW;
                    float lat = Vector3.Dot(rel, right), latC = lat + c.off;   // from the car / from the lane centre
                    if ((o.kind == 3 || o.kind == 4) && o.vel.sqrMagnitude < 0.25f && Mathf.Abs(latC) < half + HalfWidth && along < stillAlong)
                    {
                        stillAlong = along;
                        float l = latC - half - HalfWidth - 0.4f, r = latC + half + HalfWidth + 0.4f;
                        stillShift = Mathf.Abs(l) < Mathf.Abs(r) ? l : r;
                    }
                    if (along < -1 || Mathf.Abs(lat) > half + HalfWidth) continue;
                    float extent = half + HalfWidth;
                    float reach = Mathf.Abs(Vector3.Dot(c.fwd, o.fwd)) * o.halfL + Mathf.Abs(Vector3.Dot(c.fwd, o.right)) * o.halfW;
                    if ((v = Follow(along - reach - HalfLength, Mathf.Max(0, Vector3.Dot(o.vel, c.fwd)))) < vMax) { vMax = v; why = o.kind; }
                }
            }
        if (c.next >= 0 && MustStop(ref c, lane, gap, vAhead))
        {
            float d = lane.stopAt - c.s;
            if ((v = d <= 0.3f ? 0 : SafeV(0, d)) < vMax) { vMax = v; why = stopWhy; }
        }
        // pass a still obstacle standing on the lane (not a queue at the stop line): wait behind it a moment, move
        // aside when the side corridor is clear, come back once it is behind
        if (stillAlong < 1e8f)
        {
            if (c.offTarget == 0 && (why == 3 || why == 4) && c.stopped > 1.5f && lane.junction < 0 && c.s + stillAlong < lane.length - 16f
                && Mathf.Abs(stillShift) <= maxShift && SideClear(i, c.pos - right * c.off, c.fwd, right, stillShift))
                c.offTarget = stillShift;
        }
        else c.offTarget = 0;
        if (c.off != c.offTarget)
        {
            c.off = Mathf.MoveTowards(c.off, c.offTarget, 1.8f * dt);
            if ((v = c.offTarget == 0 ? 6f : 2.5f) < vMax) vMax = v;   // slow while moving across
        }
        c.why = why;
        c.speed = c.speed < vMax ? Mathf.Min(vMax, c.speed + accel * dt) : Mathf.Max(vMax, c.speed - hardBrake * dt);
        c.stopped = c.speed < 0.1f ? c.stopped + dt : 0;
        // gridlock out of sight (queues closing a loop around blocks): stuck cars far from the player and unseen
        // are moved elsewhere, like GTA does; jams the player can see dissolve once they look away
        if (c.stopped > jamTime && c.proxy < 0 && (c.pos - playerPos).sqrMagnitude > 80 * 80 && !Seen(c.pos))
        {
            jamRespawns++;
            Respawn(ref c);
            return;
        }
        if (recycleLeft > 0 && c.proxy < 0 && (c.pos - playerPos).sqrMagnitude > recycleDistance * recycleDistance && !Seen(c.pos))
        {
            recycleLeft--;
            Respawn(ref c);
            return;
        }
        c.s += c.speed * dt;
        c.spin += c.speed * dt / cars[c.model].wheelRadius * Mathf.Rad2Deg;
        if (c.s >= lane.length)
        {
            if (c.next < 0) { Respawn(ref c); return; }
            c.s -= lane.length;
            c.lane = c.next;
            c.next = Pick(c.lane);
            laneStamp[c.lane] = Time.frameCount;
            lane = lanes[c.lane];
        }
        c.pos = At(lane, c.s, out c.fwd);
        if (c.off != 0)
        {
            c.pos += new Vector3(c.fwd.z, 0, -c.fwd.x) * c.off;
            if (lane.junction >= 0) c.off = c.offTarget = 0;   // never enter a junction aside
        }
        At(lane, c.s + cars[c.model].wheelBase, out var ahead);
        c.steer = Vector3.SignedAngle(c.fwd, ahead, Vector3.up);
    }

    // distance to the rear of the car ahead along the path (current lane, then the lanes to come), speed of it
    float Ahead(int i, ref Car c, out float vAhead)
    {
        float gap = Look;
        vAhead = 0;
        for (int b = bucketStart[c.lane]; b < bucketStart[c.lane + 1]; b++)
        {
            int k = bucket[b];
            if (k == i || carsSim[k].s <= c.s) continue;
            float d = carsSim[k].s - c.s - CarLength;
            if (d < gap) { gap = d; vAhead = carsSim[k].speed; }
        }
        if (gap < Look) return gap;
        float off = lanes[c.lane].length - c.s;
        int l = c.next;
        for (int depth = 0; l >= 0 && off < Look && depth < 4; depth++)
        {
            for (int b = bucketStart[l]; b < bucketStart[l + 1]; b++)
            {
                int k = bucket[b];
                float d = off + carsSim[k].s - CarLength;
                if (d < gap) { gap = d; vAhead = carsSim[k].speed; }
            }
            if (gap < Look) return gap;
            off += lanes[l].length;
            l = lanes[l].next.Length > 0 ? lanes[l].next[0] : -1;
        }
        return gap;
    }

    // 0 green, 1 yellow, 2 red for the given arm group of a signalised junction
    int Phase(int junction, int arm)
    {
        float t = (Time.time + phaseOffset[junction]) % cycle;
        int g = (int)(t / (cycle / 2));
        float u = t - g * (cycle / 2);
        if (arm != g) return 2;
        return u < greenTime ? 0 : u < greenTime + yellowTime ? 1 : 2;
    }

    bool MustStop(ref Car c, Lane lane, float gap, float vAhead)
    {
        float d = lane.stopAt - c.s;
        if (d > 30 || d < -1) return false;
        var nx = lanes[c.next];
        // do not block the box: enter only if the lane after the junction has room for this car too
        stopWhy = 6;
        if (nx.junction >= 0 && lane.junction < 0 && !RoomAfter(nx)) return true;
        int ctl = lane.stopJunction >= 0 ? control[lane.stopJunction] : 0;
        if (ctl == 1)
        {
            int st = Phase(lane.stopJunction, nx.arm);
            stopWhy = (byte)(7 + st);
            if (st == 2) return true;
            if (st == 1 && nx.turn == 2 && d < 1.5f) return Busy(nx, false, -1);   // a left turner waiting at the line clears on yellow
            if (st == 1 && d > c.speed * c.speed / (2 * hardBrake) + 0.5f) return true;   // can still stop
            stopWhy = 9;
            return Busy(nx, nx.turn == 2, -1);   // left on green yields to oncoming traffic; nobody enters an occupied box
        }
        // connectors and merge lanes yield to the other lanes feeding the lane they join (ring segments and main
        // road lanes keep the priority)
        bool yields = (lane.junction >= 0 || lane.turn == 6) && nx.prev.Length > 1;
        if (nx.conflicts.Length == 0 && !yields) return false;
        stopWhy = 10;
        if (ctl == 2 && (c.stopped < 0.4f || d > 1.5f)) return true;   // stop sign: come to a full stop at the line first
        stopWhy = 11;
        if (c.stopped > 6f) return false;   // ponytail: patience beats gridlock
        // all-way stop: first stopped, first gone (cars still arriving on the other arms will stop too); yield and
        // uncontrolled entries also give way to the cars coming
        return Busy(nx, ctl != 2, yields ? c.lane : -1);
    }

    // a car on a lane crossing nx (or entering it this frame), or about to enter one (`approaching`: within 25 m
    // of the end of a road lane and moving, 15 m inside the junction); a car about to join nx from one of its
    // other feeders when the car comes from `from`
    bool Busy(Lane nx, bool approaching, int from)
    {
        int frame = Time.frameCount;
        for (int k = 0; k < nx.conflicts.Length; k++)
        {
            int ci = nx.conflicts[k];
            if (laneStamp[ci] == frame) return true;
            for (int b = bucketStart[ci]; b < bucketStart[ci + 1]; b++)
                if (carsSim[bucket[b]].s < nx.conflictPast[k]) return true;   // still before our crossing point
            if (!approaching) continue;
            foreach (int p in lanes[ci].prev) if (Coming(p, ci, Horizon(p))) return true;
        }
        if (from >= 0)
        {
            int ni = System.Array.IndexOf(lanes, nx);
            if (laneStamp[ni] == frame) return true;
            foreach (int p in nx.prev) if (p != from && Rank(p) < Rank(from) && Coming(p, ni, Horizon(p))) return true;
        }
        return false;
    }

    // room on the lane a connector leads to, counting the cars on it and the ones in the connectors feeding it
    bool RoomAfter(Lane nx)
    {
        if (nx.next.Length == 0) return true;
        int exit = nx.next[0], n = bucketStart[exit + 1] - bucketStart[exit];
        foreach (int p in lanes[exit].prev) if (lanes[p].junction >= 0) n += bucketStart[p + 1] - bucketStart[p];
        return (n + 1) * (CarLength + minGap + 0.5f) <= lanes[exit].length;
    }

    // priority between lanes joining the same lane: main lanes, ring, straight, right, left, merge lanes; ties by index
    int Rank(int l)
    {
        var lane = lanes[l];
        int r = lane.junction < 0 && lane.turn != 6 ? 0 : lane.turn == 3 ? 1 : lane.turn == 0 ? 2 : lane.turn == 1 ? 3 : lane.turn == 2 ? 4 : 5;
        return r * 4096 + l;
    }

    // how far back a car on lane p counts as coming: 15 m inside junctions, 3 s of travel on the road (25 m min)
    float Horizon(int p) => lanes[p].junction >= 0 ? 15f : Mathf.Max(25f, 3f * lanes[p].speed);

    // a car on lane p heading into `into` with less than `limit` m to go (moving, unless already inside a
    // junction); inside junctions the search continues one lane back
    bool Coming(int p, int into, float limit)
    {
        var lp = lanes[p];
        for (int b = bucketStart[p]; b < bucketStart[p + 1]; b++)
        {
            ref var k = ref carsSim[bucket[b]];
            if (k.next != into || lp.length - k.s > limit) continue;
            if (lp.junction >= 0 || k.speed > 1f) return true;
        }
        if (lp.junction >= 0 && limit > lp.length)
            foreach (int pp in lp.prev) if (Coming(pp, p, limit - lp.length)) return true;
        return false;
    }

    void Respawn(ref Car c)
    {
        if (c.proxy >= 0) { Detach(pool[c.proxy]); }
        var n = NewCar();
        if (Place(ref n, true)) c = n;
    }

    // ---- physical proxies ----

    void UpdateProxies()
    {
        float near2 = physicsDistance * physicsDistance, far2 = near2 * 1.7f;
        for (int i = 0; i < pool.Length; i++)
        {
            var p = pool[i];
            if (!p.go.activeSelf) continue;
            if (p.wreck)
            {
                float d2 = (p.rb.position - playerPos).sqrMagnitude;
                if (Time.time - p.time > wreckLifetime && d2 > 80 * 80 && !Visible(p.rb.position)) p.go.SetActive(false);
                continue;
            }
            if ((carsSim[p.car].pos - playerPos).sqrMagnitude > far2) Detach(p);
            else Wheels(p, ref carsSim[p.car]);
        }
        for (int i = 0; i < carsSim.Length; i++)
        {
            ref var c = ref carsSim[i];
            if (c.proxy >= 0 || (c.pos - playerPos).sqrMagnitude > near2) continue;
            var p = FreeProxy(c.model);
            if (p == null) return;
            Attach(p, i);
        }
    }

    Proxy FreeProxy(int model)
    {
        Proxy best = null;
        foreach (var p in pool)
        {
            if (p.model != model) continue;
            if (!p.go.activeSelf) return p;
            // ponytail: steal the oldest unseen wreck; grow `proxies` if cars pop in and out
            if (p.wreck && !Visible(p.rb.position) && (best == null || p.time < best.time)) best = p;
        }
        return best;
    }

    void Attach(Proxy p, int i)
    {
        ref var c = ref carsSim[i];
        var car = cars[c.model];
        p.car = i;
        p.wreck = false;
        c.proxy = System.Array.IndexOf(pool, p);
        // live traffic cars never crash into each other (the lane rules keep them apart, a near miss must not wreck
        // them); wrecks collide with everything
        foreach (var q in pool) if (q != p) Physics.IgnoreCollision(p.box, q.box, !q.wreck);
        var mats = new Material[car.subMeshes];
        for (int s = 0; s < car.subMeshes; s++) mats[s] = car.Mat(c.paint, s);
        p.body.sharedMaterials = mats;
        p.rb.isKinematic = false;
        p.rb.useGravity = false;
        p.rb.sleepThreshold = 0;   // driven every physics step: a sleeping body would stay behind at a green light
        p.rb.collisionDetectionMode = CollisionDetectionMode.Discrete;   // speculative contacts report the road at speed
        p.rb.linearDamping = 0;
        p.rb.angularDamping = 0.05f;
        p.box.center = car.boxCenter;
        p.box.size = car.boxSize;
        p.go.transform.SetPositionAndRotation(c.pos, Quaternion.LookRotation(c.fwd));
        p.go.SetActive(true);
        p.rb.position = c.pos;
        p.rb.rotation = Quaternion.LookRotation(c.fwd);
        p.rb.linearVelocity = c.fwd * c.speed;
        p.rb.angularVelocity = Vector3.zero;
        Wheels(p, ref c);
    }

    void Detach(Proxy p)
    {
        if (p.car >= 0 && p.car < carsSim.Length && carsSim[p.car].proxy == System.Array.IndexOf(pool, p)) carsSim[p.car].proxy = -1;
        p.car = -1;
        p.go.SetActive(false);
    }

    void Wheels(Proxy p, ref Car c)
    {
        for (int w = 0; w < 4; w++) p.wheels[w].localRotation = Quaternion.Euler(0, w < 2 ? c.steer : 0, 0) * Quaternion.Euler(c.spin, 0, 0);
    }

    const float Gain = 8f;   // 1/s, proxies converge on their car's spot

    void FixedUpdate()
    {
        if (pool == null) return;
        foreach (var p in pool)
        {
            if (!p.go.activeSelf || p.wreck) continue;
            ref var c = ref carsSim[p.car];
            var to = c.pos - p.rb.position;
            if (to.sqrMagnitude > 2.25f)
            {
                if (Time.time - p.lastHit < 1f)   // shoved off its line: it is free now
                {
                    Debug.Log($"traffic: {p.go.name} shoved {to.magnitude:0.0} m off its line at {p.rb.position}");
                    Wreck(p);
                    continue;
                }
                p.rb.position = c.pos;   // long frame: the physics ran ahead of the simulation, catch up
                p.rb.rotation = Quaternion.LookRotation(c.fwd);
                to = Vector3.zero;
            }
            // the car's true velocity + a correction toward its spot (the spot moves once per rendered frame,
            // the physics may step several times in between)
            p.rb.linearVelocity = c.fwd * c.speed + Vector3.ClampMagnitude(to * Gain, 6f);   // a long frame must not become a velocity spike
            var rot = Quaternion.LookRotation(c.fwd) * Quaternion.Inverse(p.rb.rotation);
            rot.ToAngleAxis(out float ang, out var axis);
            if (ang > 180) ang -= 360;
            p.rb.angularVelocity = Mathf.Abs(ang) > 1e-3f ? axis * (ang * Mathf.Deg2Rad * Gain) : Vector3.zero;
        }
    }

    public void Touch(int index, Collision col) { if (index < ParkedIndex && col.rigidbody) pool[index].lastHit = Time.time; }

    public void OnProxyHit(int index, Collision col)
    {
        if (index >= ParkedIndex) return;
        var p = pool[index];
        if (p.wreck || p.car < 0 || !col.rigidbody) return;   // live cars follow their lane: the static world never wrecks them
        bool limb = !col.rigidbody.GetComponent<SimpleCar>() && !col.rigidbody.GetComponent<TrafficProxy>();
        if (limb) return;   // ragdoll limbs do not wreck a car
        p.lastHit = Time.time;
        // a real hit transfers momentum (~0.3 m/s of the car's mass at least); grazes and speculative contacts do not
        if (col.relativeVelocity.magnitude < crashSpeed || col.impulse.magnitude < p.rb.mass * 0.3f) return;
        Debug.Log($"traffic: {p.go.name} wrecked by {col.collider.name} at {col.relativeVelocity.magnitude:0.0} m/s, {p.rb.position}");
        Wreck(p);
    }

    // the proxy keeps its momentum and lives its own physical life; the traffic car it stood for respawns out of sight
    void Wreck(Proxy p)
    {
        int i = p.car;
        p.wreck = true;
        p.time = Time.time;
        foreach (var q in pool) if (q != p) Physics.IgnoreCollision(p.box, q.box, false);
        p.car = -1;
        FreeBody(p);
        if (i >= 0 && i < carsSim.Length)
        {
            carsSim[i].proxy = -1;
            var n = NewCar();
            if (Place(ref n, true)) carsSim[i] = n;
        }
    }

    // a car body left to the physics: gravity, drag, the box lowered to the ground (it rests where the tires touch)
    void FreeBody(Proxy p)
    {
        p.rb.isKinematic = false;
        p.rb.useGravity = true;
        p.rb.sleepThreshold = 0.005f;   // Unity's default: a body at rest sleeps
        p.rb.collisionDetectionMode = CollisionDetectionMode.ContinuousSpeculative;
        p.rb.linearDamping = 0.5f;
        p.rb.angularDamping = 1.5f;
        var car = cars[p.model];
        float top = car.boxCenter.y + car.boxSize.y / 2;
        p.box.size = new Vector3(car.boxSize.x, top, car.boxSize.z);
        p.box.center = new Vector3(car.boxCenter.x, top / 2, car.boxCenter.z);
    }

    // ---- parked cars ----

    void BuildParkGrid()
    {
        if (parkCellStart == null) { parkCellStart = new int[Cells * Cells + 1]; parkItems = new int[parked.Length]; }
        System.Array.Clear(parkCellStart, 0, parkCellStart.Length);
        foreach (var q in parked) parkCellStart[CellOf(q.pos) + 1]++;
        for (int c = 0; c < Cells * Cells; c++) parkCellStart[c + 1] += parkCellStart[c];
        var f = new int[Cells * Cells];
        for (int k = 0; k < parked.Length; k++) { int c = CellOf(parked[k].pos); parkItems[parkCellStart[c] + f[c]++] = k; }
    }

    // the parked cars around the player become rigidbodies at rest; far again, they keep the pose they were left in
    void UpdateParked()
    {
        float r2 = parkRadius * parkRadius, far2 = r2 * 1.7f;
        bool regrid = false;
        foreach (var p in parkPool)
        {
            if (!p.go.activeSelf) continue;
            float d2 = (p.rb.position - playerPos).sqrMagnitude;
            if (d2 > far2 && (p.rb.IsSleeping() || d2 > far2 * 4)) regrid |= DetachParked(p);   // not in mid-air
        }
        if (regrid) BuildParkGrid();
        int cell = CellOf(playerPos), ci = cell % Cells, cj = cell / Cells;
        for (int j = Mathf.Max(0, cj - 1); j <= Mathf.Min(Cells - 1, cj + 1); j++)
            for (int i = Mathf.Max(0, ci - 1); i <= Mathf.Min(Cells - 1, ci + 1); i++)
                for (int n = parkCellStart[j * Cells + i]; n < parkCellStart[j * Cells + i + 1]; n++)
                {
                    int k = parkItems[n];
                    if (parked[k].proxy >= 0 || (parked[k].pos - playerPos).sqrMagnitude > r2) continue;
                    Proxy free = null;
                    foreach (var p in parkPool) if (!p.go.activeSelf && p.model == parked[k].model) { free = p; break; }
                    if (free == null) return;   // ponytail: pool exhausted, the farthest ones stay static; raise parkedProxies
                    AttachParked(free, k);
                }
    }

    void AttachParked(Proxy p, int k)
    {
        ref var q = ref parked[k];
        var car = cars[q.model];
        var mats = new Material[car.subMeshes];
        for (int s = 0; s < car.subMeshes; s++) mats[s] = car.Mat(q.paint, s);
        p.body.sharedMaterials = mats;
        foreach (var w in p.wheels) w.localRotation = Quaternion.identity;
        p.car = k;
        p.wreck = true;
        q.proxy = System.Array.IndexOf(parkPool, p);
        FreeBody(p);
        p.go.transform.SetPositionAndRotation(q.pos, q.rot);
        p.go.SetActive(true);
        p.rb.position = q.pos;
        p.rb.rotation = q.rot;
        p.rb.linearVelocity = p.rb.angularVelocity = Vector3.zero;
        p.rb.Sleep();
    }

    // returns true when the car left its cell (the grid must be rebuilt)
    bool DetachParked(Proxy p)
    {
        ref var q = ref parked[p.car];
        int cell = CellOf(q.pos);
        var pos = p.rb.position;
        var rot = p.rb.rotation;
        if (!q.moved && ((pos - q.pos).sqrMagnitude > 0.09f || Quaternion.Angle(rot, q.rot) > 3f)) { q.moved = true; movedParked.Add(p.car); }
        q.pos = pos;
        q.rot = rot;
        q.m = Matrix4x4.TRS(pos, rot, Vector3.one);
        q.proxy = -1;
        p.car = -1;
        p.go.SetActive(false);
        return CellOf(pos) != cell;
    }

    // ---- drawing ----

    bool Seen(Vector3 p) => (p - camPos).sqrMagnitude < drawDistance * drawDistance && Visible(p);

    bool Visible(Vector3 p)
    {
        var c = p + new Vector3(0, 0.8f, 0);
        foreach (var pl in planes) if (pl.GetDistanceToPoint(c) < -2.5f) return false;
        return true;
    }

    void Draw()
    {
        float draw2 = drawDistance * drawDistance;
        System.Array.Clear(bodyCount, 0, bodyCount.Length);
        System.Array.Clear(wheelCount, 0, wheelCount.Length);
        for (int i = 0; i < carsSim.Length; i++)
        {
            ref var c = ref carsSim[i];
            if (c.proxy >= 0 || (c.pos - camPos).sqrMagnitude > draw2 || !Visible(c.pos)) continue;
            int m = c.model, k = 0;
            for (int j = 0; j < m; j++) k += cars[j].paints;
            k += c.paint;
            if (bodyCount[k] == MaxBatch || wheelCount[m] == MaxBatch) continue;
            var car = cars[m];
            var rot = Quaternion.LookRotation(c.fwd);
            var M = Matrix4x4.TRS(c.pos, rot, Vector3.one);
            bodyMats[k][bodyCount[k]++] = M;
            var spin = Quaternion.Euler(c.spin, 0, 0);
            for (int w = 0; w < 4; w++)
                wheelMats[m][w][wheelCount[m]] = M * Matrix4x4.TRS(car.wheelPos[w], w < 2 ? Quaternion.Euler(0, c.steer, 0) * spin : spin, Vector3.one);
            wheelCount[m]++;
        }
        for (int i = 0; i < parked.Length; i++)
        {
            ref var q = ref parked[i];
            if (q.proxy >= 0 || (q.pos - camPos).sqrMagnitude > draw2 || !Visible(q.pos)) continue;
            int m = q.model, k = q.paint;
            for (int j = 0; j < m; j++) k += cars[j].paints;
            if (bodyCount[k] == MaxBatch || wheelCount[m] == MaxBatch) continue;
            var car = cars[m];
            bodyMats[k][bodyCount[k]++] = q.m;
            for (int w = 0; w < 4; w++) wheelMats[m][w][wheelCount[m]] = q.m * Matrix4x4.Translate(car.wheelPos[w]);
            wheelCount[m]++;
        }
        int b = 0;
        for (int m = 0; m < cars.Length; m++)
        {
            var car = cars[m];
            for (int p = 0; p < car.paints; p++, b++)
            {
                if (bodyCount[b] == 0) continue;
                for (int s = 0; s < car.subMeshes; s++)
                    Graphics.DrawMeshInstanced(car.body, s, car.Mat(p, s), bodyMats[b], bodyCount[b], null, ShadowCastingMode.On, true, gameObject.layer);
            }
            if (wheelCount[m] == 0) continue;
            for (int w = 0; w < 4; w++)
                Graphics.DrawMeshInstanced(car.wheels[w], 0, car.wheelMaterial, wheelMats[m][w], wheelCount[m], null, ShadowCastingMode.On, true, gameObject.layer);
        }
    }

    public int Count => carsSim?.Length ?? 0;

    // may a pedestrian step onto the crosswalk a -> b (x, z)? Not while a car moves toward it within ~3 s or is on it;
    // a car that has been waiting more than 4 s also holds the newcomers back (it goes once the crosswalk clears)
    public bool CanCross(Vector2 a, Vector2 b)
    {
        if (carsSim == null) return true;
        var ab = b - a;
        float len2 = Mathf.Max(ab.sqrMagnitude, 1e-4f);
        for (int i = 0; i < carsSim.Length; i++)   // ponytail: linear scan per waiting pedestrian; grid the cars if it shows in the profiler
        {
            ref var c = ref carsSim[i];
            var p = new Vector2(c.pos.x, c.pos.z);
            var q = a + ab * Mathf.Clamp01(Vector2.Dot(p - a, ab) / len2);
            var to = q - p;
            float d = to.magnitude;
            if (d > 40f) continue;
            if (d < HalfLength + 1.5f) return false;   // on it
            bool toward = Vector2.Dot(to, new Vector2(c.fwd.x, c.fwd.z)) > 0.3f * d;
            if (toward && (c.stopped > 4f || (c.speed > 1f && d < HalfLength + 4f + c.speed * 3f))) return false;
        }
        return true;
    }

    // dev check: moving / waiting cars, cars stuck for a long time, pairs closer than 2.8 m (overlaps; side by side in adjacent lanes is 3.4 m)
    public string Stats()
    {
        int moving = 0, stuck = 0, overlaps = 0, proxied = 0, wrecks = 0;
        for (int i = 0; i < carsSim.Length; i++)
        {
            ref var c = ref carsSim[i];
            if (c.speed > 0.5f) moving++;
            if (c.stopped > 60f) stuck++;
            if (c.proxy >= 0) proxied++;
            for (int k = i + 1; k < carsSim.Length; k++)
                if ((carsSim[k].pos - c.pos).sqrMagnitude < 2.8f * 2.8f && overlaps++ < 8)
                {
                    Lane a = lanes[c.lane], b = lanes[carsSim[k].lane];
                    Debug.Log($"overlap at {c.pos}: lane {c.lane} (j{a.junction} t{a.turn} s{c.s:0}/{a.length:0} v{c.speed:0.0}) x lane {carsSim[k].lane} (j{b.junction} t{b.turn} s{carsSim[k].s:0}/{b.length:0} v{carsSim[k].speed:0.0})");
                }
        }
        foreach (var p in pool) if (p.wreck && p.go.activeSelf) wrecks++;
        var reasons = new int[Why.Length];
        for (int i = 0; i < carsSim.Length; i++) if (carsSim[i].stopped > 60f) reasons[carsSim[i].why]++;
        var r = new System.Text.StringBuilder();
        for (int k = 0; k < Why.Length; k++) if (reasons[k] > 0) r.Append($" {Why[k]} {reasons[k]}");
        return $"cars {carsSim.Length}, moving {moving}, stuck>60s {stuck} ({r} ), overlaps {overlaps}, proxied {proxied}, wrecks {wrecks}, jam respawns {jamRespawns}, parked {parked.Length} (physical {System.Array.FindAll(parkPool, x => x.go.activeSelf).Length}, moved {movedParked.Count}), {simMs:0.00} ms";
    }

    // dev check: follow what blocks car i (the car ahead, or the head of the full lane after the junction) until
    // a car held by something else, or a cycle (gridlock)
    public string Chain(int i, int max = 40)
    {
        var sb = new System.Text.StringBuilder();
        var seen = new HashSet<int>();
        for (int n = 0; n < max && i >= 0 && seen.Add(i); n++)
        {
            ref var c = ref carsSim[i];
            var lane = lanes[c.lane];
            string nx = c.next >= 0 ? $" (j{lanes[c.next].junction} t{lanes[c.next].turn} arm {lanes[c.next].arm})" : "";
            sb.AppendLine($"#{i} [{Why[c.why]}] v {c.speed:0.0} stopped {c.stopped:0}s lane {c.lane} (j{lane.junction} t{lane.turn}) s {c.s:0}/{lane.length:0} next {c.next}{nx} at {c.pos}");
            int k = -1;
            if (c.why == 2)
            {
                float best = float.MaxValue;
                for (int b = bucketStart[c.lane]; b < bucketStart[c.lane + 1]; b++)
                {
                    int o = bucket[b];
                    if (o != i && carsSim[o].s > c.s && carsSim[o].s < best) { best = carsSim[o].s; k = o; }
                }
                if (k < 0 && c.next >= 0) k = Tail(c.next);
            }
            else if (c.why == 6 && c.next >= 0 && lanes[c.next].next.Length > 0) k = Head(lanes[c.next].next[0]);
            i = k;
        }
        if (i >= 0 && seen.Contains(i)) sb.AppendLine($"CYCLE back to #{i}");
        return sb.ToString();
    }

    int Head(int l) { int k = -1; for (int b = bucketStart[l]; b < bucketStart[l + 1]; b++) if (k < 0 || carsSim[bucket[b]].s > carsSim[k].s) k = bucket[b]; return k; }
    int Tail(int l) { int k = -1; for (int b = bucketStart[l]; b < bucketStart[l + 1]; b++) if (k < 0 || carsSim[bucket[b]].s < carsSim[k].s) k = bucket[b]; return k; }

    // first cars stopped longer than `seconds` with nobody right ahead (queue heads)
    public int[] Heads(float seconds)
    {
        var list = new List<int>();
        for (int i = 0; i < carsSim.Length; i++)
            if (carsSim[i].stopped > seconds && carsSim[i].why != 2) list.Add(i);
        return list.ToArray();
    }

    // dev check: why the cars stopped for more than `seconds` are not moving
    public string Stuck(float seconds, int max = 12, bool heads = false)
    {
        var sb = new System.Text.StringBuilder();
        int n = 0;
        for (int i = 0; i < carsSim.Length && n < max; i++)
        {
            ref var c = ref carsSim[i];
            if (c.stopped < seconds) continue;
            var lane = lanes[c.lane];
            float gap = Ahead(i, ref c, out float va);
            if (heads && gap < 3f) continue;   // only the cars with nobody right ahead
            n++;
            string ctl = lane.stopJunction >= 0 ? control[lane.stopJunction].ToString() : "-";
            string nx = c.next >= 0 ? $"next {c.next} (j{lanes[c.next].junction} t{lanes[c.next].turn} prev{lanes[c.next].prev.Length} conf{lanes[c.next].conflicts.Length})" : "no next";
            sb.AppendLine($"car {i} [{Why[c.why]}] stopped {c.stopped:0}s at {c.pos} lane {c.lane} (j{lane.junction} t{lane.turn}) s {c.s:0}/{lane.length:0} stopAt {lane.stopAt:0} ctl {ctl} {nx} gap {gap:0.0} mustStop {(c.next >= 0 && MustStop(ref c, lane, gap, va))}");
        }
        return sb.ToString();
    }
    public Vector3 Position(int i, out Vector3 fwd, out float speed) { fwd = carsSim[i].fwd; speed = carsSim[i].speed; return carsSim[i].pos; }
}

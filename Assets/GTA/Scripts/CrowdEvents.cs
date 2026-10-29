using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

// Crowd events: protests around the big empty paved lots of the city (found in the sidewalk bitmap at start). A wall
// of riot police (CRS, four rows of shields across the whole width) faces a mass of angry protesters spilling over
// the lot, the sidewalks and the streets around (signs up, shouting, throwing paving stones at the police, surging
// forward and back, milling around); here and there police club someone curled up on the ground. Protesters on the
// roadway are obstacles for the traffic (CrowdSystem.Crossing). Everyone is a pedestrian of the
// crowd (instanced, same impacts and ragdolls) with a Role. Riot police are tough: a slow car only staggers them
// (hp), a faster one knocks them down and they get back up (fall clip played backwards from where their ragdoll
// lies) and walk back to their place, unless the hit was too hard. The dead come back at their place out of sight.
public partial class CrowdSystem
{
    public enum Role : byte { None, Sign, Shout, Thrower, Crs, Beater, Victim }

    [Header("Protests")]
    public int protests = 7;
    public float protestSpacing = 230f;
    public int protesters = 280, police = 60;   // per protest
    public float crsStaggerSpeed = 8f, crsKillSpeed = 20f;   // m/s: below the first a riot policeman staggers (while hp > 1), above the second he dies
    public Mesh paveMesh;            // thrown paving stones (Gear.fbx "Pave")
    public Material paveMaterial;    // PS1Lit, instanced
    public AudioClip protestLoop;    // chanting crowd, one 3D source per protest

    const int MaxPaves = 160;
    const float Gravity = 9.81f;

    struct Pave { public Vector3 pos, vel, spin; public Quaternion rot; public bool rest, bounced; }
    struct Protest { public int first, count, police; public Vector2 c; public float yaw, phase; }   // police: first..first+police are the riot police (beaters included)
    [System.Serializable] class ParkedJson { public float[] parked; }   // traffic graph: x, y, z, fwd x, fwd z per parked car

    readonly List<Protest> events = new List<Protest>();
    readonly Pave[] paves = new Pave[MaxPaves];
    readonly Matrix4x4[] paveMats = new Matrix4x4[MaxPaves];
    int paveCount, paveNext;
    int[] walkerChars;
    int crsChar = -1;
    int[] signChars;
    Vector2[] parkedCars;

    void InitEvents()
    {
        var w = new List<int>();
        var s = new List<int>();
        for (int c = 0; c < characters.Length; c++)
        {
            string n = characters[c].name;
            if (!characters[c].eventOnly) w.Add(c);
            else if (n == "crs") crsChar = c;
            else s.Add(c);
        }
        walkerChars = w.ToArray();
        signChars = s.ToArray();
    }

    // ---- placement ----

    // centres (and long axis) of fully paved 16 x 24 m rectangles, spread over the city, at most `protests`
    List<(Vector2 c, float yaw)> ProtestSites()
    {
        // ponytail: 2 m cells scanned once at start (~50 M bit tests); bake the sites in GTA > Setup Crowd if it shows at load
        int W = w / 4, H = h / 4;
        var I = new int[(W + 1) * (H + 1)];
        for (int j = 0; j < H; j++)
            for (int i = 0, row = 0; i < W; i++)
            {
                bool full = true;
                for (int b = 0; b < 16 && full; b++)
                {
                    int k = (j * 4 + (b >> 2)) * w + i * 4 + (b & 3);
                    full = (bits[k >> 3] & (1 << (k & 7))) != 0;
                }
                row += full ? 1 : 0;
                I[(j + 1) * (W + 1) + i + 1] = I[j * (W + 1) + i + 1] + row;
            }
        int Sum(int i, int j, int a, int b) => I[(j + b) * (W + 1) + i + a] - I[j * (W + 1) + i + a] - I[(j + b) * (W + 1) + i] + I[j * (W + 1) + i];
        var found = new List<(Vector2, float)>();
        for (int j = 0; j + 12 <= H; j += 2)
            for (int i = 0; i + 12 <= W; i += 2)
            {
                bool alongZ = Sum(i, j, 8, 12) == 96, alongX = Sum(i, j, 12, 8) == 96;
                if (!alongZ && !alongX) continue;
                var c = new Vector2(minX + (i + (alongZ ? 4 : 6)) * 4 * cell, minZ + (j + (alongZ ? 6 : 4)) * 4 * cell);
                found.Add((c, (alongZ ? 0 : 90) + (Random.value < 0.5f ? 180 : 0)));
            }
        for (int k = found.Count - 1; k > 0; k--) { int r = Random.Range(0, k + 1); (found[k], found[r]) = (found[r], found[k]); }
        var sites = new List<(Vector2 c, float yaw)>();
        foreach (var f in found)
        {
            if (sites.Count == protests) break;
            if (InCar(f.Item1, 15f)) continue;
            bool far = true;
            foreach (var s in sites) far &= (s.c - f.Item1).sqrMagnitude > protestSpacing * protestSpacing;
            if (far) sites.Add(f);
        }
        return sites;
    }

    // local frame of a protest: +z from the protesters toward the police line, x to the right
    static Vector2 Local(Vector2 c, float yaw, float x, float z)
    {
        var f = Dir(yaw);
        return c + Right(f) * x + f * z;
    }

    // where someone can stand: the sidewalk bitmap, else the ground under a ray from above at road height (streets,
    // alleys, lawns; not roofs, props, raised decks) away from the parked cars
    bool Ground(Vector2 q, out float y)
    {
        y = groundY;
        if (Walkable(q)) return true;
        if (!Physics.Raycast(new Vector3(q.x, 400, q.y), Vector3.down, out var hit, 500, Physics.DefaultRaycastLayers, QueryTriggerInteraction.Ignore)) return false;
        y = hit.point.y;
        if (y < groundY - 0.4f || y > groundY + 0.05f) return false;
        foreach (var c in parkedCars) if ((c - q).sqrMagnitude < 2.6f * 2.6f) return false;
        return true;
    }

    void AddProtests(List<Ped> list)
    {
        var pj = traffic ? JsonUtility.FromJson<ParkedJson>(traffic.laneGraph.text) : null;
        int np = pj?.parked == null ? 0 : pj.parked.Length / 5;
        parkedCars = new Vector2[np];
        for (int k = 0; k < np; k++) parkedCars[k] = new Vector2(pj.parked[k * 5], pj.parked[k * 5 + 2]);
        foreach (var (c, deg) in ProtestSites())
        {
            float yaw = deg * Mathf.Deg2Rad, back = yaw + Mathf.PI;
            int first = list.Count;
            // riot police: long rows of shields (26 wide), staggered, as wide as the ground allows
            for (int row = 0, n = 0; row < 4 && n < police; row++)
                for (int k = 0, inRow = 0; k < 49 && n < police && inRow < 26; k++)
                {
                    float x = (k % 2 == 0 ? 1 : -1) * ((k + 1) / 2) + (row % 2) * 0.5f;
                    var q = Local(c, yaw, x * 1.0f, 5f + row * 1.4f + Random.Range(-0.1f, 0.1f));
                    if (!Ground(q, out float y)) continue;
                    var p = EventPed(q, back, Role.Crs);
                    p.y = p.homeY = y;
                    list.Add(p);
                    n++;
                    inRow++;
                }
            // here and there in front of the line, someone curled up on the ground clubbed by two or three of them
            int beatings = Random.Range(2, 5);
            for (int b = 0, t = 0; b < beatings && t < 40; t++)
            {
                var v = Local(c, yaw, Random.Range(-14f, 14f), Random.Range(1.5f, 3.5f));
                if (!Ground(v, out float vy)) continue;
                int victim = list.Count;
                var vp = EventPed(v, Random.value * Mathf.PI * 2, Role.Victim);
                vp.y = vp.homeY = vy;
                list.Add(vp);
                int n = Random.value < 0.4f ? 3 : 2;
                float a0 = Random.value * Mathf.PI * 2;
                for (int m = 0; m < n; m++)
                {
                    float a = a0 + m * Mathf.PI * 2 / n + Random.Range(-0.3f, 0.3f);
                    var p = EventPed(v + Dir(a) * 0.85f, a + Mathf.PI, Role.Beater);
                    p.y = p.homeY = vy;
                    p.link = victim;
                    list.Add(p);
                }
                b++;
            }
            int policeEnd = list.Count;
            // the protesters: a fill over the ground (0.85 m cells in the protest frame) from the middle of the front,
            // nearest cells first (wider than deep, ragged edge): a packed mass facing the police that pours into the
            // streets and alleys it touches, never through a building
            const float step = 0.85f;
            var seen = new HashSet<long>();
            var open = new SortedSet<(float pr, int i, int k)>();
            long Key(int a, int b) => ((long)a << 32) ^ (uint)b;
            float Pri(int a, int b) => Mathf.Sqrt(a * a / 4f + b * b) * step + Random.Range(0f, 2.5f);
            for (int a = -4; a <= 4; a++) { open.Add((Pri(a, 0), a, 0)); seen.Add(Key(a, 0)); }
            int placed = 0;
            var nb = new (int, int)[] { (1, 0), (-1, 0), (0, 1), (0, -1) };
            while (open.Count > 0 && placed < protesters)
            {
                var cur = open.Min;
                open.Remove(cur);
                var (_, ci, ck) = cur;
                float x = ci * step, z = -1f - ck * step;
                var q = Local(c, yaw, x + Random.Range(-0.25f, 0.25f), z + Random.Range(-0.25f, 0.25f));
                if (!Ground(Local(c, yaw, x, z), out float y)) continue;
                for (int m = 0; m < 4; m++)
                {
                    int r = Random.Range(m, 4);
                    (nb[m], nb[r]) = (nb[r], nb[m]);
                    var (di, dk) = nb[m];
                    int ni = ci + di, nk = ck + dk;
                    if (nk < 0 || nk > 140 || ni < -70 || ni > 70 || !seen.Add(Key(ni, nk))) continue;
                    open.Add((Pri(ni, nk), ni, nk));
                }
                if (Random.value < 0.1f) continue;   // a few gaps
                var target = Local(c, yaw, x * 0.4f, 5f) - q;
                float rr = Random.value, face = Mathf.Atan2(target.x, target.y) + Random.Range(-0.35f, 0.35f);
                var role = ck < 4 ? (rr < 0.3f ? Role.Sign : rr < 0.6f ? Role.Shout : Role.Thrower)
                                  : (rr < 0.45f ? Role.Sign : rr < 0.85f ? Role.Shout : Role.Thrower);
                var p = EventPed(q, face, role);
                p.y = p.homeY = y;
                p.lane = Mathf.Clamp01(1 - ck * step / 25f);   // how much this one surges with the front (1 at the front, 0 from 25 m back)
                list.Add(p);
                placed++;
            }
            events.Add(new Protest { first = first, count = list.Count - first, police = policeEnd - first, c = c, yaw = yaw, phase = Random.value * 20 });
            if (protestLoop)
            {
                var go = new GameObject("Protest");
                go.transform.SetParent(transform, false);
                go.transform.position = new Vector3(c.x, groundY + 1.5f, c.y);
                var a = GameAudio.Make3D(go.AddComponent<AudioSource>(), 15f, 220f);
                a.clip = protestLoop;
                a.loop = true;
                a.volume = GameAudio.I ? GameAudio.I.volume : 1f;
                a.time = Random.value * protestLoop.length;
                a.Play();
            }
        }
    }

    bool NearProtest(Vector2 q)
    {
        foreach (var e in events) if ((e.c - q).sqrMagnitude < 55 * 55) return true;
        return false;
    }

    Ped EventPed(Vector2 pos, float yaw, Role role)
    {
        int ch = role == Role.Crs || role == Role.Beater ? crsChar
               : role == Role.Sign ? signChars[Random.Range(0, signChars.Length)]
               : walkerChars[Random.Range(0, walkerChars.Length)];
        var p = new Ped
        {
            pos = pos, y = groundY, yaw = yaw, still = true, role = role, home = pos, homeYaw = yaw, link = -1, evt = events.Count, homeY = groundY,
            ch = ch, skin = Random.Range(0, characters[ch].skins.Length), anim = Random.value * 10,
            timer = Random.Range(1f, 8f), hp = 3, speed = role == Role.Crs || role == Role.Beater ? walkSpeed : 0.9f, wanderT = Random.Range(0f, 9f),
        };
        p.clip = RoleClip(ref p);
        return p;
    }

    static Clip RoleClip(ref Ped p) => p.role switch
    {
        Role.Sign => Clip.Sign, Role.Crs => Clip.Guard, Role.Beater => Clip.Strike, Role.Victim => Clip.Cower, _ => Clip.Talk,
    };

    float Len(ref Ped p, Clip c) => characters[p.ch].clipFrames[(int)c] / characters[p.ch].fps;

    // dev checks: where the protests are (+z toward the police line)
    public int Protests => events.Count;
    public Vector3 ProtestCenter(int i, out float yawDeg)
    {
        yawDeg = events[i].yaw * Mathf.Rad2Deg;
        return new Vector3(events[i].c.x, groundY, events[i].c.y);
    }
    public int Down, Dead;   // riot police knocked down / event pedestrians dead, this frame

    // ---- behaviour ----

    // returns false when the pedestrian is not in the world (dead, or a ragdoll for now)
    bool EventStep(ref Ped p, float dt)
    {
        if (p.dead) Dead++;
        if (p.down) Down++;
        if (p.dead)
        {
            if (Time.time - p.hitAt > 25f && Hidden(p.home)) { var n = EventPed(p.home, p.homeYaw, p.role); n.link = p.link; n.evt = p.evt; n.y = p.homeY; n.lane = p.lane; p = n; }
            return !p.dead;
        }
        if (p.down) return StandUp(ref p);
        if (p.clip == Clip.Fall)   // getting up: the fall backwards
        {
            p.anim -= dt * 1.3f;
            if (p.anim <= 0) { p.clip = Clip.Walk; p.anim = 0; }
            return true;
        }
        p.anim += p.clip == Clip.Walk ? dt * p.speed / walkSpeed : dt;
        bool protester = p.role == Role.Sign || p.role == Role.Shout || p.role == Role.Thrower;
        if (protester && p.clip != Clip.Throw && Near(p.pos, fullSimDistance) && Mill(ref p, dt)) return true;
        if (p.clip == Clip.Walk)   // back to his place in the line
        {
            var to = p.home - p.pos;
            float dist = to.magnitude;
            if (dist < 0.3f) { p.yaw = p.homeYaw; p.clip = RoleClip(ref p); return true; }
            var dir = to / dist;
            float d = Mathf.DeltaAngle(p.yaw * Mathf.Rad2Deg, Mathf.Atan2(dir.x, dir.y) * Mathf.Rad2Deg) * Mathf.Deg2Rad;
            p.yaw += Mathf.Clamp(d, -TurnRate * dt, TurnRate * dt);
            var next = p.pos + dir * Mathf.Min(dist, p.speed * dt);
            if (!InCar(next, 0.45f)) p.pos = next;
            return true;
        }
        if (p.clip == Clip.Stagger)
        {
            if (p.anim >= Len(ref p, Clip.Stagger) - 0.01f) { p.clip = Clip.Walk; p.anim = 0; }
            return true;
        }
        switch (p.role)
        {
            case Role.Thrower:
                if (p.clip == Clip.Throw)
                {
                    float len = Len(ref p, Clip.Throw);
                    if (!p.thrown && p.anim > len * 0.55f) { p.thrown = true; Throw(ref p); }
                    if (p.anim >= len - 0.01f) { p.clip = Clip.Talk; p.timer = Random.Range(2.5f, 7f); }
                }
                else if ((p.timer -= dt) <= 0) { p.clip = Clip.Throw; p.anim = 0; p.thrown = false; }
                break;
            case Role.Beater:
                bool victim = p.link >= 0 && !peds[p.link].dead;
                if (!victim) { if (p.clip == Clip.Strike) p.clip = Clip.Guard; break; }
                if (p.clip != Clip.Strike) { p.clip = Clip.Strike; p.anim = 0; }
                float sl = Len(ref p, Clip.Strike), ph = p.anim % sl;
                if (ph >= sl * 0.45f && ph - dt < sl * 0.45f && Near(p.pos, 40f) && GameAudio.I)
                {
                    GameAudio.Play(GameAudio.I.baton, new Vector3(p.pos.x, p.y + 0.5f, p.pos.y), 0.8f, 0, Random.Range(0.9f, 1.1f), 0.12f);
                    var v = peds[p.link];
                    if (Random.value < 0.15f) GameAudio.Play(female[v.ch] ? GameAudio.I.screamFemale : GameAudio.I.screamMale, new Vector3(v.pos.x, v.y + 0.5f, v.pos.y), 0.5f, 0.1f, 1f, 1.5f);
                }
                break;
        }
        return true;
    }

    // protesters move: the whole crowd surges toward the police and back (front rows the most), and everyone drifts
    // around his place. Returns true while walking. Sign holders shuffle without the walk clip (it would swing the sign).
    bool Mill(ref Ped p, float dt)
    {
        var e = events[p.evt];
        if ((p.wanderT -= dt) <= 0)
        {
            p.wanderT = Random.Range(3f, 9f);
            p.wander = Random.insideUnitCircle * 1.2f;
        }
        float surge = Mathf.Max(0, Mathf.Sin((Time.time + e.phase) * (2 * Mathf.PI / 16f))) * 2.5f * p.lane;
        var target = p.home + Dir(e.yaw) * surge + p.wander;
        var to = target - p.pos;
        float dist = to.magnitude;
        bool sign = p.role == Role.Sign;
        if (dist < (p.clip == Clip.Walk || p.moving ? 0.15f : 0.5f))
        {
            if (p.moving) { p.moving = false; p.clip = RoleClip(ref p); }
            float d0 = Mathf.DeltaAngle(p.yaw * Mathf.Rad2Deg, p.homeYaw * Mathf.Rad2Deg) * Mathf.Deg2Rad;
            p.yaw += Mathf.Clamp(d0, -TurnRate * 0.5f * dt, TurnRate * 0.5f * dt);
            return false;
        }
        p.moving = true;
        var dir = to / dist;
        if (!sign) p.clip = Clip.Walk;
        float want = sign ? p.homeYaw : Mathf.Atan2(dir.x, dir.y);
        float d = Mathf.DeltaAngle(p.yaw * Mathf.Rad2Deg, want * Mathf.Rad2Deg) * Mathf.Deg2Rad;
        p.yaw += Mathf.Clamp(d, -TurnRate * dt, TurnRate * dt);
        var next = p.pos + dir * Mathf.Min(dist, (sign ? 0.5f : p.speed) * dt);
        if (!InCar(next, 0.45f)) p.pos = next;
        return true;
    }

    bool Near(Vector2 q, float r) => (q - new Vector2(camPos.x, camPos.z)).sqrMagnitude < r * r;

    bool Hidden(Vector2 q)
    {
        var f = new Vector3(q.x, groundY, q.y);
        float d2 = (f - camPos).sqrMagnitude;
        return d2 > 3600 && (d2 > drawDistance * drawDistance || !Visible(f));
    }

    // the car or a body hit an event pedestrian: riot police resist, the others go down like anybody
    void EventHit(ref Ped p, Vector3 v)
    {
        bool police = p.role == Role.Crs || p.role == Role.Beater;
        if (police && Time.time - p.hitAt < 0.8f) return;   // just staggered: the car is still on him
        float speed = v.magnitude / 1.3f;
        p.hitAt = Time.time;
        var pos3 = new Vector3(p.pos.x, p.y + 1f, p.pos.y);
        if (police && GameAudio.I) GameAudio.Play(GameAudio.I.armor, pos3, 0.6f + speed / 25f, 0, 1, 0.05f);
        if (police && speed < crsStaggerSpeed && p.hp > 1)
        {
            p.hp--;
            p.clip = Clip.Stagger;
            p.anim = 0;
            var flat = new Vector2(v.x, v.z);
            if (flat.sqrMagnitude > 0.01f) { p.pos += flat.normalized * 0.7f; p.yaw = Mathf.Atan2(-flat.x, -flat.y); }
            if (carRb) carRb.linearVelocity *= 0.8f;   // a guy in armour behind a shield
            if (GameAudio.I) GameAudio.Play(GameAudio.I.shout, pos3 + Vector3.up * 0.6f, 0.7f, 0.05f, 0.9f, 0.5f);
            return;
        }
        var b = Kill(ref p, v);
        if (police && carRb) carRb.linearVelocity *= 0.92f;
        if (police && speed < crsKillSpeed && --p.hp > 0) { p.down = true; p.body = b; p.bodyTime = b.time; }
        else p.dead = true;
    }

    // a knocked down policeman lies still: swap the ragdoll for the instanced body on the last frame of the fall clip,
    // laid along the ragdoll (hips -> head), and play the fall backwards
    bool StandUp(ref Ped p)
    {
        var b = p.body;
        if (!b.go.activeSelf || b.time != p.bodyTime) { p.down = false; p.dead = true; return false; }   // body recycled
        float age = Time.time - b.time;
        if (!(age > 3f && b.hips.linearVelocity.sqrMagnitude < 0.2f) && age < 10f) return false;
        var ch = characters[p.ch];
        var hips = b.hips.position;
        var head = b.anim.GetBoneTransform(HumanBodyBones.Head).position;
        var lie = ch.lieHead - ch.lieHips;
        float yaw = Mathf.Atan2(head.x - hips.x, head.z - hips.z) - Mathf.Atan2(lie.x, lie.z);
        var off = Quaternion.Euler(0, yaw * Mathf.Rad2Deg, 0) * ch.lieHips;
        p.pos = new Vector2(hips.x - off.x, hips.z - off.z);
        p.y = Mathf.Max(groundY - 0.2f, hips.y - ch.lieHips.y);
        p.yaw = yaw;
        p.clip = Clip.Fall;
        p.anim = Len(ref p, Clip.Fall) - 0.01f;
        p.down = false;
        b.go.SetActive(false);
        return true;
    }

    // ---- thrown paving stones ----

    void Throw(ref Ped p)
    {
        if (!paveMesh) return;
        var f = Dir(p.yaw);
        var from = new Vector3(p.pos.x + f.x * 0.3f, p.y + 1.7f, p.pos.y + f.y * 0.3f);
        Vector3 to;
        var carD = carRb ? new Vector2(carRb.position.x, carRb.position.z) - p.pos : Vector2.one * 1e4f;
        if (carRb && carD.sqrMagnitude < 25 * 25 && Random.value < 0.5f) to = carRb.position + Vector3.up * 0.8f;   // the car came too close
        else
        {
            var e = Event(ref p);
            int k = e.first;
            for (int t = 0; t < 8; t++)
            {
                k = e.first + Random.Range(0, e.police);
                if (peds[k].role == Role.Crs && !peds[k].dead && !peds[k].down) break;
            }
            to = new Vector3(peds[k].pos.x, peds[k].y + 1.3f, peds[k].pos.y) + Random.insideUnitSphere * 0.8f;
        }
        float T = Vector3.Distance(from, to) / 13f + 0.35f;
        var vel = (to - from) / T + Vector3.up * (0.5f * Gravity * T);
        paves[paveNext] = new Pave { pos = from, vel = vel, rot = Random.rotation, spin = Random.insideUnitSphere * 12f };
        paveNext = (paveNext + 1) % MaxPaves;   // the oldest stone on the ground goes
        paveCount = Mathf.Min(paveCount + 1, MaxPaves);
    }

    Protest Event(ref Ped p) => events[p.evt];

    void UpdatePaves(float dt)
    {
        for (int i = 0; i < paveCount; i++)
        {
            ref var s = ref paves[i];
            if (s.rest) continue;
            s.vel.y -= Gravity * dt;
            s.pos += s.vel * dt;
            s.rot = Quaternion.Euler(s.spin * (dt * Mathf.Rad2Deg)) * s.rot;
            var q = new Vector2(s.pos.x, s.pos.z);
            if (s.vel.y < 0 && s.pos.y < groundY + 0.05f)
            {
                s.pos.y = groundY + 0.05f;
                if (s.vel.sqrMagnitude > 6) { s.vel = new Vector3(s.vel.x * 0.4f, -s.vel.y * 0.25f, s.vel.z * 0.4f); s.spin *= 0.5f; }
                else s.rest = true;
                continue;
            }
            // against a shield or the car: knocked back
            if (s.bounced) continue;   // knocked back once already: falls to the ground
            bool hit = carRb && s.pos.y < carRb.position.y + 1.5f && InCar(q, 0.1f);
            if (!hit)
                foreach (var e in events)
                {
                    var c = peds[e.first].pos;
                    if ((c - q).sqrMagnitude > 20 * 20) continue;
                    for (int k = e.first; k < e.first + e.police && !hit; k++)
                        hit = (peds[k].role == Role.Crs || peds[k].role == Role.Beater) && !peds[k].dead && !peds[k].down &&
                              s.pos.y < peds[k].y + 2f && (peds[k].pos - q).sqrMagnitude < 0.5f * 0.5f;
                    if (hit) break;
                }
            if (hit)
            {
                s.bounced = true;
                s.vel = new Vector3(-s.vel.x * 0.25f, Mathf.Abs(s.vel.y) * 0.2f, -s.vel.z * 0.25f);
                if (GameAudio.I && Near(q, 60f)) GameAudio.Play(GameAudio.I.rock, s.pos, 0.7f, 0, Random.Range(0.9f, 1.15f), 0.05f);
            }
        }
    }

    void DrawPaves()
    {
        if (!paveMesh || !paveMaterial) return;
        int n = 0;
        float d2 = drawDistance * drawDistance * 0.36f;
        for (int i = 0; i < paveCount; i++)
            if ((paves[i].pos - camPos).sqrMagnitude < d2) paveMats[n++] = Matrix4x4.TRS(paves[i].pos, paves[i].rot, Vector3.one);
        if (n > 0) Graphics.DrawMeshInstanced(paveMesh, 0, paveMaterial, paveMats, n, null, ShadowCastingMode.Off, false, gameObject.layer);
    }
}

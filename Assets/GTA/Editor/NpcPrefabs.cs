using System.Collections.Generic;
using System.IO;
using System.Linq;
using Unity.Collections;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Animations;
using UnityEngine.Playables;

// Pedestrian crowd build (see Scripts/CrowdSystem.cs and skill ps1-npc).
// Menu GTA > Build NPC Crowd: for each character FBX in Assets/GTA/NPC/ (hero.fbx = man, hero_f.fbx = woman):
//   - outfits: one PS1Lit material per Assets/GTA/Textures/T_<fbx>*.png (Skins/M_*.mat) + the same textures in a
//     Texture2DArray (Crowd/<fbx>_Skins.asset);
//   - vertex animation texture: the Humanoid mocap clips (Quaternius UAL, CC0) retargeted on the body and baked at
//     20 fps (Crowd/<fbx>_VatPos / _VatNrm), + the body mesh carrying its vertex index (Crowd/<fbx>_Body);
//   - the ragdoll prefab Prefabs/NPC/<fbx>_Ragdoll.prefab (Animator for posing + 11 rigidbodies / joints);
//   - Crowd/<fbx>.asset (CrowdCharacter) tying it together.
// Menu GTA > Setup Crowd In Open Scene: bakes the sidewalk bitmap of the scene (Crowd/<scene>_walk.bytes) and puts a
// "Crowd" object (CrowdSystem with every character) in the scene.
static class NpcPrefabs
{
    const string NpcDir = "Assets/GTA/NPC", CrowdDir = NpcDir + "/Crowd", SkinDir = NpcDir + "/Skins";
    const string PrefabDir = "Assets/GTA/Prefabs/NPC", AnimLib = NpcDir + "/Anims/UAL_Standard.fbx";
    static readonly string[] Clips = { "Idle_Loop", "Walk_Loop", "Sitting_Idle_Loop", "Sitting_Talking_Loop", "Idle_Talking_Loop" };   // = CrowdSystem.Clip
    const float Fps = 20f;

    static string[] Characters => Directory.GetFiles(NpcDir, "*.fbx").Select(p => p.Replace('\\', '/')).OrderBy(p => p).ToArray();

    [MenuItem("GTA/Build NPC Crowd")]
    public static void Build()
    {
        Directory.CreateDirectory(PrefabDir);
        Directory.CreateDirectory(SkinDir);
        Directory.CreateDirectory(CrowdDir);
        var all = AssetDatabase.LoadAllAssetsAtPath(AnimLib).OfType<AnimationClip>().ToArray();
        var clips = Clips.Select(n => all.First(c => c.name == n)).ToArray();
        var names = Characters.Select(Path.GetFileNameWithoutExtension).ToArray();
        foreach (var fbx in Characters)
        {
            string name = Path.GetFileNameWithoutExtension(fbx);
            var model = AssetDatabase.LoadAssetAtPath<GameObject>(fbx);
            var template = model.GetComponentInChildren<SkinnedMeshRenderer>().sharedMaterial;
            var texs = SkinTextures(name, names);
            var skins = texs.Select(t => SkinMaterial(t, template)).ToArray();

            var cc = Save(ScriptableObject.CreateInstance<CrowdCharacter>(), CrowdDir + "/" + name + ".asset");
            cc.skins = skins;
            cc.clips = clips;
            cc.fps = Fps;
            BakeVat(model, clips, out var pos, out var nrm, out cc.clipStart, out cc.clipFrames, out var body);
            pos = Save(pos, CrowdDir + "/" + name + "_VatPos.asset");
            nrm = Save(nrm, CrowdDir + "/" + name + "_VatNrm.asset");
            cc.mesh = Save(body, CrowdDir + "/" + name + "_Body.asset");
            var array = Save(SkinArray(texs), CrowdDir + "/" + name + "_Skins.asset");
            var mat = Save(new Material(Shader.Find("GTA/PS1Crowd")), CrowdDir + "/M_" + name + "_Crowd.mat");
            mat.shader = Shader.Find("GTA/PS1Crowd");
            mat.SetTexture("_Skins", array);
            mat.SetTexture("_VatPos", pos);
            mat.SetTexture("_VatNrm", nrm);
            mat.enableInstancing = true;
            EditorUtility.SetDirty(mat);
            cc.material = mat;
            cc.ragdoll = BuildRagdoll(model, name, skins[0]);
            EditorUtility.SetDirty(cc);
            Debug.Log($"{name}: {skins.Length} outfits, VAT {pos.width}x{pos.height}");
        }
        AssetDatabase.SaveAssets();
    }

    static T Save<T>(T obj, string path) where T : Object
    {
        var old = AssetDatabase.LoadAssetAtPath<T>(path);
        if (!old) { AssetDatabase.CreateAsset(obj, path); return obj; }
        EditorUtility.CopySerialized(obj, old);
        old.name = Path.GetFileNameWithoutExtension(path);
        EditorUtility.SetDirty(old);
        return old;
    }

    // T_<name>.png and T_<name>_<Variant>.png, minus those of a character whose name extends this one (hero vs hero_f)
    static string[] SkinTextures(string name, string[] allNames)
    {
        var others = allNames.Where(n => n != name && n.StartsWith(name + "_")).ToArray();
        bool Of(string p, string n) { var b = Path.GetFileNameWithoutExtension(p).Substring(2); return b == n || b.StartsWith(n + "_"); }
        return Directory.GetFiles("Assets/GTA/Textures", "T_" + name + "*.png").Select(p => p.Replace('\\', '/'))
            .Where(p => Of(p, name) && !others.Any(o => Of(p, o))).OrderBy(p => p).ToArray();
    }

    static Material SkinMaterial(string tex, Material template)
    {
        string path = SkinDir + "/M_" + Path.GetFileNameWithoutExtension(tex).Substring(2) + ".mat";
        var m = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (!m) { m = new Material(template); AssetDatabase.CreateAsset(m, path); }
        m.shader = template.shader;
        m.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>(tex));
        m.SetColor("_BaseColor", Color.white);
        EditorUtility.SetDirty(m);
        return m;
    }

    static Texture2DArray SkinArray(string[] texs)
    {
        var imgs = texs.Select(p => { var t = new Texture2D(2, 2, TextureFormat.RGBA32, false); t.LoadImage(File.ReadAllBytes(p)); return t; }).ToArray();
        var a = new Texture2DArray(imgs[0].width, imgs[0].height, imgs.Length, TextureFormat.RGBA32, false, false)
        { filterMode = FilterMode.Point, wrapMode = TextureWrapMode.Clamp, anisoLevel = 0 };
        for (int i = 0; i < imgs.Length; i++) { a.SetPixels32(imgs[i].GetPixels32(), i); Object.DestroyImmediate(imgs[i]); }
        a.Apply(false, true);   // not readable: no CPU copy at runtime
        return a;
    }

    // Plays each Humanoid clip on the body (PlayableGraph, in edit mode), bakes the skinned mesh every frame:
    // positions (half floats) and normals of vertex v at frame f go to texel (v, row). Root space = the prefab root.
    static void BakeVat(GameObject model, AnimationClip[] clips, out Texture2D pos, out Texture2D nrm, out int[] start, out int[] frames, out Mesh body)
    {
        var go = (GameObject)Object.Instantiate(model);
        try
        {
            go.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
            var anim = go.GetComponent<Animator>();
            anim.runtimeAnimatorController = null;
            anim.applyRootMotion = false;
            anim.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            var smr = go.GetComponentInChildren<SkinnedMeshRenderer>();
            var src = smr.sharedMesh;
            int V = src.vertexCount, H = 0;
            start = new int[clips.Length];
            frames = new int[clips.Length];
            for (int c = 0; c < clips.Length; c++) { start[c] = H; frames[c] = Mathf.Max(1, Mathf.RoundToInt(clips[c].length * Fps)); H += frames[c]; }
            var P = new ushort[V * H * 4];
            var N = new Color32[V * H];
            var first = new Vector3[V];
            var baked = new Mesh();
            var vs = new List<Vector3>();
            var ns = new List<Vector3>();
            float minY = float.MaxValue, maxY = float.MinValue;
            var g = PlayableGraph.Create("vat");
            g.SetTimeUpdateMode(DirectorUpdateMode.Manual);
            var output = AnimationPlayableOutput.Create(g, "vat", anim);
            for (int c = 0; c < clips.Length; c++)
            {
                var cp = AnimationClipPlayable.Create(g, clips[c]);
                output.SetSourcePlayable(cp);
                for (int f = 0; f < frames[c]; f++)
                {
                    cp.SetTime(f * clips[c].length / frames[c]);   // loops: the last frame is not the first one again
                    g.Evaluate();
                    smr.BakeMesh(baked, true);
                    baked.GetVertices(vs);
                    baked.GetNormals(ns);
                    var m = smr.transform.localToWorldMatrix;   // BakeMesh(useScale) returns renderer-local positions (hero_f's renderer is scaled 0.01)
                    int row = start[c] + f;
                    for (int v = 0; v < V; v++)
                    {
                        var p = m.MultiplyPoint3x4(vs[v]);
                        var n = (smr.transform.rotation * ns[v]).normalized;
                        int i = row * V + v;
                        P[i * 4] = Mathf.FloatToHalf(p.x);
                        P[i * 4 + 1] = Mathf.FloatToHalf(p.y);
                        P[i * 4 + 2] = Mathf.FloatToHalf(p.z);
                        P[i * 4 + 3] = Mathf.FloatToHalf(1);
                        N[i] = new Color32((byte)(n.x * 127.5f + 127.5f), (byte)(n.y * 127.5f + 127.5f), (byte)(n.z * 127.5f + 127.5f), 255);
                        if (row == 0) first[v] = p;
                        minY = Mathf.Min(minY, p.y);
                        maxY = Mathf.Max(maxY, p.y);
                    }
                }
            }
            g.Destroy();
            Object.DestroyImmediate(baked);
            Debug.Log($"{model.name} VAT: {V} vertices x {H} frames, y {minY:0.00}..{maxY:0.00}");
            pos = new Texture2D(V, H, TextureFormat.RGBAHalf, false, true) { filterMode = FilterMode.Point, wrapMode = TextureWrapMode.Clamp };
            pos.SetPixelData(P, 0);
            pos.Apply(false, true);
            nrm = new Texture2D(V, H, TextureFormat.RGBA32, false, true) { filterMode = FilterMode.Point, wrapMode = TextureWrapMode.Clamp };
            nrm.SetPixels32(N);
            nrm.Apply(false, true);
            body = new Mesh { name = model.name + "_Body" };
            body.SetVertices(first);
            body.SetUVs(0, src.uv);
            body.SetUVs(1, Enumerable.Range(0, V).Select(i => new Vector2(i, 0)).ToArray());
            body.SetTriangles(src.triangles, 0);
            body.bounds = new Bounds(new Vector3(0, 1, 0), new Vector3(2, 2.2f, 2));
            body.UploadMeshData(true);
        }
        finally { Object.DestroyImmediate(go); }
    }

    // ---- ragdoll ----

    static GameObject BuildRagdoll(GameObject model, string name, Material skin)
    {
        var go = (GameObject)PrefabUtility.InstantiatePrefab(model);
        go.name = name + "_Ragdoll";
        var anim = go.GetComponent<Animator>();
        anim.runtimeAnimatorController = null;
        anim.applyRootMotion = false;
        anim.cullingMode = AnimatorCullingMode.AlwaysAnimate;
        anim.enabled = false;
        var smr = go.GetComponentInChildren<SkinnedMeshRenderer>();
        smr.sharedMaterial = skin;
        smr.updateWhenOffscreen = true;
        Transform B(HumanBodyBones b) => anim.GetBoneTransform(b);
        var torsoEnd = B(HumanBodyBones.Neck) ?? B(HumanBodyBones.Head);
        var hips = Part(B(HumanBodyBones.Hips), B(HumanBodyBones.Spine), null, 12f, 0.14f);
        var spine = Part(B(HumanBodyBones.Spine), torsoEnd, hips, 20f, 0.15f);
        Part(B(HumanBodyBones.Head), null, spine, 5f, 0.11f);
        foreach (var s in new[] { "Left", "Right" })
        {
            HumanBodyBones H(string b) => (HumanBodyBones)System.Enum.Parse(typeof(HumanBodyBones), s + b);
            var ua = Part(B(H("UpperArm")), B(H("LowerArm")), spine, 2.5f, 0.05f);
            Part(B(H("LowerArm")), B(H("Hand")), ua, 2f, 0.045f);
            var ul = Part(B(H("UpperLeg")), B(H("LowerLeg")), hips, 7.5f, 0.08f);
            Part(B(H("LowerLeg")), B(H("Foot")), ul, 4.5f, 0.06f);
        }
        foreach (var t in go.GetComponentsInChildren<Transform>()) t.gameObject.layer = 2;   // Ignore Raycast: the car's wheels roll through bodies
        var prefab = PrefabUtility.SaveAsPrefabAsset(go, PrefabDir + "/" + name + "_Ragdoll.prefab");
        Object.DestroyImmediate(go);
        return prefab;
    }

    // capsule from the bone to the next one (sphere above a head), rigidbody, joint to the parent body
    static Rigidbody Part(Transform bone, Transform end, Rigidbody parent, float mass, float radius)
    {
        float s = bone.lossyScale.x;
        if (end)
        {
            var d = bone.InverseTransformPoint(end.position);
            var a = new[] { Mathf.Abs(d.x), Mathf.Abs(d.y), Mathf.Abs(d.z) };
            var cap = bone.gameObject.AddComponent<CapsuleCollider>();
            cap.direction = System.Array.IndexOf(a, a.Max());
            cap.center = d * 0.5f;
            cap.radius = radius / s;
            cap.height = d.magnitude + radius / s;
        }
        else
        {
            var sph = bone.gameObject.AddComponent<SphereCollider>();
            sph.center = bone.InverseTransformPoint(bone.position + Vector3.up * 0.1f);
            sph.radius = radius / s;
        }
        var rb = bone.gameObject.AddComponent<Rigidbody>();
        rb.mass = mass;
        rb.isKinematic = true;
        rb.interpolation = RigidbodyInterpolation.Interpolate;
        rb.collisionDetectionMode = CollisionDetectionMode.ContinuousSpeculative;
        if (parent)
        {
            var j = bone.gameObject.AddComponent<CharacterJoint>();
            j.connectedBody = parent;
            j.lowTwistLimit = new SoftJointLimit { limit = -30 };
            j.highTwistLimit = new SoftJointLimit { limit = 40 };
            j.swing1Limit = new SoftJointLimit { limit = 50 };
            j.swing2Limit = new SoftJointLimit { limit = 30 };
            j.enableProjection = true;
        }
        return rb;
    }

    // ---- scene ----

    [MenuItem("GTA/Setup Crowd In Open Scene")]
    public static void Setup()
    {
        var scene = EditorSceneManager.GetActiveScene();
        var map = BakeWalkMap(scene.name);
        foreach (var n in new[] { "NPCs", "Crowd" }) { var old = GameObject.Find(n); if (old) Object.DestroyImmediate(old); }
        var crowd = new GameObject("Crowd").AddComponent<CrowdSystem>();
        crowd.characters = Characters.Select(f => AssetDatabase.LoadAssetAtPath<CrowdCharacter>(CrowdDir + "/" + Path.GetFileNameWithoutExtension(f) + ".asset")).ToArray();
        crowd.walkMap = map;
        crowd.pedGraph = AssetDatabase.LoadAssetAtPath<TextAsset>("Assets/GTA/City/" + scene.name + "_peds.json");   // city_demo.export_peds
        crowd.spots = Spots();
        EditorSceneManager.MarkSceneDirty(scene);
        EditorSceneManager.SaveScene(scene);
        Debug.Log($"crowd: {crowd.spots.Length} seats / waiting spots");
    }

    // Seats of the placed benches and bus stops (kit.bench / kit.bus_stop: the sitter faces the prop's +Z, seat 0.46 m
    // high, which is where the UAL sitting clips put the pelvis), and standing spots in front of the bus stops.
    // The clip's pelvis sits 0.13 m behind the root: the root goes 0.13 m in front of the seat's middle.
    static CrowdSystem.Spot[] Spots()
    {
        var list = new List<CrowdSystem.Spot>();
        var placed = GameObject.Find("Placed");
        if (!placed) return list.ToArray();
        void Add(Transform t, float x, float z, bool seat) =>
            list.Add(new CrowdSystem.Spot { pos = t.TransformPoint(new Vector3(x, 0, z)), yaw = t.eulerAngles.y, seat = seat });
        foreach (Transform t in placed.transform)
        {
            if (t.name.StartsWith("Bench")) { Add(t, -0.42f, 0.05f, true); Add(t, 0.42f, 0.05f, true); }
            else if (t.name.StartsWith("BusStop"))
            {
                foreach (var x in new[] { -0.8f, 0f, 0.8f }) Add(t, x, -0.26f, true);   // bench card 0.35 m behind the pivot
                Add(t, -0.7f, 1.3f, false);
                Add(t, 1.1f, 1.0f, false);
            }
        }
        return list.ToArray();
    }

    // 0.5 m cells, set where a ray from above lands on a "Sidewalk" submesh of the city (props hidden), eroded by
    // a cell, minus the footprints of the props (trunks and poles as small discs, the rest as their bounds). Header: minX, minZ, cell,
    // ground y (floats), w, h (ints), then one bit per cell, row major.
    static TextAsset BakeWalkMap(string sceneName)
    {
        const float cellSize = 0.5f;
        var city = GameObject.Find("CityDemo") ?? GameObject.Find("DAScene");
        var bounds = city.GetComponentsInChildren<MeshRenderer>().Select(r => r.bounds).Aggregate((a, b) => { a.Encapsulate(b); return a; });
        int w = Mathf.CeilToInt(bounds.size.x / cellSize), h = Mathf.CeilToInt(bounds.size.z / cellSize);
        float minX = bounds.min.x, minZ = bounds.min.z, top = bounds.max.y + 5;
        var bits = new byte[(w * h + 7) / 8];
        var placed = GameObject.Find("Placed");
        if (placed) placed.SetActive(false);
        var ranges = new Dictionary<Collider, Vector2Int[]>();
        double ySum = 0;
        int yCount = 0;
        var cmds = new NativeArray<RaycastCommand>(w, Allocator.TempJob);
        var hits = new NativeArray<RaycastHit>(w, Allocator.TempJob);
        try
        {
            {
                var q = new QueryParameters(Physics.DefaultRaycastLayers, false, QueryTriggerInteraction.Ignore, false);
                for (int j = 0; j < h; j++)
                {
                    for (int i = 0; i < w; i++)
                        cmds[i] = new RaycastCommand(new Vector3(minX + (i + 0.5f) * cellSize, top, minZ + (j + 0.5f) * cellSize), Vector3.down, q, top - bounds.min.y + 5);
                    RaycastCommand.ScheduleBatch(cmds, hits, 256, 1).Complete();
                    for (int i = 0; i < w; i++)
                    {
                        var hit = hits[i];
                        var col = hit.collider;
                        if (!col || hit.triangleIndex < 0) continue;
                        if (!ranges.TryGetValue(col, out var rs)) ranges[col] = rs = SidewalkRanges(col);
                        int tri = hit.triangleIndex * 3;
                        if (!rs.Any(r => tri >= r.x && tri < r.y)) continue;
                        int k = j * w + i;
                        bits[k >> 3] |= (byte)(1 << (k & 7));
                        ySum += hit.point.y;
                        yCount++;
                    }
                }
            }
        }
        finally
        {
            cmds.Dispose();
            hits.Dispose();
            if (placed) placed.SetActive(true);
        }

        // erode by one cell: the pedestrian's center stays 0.5 m away from curbs and facades
        var eroded = (byte[])bits.Clone();
        bool Bit(int i, int j) { int k = j * w + i; return (bits[k >> 3] & (1 << (k & 7))) != 0; }
        for (int j = 1; j < h - 1; j++)
            for (int i = 1; i < w - 1; i++)
                if (Bit(i, j) && !(Bit(i - 1, j) && Bit(i + 1, j) && Bit(i, j - 1) && Bit(i, j + 1)))
                {
                    int k = j * w + i;
                    eroded[k >> 3] &= (byte)~(1 << (k & 7));
                }
        bits = eroded;

        void Clear(Vector2 c, float r)
        {
            for (int j = Mathf.FloorToInt((c.y - r - minZ) / cellSize); j <= Mathf.FloorToInt((c.y + r - minZ) / cellSize); j++)
                for (int i = Mathf.FloorToInt((c.x - r - minX) / cellSize); i <= Mathf.FloorToInt((c.x + r - minX) / cellSize); i++)
                {
                    if (i < 0 || j < 0 || i >= w || j >= h) continue;
                    int k = j * w + i;
                    bits[k >> 3] &= (byte)~(1 << (k & 7));
                }
        }
        if (placed)
            foreach (Transform prop in placed.transform)
            {
                string n = prop.name;
                var p = new Vector2(prop.position.x, prop.position.z);
                if (n.Contains("Bush")) Clear(p, 0.8f);
                else if (n.Contains("Palm") || n.Contains("Broadleaf") || n.Contains("Lamp") || n.Contains("Pole") || n.Contains("Sign")) Clear(p, 0.3f);
                else if (!n.Contains("Grass"))
                {
                    var rs = prop.GetComponentsInChildren<Renderer>();
                    if (rs.Length == 0) continue;
                    var b = rs.Select(r => r.bounds).Aggregate((a, c) => { a.Encapsulate(c); return a; });
                    if (b.size.x > 6 || b.size.z > 6) continue;   // big overhangs (signals...) are not ground obstacles
                    for (float z = b.min.z; z <= b.max.z + cellSize; z += cellSize)
                        for (float x = b.min.x; x <= b.max.x + cellSize; x += cellSize)
                            Clear(new Vector2(Mathf.Min(x, b.max.x), Mathf.Min(z, b.max.z)), 0.1f);
                }
            }

        string path = CrowdDir + "/" + sceneName + "_walk.bytes";
        Directory.CreateDirectory(CrowdDir);
        using (var bw = new BinaryWriter(File.Create(path)))
        {
            bw.Write(minX); bw.Write(minZ); bw.Write(cellSize); bw.Write(yCount > 0 ? (float)(ySum / yCount) : 0f);
            bw.Write(w); bw.Write(h);
            bw.Write(bits);
        }
        AssetDatabase.ImportAsset(path);
        Debug.Log($"walk map {w}x{h}, {yCount} sidewalk cells ({yCount * cellSize * cellSize:0} m2)");
        return AssetDatabase.LoadAssetAtPath<TextAsset>(path);
    }

    static Vector2Int[] SidewalkRanges(Collider col)
    {
        var mc = col as MeshCollider;
        var r = col.GetComponent<Renderer>();
        if (!mc || !r) return new Vector2Int[0];
        var mesh = mc.sharedMesh;
        var list = new List<Vector2Int>();
        for (int s = 0; s < mesh.subMeshCount && s < r.sharedMaterials.Length; s++)
            if (r.sharedMaterials[s] && r.sharedMaterials[s].name.StartsWith("Sidewalk"))
            {
                var sm = mesh.GetSubMesh(s);
                list.Add(new Vector2Int(sm.indexStart, sm.indexStart + sm.indexCount));
            }
        return list.ToArray();
    }
}

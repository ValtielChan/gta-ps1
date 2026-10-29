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
// Event characters (Kits: riot police, protesters) are a body FBX + gear meshes (NPC/Gear/Gear.fbx, Tools/citygen/
// gear.py) glued to its bones and skinned to them, with 512 x 256 outfits (body atlas | gear, Tools/texture/gear_atlas.py);
// they bake only the clips they play (the others get one frame) and never walk the streets.
// Menu GTA > Setup Crowd In Open Scene: bakes the sidewalk bitmap of the scene (Crowd/<scene>_walk.bytes) and puts a
// "Crowd" object (CrowdSystem with every character) in the scene.
static class NpcPrefabs
{
    const string NpcDir = "Assets/GTA/NPC", CrowdDir = NpcDir + "/Crowd", SkinDir = NpcDir + "/Skins";
    const string PrefabDir = "Assets/GTA/Prefabs/NPC", AnimLib = NpcDir + "/Anims/UAL_Standard.fbx";
    static readonly string[] Clips = { "Idle_Loop", "Walk_Loop", "Sitting_Idle_Loop", "Sitting_Talking_Loop", "Idle_Talking_Loop",
        "Idle_Torch_Loop", "Sword_Idle", "Sword_Attack", "Spell_Simple_Shoot", "Crouch_Idle_Loop", "Death01", "Hit_Chest" };   // = CrowdSystem.Clip
    const float Fps = 20f;
    const string GearFbx = NpcDir + "/Gear/Gear.fbx";

    // gear placed in the character's root space (offset from the bone, rotation) on the first frame of `pose`
    // (aPose: the model's rest pose), then skinned rigidly to `bone`
    struct Gear
    {
        public string mesh; public HumanBodyBones bone; public CrowdSystem.Clip pose; public bool aPose; public Vector3 pos, rot;
        public Gear(string mesh, HumanBodyBones bone, CrowdSystem.Clip pose, Vector3 pos, Vector3 rot, bool aPose = false)
        { this.mesh = mesh; this.bone = bone; this.pose = pose; this.pos = pos; this.rot = rot; this.aPose = aPose; }
    }
    class Kit { public string name, body; public Gear[] gear; public CrowdSystem.Clip[] clips; }
    static readonly CrowdSystem.Clip[] Walker = { CrowdSystem.Clip.Idle, CrowdSystem.Clip.Walk, CrowdSystem.Clip.Sit, CrowdSystem.Clip.SitTalk,
        CrowdSystem.Clip.Talk, CrowdSystem.Clip.Throw, CrowdSystem.Clip.Cower };   // also the protesters without a sign and the beaten ones
    static readonly Kit[] Kits =
    {
        new Kit { name = "crs", body = "hero", clips = new[] { CrowdSystem.Clip.Idle, CrowdSystem.Clip.Walk, CrowdSystem.Clip.Guard, CrowdSystem.Clip.Strike, CrowdSystem.Clip.Fall, CrowdSystem.Clip.Stagger },
            gear = new[] {
                new Gear("Helmet", HumanBodyBones.Head, 0, new Vector3(0, 0.1f, 0.01f), Vector3.zero, true),
                new Gear("Shield", HumanBodyBones.LeftLowerArm, CrowdSystem.Clip.Guard, new Vector3(0.05f, 0.05f, 0.2f), Vector3.zero),
                new Gear("Baton", HumanBodyBones.RightHand, CrowdSystem.Clip.Guard, new Vector3(0, 0, 0.06f), new Vector3(-30, 0, 0)) } },
        new Kit { name = "demo", body = "hero", clips = new[] { CrowdSystem.Clip.Idle, CrowdSystem.Clip.Sign },
            gear = new[] { new Gear("Sign", HumanBodyBones.LeftHand, CrowdSystem.Clip.Sign, new Vector3(0, 0, 0.06f), Vector3.zero) } },
        new Kit { name = "demo_f", body = "hero_f", clips = new[] { CrowdSystem.Clip.Idle, CrowdSystem.Clip.Sign },
            gear = new[] { new Gear("Sign", HumanBodyBones.LeftHand, CrowdSystem.Clip.Sign, new Vector3(0, 0, 0.06f), Vector3.zero) } },
    };

    static string[] Bodies => Directory.GetFiles(NpcDir, "*.fbx").Select(p => p.Replace('\\', '/')).OrderBy(p => p).ToArray();
    // every crowd character: the bodies as they are (walkers), then the kits
    static Kit[] Characters => Bodies.Select(f => new Kit { name = Path.GetFileNameWithoutExtension(f), body = Path.GetFileNameWithoutExtension(f), gear = new Gear[0], clips = Walker })
        .Concat(Kits).ToArray();

    [MenuItem("GTA/Build NPC Crowd")]
    public static void Build()
    {
        Directory.CreateDirectory(PrefabDir);
        Directory.CreateDirectory(SkinDir);
        Directory.CreateDirectory(CrowdDir);
        var all = AssetDatabase.LoadAllAssetsAtPath(AnimLib).OfType<AnimationClip>().ToArray();
        var clips = Clips.Select(n => all.First(c => c.name == n)).ToArray();
        var names = Characters.Select(k => k.name).ToArray();
        foreach (var kit in Characters)
        {
            string name = kit.name;
            var model = AssetDatabase.LoadAssetAtPath<GameObject>(NpcDir + "/" + kit.body + ".fbx");
            var skinned = kit.gear.Length > 0 ? Save(Equip(model, kit.gear, clips), CrowdDir + "/" + name + "_Skinned.asset") : null;
            var template = model.GetComponentInChildren<SkinnedMeshRenderer>().sharedMaterial;
            var texs = SkinTextures(name, names);
            var skins = texs.Select(t => SkinMaterial(t, template)).ToArray();

            var cc = Save(ScriptableObject.CreateInstance<CrowdCharacter>(), CrowdDir + "/" + name + ".asset");
            cc.skins = skins;
            cc.clips = clips;
            cc.fps = Fps;
            cc.eventOnly = kit.gear.Length > 0;
            var full = clips.Select((c, i) => kit.clips.Contains((CrowdSystem.Clip)i)).ToArray();
            BakeVat(model, skinned, clips, full, out var pos, out var nrm, out cc.clipStart, out cc.clipFrames, out var body, out cc.lieHips, out cc.lieHead);
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
            cc.ragdoll = BuildRagdoll(model, name, skins[0], skinned);
            EditorUtility.SetDirty(cc);
            Debug.Log($"{name}: {skins.Length} outfits, VAT {pos.width}x{pos.height}");
        }
        AssetDatabase.SaveAssets();
    }

    static T Save<T>(T obj, string path) where T : Object
    {
        var old = AssetDatabase.LoadAssetAtPath<T>(path);
        if (old is Mesh) { AssetDatabase.DeleteAsset(path); old = null; }   // CopySerialized keeps a mesh's old vertex data
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
    // full[c] false: the clip is not played by this character, one frame only. lieHips / lieHead: where the last frame
    // of the fall clip puts the hips and the head (root space), to stand a knocked down body back up from its ragdoll.
    static void BakeVat(GameObject model, Mesh skinned, AnimationClip[] clips, bool[] full, out Texture2D pos, out Texture2D nrm, out int[] start, out int[] frames,
        out Mesh body, out Vector3 lieHips, out Vector3 lieHead)
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
            if (skinned) smr.sharedMesh = skinned;
            var src = smr.sharedMesh;
            int V = src.vertexCount, H = 0;
            start = new int[clips.Length];
            frames = new int[clips.Length];
            lieHips = lieHead = Vector3.zero;
            for (int c = 0; c < clips.Length; c++) { start[c] = H; frames[c] = full[c] ? Mathf.Max(1, Mathf.RoundToInt(clips[c].length * Fps)) : 1; H += frames[c]; }
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
                    bool lying = c == (int)CrowdSystem.Clip.Fall && f == frames[c] - 1 && frames[c] > 1;
                    cp.SetTime(lying ? clips[c].length : f * clips[c].length / frames[c]);   // loops: the last frame is not the first one again
                    g.Evaluate();
                    if (lying)
                    {
                        lieHips = anim.GetBoneTransform(HumanBodyBones.Hips).position;
                        lieHead = anim.GetBoneTransform(HumanBodyBones.Head).position;
                    }
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
            body.bounds = new Bounds(new Vector3(0, 1.2f, 0), new Vector3(3, 3f, 3));   // signs reach 2.6 m
            body.UploadMeshData(true);
        }
        finally { Object.DestroyImmediate(go); }
    }

    // The body mesh + the gear meshes skinned rigidly to their bone; body UVs squeezed into the left half of the atlas,
    // gear UVs (0..1 in the gear half) into the right half. A gear vertex is placed in root space on its pose and
    // stored in mesh space through the inverse of that pose's skinning matrix: it keeps its placement relative to the bone.
    static Mesh Equip(GameObject model, Gear[] gear, AnimationClip[] clips)
    {
        var go = (GameObject)Object.Instantiate(model);
        var g = PlayableGraph.Create("equip");
        try
        {
            go.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
            var anim = go.GetComponent<Animator>();
            anim.runtimeAnimatorController = null;
            anim.applyRootMotion = false;
            anim.cullingMode = AnimatorCullingMode.AlwaysAnimate;   // (an unseen instance is not posed otherwise)
            var smr = go.GetComponentInChildren<SkinnedMeshRenderer>();
            var src = smr.sharedMesh;
            // gear meshes with their object transform in the FBX (the axis conversion may sit there)
            var gearRoot = AssetDatabase.LoadAssetAtPath<GameObject>(GearFbx).transform;
            var gearMeshes = gearRoot.GetComponentsInChildren<MeshFilter>().ToDictionary(f => f.sharedMesh.name, f => (f.sharedMesh, gearRoot.worldToLocalMatrix * f.transform.localToWorldMatrix));
            var v = new List<Vector3>(src.vertices);
            var n = new List<Vector3>(src.normals);
            var uv = src.uv.Select(t => new Vector2(t.x * 0.5f, t.y)).ToList();
            var bw = new List<BoneWeight>(src.boneWeights);
            var tris = new List<int>(src.triangles);
            g.SetTimeUpdateMode(DirectorUpdateMode.Manual);
            var output = AnimationPlayableOutput.Create(g, "equip", anim);
            // rest pose first (before any clip moved the bones), then the clip poses
            foreach (var gr in gear.OrderBy(x => x.aPose ? 0 : 1))
            {
                var (gm, own) = gearMeshes[gr.mesh];
                if (!gr.aPose)
                {
                    var cp = AnimationClipPlayable.Create(g, clips[(int)gr.pose]);
                    output.SetSourcePlayable(cp);
                    cp.SetTime(0);
                    g.Evaluate();
                }
                var bone = anim.GetBoneTransform(gr.bone);
                int bi = System.Array.IndexOf(smr.bones, bone);
                var place = Matrix4x4.TRS(bone.position + gr.pos, Quaternion.Euler(gr.rot), Vector3.one);
                // skinning maps mesh space to the renderer's space: renderer^-1 * bone * bindpose (hero_f's renderer is scaled 0.01)
                var skin = smr.transform.worldToLocalMatrix * bone.localToWorldMatrix * src.bindposes[bi];
                var m = skin.inverse * smr.transform.worldToLocalMatrix * place * own;
                int o = v.Count;
                v.AddRange(gm.vertices.Select(p => m.MultiplyPoint3x4(p)));
                n.AddRange(gm.normals.Select(d => m.MultiplyVector(d).normalized));
                uv.AddRange(gm.uv.Select(t => new Vector2(0.5f + t.x * 0.5f, t.y)));
                bw.AddRange(Enumerable.Repeat(new BoneWeight { boneIndex0 = bi, weight0 = 1 }, gm.vertexCount));
                tris.AddRange(gm.triangles.Select(i => i + o));
            }
            var mesh = new Mesh { name = model.name + "_Equipped", indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 };
            mesh.SetVertices(v);
            mesh.SetNormals(n);
            mesh.SetUVs(0, uv);
            mesh.boneWeights = bw.ToArray();
            mesh.bindposes = src.bindposes;
            mesh.SetTriangles(tris, 0);
            mesh.RecalculateBounds();
            return mesh;
        }
        finally { g.Destroy(); Object.DestroyImmediate(go); }
    }

    // ---- ragdoll ----

    static GameObject BuildRagdoll(GameObject model, string name, Material skin, Mesh skinned)
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
        if (skinned) smr.sharedMesh = skinned;
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
        crowd.characters = Characters.Select(k => AssetDatabase.LoadAssetAtPath<CrowdCharacter>(CrowdDir + "/" + k.name + ".asset")).ToArray();
        crowd.walkMap = map;
        crowd.pedGraph = AssetDatabase.LoadAssetAtPath<TextAsset>("Assets/GTA/City/" + scene.name + "_peds.json");   // city_demo.export_peds
        crowd.spots = Spots();
        BloodMaterials(crowd);
        ProtestAssets(crowd);
        EditorSceneManager.MarkSceneDirty(scene);
        EditorSceneManager.SaveScene(scene);
        Debug.Log($"crowd: {crowd.spots.Length} seats / waiting spots");
    }

    // BloodFX materials: stains = PS1Lit cut-out with the T_Blood atlas (Tools/texture/blood.py), drawn instanced;
    // sprays = URP unlit particles colored by the droplets
    public static void BloodMaterials(CrowdSystem crowd)
    {
        Material Mat(string name, string shader)
        {
            string path = "Assets/GTA/Materials/" + name + ".mat";
            var m = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (!m) { m = new Material(Shader.Find(shader)); AssetDatabase.CreateAsset(m, path); }
            return m;
        }
        var stain = Mat("M_Blood", "GTA/PS1Lit");
        stain.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>("Assets/GTA/Textures/T_Blood.png"));
        stain.SetFloat("_AlphaClip", 1);
        stain.EnableKeyword("_ALPHATEST_ON");
        stain.SetFloat("_Cutoff", 0.5f);
        stain.enableInstancing = true;
        var spray = Mat("M_BloodSpray", "Universal Render Pipeline/Particles/Unlit");
        spray.SetColor("_BaseColor", Color.white);
        EditorUtility.SetDirty(stain);
        EditorUtility.SetDirty(spray);
        AssetDatabase.SaveAssets();
        crowd.bloodStain = stain;
        crowd.bloodSpray = spray;
        crowd.blob = LightingBake.Blob();
        EditorUtility.SetDirty(crowd);
    }

    // thrown paving stones: the Gear.fbx "Pave" mesh, PS1Lit concrete drawn instanced; the protest chant (GameAudio)
    static void ProtestAssets(CrowdSystem crowd)
    {
        crowd.paveMesh = AssetDatabase.LoadAllAssetsAtPath(GearFbx).OfType<Mesh>().FirstOrDefault(m => m.name == "Pave");
        string path = "Assets/GTA/Materials/M_Pave.mat";
        var m = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (!m) { m = new Material(Shader.Find("GTA/PS1Lit")); AssetDatabase.CreateAsset(m, path); }
        m.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>("Assets/GTA/Textures/T_Concrete.png"));
        m.SetColor("_BaseColor", new Color(0.75f, 0.72f, 0.7f));
        m.enableInstancing = true;
        EditorUtility.SetDirty(m);
        crowd.paveMaterial = m;
        var audio = Object.FindAnyObjectByType<GameAudio>();
        if (audio) crowd.protestLoop = audio.protest;
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
        var bounds = city.GetComponentsInChildren<MeshRenderer>().Where(r => !r.name.StartsWith("Ground"))   // not the hills
            .Select(r => r.bounds).Aggregate((a, b) => { a.Encapsulate(b); return a; });
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

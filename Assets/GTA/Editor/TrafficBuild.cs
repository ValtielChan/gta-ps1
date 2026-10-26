using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

// Traffic build (see Scripts/TrafficSystem.cs).
// Menu GTA > Build Traffic Cars: for each traffic model Assets/GTA/Cars/Traffic/<name>.fbx (Tools/citygen/cars.py
// export_car(name, traffic=True): a body + wheels *_Wheel_FL/FR/RL/RR at their centres; the player's car stays out):
//   - the model's parts but the wheels combined into one mesh (one submesh per material) + the 4 wheel meshes;
//   - one material set per paint: the body atlas T_<atlas>.png and every T_<atlas>_<Paint>.png made by
//     Tools/texture/car_paint.py (glass material swapped the same way), instancing enabled;
//   - the proxy prefab Prefabs/Traffic/<name>_Traffic.prefab (rigidbody + box above the wheel centres + the model,
//     mass from the footprint: ~1450 kg for a car, ~5.7 t for the bus);
//   - Assets/GTA/Traffic/<name>.asset (TrafficCar) tying it together.
// Menu GTA > Setup Traffic In Open Scene: puts a "Traffic" object (TrafficSystem with every car and the scene's
// lane graph Assets/GTA/City/<scene>_traffic.json) in the scene.
static class TrafficBuild
{
    const string Dir = "Assets/GTA/Traffic", PrefabDir = "Assets/GTA/Prefabs/Traffic", TexDir = "Assets/GTA/Textures", ModelDir = "Assets/GTA/Cars/Traffic";
    static readonly string[] WheelNames = { "_Wheel_FL", "_Wheel_FR", "_Wheel_RL", "_Wheel_RR" };

    [MenuItem("GTA/Build Traffic Cars")]
    public static void Build()
    {
        Directory.CreateDirectory(Dir);
        Directory.CreateDirectory(PrefabDir);
        foreach (var path in Directory.GetFiles(ModelDir, "*.fbx").Select(p => p.Replace('\\', '/')))
        {
            var model = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            string name = model.name;
            var root = model.transform;
            var parts = model.GetComponentsInChildren<Transform>();
            var wheelT = WheelNames.Select(w => parts.FirstOrDefault(t => t.name.EndsWith(w))).ToArray();
            if (wheelT.Contains(null)) { Debug.LogError($"{path}: needs 4 wheels named *{string.Join(", *", WheelNames)}"); continue; }

            // combine every part but the wheels, grouped by material
            var order = new List<Material>();
            var groups = new Dictionary<Material, List<CombineInstance>>();
            foreach (var mf in model.GetComponentsInChildren<MeshFilter>())
            {
                if (wheelT.Contains(mf.transform)) continue;
                var mr = mf.GetComponent<MeshRenderer>();
                for (int s = 0; s < mf.sharedMesh.subMeshCount; s++)
                {
                    var m = mr.sharedMaterials[s];
                    if (!groups.ContainsKey(m)) { groups[m] = new List<CombineInstance>(); order.Add(m); }
                    groups[m].Add(new CombineInstance { mesh = mf.sharedMesh, subMeshIndex = s, transform = root.worldToLocalMatrix * mf.transform.localToWorldMatrix });
                }
            }
            var merged = order.Select(m => { var g = new Mesh { indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 }; g.CombineMeshes(groups[m].ToArray(), true, true); return new CombineInstance { mesh = g, transform = Matrix4x4.identity }; }).ToArray();
            var body = new Mesh { name = name + "_Body", indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 };
            body.CombineMeshes(merged, false, false);
            body.RecalculateBounds();
            body = Save(body, Dir + "/" + name + "_Body.asset");
            var wheels = new Mesh[4];
            for (int w = 0; w < 4; w++) wheels[w] = Save(Object.Instantiate(wheelT[w].GetComponent<MeshFilter>().sharedMesh), Dir + "/" + name + "_Wheel" + w + ".asset");

            // paints: the body atlas and its variants
            var bodyMat = order.First(m => !m.name.EndsWith("__Glass") && m.GetTexture("_BaseMap"));
            string atlas = bodyMat.GetTexture("_BaseMap").name.Substring(2);
            var texs = new[] { TexDir + "/T_" + atlas + ".png" }.Concat(Directory.GetFiles(TexDir, "T_" + atlas + "_*.png").Select(p => p.Replace('\\', '/')).OrderBy(p => p)).ToArray();
            var materials = new List<Material>();
            foreach (var tex in texs)
            {
                string paint = Path.GetFileNameWithoutExtension(tex).Substring(2 + atlas.Length).TrimStart('_');
                if (paint == "") paint = "Base";
                var t = AssetDatabase.LoadAssetAtPath<Texture2D>(tex);
                foreach (var m in order)
                {
                    bool painted = m.GetTexture("_BaseMap") == bodyMat.GetTexture("_BaseMap");
                    string mp = Dir + "/M_" + name + "_" + (painted ? paint + (m.name.EndsWith("__Glass") ? "_Glass" : "") : m.name.Replace("__", "_")) + ".mat";
                    var mat = AssetDatabase.LoadAssetAtPath<Material>(mp);
                    if (!mat) { mat = new Material(m); AssetDatabase.CreateAsset(mat, mp); }
                    mat.CopyPropertiesFromMaterial(m);
                    mat.shader = m.shader;
                    mat.renderQueue = m.renderQueue;
                    if (painted) mat.SetTexture("_BaseMap", t);
                    mat.enableInstancing = true;
                    EditorUtility.SetDirty(mat);
                    materials.Add(mat);
                }
            }
            var wheelMat = materials[order.IndexOf(bodyMat)];   // tires / rims are not paint: the base atlas does

            var tc = Save(ScriptableObject.CreateInstance<TrafficCar>(), Dir + "/" + name + ".asset");
            tc.body = body;
            tc.wheels = wheels;
            tc.wheelPos = wheelT.Select(w => root.InverseTransformPoint(w.position)).ToArray();
            tc.wheelRadius = wheels[0].bounds.extents.y;
            tc.wheelBase = Mathf.Abs(tc.wheelPos[0].z - tc.wheelPos[2].z);
            // like the playable car's box: from just above the wheel centres (curbs pass under) to the roof
            var b = body.bounds;
            float bottom = tc.wheelPos[0].y + 0.1f;
            tc.boxCenter = new Vector3(b.center.x, (bottom + b.max.y) / 2, b.center.z);
            tc.boxSize = new Vector3(b.size.x, b.max.y - bottom, b.size.z);
            tc.paints = texs.Length;
            tc.subMeshes = order.Count;
            tc.materials = materials.ToArray();
            tc.wheelMaterial = wheelMat;
            tc.proxy = BuildProxy(name, tc, 175f * b.size.x * b.size.z);   // 1450 kg for the 4.7 x 1.77 m W123
            EditorUtility.SetDirty(tc);
            Debug.Log($"{name}: {tc.paints} paints, {tc.subMeshes} submeshes, body {body.vertexCount} vertices");
        }
        AssetDatabase.SaveAssets();
    }

    static T Save<T>(T obj, string path) where T : Object
    {
        var old = AssetDatabase.LoadAssetAtPath<T>(path);
        if (!old) { AssetDatabase.CreateAsset(obj, path); return obj; }
        if (obj is Mesh src && old is Mesh dst)
        {
            // through the mesh API: a mesh CopySerialized over keeps drawing its old geometry (seen: the W123i body
            // without its glass instead of the new W123)
            dst.Clear();
            dst.indexFormat = src.indexFormat;
            dst.SetVertices(src.vertices);
            dst.SetNormals(src.normals);
            dst.SetUVs(0, src.uv);
            dst.SetColors(src.colors);
            dst.subMeshCount = src.subMeshCount;
            for (int s = 0; s < src.subMeshCount; s++) dst.SetTriangles(src.GetTriangles(s), s);
            dst.RecalculateBounds();
        }
        else EditorUtility.CopySerialized(obj, old);
        old.name = Path.GetFileNameWithoutExtension(path);
        EditorUtility.SetDirty(old);
        return old;
    }

    // rigidbody (the car's mass) + box + the combined body and 4 wheels, driven by TrafficSystem
    static GameObject BuildProxy(string name, TrafficCar tc, float mass)
    {
        var go = new GameObject(name + "_Traffic");
        var rb = go.AddComponent<Rigidbody>();
        rb.mass = mass;
        rb.useGravity = false;
        rb.interpolation = RigidbodyInterpolation.Interpolate;
        rb.collisionDetectionMode = CollisionDetectionMode.ContinuousSpeculative;
        var box = go.AddComponent<BoxCollider>();
        box.center = tc.boxCenter;
        box.size = tc.boxSize;
        box.sharedMaterial = AssetDatabase.LoadAssetAtPath<PhysicsMaterial>("Assets/GTA/Materials/CarBody.physicMaterial");
        go.AddComponent<TrafficProxy>();
        var body = new GameObject("Body");
        body.transform.SetParent(go.transform, false);
        body.AddComponent<MeshFilter>().sharedMesh = tc.body;
        body.AddComponent<MeshRenderer>().sharedMaterials = Enumerable.Range(0, tc.subMeshes).Select(s => tc.Mat(0, s)).ToArray();
        for (int w = 0; w < 4; w++)
        {
            var wh = new GameObject("Wheel" + w);
            wh.transform.SetParent(go.transform, false);
            wh.transform.localPosition = tc.wheelPos[w];
            wh.AddComponent<MeshFilter>().sharedMesh = tc.wheels[w];
            wh.AddComponent<MeshRenderer>().sharedMaterial = tc.wheelMaterial;
        }
        var prefab = PrefabUtility.SaveAsPrefabAsset(go, PrefabDir + "/" + name + "_Traffic.prefab");
        Object.DestroyImmediate(go);
        return prefab;
    }

    [MenuItem("GTA/Setup Traffic In Open Scene")]
    public static void Setup()
    {
        var scene = EditorSceneManager.GetActiveScene();
        var old = GameObject.Find("Traffic");
        if (old) Object.DestroyImmediate(old);
        var traffic = new GameObject("Traffic").AddComponent<TrafficSystem>();
        traffic.cars = AssetDatabase.FindAssets("t:TrafficCar", new[] { Dir }).Select(g => AssetDatabase.LoadAssetAtPath<TrafficCar>(AssetDatabase.GUIDToAssetPath(g))).ToArray();
        traffic.laneGraph = AssetDatabase.LoadAssetAtPath<TextAsset>("Assets/GTA/City/" + scene.name + "_traffic.json");   // city_demo.export_traffic
        EditorSceneManager.MarkSceneDirty(scene);
        EditorSceneManager.SaveScene(scene);
        Debug.Log($"traffic: {traffic.cars.Length} car models, graph {(traffic.laneGraph ? "ok" : "MISSING")}");
    }
}

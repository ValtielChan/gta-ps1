using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

// Traffic build (see Scripts/TrafficSystem.cs).
// Menu GTA > Build Traffic Cars: for each playable car prefab Assets/GTA/Prefabs/Car_*.prefab (SimpleCar):
//   - the model's parts but the wheels combined into one mesh (one submesh per material) + the 4 wheel meshes;
//   - one material set per paint: the body atlas T_<atlas>.png and every T_<atlas>_<Paint>.png made by
//     Tools/texture/car_paint.py (glass material swapped the same way), instancing enabled;
//   - the proxy prefab Prefabs/Traffic/<name>_Traffic.prefab (rigidbody + box + the model);
//   - Assets/GTA/Traffic/<name>.asset (TrafficCar) tying it together.
// Menu GTA > Setup Traffic In Open Scene: puts a "Traffic" object (TrafficSystem with every car and the scene's
// lane graph Assets/GTA/City/<scene>_traffic.json) in the scene.
static class TrafficBuild
{
    const string Dir = "Assets/GTA/Traffic", PrefabDir = "Assets/GTA/Prefabs/Traffic", TexDir = "Assets/GTA/Textures";

    [MenuItem("GTA/Build Traffic Cars")]
    public static void Build()
    {
        Directory.CreateDirectory(Dir);
        Directory.CreateDirectory(PrefabDir);
        foreach (var path in Directory.GetFiles("Assets/GTA/Prefabs", "Car_*.prefab").Select(p => p.Replace('\\', '/')))
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            var car = prefab.GetComponent<SimpleCar>();
            if (!car) continue;
            string name = prefab.name.Substring(4);
            var box = prefab.GetComponent<BoxCollider>();
            var root = prefab.transform;

            // combine every part but the wheels, grouped by material
            var order = new List<Material>();
            var groups = new Dictionary<Material, List<CombineInstance>>();
            foreach (var mf in prefab.GetComponentsInChildren<MeshFilter>())
            {
                if (car.wheels.Contains(mf.transform)) continue;
                var mr = mf.GetComponent<MeshRenderer>();
                for (int s = 0; s < mf.sharedMesh.subMeshCount; s++)
                {
                    var m = mr.sharedMaterials[s];
                    if (!groups.ContainsKey(m)) { groups[m] = new List<CombineInstance>(); order.Add(m); }
                    groups[m].Add(new CombineInstance { mesh = mf.sharedMesh, subMeshIndex = s, transform = root.worldToLocalMatrix * mf.transform.localToWorldMatrix });
                }
            }
            var parts = order.Select(m => { var g = new Mesh { indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 }; g.CombineMeshes(groups[m].ToArray(), true, true); return new CombineInstance { mesh = g, transform = Matrix4x4.identity }; }).ToArray();
            var body = new Mesh { name = name + "_Body", indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 };
            body.CombineMeshes(parts, false, false);
            body.RecalculateBounds();
            body = Save(body, Dir + "/" + name + "_Body.asset");
            var wheels = new Mesh[4];
            for (int w = 0; w < 4; w++) wheels[w] = Save(Object.Instantiate(car.wheels[w].GetComponent<MeshFilter>().sharedMesh), Dir + "/" + name + "_Wheel" + w + ".asset");

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
            tc.wheelPos = car.wheels.Select(w => root.InverseTransformPoint(w.position)).ToArray();
            tc.wheelRadius = car.wheelRadius;
            tc.wheelBase = Mathf.Abs(tc.wheelPos[0].z - tc.wheelPos[2].z);
            tc.boxCenter = box.center;
            tc.boxSize = box.size;
            tc.paints = texs.Length;
            tc.subMeshes = order.Count;
            tc.materials = materials.ToArray();
            tc.wheelMaterial = wheelMat;
            tc.proxy = BuildProxy(name, tc, prefab);
            EditorUtility.SetDirty(tc);
            Debug.Log($"{name}: {tc.paints} paints, {tc.subMeshes} submeshes, body {body.vertexCount} vertices");
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

    // rigidbody (the car's mass) + box + the combined body and 4 wheels, driven by TrafficSystem
    static GameObject BuildProxy(string name, TrafficCar tc, GameObject carPrefab)
    {
        var go = new GameObject(name + "_Traffic");
        var rb = go.AddComponent<Rigidbody>();
        rb.mass = carPrefab.GetComponent<Rigidbody>().mass;
        rb.useGravity = false;
        rb.interpolation = RigidbodyInterpolation.Interpolate;
        rb.collisionDetectionMode = CollisionDetectionMode.ContinuousSpeculative;
        var box = go.AddComponent<BoxCollider>();
        box.center = tc.boxCenter;
        box.size = tc.boxSize;
        box.sharedMaterial = carPrefab.GetComponent<BoxCollider>().sharedMaterial;
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

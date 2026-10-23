using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

// Repeated props exported by Tools/citygen (kit.PREFABS) live as Assets/GTA/Props/<Name>.fbx.
// This tool wraps each one in a prefab (Assets/GTA/Prefabs/Props/<Name>.prefab, a variant of the model, so
// re-exports flow through) and instantiates them in the open scene from <Scene>_placements.json.
public static class PropPlacer
{
    const string ModelDir = "Assets/GTA/Props", PrefabDir = "Assets/GTA/Prefabs/Props";

    [Serializable] class Item { public string prefab; public float x, y, z, yaw; }
    [Serializable] class Placements { public Item[] items; }

    [MenuItem("GTA/Place Props In Open Scene")]
    public static void Run()
    {
        BuildPrefabs();
        var scene = EditorSceneManager.GetActiveScene();
        var json = Directory.GetFiles("Assets/GTA", scene.name + "_placements.json", SearchOption.AllDirectories);
        if (json.Length == 0) { Debug.LogWarning("No placements for scene " + scene.name); return; }
        Place(json[0]);
        EditorSceneManager.MarkSceneDirty(scene);
    }

    public static void BuildPrefabs()
    {
        Directory.CreateDirectory(PrefabDir);
        foreach (var guid in AssetDatabase.FindAssets("t:Model", new[] { ModelDir }))
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            string prefab = PrefabDir + "/" + Path.GetFileNameWithoutExtension(path) + ".prefab";
            if (File.Exists(prefab)) continue;   // variants follow model re-imports by themselves
            var inst = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>(path));
            foreach (var t in inst.GetComponentsInChildren<Transform>()) t.gameObject.isStatic = true;
            PrefabUtility.SaveAsPrefabAsset(inst, prefab);
            UnityEngine.Object.DestroyImmediate(inst);
        }
    }

    // Blender (x, y, z) -> Unity (-x, z, -y); Blender yaw (CCW, radians) -> Unity yaw = -yaw.
    public static void Place(string jsonPath)
    {
        var data = JsonUtility.FromJson<Placements>(File.ReadAllText(jsonPath));
        var old = GameObject.Find("Placed");
        if (old) UnityEngine.Object.DestroyImmediate(old);
        var root = new GameObject("Placed") { isStatic = true };
        foreach (var it in data.items)
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(PrefabDir + "/" + it.prefab + ".prefab");
            if (!prefab) { Debug.LogWarning("Missing prefab " + it.prefab); continue; }
            var go = (GameObject)PrefabUtility.InstantiatePrefab(prefab, root.transform);
            go.transform.SetPositionAndRotation(new Vector3(-it.x, it.z, -it.y), Quaternion.Euler(0, -it.yaw * Mathf.Rad2Deg, 0));
        }
    }
}

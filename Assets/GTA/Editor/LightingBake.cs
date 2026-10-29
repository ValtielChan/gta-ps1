using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

// Menu GTA > Bake Lighting: PS1-style baked lighting of the open scene. The sun goes Mixed / Subtractive so the
// lightmaps hold its direct light, the sky and the shadows of the static world (1 texel per metre, bilinear:
// soft 1 m shadow texels, the PS1 render pixelates them anyway). Props (Placed) only cast baked shadows
// (lit by the realtime sun + ambient, their charts would eat the atlas). Nothing casts real-time shadows: the URP
// assets have main light shadows off, cars and pedestrians get blob shadows (BlobShadow, material M_Blob).
// Re-run after regenerating the city (the lightmaps belong to the scene: Assets/Scenes/<Scene>/).
public static class LightingBake
{
    const string SettingsPath = "Assets/Settings/CityLighting.lighting";
    const string BlobPath = "Assets/GTA/Materials/M_Blob.mat";

    [MenuItem("GTA/Bake Lighting")]
    static void Bake()
    {
        var scene = EditorSceneManager.GetActiveScene();
        var ls = AssetDatabase.LoadAssetAtPath<LightingSettings>(SettingsPath);
        if (!ls) { ls = new LightingSettings { name = "CityLighting" }; AssetDatabase.CreateAsset(ls, SettingsPath); }
        ls.lightmapper = LightingSettings.Lightmapper.ProgressiveGPU;
        ls.realtimeGI = false;
        ls.bakedGI = true;
        ls.mixedBakeMode = MixedLightingMode.Subtractive;
        ls.lightmapResolution = 1f;      // texels per metre (bilinear: the 1 m texels blend into soft PS1 shadows)
        ls.lightmapMaxSize = 2048;
        ls.lightmapPadding = 2;
        ls.directionalityMode = LightmapsMode.NonDirectional;
        ls.lightmapCompression = LightmapCompression.NormalQuality;
        ls.directSampleCount = 32;
        ls.indirectSampleCount = 128;
        ls.environmentSampleCount = 128;
        ls.maxBounces = 1;
        ls.ao = false;
        ls.filteringMode = LightingSettings.FilterMode.Auto;   // denoised, slightly soft edges (bilinear lightmaps)
        EditorUtility.SetDirty(ls);
        Lightmapping.lightingSettings = ls;

        foreach (var l in Object.FindObjectsByType<Light>(FindObjectsSortMode.None))
            if (l.type == LightType.Directional) { l.lightmapBakeType = LightmapBakeType.Mixed; l.shadows = LightShadows.Hard; }

        int lightmapped = 0, casters = 0;
        foreach (var r in Object.FindObjectsByType<MeshRenderer>(FindObjectsSortMode.None))
        {
            string root = r.transform.root.name;
            bool world = root == scene.name, prop = root == "Placed";
            if (!world && !prop || r.name.EndsWith("_Rotor")) continue;   // rotors spin: lit by probes only
            var flags = GameObjectUtility.GetStaticEditorFlags(r.gameObject) | StaticEditorFlags.ContributeGI;
            GameObjectUtility.SetStaticEditorFlags(r.gameObject, flags);
            var b = r.bounds;
            bool big = prop && House(r.name);   // houses: lightmapped like the buildings
            r.receiveGI = world || big ? ReceiveGI.Lightmaps : ReceiveGI.LightProbes;
            var so = new SerializedObject(r);
            so.FindProperty("m_ScaleInLightmap").floatValue = Scale(r.name, b, r.GetComponent<MeshFilter>().sharedMesh);
            so.ApplyModifiedProperties();
            if (world || big) lightmapped++; else casters++;
        }
        EditorSceneManager.MarkSceneDirty(scene);
        EditorSceneManager.SaveScene(scene);
        Debug.Log($"lighting: baking {scene.name}, {lightmapped} lightmapped renderers, {casters} shadow casters only");
        Lightmapping.BakeAsync();
    }

    static bool House(string n) => n.StartsWith("House") || n.StartsWith("Ranch") || n.StartsWith("Mansion");

    // texel density per world layer (x the 1 texel/m): markings are thin, the ground only shows between the lots
    // and the roads, the hills beyond ~1.1 km are far inside the fog.
    // Planar tiles (ImportRules.Planar) hold sparse geometry in a full top-down chart: Unity sizes a chart from the
    // mesh surface area, so a tile whose roads cover 25 % of its footprint would get half the density (markings
    // 1/14): compensate by sqrt(footprint / surface).
    static float Scale(string name, Bounds b, Mesh mesh)
    {
        string layer = name.Split('_')[0];
        float f = 1f;
        if (layer == "Markings" || layer == "LotMarkings") f = 0.5f;
        else if (layer == "Ground") f = new Vector2(b.center.x, b.center.z).magnitude < 1100f ? 0.5f : 0.2f;
        if (System.Array.IndexOf(ImportRules.Planar, layer) < 0 || !mesh) return f;
        var v = mesh.vertices; var t = mesh.triangles;
        float area = 0;
        for (int i = 0; i < t.Length; i += 3) area += Vector3.Cross(v[t[i + 1]] - v[t[i]], v[t[i + 2]] - v[t[i]]).magnitude * 0.5f;
        return f * Mathf.Sqrt(Mathf.Max(b.size.x * b.size.z, 1f) / Mathf.Max(area, 1f));
    }

    // the shared blob shadow material (Setup Crowd / Setup Traffic, the player's car)
    public static Material Blob()
    {
        var m = AssetDatabase.LoadAssetAtPath<Material>(BlobPath);
        if (!m) { m = new Material(Shader.Find("GTA/PS1Blob")); AssetDatabase.CreateAsset(m, BlobPath); }
        m.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>("Assets/GTA/Textures/T_Blob.png"));
        m.SetFloat("_Shade", 0.5f);
        m.enableInstancing = true;
        EditorUtility.SetDirty(m);
        return m;
    }
}

using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

// The shader variants the game draws, compiled while the build loads instead of the first time each one shows up
// (WebGL compiles a GL program on its first draw: a 100-700 ms freeze per variant).
// GTA > Shader Variants > Start Recording, play (drive, crash, run people over: ragdolls, blood), then
// GTA > Shader Variants > Save: writes Assets/GTA/Shaders/GTA.shadervariants and lists it in Graphics Settings >
// Preloaded Shaders. Record again when a shader, a material keyword or the URP asset changes.
static class ShaderVariants
{
    const string Path = "Assets/GTA/Shaders/GTA.shadervariants";

    // ShaderUtil's variant tracking (the Graphics Settings "Save to asset" button) is internal
    static object Call(string method, params object[] args) =>
        typeof(ShaderUtil).GetMethod(method, System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static).Invoke(null, args);

    [MenuItem("GTA/Shader Variants/Start Recording")]
    static void Start()
    {
        Call("ClearCurrentShaderVariantCollection");
        Debug.Log("Shader variants: recording, play the game then GTA > Shader Variants > Save");
    }

    [MenuItem("GTA/Shader Variants/Save")]
    static void Save()
    {
        Call("SaveCurrentShaderVariantCollection", Path);
        AssetDatabase.ImportAsset(Path);
        var svc = AssetDatabase.LoadAssetAtPath<ShaderVariantCollection>(Path);
        var gs = new SerializedObject(GraphicsSettings.GetGraphicsSettings());   // the live settings object (a loaded copy is not saved)
        var list = gs.FindProperty("m_PreloadedShaders");
        bool listed = false;
        for (int i = 0; i < list.arraySize; i++) listed |= list.GetArrayElementAtIndex(i).objectReferenceValue == svc;
        if (!listed)
        {
            list.InsertArrayElementAtIndex(list.arraySize);
            list.GetArrayElementAtIndex(list.arraySize - 1).objectReferenceValue = svc;
            gs.ApplyModifiedPropertiesWithoutUndo();
            AssetDatabase.SaveAssets();
        }
        Debug.Log($"Shader variants: {svc.shaderCount} shaders, {svc.variantCount} variants saved to {Path}, preloaded at startup");
    }
}

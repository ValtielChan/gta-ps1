using System.Collections;
using UnityEngine;

// Builds only: once every Start() has run (JSON graphs, pools), one GC so their garbage is not collected in game.
// Not in the editor: a GC there walks the whole editor heap (~350 ms).
// ponytail: no shader warm-up; Shader.WarmupAllShaders takes minutes on WebGL (every URP variant). If first-draw
// hitches show in builds, warm a ShaderVariantCollection of the GTA shaders instead.
public class Preload : MonoBehaviour
{
#if !UNITY_EDITOR
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Boot() => new GameObject("Preload").AddComponent<Preload>();
#endif

    IEnumerator Start()
    {
        yield return null;
        System.GC.Collect();
        Destroy(gameObject);
    }
}

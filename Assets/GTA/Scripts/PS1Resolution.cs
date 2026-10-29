using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

// Keeps the internal render height fixed (PS1-ish low res) whatever the window size, by driving the URP
// render scale. The URP asset upscales with point filtering, so pixels stay square and crisp.
// Also sets the per-layer draw distances (PS1-style pop-in, inside the fog): small street props, flat details
// (markings, fences, hedges, wires, driveways) and houses vanish sooner than the buildings and the terrain.
[ExecuteAlways]
public class PS1Resolution : MonoBehaviour
{
    public int targetHeight = 360;
    public float smallProps = 160f, details = 250f, houses = 380f;   // metres, layers SmallProps / Details / Houses

    void OnEnable()
    {
        var cam = GetComponent<Camera>();
        if (!cam) return;
        var d = new float[32];
        d[LayerMask.NameToLayer("SmallProps")] = smallProps;
        d[LayerMask.NameToLayer("Details")] = details;
        d[LayerMask.NameToLayer("Houses")] = houses;
        cam.layerCullDistances = d;   // (URP: planar distances, layerCullSpherical is built-in only)
    }

    void Update()
    {
        if (GraphicsSettings.currentRenderPipeline is UniversalRenderPipelineAsset urp && Screen.height > 0)
        {
            float scale = Mathf.Clamp((float)targetHeight / Screen.height, 0.1f, 1f);
            if (urp.renderScale != scale) urp.renderScale = scale;   // only on a resize: the setter rebuilds the pipeline state
        }
    }
}

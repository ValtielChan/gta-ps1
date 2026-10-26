using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

// Keeps the internal render height fixed (PS1-ish low res) whatever the window size, by driving the URP
// render scale. The URP asset upscales with point filtering, so pixels stay square and crisp.
[ExecuteAlways]
public class PS1Resolution : MonoBehaviour
{
    public int targetHeight = 360;
    static readonly int ShadowRes = Shader.PropertyToID("_PS1ShadowmapRes");

    void Update()
    {
        if (GraphicsSettings.currentRenderPipeline is UniversalRenderPipelineAsset urp && Screen.height > 0)
        {
            float scale = Mathf.Clamp((float)targetHeight / Screen.height, 0.1f, 1f);
            if (urp.renderScale != scale) urp.renderScale = scale;   // only on a resize: the setter rebuilds the pipeline state
            // PS1Lit / PS1Crowd read the shadow map at its texel centres (square shadow pixels); URP only sets
            // _MainLightShadowmapSize with soft shadows, and querying the texture size breaks the shadow sampler on WebGL
            Shader.SetGlobalFloat(ShadowRes, urp.mainLightShadowmapResolution);
        }
    }
}

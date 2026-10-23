using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

// Keeps the internal render height fixed (PS1-ish low res) whatever the window size, by driving the URP
// render scale. The URP asset upscales with point filtering, so pixels stay square and crisp.
[ExecuteAlways]
public class PS1Resolution : MonoBehaviour
{
    public int targetHeight = 360;

    void Update()
    {
        if (GraphicsSettings.currentRenderPipeline is UniversalRenderPipelineAsset urp && Screen.height > 0)
            urp.renderScale = Mathf.Clamp((float)targetHeight / Screen.height, 0.1f, 1f);
    }
}

// Full-screen PS1 color pass (Full Screen Pass Renderer Feature, after post-processing, before the
// point upscale): ordered 4x4 Bayer dither + quantization to _Levels steps per channel (32 = 15-bit look).
Shader "GTA/PS1Post"
{
    Properties
    {
        _Levels ("Levels per channel", Float) = 32
        _Dither ("Dither strength", Range(0, 1)) = 1
    }

    SubShader
    {
        Tags { "RenderPipeline" = "UniversalPipeline" }
        ZWrite Off Cull Off ZTest Always

        Pass
        {
            Name "PS1Post"
            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.core/Runtime/Utilities/Blit.hlsl"

            float _Levels;
            float _Dither;

            static const float BAYER[16] = { 0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5 };

            half4 Frag(Varyings i) : SV_Target
            {
                half4 c = SAMPLE_TEXTURE2D_X(_BlitTexture, sampler_PointClamp, i.texcoord);
                uint2 p = uint2(i.positionCS.xy) % 4;
                float d = (BAYER[p.y * 4 + p.x] / 16.0 - 0.5) * _Dither;
                half3 s = LinearToSRGB(saturate(c.rgb));
                s = floor(s * (_Levels - 1) + 0.5 + d) / (_Levels - 1);
                return half4(SRGBToLinear(saturate(s)), c.a);
            }
            ENDHLSL
        }
    }
}

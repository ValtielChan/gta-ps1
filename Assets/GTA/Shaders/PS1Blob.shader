// PS1 blob shadow: a dark quad multiplied over the ground under cars and pedestrians (T_Blob mask, 4 grey levels).
// Drawn after the opaque world, no depth write, pushed toward the camera so it never fights the road. No fog: blobs
// are only drawn within ~120 m, far inside the fog range.
Shader "GTA/PS1Blob"
{
    Properties
    {
        _BaseMap ("Mask", 2D) = "white" {}
        _Shade ("Shade", Range(0, 1)) = 0.5
    }

    SubShader
    {
        // transparent queue: drawn after every opaque with a plain depth test (the opaque pass may depth-prime)
        Tags { "RenderType" = "Transparent" "RenderPipeline" = "UniversalPipeline" "Queue" = "Transparent-100" }

        Pass
        {
            Name "Blob"
            Tags { "LightMode" = "UniversalForward" }
            Blend DstColor Zero
            ZWrite Off
            Offset -1, -1
            Cull Off

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            TEXTURE2D(_BaseMap); SAMPLER(sampler_BaseMap);
            CBUFFER_START(UnityPerMaterial)
                float4 _BaseMap_ST;
                half _Shade;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                float2 uv : TEXCOORD0;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float2 uv : TEXCOORD0;
            };

            Varyings vert(Attributes v)
            {
                UNITY_SETUP_INSTANCE_ID(v);
                Varyings o;
                o.positionCS = TransformObjectToHClip(v.positionOS.xyz);
                o.uv = v.uv;
                return o;
            }

            half4 frag(Varyings i) : SV_Target
            {
                half a = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, i.uv).r;
                half m = lerp(1, _Shade, a);
                return half4(m, m, m, 1);
            }
            ENDHLSL
        }
    }
}

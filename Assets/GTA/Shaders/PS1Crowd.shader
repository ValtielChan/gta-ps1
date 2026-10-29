// Crowd pedestrians drawn with GPU instancing (CrowdSystem): PS1Lit lighting, but the vertices come from a vertex
// animation texture (VAT, baked by GTA > Build NPC Crowd) and the albedo from a Texture2DArray of outfits.
// Per instance: _Crowd.x = outfit slice, _Crowd.y = VAT row (clip frame, chosen on the CPU: no interpolation,
// 20 fps, PS1 style). The mesh carries its vertex index in TEXCOORD1.x. WebGL 2 / GLES 3 friendly (texelFetch).
Shader "GTA/PS1Crowd"
{
    Properties
    {
        _Skins ("Outfits", 2DArray) = "" {}
        _VatPos ("VAT positions", 2D) = "black" {}
        _VatNrm ("VAT normals", 2D) = "gray" {}
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" "Queue" = "Geometry" }

        HLSLINCLUDE
        #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
        TEXTURE2D_ARRAY(_Skins);
        SAMPLER(sampler_Skins);
        TEXTURE2D(_VatPos);
        TEXTURE2D(_VatNrm);
        CBUFFER_START(UnityPerMaterial)
            float4 _Skins_ST;
        CBUFFER_END
        UNITY_INSTANCING_BUFFER_START(Crowd)
            UNITY_DEFINE_INSTANCED_PROP(float4, _Crowd)
        UNITY_INSTANCING_BUFFER_END(Crowd)

        struct Attributes
        {
            float4 positionOS : POSITION;
            float2 uv : TEXCOORD0;
            float2 vid : TEXCOORD1;
            UNITY_VERTEX_INPUT_INSTANCE_ID
        };

        void Vat(Attributes v, out float3 pos, out float3 nrm)
        {
            int2 t = int2(v.vid.x + 0.5, UNITY_ACCESS_INSTANCED_PROP(Crowd, _Crowd).y + 0.5);
            pos = LOAD_TEXTURE2D_LOD(_VatPos, t, 0).xyz;
            nrm = LOAD_TEXTURE2D_LOD(_VatNrm, t, 0).xyz * 2 - 1;
        }
        ENDHLSL

        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode" = "UniversalForward" }

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile _ _ADDITIONAL_LIGHTS
            #pragma multi_compile _ _FORWARD_PLUS
            #pragma multi_compile_fog
            #pragma multi_compile_instancing
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 uvSkin : TEXCOORD0;
                float3 positionWS : TEXCOORD1;
                half3 normalWS : TEXCOORD2;
                half fog : TEXCOORD3;
            };

            Varyings vert(Attributes v)
            {
                UNITY_SETUP_INSTANCE_ID(v);
                float3 p, n;
                Vat(v, p, n);
                Varyings o;
                VertexPositionInputs vp = GetVertexPositionInputs(p);
                o.positionCS = vp.positionCS;
                o.positionWS = vp.positionWS;
                o.normalWS = TransformObjectToWorldNormal(n);
                o.uvSkin = float3(v.uv, UNITY_ACCESS_INSTANCED_PROP(Crowd, _Crowd).x);
                o.fog = ComputeFogFactor(vp.positionCS.z);
                return o;
            }

            half4 frag(Varyings i) : SV_Target
            {
                half3 tex = SAMPLE_TEXTURE2D_ARRAY(_Skins, sampler_Skins, i.uvSkin.xy, i.uvSkin.z).rgb;
                half3 n = normalize(i.normalWS);
                Light sun = GetMainLight();
                half3 light = sun.color * (saturate(dot(n, sun.direction)) * sun.distanceAttenuation);
                light += SampleSH(n);
                #if defined(_ADDITIONAL_LIGHTS)
                InputData inputData = (InputData)0;
                inputData.positionWS = i.positionWS;
                inputData.normalizedScreenSpaceUV = GetNormalizedScreenSpaceUV(i.positionCS);
                uint count = GetAdditionalLightsCount();
                LIGHT_LOOP_BEGIN(count)
                    Light l = GetAdditionalLight(lightIndex, i.positionWS);
                    light += l.color * (l.distanceAttenuation * saturate(dot(n, l.direction)));
                LIGHT_LOOP_END
                #endif
                return half4(MixFog(tex * light, i.fog), 1);
            }
            ENDHLSL
        }

        Pass
        {
            Name "ShadowCaster"
            Tags { "LightMode" = "ShadowCaster" }
            ZWrite On
            ColorMask 0

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing
            #pragma multi_compile_vertex _ _CASTING_PUNCTUAL_LIGHT_SHADOW
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Shadows.hlsl"
            float3 _LightDirection;
            float3 _LightPosition;

            float4 vert(Attributes v) : SV_POSITION
            {
                UNITY_SETUP_INSTANCE_ID(v);
                float3 p, n;
                Vat(v, p, n);
                float3 pw = TransformObjectToWorld(p);
                float3 nw = TransformObjectToWorldNormal(n);
                #if _CASTING_PUNCTUAL_LIGHT_SHADOW
                float3 ld = normalize(_LightPosition - pw);
                #else
                float3 ld = _LightDirection;
                #endif
                float4 cs = TransformWorldToHClip(ApplyShadowBias(pw, nw, ld));
                #if UNITY_REVERSED_Z
                cs.z = min(cs.z, cs.w * UNITY_NEAR_CLIP_VALUE);
                #else
                cs.z = max(cs.z, cs.w * UNITY_NEAR_CLIP_VALUE);
                #endif
                return cs;
            }

            half4 frag() : SV_Target { return 0; }
            ENDHLSL
        }

        Pass
        {
            Name "DepthOnly"
            Tags { "LightMode" = "DepthOnly" }
            ZWrite On
            ColorMask R

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing

            float4 vert(Attributes v) : SV_POSITION
            {
                UNITY_SETUP_INSTANCE_ID(v);
                float3 p, n;
                Vat(v, p, n);
                return TransformObjectToHClip(p);
            }

            half4 frag() : SV_Target { return 0; }
            ENDHLSL
        }
    }
}

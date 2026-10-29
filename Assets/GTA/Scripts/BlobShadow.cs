using UnityEngine;
using UnityEngine.Rendering;

// PS1 blob shadows: a dark multiply quad (shader GTA/PS1Blob, mask T_Blob) under every car and pedestrian instead
// of real-time shadows (the static world has its shadows baked in the lightmaps, GTA > Bake Lighting).
// T_Blob cells: 0 = disc (pedestrians), 1 = rounded rectangle (cars). Crowd and traffic draw theirs instanced
// through Draw; the player's car carries this component, which hangs one quad under the body.
// Like the PS1 games the blob is bigger than the object and pushed a little along the sun (SunOffset), so it reads
// as a shadow instead of hiding under the body.
public class BlobShadow : MonoBehaviour
{
    public const int Disc = 0, Rect = 1, MaxBatch = 1023;
    public const float Lift = 0.08f;   // above the ground point: the rendered road / sidewalk sits a few cm above the colliders

    public Material material;
    public Vector2 size = new Vector2(2.1f, 5f);      // x, z in car space
    public Vector3 offset = new Vector3(0, Lift, 0);   // from the car origin (ground level)

    static Mesh[] quads;
    static Vector3 sunOffset;
    static bool sunKnown;

    // horizontal push of a blob along the sun light, scaled by the object's height (metres)
    public static Vector3 SunOffset(float height)
    {
        if (!sunKnown)
        {
            var sun = RenderSettings.sun;
            if (!sun) foreach (var l in FindObjectsByType<Light>(FindObjectsSortMode.None)) if (l.type == LightType.Directional) { sun = l; break; }
            var d = sun ? sun.transform.forward : Vector3.zero;
            sunOffset = new Vector3(d.x, 0, d.z) * 0.35f;
            sunKnown = true;
        }
        return sunOffset * height;
    }

    // 1 x 1 quad in the XZ plane showing one cell of T_Blob
    public static Mesh Quad(int cell)
    {
        if (quads == null) quads = new Mesh[2];
        if (quads[cell]) return quads[cell];
        float u = cell * 0.5f;
        return quads[cell] = new Mesh
        {
            name = "Blob" + cell,
            vertices = new[] { new Vector3(-0.5f, 0, -0.5f), new Vector3(-0.5f, 0, 0.5f), new Vector3(0.5f, 0, 0.5f), new Vector3(0.5f, 0, -0.5f) },
            uv = new[] { new Vector2(u, 0), new Vector2(u, 1), new Vector2(u + 0.5f, 1), new Vector2(u + 0.5f, 0) },
            triangles = new[] { 0, 1, 2, 0, 2, 3 },
        };
    }

    public static void Draw(Material material, int cell, Matrix4x4[] mats, int count)
    {
        if (count > 0 && material) Graphics.DrawMeshInstanced(Quad(cell), 0, material, mats, count, null, ShadowCastingMode.Off, false);
    }

    Transform quad;

    void Start()
    {
        var go = new GameObject("Blob");
        go.transform.SetParent(transform, false);
        go.transform.localScale = new Vector3(size.x, 1, size.y);
        go.AddComponent<MeshFilter>().sharedMesh = Quad(Rect);
        var r = go.AddComponent<MeshRenderer>();
        r.sharedMaterial = material;
        r.shadowCastingMode = ShadowCastingMode.Off;
        r.receiveShadows = false;
        quad = go.transform;
    }

    void LateUpdate()
    {
        quad.position = transform.TransformPoint(offset) + SunOffset(1.4f);
    }
}

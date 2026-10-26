using UnityEngine;

// Baked data of one traffic car model for TrafficSystem. Made by GTA > Build Traffic Cars (Editor/TrafficBuild.cs)
// from a traffic model (Assets/GTA/Cars/Traffic/<name>.fbx), never by hand.
public class TrafficCar : ScriptableObject
{
    public Mesh body;                 // every part but the wheels, combined; one submesh per material
    public Mesh[] wheels;             // FL, FR, RL, RR
    public Vector3[] wheelPos;        // wheel centres in car space (rest position)
    public float wheelRadius, wheelBase;
    public Vector3 boxCenter, boxSize;
    public int paints, subMeshes;
    public Material[] materials;      // [paint * subMeshes + sub], instancing enabled
    public Material wheelMaterial;
    public GameObject proxy;          // rigidbody + box + the model (Prefabs/Traffic/<name>_Traffic.prefab)

    public Material Mat(int paint, int sub) => materials[paint * subMeshes + sub];

    [System.NonSerialized] Material[][] sets;
    // the body's sharedMaterials for a paint, built once (no garbage each time a proxy is attached)
    public Material[] Mats(int paint)
    {
        if (sets == null) sets = new Material[paints][];
        if (sets[paint] == null)
        {
            sets[paint] = new Material[subMeshes];
            for (int s = 0; s < subMeshes; s++) sets[paint][s] = Mat(paint, s);
        }
        return sets[paint];
    }
}

using UnityEngine;

// Baked data of one traffic car model for TrafficSystem. Made by GTA > Build Traffic Cars (Editor/TrafficBuild.cs)
// from a playable car prefab (Assets/GTA/Prefabs/Car_*.prefab), never by hand.
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
}

using UnityEngine;

// Constant rotation of a prefab part (wind turbine rotor: PropPlacer adds it to every *_Rotor child).
public class Spin : MonoBehaviour
{
    public Vector3 axis = Vector3.forward;   // local axis (the rotor faces +Z in Unity, -Y in Blender)
    public float rpm = 10f;

    void Update() => transform.Rotate(axis, rpm * 6f * Time.deltaTime, Space.Self);
}

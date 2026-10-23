using UnityEngine;
using UnityEngine.InputSystem;

// Arcade raycast car: 4 spring wheels, lateral grip capped by load, rear-wheel drive.
// Keyboard: WASD / arrows, Space = handbrake, R = reset. Gamepad: triggers, left stick, A.
[RequireComponent(typeof(Rigidbody))]
public class SimpleCar : MonoBehaviour
{
    public Transform[] wheels = new Transform[4];   // FL, FR, RL, RR wheel meshes at their rest position (center)
    public float wheelRadius = 0.34f;
    public float restLength = 0.45f;
    public float spring = 38000f, damper = 3800f;
    public float motorForce = 8000f, brakeForce = 12000f;
    public float topSpeed = 55f, reverseSpeed = 12f;          // m/s
    public float maxSteer = 34f, steerAtTopSpeed = 7f;        // degrees
    public float grip = 0.9f, handbrakeGrip = 0.2f, friction = 1.3f;
    public float airDrag = 0.4f;

    Rigidbody rb;
    Vector3[] mounts;
    Quaternion[] wheelRot;
    float[] spin;
    float throttle, steerInput, steer, flippedTime;
    bool handbrake;

    public float SpeedKmh => Vector3.Dot(rb.linearVelocity, transform.forward) * 3.6f;

    void Awake()
    {
        rb = GetComponent<Rigidbody>();
        rb.centerOfMass = new Vector3(0, 0.15f, 0);
        rb.interpolation = RigidbodyInterpolation.Interpolate;
        mounts = new Vector3[4];
        wheelRot = new Quaternion[4];
        spin = new float[4];
        // wheels are placed at their rest position (model's wheel centers): the suspension top sits above them,
        // minus the static sag, so the car rests exactly as modeled
        float sag = rb.mass * -Physics.gravity.y / 4f / spring;
        for (int i = 0; i < 4; i++)
        {
            mounts[i] = wheels[i].localPosition + Vector3.up * (restLength - sag);
            wheelRot[i] = wheels[i].localRotation;
        }
    }

    void Update()
    {
        var kb = Keyboard.current;
        var gp = Gamepad.current;
        throttle = steerInput = 0;
        handbrake = false;
        if (kb != null)
        {
            throttle += (kb.wKey.isPressed || kb.upArrowKey.isPressed ? 1 : 0) - (kb.sKey.isPressed || kb.downArrowKey.isPressed ? 1 : 0);
            steerInput += (kb.dKey.isPressed || kb.rightArrowKey.isPressed ? 1 : 0) - (kb.aKey.isPressed || kb.leftArrowKey.isPressed ? 1 : 0);
            handbrake |= kb.spaceKey.isPressed;
            if (kb.rKey.wasPressedThisFrame) ResetCar();
        }
        if (gp != null)
        {
            throttle += gp.rightTrigger.ReadValue() - gp.leftTrigger.ReadValue();
            steerInput += gp.leftStick.x.ReadValue();
            handbrake |= gp.buttonSouth.isPressed;
            if (gp.buttonNorth.wasPressedThisFrame) ResetCar();
        }
        throttle = Mathf.Clamp(throttle, -1, 1);
        steerInput = Mathf.Clamp(steerInput, -1, 1);

        flippedTime = transform.up.y < 0.3f ? flippedTime + Time.deltaTime : 0;
        if (flippedTime > 2f) ResetCar();
    }

    void FixedUpdate()
    {
        float dt = Time.fixedDeltaTime;
        float v = Vector3.Dot(rb.linearVelocity, transform.forward);
        float speed01 = Mathf.Clamp01(Mathf.Abs(v) / topSpeed);
        steer = Mathf.MoveTowards(steer, steerInput * Mathf.Lerp(maxSteer, steerAtTopSpeed, speed01), 140f * dt);

        float drive = 0, brake = 0;
        if (throttle > 0) { if (v > -1) drive = throttle * Mathf.Clamp01(1 - v / topSpeed); else brake = throttle; }
        else if (throttle < 0) { if (v > 1) brake = -throttle; else drive = throttle * Mathf.Clamp01(1 + v / reverseSpeed); }

        float maxDist = restLength + wheelRadius;
        for (int i = 0; i < 4; i++)
        {
            bool front = i < 2;
            Vector3 origin = transform.TransformPoint(mounts[i]);
            float dist = maxDist;
            if (Physics.Raycast(origin, -transform.up, out RaycastHit hit, maxDist, Physics.DefaultRaycastLayers, QueryTriggerInteraction.Ignore))
            {
                dist = hit.distance;
                Vector3 vel = rb.GetPointVelocity(hit.point);
                float load = Mathf.Max(0, (maxDist - dist) * spring - Vector3.Dot(vel, transform.up) * damper);
                rb.AddForceAtPosition(transform.up * load, origin);

                Quaternion rot = front ? Quaternion.AngleAxis(steer, transform.up) : Quaternion.identity;
                Vector3 fwd = Vector3.ProjectOnPlane(rot * transform.forward, hit.normal).normalized;
                Vector3 side = Vector3.ProjectOnPlane(rot * transform.right, hit.normal).normalized;
                float vLong = Vector3.Dot(vel, fwd);

                float g = handbrake && !front ? handbrakeGrip : grip;
                float lateral = -Vector3.Dot(vel, side) * g * rb.mass * 0.25f / dt;
                float dir = Mathf.Clamp(vLong * 2f, -1f, 1f);   // smooth sign: no jitter at standstill
                float longi = (front ? 0 : drive * motorForce * 0.5f) - dir * brake * brakeForce * 0.25f - vLong * 15f;
                if (handbrake && !front) longi -= dir * brakeForce * 0.25f;
                Vector3 f = side * lateral + fwd * longi;
                float cap = load * friction;   // traction circle
                if (f.magnitude > cap) f = f.normalized * cap;
                rb.AddForceAtPosition(f, hit.point + transform.up * wheelRadius);
                spin[i] += vLong * dt / wheelRadius * Mathf.Rad2Deg;
            }
            var w = wheels[i];
            w.position = origin - transform.up * (dist - wheelRadius);
            w.localRotation = Quaternion.Euler(0, front ? steer : 0, 0) * Quaternion.Euler(spin[i], 0, 0) * wheelRot[i];
        }
        rb.AddForce(-rb.linearVelocity * rb.linearVelocity.magnitude * airDrag);
    }

    public void ResetCar()
    {
        var yaw = Quaternion.Euler(0, transform.eulerAngles.y, 0);
        rb.linearVelocity = rb.angularVelocity = Vector3.zero;
        rb.position = transform.position + Vector3.up * 2f;
        rb.rotation = yaw;
        transform.SetPositionAndRotation(rb.position, yaw);
    }

    void OnGUI()
    {
        GUI.Label(new Rect(20, 20, 300, 30), $"{Mathf.Abs(SpeedKmh):0} km/h", new GUIStyle(GUI.skin.label) { fontSize = 28 });
    }
}

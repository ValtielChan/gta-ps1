using UnityEngine;
using UnityEngine.InputSystem;

// Arcade raycast car: 4 spring wheels, lateral and longitudinal grip capped by load, rear-wheel drive.
// Tires sliding sideways keep only their kinetic grip, so a handbrake turn keeps its momentum and the slide goes on
// after the release; the drive stays available while sliding (power out of the drift) and a yaw damper while the
// tires slide keeps the drift controllable instead of spinning out.
// Keyboard: WASD / arrows, Space = handbrake, R = reset. Gamepad: triggers, left stick, A.
[RequireComponent(typeof(Rigidbody))]
public class SimpleCar : MonoBehaviour
{
    public Transform[] wheels = new Transform[4];   // FL, FR, RL, RR wheel meshes at their rest position (center)
    public float wheelRadius = 0.34f;
    public float restLength = 0.45f;
    public float spring = 38000f, damper = 3800f;
    public float motorForce = 20000f, brakeForce = 16000f;
    public float engineBrake = 0.08f;                         // brake fraction with the pedals released (coast down, hold on slopes)
    public float topSpeed = 65f, reverseSpeed = 12f;          // m/s
    public float maxSteer = 34f, steerAtTopSpeed = 7f;        // degrees
    public float grip = 0.9f, friction = 1.6f;                // lateral slip cancelled per step; static friction coefficient (arcade)
    public float slideFriction = 0.4f, handbrakeFriction = 0.3f;     // friction multiplier of a tire sliding sideways / of the locked rear (handbrake)
    public float driftYawDamp = 4000f;                        // N.m per rad/s of yaw while the tires slide (anti spin-out)
    public float airDrag = 0.4f;

    Rigidbody rb;
    Vector3[] mounts;
    Quaternion[] wheelRot;
    float[] spin;
    float throttle, steerInput, steer, flippedTime;
    bool handbrake;

    public float SpeedKmh => Vector3.Dot(rb.linearVelocity, transform.forward) * 3.6f;
    public float Throttle => throttle;     // -1 (brake / reverse) .. 1
    public bool Handbrake => handbrake;
    public bool Grounded { get; private set; }   // at least one wheel on the ground (last physics step)
    public float Slide { get; private set; }     // 0 tires rolling .. 1 sliding sideways (last physics step)

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
        steer = Mathf.MoveTowards(steer, steerInput * Mathf.Lerp(maxSteer, steerAtTopSpeed, speed01), 180f * dt);

        float drive = 0, brake = 0;
        if (throttle > 0) { if (v > -1) drive = throttle * Mathf.Clamp01(1 - v / topSpeed); else brake = throttle; }
        else if (throttle < 0) { if (v > 1) brake = -throttle; else drive = throttle * Mathf.Clamp01(1 + v / reverseSpeed); }
        else brake = engineBrake;   // pedals released: coast down and stay put (no creeping)

        // sliding = the body moves sideways (drift), not a steered wheel at speed: steering must keep its grip
        float sliding = Mathf.InverseLerp(2f, 6f, Mathf.Abs(Vector3.Dot(rb.linearVelocity, transform.right)));
        float maxDist = restLength + wheelRadius;
        bool grounded = false;
        for (int i = 0; i < 4; i++)
        {
            bool front = i < 2;
            Vector3 origin = transform.TransformPoint(mounts[i]);
            float dist = maxDist;
            if (Physics.Raycast(origin, -transform.up, out RaycastHit hit, maxDist, Physics.DefaultRaycastLayers, QueryTriggerInteraction.Ignore))
            {
                dist = hit.distance;
                grounded = true;
                Vector3 vel = rb.GetPointVelocity(hit.point);
                float load = Mathf.Max(0, (maxDist - dist) * spring - Vector3.Dot(vel, transform.up) * damper);
                rb.AddForceAtPosition(hit.normal * load, origin);   // along the ground normal: a pitched car must not push itself along the road

                Quaternion rot = front ? Quaternion.AngleAxis(steer, transform.up) : Quaternion.identity;
                Vector3 fwd = Vector3.ProjectOnPlane(rot * transform.forward, hit.normal).normalized;
                Vector3 side = Vector3.ProjectOnPlane(rot * transform.right, hit.normal).normalized;
                float vLong = Vector3.Dot(vel, fwd), vSide = Vector3.Dot(vel, side);
                float share = rb.mass * 0.25f / dt;   // force per (m/s) that cancels this wheel's share of a velocity in one step

                // a tire sliding sideways keeps only its kinetic grip: the car keeps its momentum through a drift
                float muLat = friction * Mathf.Lerp(1, slideFriction, sliding), muLong = friction;
                float brakeCap = brake * brakeForce * 0.25f;   // exact brake: never overshoots, so no jitter and a true standstill
                float longi = -Mathf.Clamp(vLong * share, -brakeCap, brakeCap) - vLong * 15f;
                if (!front)
                {
                    if (handbrake)   // locked rear: little grip both ways, drive cut
                    {
                        muLat = friction * handbrakeFriction;
                        muLong = friction * handbrakeFriction;
                        longi -= Mathf.Clamp(vLong * share, -brakeForce * 0.25f, brakeForce * 0.25f);
                    }
                    else longi += drive * motorForce * 0.5f;
                }
                // lateral and longitudinal grip capped separately (arcade): full drive is available while sliding, so you power out of a drift
                float lateral = Mathf.Clamp(-vSide * grip * share, -load * muLat, load * muLat);
                longi = Mathf.Clamp(longi, -load * muLong, load * muLong);
                rb.AddForceAtPosition(side * lateral + fwd * longi, hit.point + transform.up * wheelRadius);
                spin[i] += vLong * dt / wheelRadius * Mathf.Rad2Deg;
            }
            var w = wheels[i];
            w.position = origin - transform.up * (dist - wheelRadius);
            w.localRotation = Quaternion.Euler(0, front ? steer : 0, 0) * Quaternion.Euler(spin[i], 0, 0) * wheelRot[i];
        }
        rb.AddForce(-rb.linearVelocity * rb.linearVelocity.magnitude * airDrag);
        if (grounded && sliding > 0)   // drift assist: bleed the yaw rate while the tires slide so the car does not spin out (lighter while the handbrake is held: the player wants to rotate)
            rb.AddTorque(-transform.up * Vector3.Dot(rb.angularVelocity, transform.up) * driftYawDamp * sliding * (handbrake ? 0.3f : 1f));
        Grounded = grounded;
        Slide = sliding;
    }

    public void ResetCar()
    {
        var yaw = Quaternion.Euler(0, transform.eulerAngles.y, 0);
        rb.linearVelocity = rb.angularVelocity = Vector3.zero;
        rb.position = transform.position + Vector3.up * 2f;
        rb.rotation = yaw;
        transform.SetPositionAndRotation(rb.position, yaw);
    }
}

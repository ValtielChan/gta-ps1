using UnityEngine;

// Sound of the player's car (on the same object as SimpleCar):
// - engine: the 5 RPM loops of a sound pack set (Assets/GTA/Sounds/Car Engine: *_engine_loop_0x..4x, idle to
//   redline) cross-faded on a simulated RPM (speed through a 4-gear box, throttle revs, a short dip on upshifts),
//   pitch nudged inside each band so two neighbours meet at the same pitch, louder under load;
// - tires: a skid loop on lateral slip, hard braking or handbrake;
// - impacts: OnCollisionEnter by the speed change it caused: crash / bump against cars and walls, a clang
//   against poles and signs; pedestrians are left to CrowdSystem (their own body hit and screams).
[RequireComponent(typeof(SimpleCar))]
public class CarAudio : MonoBehaviour
{
    public AudioClip[] engineLoops = new AudioClip[5];   // 0x (idle) .. 4x (redline)
    public AudioClip skid;
    [Range(0, 1)] public float engineVolume = 0.55f, skidVolume = 0.5f;
    public float[] gearTop = { 0f, 11f, 21f, 32f, 44f, 56f };   // m/s at the top of each gear

    SimpleCar car;
    Rigidbody rb;
    AudioSource[] loops;
    AudioSource tires;
    float rpm, shiftDip;
    int gear = 1;
    float lastImpact;

    void Start()
    {
        car = GetComponent<SimpleCar>();
        rb = GetComponent<Rigidbody>();
        loops = new AudioSource[engineLoops.Length];
        for (int i = 0; i < loops.Length; i++)
        {
            if (!engineLoops[i]) continue;
            var s = GameAudio.Make3D(gameObject.AddComponent<AudioSource>(), 6f, 90f);
            s.clip = engineLoops[i];
            s.loop = true;
            s.spatialBlend = 0.6f;   // the camera follows a few meters behind: mostly in the head
            s.volume = 0;
            s.time = Random.value * s.clip.length;
            s.Play();
            loops[i] = s;
        }
        if (skid)
        {
            tires = GameAudio.Make3D(gameObject.AddComponent<AudioSource>(), 5f, 80f);
            tires.clip = skid;
            tires.loop = true;
            tires.volume = 0;
            tires.Play();
        }
    }

    void Update()
    {
        float dt = Time.deltaTime;
        var v = rb.linearVelocity;
        float speed = Mathf.Abs(Vector3.Dot(v, transform.forward));
        float throttle = Mathf.Abs(car.Throttle);

        // gearbox: up at the top of the gear, down 15 % below the previous top
        while (gear < gearTop.Length - 1 && speed > gearTop[gear]) { gear++; shiftDip = 0.25f; }
        while (gear > 1 && speed < gearTop[gear - 1] * 0.85f) gear--;
        float band = Mathf.InverseLerp(gearTop[gear - 1] * 0.6f, gearTop[gear], speed);
        float target = speed < 1.5f ? 0.05f + throttle * 0.35f : Mathf.Lerp(0.2f, 1f, band) + throttle * 0.08f;
        target -= shiftDip;
        shiftDip = Mathf.MoveTowards(shiftDip, 0, dt);
        rpm = Mathf.MoveTowards(rpm, Mathf.Clamp01(target), dt * (target > rpm ? 1.6f : 1.2f));

        // cross-fade the two neighbouring loops; inside a band the lower one pitches up and the upper one down
        float x = rpm * (loops.Length - 1);
        int lo = Mathf.Min((int)x, loops.Length - 2);
        float f = x - lo;
        float load = Mathf.Lerp(0.55f, 1f, throttle);
        for (int i = 0; i < loops.Length; i++)
        {
            if (!loops[i]) continue;
            float w = i == lo ? 1 - f : i == lo + 1 ? f : 0;
            loops[i].volume = engineVolume * load * Mathf.Sqrt(w);   // equal power
            loops[i].pitch = i == lo ? 1f + 0.12f * f : i == lo + 1 ? 0.89f + 0.11f * f : 1f;
        }

        if (tires)
        {
            float lateral = Mathf.Abs(Vector3.Dot(v, transform.right));
            float slip = Mathf.InverseLerp(3f, 9f, lateral);
            if (car.Handbrake && speed > 5) slip = Mathf.Max(slip, 0.8f);
            if (car.Throttle < -0.5f && Vector3.Dot(v, transform.forward) > 8) slip = Mathf.Max(slip, 0.5f);   // hard braking
            if (!car.Grounded) slip = 0;
            tires.volume = Mathf.MoveTowards(tires.volume, skidVolume * slip, dt * 4);
            tires.pitch = 0.9f + 0.2f * slip;
        }
    }

    void OnCollisionEnter(Collision c)
    {
        if (Time.time - lastImpact < 0.15f) return;
        var other = c.rigidbody;
        if (other && other.mass < 200) return;   // ragdoll parts: CrowdSystem plays the body hit
        float dv = c.impulse.magnitude / rb.mass;   // speed change of the car
        if (dv < 1.2f) return;
        var p = c.GetContact(0).point;
        string n = c.collider.name;
        bool thin = !other && (n.Contains("Lamp") || n.Contains("Pole") || n.Contains("Sign") || n.Contains("Signal") ||
                               n.Contains("Hydrant") || n.Contains("Meter") || n.Contains("Mailbox") || n.Contains("Trash") || n.Contains("NewsBox"));
        bool hard = dv > 5f;
        float vol = Mathf.InverseLerp(1f, 10f, dv) * 0.7f + 0.3f;
        if (thin) GameAudio.Play(GameAudio.I ? GameAudio.I.pole : null, p, vol);
        else GameAudio.Play(GameAudio.I ? (hard ? GameAudio.I.crash : GameAudio.I.bump) : null, p, vol);
        lastImpact = Time.time;
    }
}

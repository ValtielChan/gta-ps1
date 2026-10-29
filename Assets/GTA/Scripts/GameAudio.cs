using System.Collections.Generic;
using UnityEngine;

// One-shot sound effects of the whole game (GTA > Setup Audio In Open Scene fills the clips from Assets/GTA/Sounds/SFX):
// a pool of 3D AudioSources, a random variation per call, small pitch jitter, and a minimum interval per sound set
// so a pile-up does not fire twenty identical thuds in one frame. Plus the city ambience bed (2D loop).
public class GameAudio : MonoBehaviour
{
    public static GameAudio I { get; private set; }

    [Header("Impacts")]
    public AudioClip[] crash;        // car against car / wall, hard
    public AudioClip[] bump;         // car, soft
    public AudioClip[] pole;         // car against a pole, sign, lamp
    public AudioClip[] bodyHit;      // car against a pedestrian
    public AudioClip[] splat;        // gore layer for fast hits
    public AudioClip[] bodyLand;     // ragdoll hitting the ground
    [Header("Voices")]
    public AudioClip[] screamMale, screamFemale;
    public AudioClip[] shout;        // bystanders
    public AudioClip[] panic;        // crowd panic bed
    [Header("Protests")]
    public AudioClip[] baton;        // riot police clubbing someone
    public AudioClip[] armor;        // car against a riot policeman (armour, shield)
    public AudioClip[] rock;         // thrown paving stone against a shield / the car
    public AudioClip protest;        // chanting crowd loop (CrowdSystem.protestLoop)
    [Header("Traffic")]
    public AudioClip[] horn;
    [Header("Beds")]
    public AudioClip ambience;
    [Range(0, 1)] public float ambienceVolume = 0.35f;
    [Range(0, 1)] public float volume = 1f;
    public int voices = 24;

    AudioSource[] pool;
    float[] started;
    AudioSource bed;
    readonly Dictionary<AudioClip[], float> last = new Dictionary<AudioClip[], float>();
    public static readonly List<string> History = new List<string>();   // dev check: the last 40 sounds played

    void Awake()
    {
        I = this;
        pool = new AudioSource[voices];
        started = new float[voices];
        for (int i = 0; i < voices; i++)
        {
            var go = new GameObject("Voice" + i);
            go.transform.SetParent(transform, false);
            pool[i] = Make3D(go.AddComponent<AudioSource>(), 4f, 120f);
        }
        if (ambience)
        {
            bed = gameObject.AddComponent<AudioSource>();
            bed.clip = ambience;
            bed.loop = true;
            bed.spatialBlend = 0;
            bed.volume = ambienceVolume * volume;
            bed.Play();
        }
    }

    public static AudioSource Make3D(AudioSource s, float minDist, float maxDist)
    {
        s.playOnAwake = false;
        s.spatialBlend = 1;
        s.rolloffMode = AudioRolloffMode.Logarithmic;
        s.minDistance = minDist;
        s.maxDistance = maxDist;
        s.dopplerLevel = 0;
        return s;
    }

    // plays a random clip of `set` at `pos`; returns false when the set is empty or played less than minInterval ago
    public static bool Play(AudioClip[] set, Vector3 pos, float vol = 1f, float delay = 0f, float pitch = 1f, float minInterval = 0.06f)
    {
        if (!I || set == null || set.Length == 0) return false;
        float now = Time.unscaledTime;
        if (I.last.TryGetValue(set, out float t) && now - t < minInterval) return false;
        I.last[set] = now;
        var s = I.Voice();
        I.started[System.Array.IndexOf(I.pool, s)] = now;
        s.transform.position = pos;
        s.clip = set[Random.Range(0, set.Length)];
        s.volume = Mathf.Clamp01(vol) * I.volume;
        s.pitch = pitch * Random.Range(0.92f, 1.08f);
        if (delay > 0) s.PlayDelayed(delay); else s.Play();
        if (History.Count == 40) History.RemoveAt(0);
        History.Add($"{Time.time:0.00} {s.clip.name} vol {s.volume:0.00}");
        return true;
    }

    // a free voice, else the oldest one
    AudioSource Voice()
    {
        int best = 0;
        for (int i = 0; i < pool.Length; i++)
        {
            if (!pool[i].isPlaying) return pool[i];
            if (started[i] < started[best]) best = i;
        }
        return pool[best];
    }
}

using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

// Menu GTA > Setup Audio In Open Scene: wires every sound of the game.
// - "Audio" object (GameAudio) with the one-shots Assets/GTA/Sounds/SFX/<Category>_NN.ogg (Tools/audio/sfx_import.py);
// - CarAudio on the playable car prefabs: the 5 engine loops of PlayerEngine (Fabien's pack, Sounds/Car Engine) + skid;
// - TrafficSystem.engineLoops: the low-RPM loop of every other pack set (a different engine per car).
static class AudioSetup
{
    const string Sfx = "Assets/GTA/Sounds/SFX", Engines = "Assets/GTA/Sounds/Car Engine";
    const string PlayerEngine = "City/car_city_a";   // <folder>/<set prefix>: *_engine_loop_0x..4x.ogg

    static AudioClip[] Set(string category) =>
        Directory.Exists(Sfx) ? Directory.GetFiles(Sfx, category + "_*.ogg").OrderBy(p => p)
            .Select(p => AssetDatabase.LoadAssetAtPath<AudioClip>(p.Replace('\\', '/'))).Where(c => c).ToArray() : new AudioClip[0];

    [MenuItem("GTA/Setup Audio In Open Scene")]
    public static void Setup()
    {
        var scene = EditorSceneManager.GetActiveScene();
        var old = GameObject.Find("Audio");
        if (old) Object.DestroyImmediate(old);
        var a = new GameObject("Audio").AddComponent<GameAudio>();
        a.crash = Set("Crash"); a.bump = Set("Bump"); a.pole = Set("Pole");
        a.bodyHit = Set("BodyHit"); a.splat = Set("Splat"); a.bodyLand = Set("BodyLand");
        a.screamMale = Set("ScreamM"); a.screamFemale = Set("ScreamF"); a.shout = Set("Shout"); a.panic = Set("Panic");
        a.horn = Set("Horn");
        a.baton = Set("Baton"); a.armor = Set("Armor"); a.rock = Set("Rock");
        a.protest = Set("Protest").FirstOrDefault();
        var crowd = Object.FindAnyObjectByType<CrowdSystem>();
        if (crowd) { crowd.protestLoop = a.protest; EditorUtility.SetDirty(crowd); }
        a.ambience = Set("Ambience").FirstOrDefault();

        var skid = Set("Skid").FirstOrDefault();
        var loops = Enumerable.Range(0, 5).Select(i => AssetDatabase.LoadAssetAtPath<AudioClip>($"{Engines}/{PlayerEngine}_engine_loop_{i}x.ogg")).ToArray();
        foreach (var path in Directory.GetFiles("Assets/GTA/Prefabs", "Car_*.prefab").Select(p => p.Replace('\\', '/')))
        {
            var root = PrefabUtility.LoadPrefabContents(path);
            if (root.GetComponent<SimpleCar>())
            {
                var ca = root.GetComponent<CarAudio>() ?? root.AddComponent<CarAudio>();
                ca.engineLoops = loops;
                ca.skid = skid;
                PrefabUtility.SaveAsPrefabAsset(root, path);
            }
            PrefabUtility.UnloadPrefabContents(root);
        }

        var traffic = Object.FindAnyObjectByType<TrafficSystem>();
        if (traffic)
        {
            traffic.engineLoops = Directory.GetFiles(Engines, "*_engine_loop_1x.ogg", SearchOption.AllDirectories)
                .Select(p => p.Replace('\\', '/')).Where(p => !p.Contains(PlayerEngine)).OrderBy(p => p)
                .Select(p => AssetDatabase.LoadAssetAtPath<AudioClip>(p)).ToArray();
            EditorUtility.SetDirty(traffic);
        }
        EditorSceneManager.MarkSceneDirty(scene);
        EditorSceneManager.SaveScene(scene);
        Debug.Log($"audio: crash {a.crash.Length}, bump {a.bump.Length}, pole {a.pole.Length}, body {a.bodyHit.Length}/{a.splat.Length}/{a.bodyLand.Length}, " +
                  $"screams {a.screamMale.Length}/{a.screamFemale.Length}, shouts {a.shout.Length}, panic {a.panic.Length}, horns {a.horn.Length}, " +
                  $"protest baton {a.baton.Length} armor {a.armor.Length} rock {a.rock.Length} loop {(a.protest ? a.protest.name : "none")}, " +
                  $"ambience {(a.ambience ? a.ambience.name : "none")}, skid {(skid ? skid.name : "none")}, player engine {loops.Count(c => c)}/5, " +
                  $"traffic engines {(traffic ? traffic.engineLoops.Length : 0)}");
    }
}

using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

// Menu GTA > Build WebGL: builds the enabled scenes to Builds/WebGL (the gh-pages checkout, see README) on the next
// editor tick, then writes Builds/build_report.txt (result, size, errors). Publishing = commit + push in Builds/WebGL.
static class WebGLBuild
{
    const string Out = "Builds/WebGL", Report = "Builds/build_report.txt";

    [MenuItem("GTA/Build WebGL")]
    public static void Build()
    {
        if (File.Exists(Report)) File.Delete(Report);
        EditorApplication.delayCall += () =>
        {
            string text;
            try
            {
                var r = BuildPipeline.BuildPlayer(new BuildPlayerOptions
                {
                    scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToArray(),
                    locationPathName = Out,
                    target = BuildTarget.WebGL,
                });
                var s = r.summary;
                text = $"result={s.result} errors={s.totalErrors} warnings={s.totalWarnings} size={s.totalSize / 1048576f:0.0}MB time={s.totalTime}\n" +
                       string.Join("\n", r.steps.SelectMany(st => st.messages).Where(m => m.type == LogType.Error || m.type == LogType.Exception).Select(m => m.content).Take(20));
            }
            catch (System.Exception e) { text = "exception " + e; }
            File.WriteAllText(Report, text);
        };
    }
}

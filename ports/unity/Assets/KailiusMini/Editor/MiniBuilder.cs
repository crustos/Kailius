using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace KailiusMini.EditorTools
{
    /// <summary>
    /// Editor helpers. build.py calls Build() in batch mode:
    /// Unity -batchmode -quit -projectPath . -buildTarget linux64 -executeMethod KailiusMini.EditorTools.MiniBuilder.Build
    /// </summary>
    public static class MiniBuilder
    {
        const string ScenePath = "Assets/Scenes/KailiusMini.unity";

        /// <summary>Recreates the scene from scratch if the shipped scene file is ever missing or broken.</summary>
        [MenuItem("Kailius/Recreate Mini Scene")]
        public static void CreateScene()
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            new GameObject("MiniGame").AddComponent<MiniGame>();
            Directory.CreateDirectory("Assets/Scenes");
            EditorSceneManager.SaveScene(scene, ScenePath);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
        }

        public static void Build()
        {
            if (!File.Exists(ScenePath)) CreateScene();

            string outDir = ArgumentValue("-kailiusOut") ?? "Builds";
            Directory.CreateDirectory(outDir);

            BuildTarget target = EditorUserBuildSettings.activeBuildTarget;
            string extension = target == BuildTarget.StandaloneWindows64 ? ".exe" : "";

            var options = new BuildPlayerOptions
            {
                scenes = new[] { ScenePath },
                locationPathName = Path.Combine(outDir, "KailiusMini" + extension),
                target = target,
                options = BuildOptions.None
            };

            var report = BuildPipeline.BuildPlayer(options);
            if (report.summary.result != UnityEditor.Build.Reporting.BuildResult.Succeeded)
            {
                Debug.LogError("KailiusMini build failed: " + report.summary.result);
                EditorApplication.Exit(1);
            }
        }

        static string ArgumentValue(string name)
        {
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
                if (args[i] == name) return args[i + 1];
            return null;
        }
    }
}

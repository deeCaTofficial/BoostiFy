using System;
using System.IO;
using System.Text;
using System.Threading;

namespace Boostify.Runtime.Worker
{
    internal enum LogLevel
    {
        Info,
        Success,
        Warning,
        Error,
    }

    internal static class WorkerLog
    {
        private const long MaximumLogBytes = 5 * 1024 * 1024;
        private static readonly string LogDirectory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "BoostiFy",
            "logs");
        private static readonly string LogPath = Path.Combine(LogDirectory, "worker.log");
        private static readonly string ErrorPath = Path.Combine(LogDirectory, "worker-error.log");
        private static readonly Mutex LogMutex = new Mutex(false, @"Local\BoostiFy.WorkerLog");

        public static void Emit(LogLevel level, uint appId, string message)
        {
            var appPart = appId > 0 ? $"[AppID {appId}]" : string.Empty;
            var line = $"[{DateTime.Now:HH:mm:ss}][{level.ToString().ToUpperInvariant()}]{appPart} {message}";
            Console.WriteLine(line);
            Append(LogPath, line);
            if (level == LogLevel.Error)
            {
                Append(ErrorPath, line);
            }
        }

        public static void Trace(string message)
        {
            Append(LogPath, message);
        }

        public static void Fatal(string message)
        {
            Append(ErrorPath, message);
        }

        private static void Append(string path, string line)
        {
            var lockTaken = false;
            try
            {
                try
                {
                    lockTaken = LogMutex.WaitOne(TimeSpan.FromSeconds(2));
                }
                catch (AbandonedMutexException)
                {
                    lockTaken = true;
                }
                if (!lockTaken)
                {
                    return;
                }
                Directory.CreateDirectory(LogDirectory);
                RotateIfNeeded(path);
                File.AppendAllText(
                    path,
                    $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {line}{Environment.NewLine}",
                    Encoding.UTF8);
            }
            catch (Exception)
            {
                // Logging must never terminate a booster process.
            }
            finally
            {
                if (lockTaken)
                {
                    try
                    {
                        LogMutex.ReleaseMutex();
                    }
                    catch (ApplicationException)
                    {
                    }
                }
            }
        }

        private static void RotateIfNeeded(string path)
        {
            var file = new FileInfo(path);
            if (!file.Exists || file.Length < MaximumLogBytes)
            {
                return;
            }
            for (var index = 3; index >= 1; index--)
            {
                var source = index == 1 ? path : $"{path}.{index - 1}";
                var target = $"{path}.{index}";
                if (!File.Exists(source))
                {
                    continue;
                }
                if (File.Exists(target))
                {
                    File.Delete(target);
                }
                File.Move(source, target);
            }
        }
    }
}

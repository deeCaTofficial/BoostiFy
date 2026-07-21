using System;
using System.Threading;
using Boostify.Runtime.Steam;

namespace Boostify.Runtime.Worker
{
    internal static class BoostSession
    {
        public static int Run(WorkerOptions options)
        {
            if (options.AppId == 0)
            {
                WorkerLog.Emit(
                    LogLevel.Error,
                    0,
                    $"Usage: {AppDomain.CurrentDomain.FriendlyName} --appid <AppID> [--unlock-all] ...");
                return 1;
            }

            WorkerLog.Emit(LogLevel.Info, options.AppId, "Process started.");
            try
            {
                using (var session = SteamSession.Open(options.AppId))
                using (var cancellation = new CancellationTokenSource())
                {
                    WorkerLog.Emit(LogLevel.Info, options.AppId, "Steam API initialized.");
                    if (options.ExitAfterSeconds > 0)
                    {
                        WorkerLog.Emit(
                            LogLevel.Info,
                            options.AppId,
                            $"Timer set to {options.ExitAfterSeconds} seconds.");
                        cancellation.CancelAfter(TimeSpan.FromSeconds(options.ExitAfterSeconds));
                    }

                    if (options.UnlockAll)
                    {
                        WorkerLog.Emit(
                            LogLevel.Info,
                            options.AppId,
                            "Waiting 15 seconds for achievements schema to load.");
                        if (cancellation.Token.WaitHandle.WaitOne(TimeSpan.FromSeconds(15)))
                        {
                            WorkerLog.Emit(
                                LogLevel.Warning,
                                options.AppId,
                                "Timer expired before achievement schema initialization completed.");
                            return 0;
                        }
                        var result = AchievementWorkflow.Run(session, options, cancellation.Token);
                        if (result == AchievementOutcome.Cancelled)
                        {
                            return 0;
                        }
                        if (IsFailure(result))
                        {
                            return 2;
                        }

                        if (options.ExitAfterSeconds == 0)
                        {
                            return 0;
                        }

                        WorkerLog.Emit(
                            LogLevel.Success,
                            options.AppId,
                            $"Unlocking finished. Waiting for timer ({options.ExitAfterSeconds} sec).");
                    }
                    else
                    {
                        WorkerLog.Emit(
                            LogLevel.Info,
                            options.AppId,
                            "Activity emulation started. Waiting for timer or termination.");
                    }

                    MemoryTrimmer.TrimWorkingSet();
                    while (!cancellation.IsCancellationRequested)
                    {
                        session.PumpCallbacks();
                        cancellation.Token.WaitHandle.WaitOne(5000);
                    }
                }
            }
            catch (SteamAccessException exception)
            {
                if (exception.Failure == SteamAccessFailure.SteamNotInstalled)
                {
                    WorkerLog.Emit(
                        LogLevel.Warning,
                        options.AppId,
                        "Could not find Steam path in registry. This is a known issue if Steam was not installed normally.");
                    WorkerLog.Fatal($"[KNOWN ISSUE] {exception}");
                    return 101;
                }

                WorkerLog.Emit(
                    LogLevel.Error,
                    options.AppId,
                    $"Failed to initialize Steam API. Please ensure Steam is running and logged in. Error: {exception.Message}");
                WorkerLog.Fatal($"[FATAL] Steam API initialization failed: {exception}");
                return -1;
            }

            WorkerLog.Emit(LogLevel.Success, options.AppId, "Process finished.");
            return 0;
        }

        private static bool IsFailure(AchievementOutcome result)
        {
            return result == AchievementOutcome.ServiceUnavailable ||
                   result == AchievementOutcome.PartialFailure ||
                   result == AchievementOutcome.CommitFailed;
        }
    }
}

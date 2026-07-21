using System;
using System.IO;
using System.Threading;
using Boostify.Runtime.Steam;
using Boostify.Runtime.Steam.Schemas;

namespace Boostify.Runtime.Worker
{
    internal enum AchievementOutcome
    {
        Completed,
        AlreadyUnlocked,
        NoAchievements,
        ServiceUnavailable,
        PartialFailure,
        CommitFailed,
        Cancelled,
    }

    internal static class AchievementWorkflow
    {
        public static AchievementOutcome Run(
            SteamSession session,
            WorkerOptions options,
            CancellationToken cancellationToken)
        {
            if (!session.Achievements.IsAvailable)
            {
                WorkerLog.Emit(
                    LogLevel.Error,
                    options.AppId,
                    "SteamUserStats unavailable. Unlocking not possible.");
                return AchievementOutcome.ServiceUnavailable;
            }

            var schemaPath = Path.Combine(
                session.InstallDirectory,
                "appcache",
                "stats",
                $"UserGameStatsSchema_{options.AppId}.bin");
            var achievementNames = AchievementCatalog.ReadNames(schemaPath, options.AppId);
            if (achievementNames.Count == 0)
            {
                WorkerLog.Emit(
                    LogLevel.Warning,
                    options.AppId,
                    "No achievements found, but will emulate activity until timer expires.");
                return AchievementOutcome.NoAchievements;
            }

            WorkerLog.Emit(
                LogLevel.Info,
                options.AppId,
                $"Found {achievementNames.Count} achievements. Checking status...");

            var pending = new System.Collections.Generic.List<string>();
            var alreadyUnlocked = 0;
            foreach (var achievementName in achievementNames)
            {
                if (cancellationToken.IsCancellationRequested)
                {
                    return AchievementOutcome.Cancelled;
                }
                if (!session.Achievements.TryGetUnlocked(achievementName, out var unlocked))
                {
                    continue;
                }

                if (unlocked)
                {
                    alreadyUnlocked++;
                }
                else
                {
                    pending.Add(achievementName);
                }
            }

            WorkerLog.Emit(
                LogLevel.Info,
                options.AppId,
                $"Status: {alreadyUnlocked} already unlocked, {pending.Count} to unlock.");
            if (pending.Count == 0)
            {
                WorkerLog.Emit(LogLevel.Success, options.AppId, "All achievements already unlocked.");
                return AchievementOutcome.AlreadyUnlocked;
            }

            var random = new Random();
            var unlockedCount = 0;
            var failedCount = 0;
            foreach (var achievementName in pending)
            {
                if (cancellationToken.IsCancellationRequested)
                {
                    WorkerLog.Emit(LogLevel.Warning, options.AppId, "Unlocking cancelled by timer or user.");
                    return AchievementOutcome.Cancelled;
                }
                if (session.Achievements.Unlock(achievementName))
                {
                    unlockedCount++;
                    WorkerLog.Emit(
                        LogLevel.Success,
                        options.AppId,
                        $"Unlocked: {achievementName} ({unlockedCount}/{pending.Count})");
                    ApplyDelay(options, random, cancellationToken);
                }
                else
                {
                    failedCount++;
                    WorkerLog.Emit(
                        LogLevel.Error,
                        options.AppId,
                        $"Failed to unlock achievement: {achievementName}");
                }
            }

            if (!session.Achievements.Commit())
            {
                WorkerLog.Emit(LogLevel.Error, options.AppId, "Failed to store achievement changes.");
                return AchievementOutcome.CommitFailed;
            }

            WorkerLog.Emit(
                LogLevel.Success,
                options.AppId,
                $"Unlocking complete: {unlockedCount} achievements unlocked.");
            return failedCount == 0
                ? AchievementOutcome.Completed
                : AchievementOutcome.PartialFailure;
        }

        private static void ApplyDelay(
            WorkerOptions options,
            Random random,
            CancellationToken cancellationToken)
        {
            if (options.RandomAchievementDelay)
            {
                cancellationToken.WaitHandle.WaitOne(random.Next(100, 300));
            }
            else if (options.DelayPerAchievement > 0)
            {
                cancellationToken.WaitHandle.WaitOne(TimeSpan.FromSeconds(options.DelayPerAchievement));
            }
        }
    }
}

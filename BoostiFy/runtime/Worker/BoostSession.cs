using System;
using System.Threading;
using Boostify.Runtime.Steam;

namespace Boostify.Runtime.Worker
{
    internal static class BoostSession
    {
        // Контракт кодов возврата (его же разбирает booster.py):
        //   0   — успех
        //   2   — достижения не сохранились (проблема сервиса/среды, НЕ самой игры)
        //   3   — игра недоступна для буста: Steam не принял её AppID
        //   101 — Steam не найден в реестре
        //  -1   — Steam API не поднялся (закрыт/перезапускается) — временный сбой
        // Только код 3 означает воспроизводимую проблему конкретной игры, поэтому
        // лишь он приводит к попаданию в чёрный список на стороне GUI.
        private const int GameUnavailableExitCode = 3;
        private const int AchievementFailureExitCode = 2;

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
            var achievementIssue = false;
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

                        // Проблема с достижениями больше НЕ обрывает сессию: часть
                        // достижений уже сохранена, а игре всё ещё нужно доиграть свой
                        // таймер. Раньше здесь стоял ранний return 2 — игра теряла и
                        // оставшееся время активности, и попадала в чёрный список.
                        achievementIssue = IsFailure(result);
                        if (achievementIssue)
                        {
                            WorkerLog.Emit(
                                LogLevel.Warning,
                                options.AppId,
                                "Achievements were not stored. Continuing activity emulation.");
                        }

                        if (options.ExitAfterSeconds == 0)
                        {
                            return achievementIssue ? AchievementFailureExitCode : 0;
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

                // Steam не принял AppID — единственный отказ, относящийся к самой игре
                // (её нет в аккаунте либо AppID неверный). Отделяем его от временных
                // сбоев, чтобы в чёрный список уходила только она.
                if (exception.Failure == SteamAccessFailure.AppIdMismatch)
                {
                    WorkerLog.Emit(
                        LogLevel.Error,
                        options.AppId,
                        "Steam rejected this AppID. The game is probably not on the account.");
                    WorkerLog.Fatal($"[GAME UNAVAILABLE] {exception}");
                    return GameUnavailableExitCode;
                }

                WorkerLog.Emit(
                    LogLevel.Error,
                    options.AppId,
                    $"Failed to initialize Steam API. Please ensure Steam is running and logged in. Error: {exception.Message}");
                WorkerLog.Fatal($"[FATAL] Steam API initialization failed: {exception}");
                return -1;
            }

            WorkerLog.Emit(LogLevel.Success, options.AppId, "Process finished.");
            return achievementIssue ? AchievementFailureExitCode : 0;
        }

        private static bool IsFailure(AchievementOutcome result)
        {
            // PartialFailure намеренно НЕ провал: часть достижений недоступна для
            // разблокировки штатно (серверные, привязанные к статистике), и это
            // нормальный исход, а не поломка игры.
            return result == AchievementOutcome.ServiceUnavailable ||
                   result == AchievementOutcome.CommitFailed;
        }
    }
}

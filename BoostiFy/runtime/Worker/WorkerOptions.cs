using System;
using System.Globalization;

namespace Boostify.Runtime.Worker
{
    internal sealed class WorkerOptions
    {
        public bool ServerMode { get; private set; }
        public bool SelfTestMode { get; private set; }
        public uint AppId { get; private set; }
        public bool UnlockAll { get; private set; }
        public int ExitAfterSeconds { get; private set; }
        public double DelayPerAchievement { get; private set; }
        public bool RandomAchievementDelay { get; private set; }
        public string ValidationError { get; private set; }
        public bool IsValid => string.IsNullOrEmpty(ValidationError);

        public static WorkerOptions Parse(string[] args)
        {
            var result = new WorkerOptions();
            for (var index = 0; index < args.Length; index++)
            {
                switch (args[index])
                {
                    case "--server":
                        result.ServerMode = true;
                        break;
                    case "--self-test":
                        result.SelfTestMode = true;
                        break;
                    case "--appid":
                        if (index + 1 >= args.Length ||
                            !uint.TryParse(args[++index], NumberStyles.None, CultureInfo.InvariantCulture, out var appId) ||
                            appId == 0)
                        {
                            result.SetError("--appid requires a positive 32-bit integer.");
                            break;
                        }
                        result.AppId = appId;
                        break;
                    case "--unlock-all":
                        result.UnlockAll = true;
                        break;
                    case "--exit-after":
                        if (index + 1 >= args.Length ||
                            !int.TryParse(args[++index], NumberStyles.Integer, CultureInfo.InvariantCulture, out var seconds) ||
                            seconds < 0 || seconds > 604920)
                        {
                            result.SetError("--exit-after must be between 0 and 604920 seconds.");
                            break;
                        }
                        result.ExitAfterSeconds = seconds;
                        break;
                    case "--delay-per-achievement":
                        if (index + 1 >= args.Length ||
                            !double.TryParse(
                                args[++index],
                                NumberStyles.Float,
                                CultureInfo.InvariantCulture,
                                out var delay) ||
                            double.IsNaN(delay) ||
                            double.IsInfinity(delay) ||
                            delay < 0 || delay > 3600)
                        {
                            result.SetError("--delay-per-achievement must be between 0 and 3600 seconds.");
                            break;
                        }
                        result.DelayPerAchievement = delay;
                        break;
                    case "--random-delay-per-achievement":
                        result.RandomAchievementDelay = true;
                        break;
                    default:
                        result.SetError($"Unknown argument: {args[index]}");
                        break;
                }
            }

            var modes = (result.ServerMode ? 1 : 0) + (result.SelfTestMode ? 1 : 0);
            if (modes > 1)
            {
                result.SetError("--server and --self-test cannot be combined.");
            }
            else if (modes == 0 && result.AppId == 0)
            {
                result.SetError("--appid is required in booster mode.");
            }
            else if (modes > 0 &&
                     (result.AppId != 0 || result.UnlockAll || result.ExitAfterSeconds != 0 ||
                      result.DelayPerAchievement != 0 || result.RandomAchievementDelay))
            {
                result.SetError("Diagnostic/server modes cannot be combined with booster arguments.");
            }
            else if (result.RandomAchievementDelay && result.DelayPerAchievement > 0)
            {
                result.SetError("Choose either fixed or random achievement delay, not both.");
            }
            return result;
        }

        private void SetError(string message)
        {
            if (string.IsNullOrEmpty(ValidationError))
            {
                ValidationError = message;
            }
        }
    }
}

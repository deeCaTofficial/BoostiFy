using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Boostify.Runtime.Steam;

namespace Boostify.Runtime.Worker
{
    internal static class OwnershipProtocol
    {
        private const int MaximumBatchSize = 500;

        public static int Run()
        {
            using (var session = SteamSession.Open(0))
            {
                if (session.Apps == null || !session.Apps.IsAvailable)
                {
                    throw new SteamAccessException(
                        SteamAccessFailure.ClientInterfaceMissing,
                        "SteamApps008 is unavailable.");
                }
                Console.WriteLine("READY");
                string input;
                while ((input = Console.ReadLine()) != null)
                {
                    if (string.Equals(input, "exit", StringComparison.OrdinalIgnoreCase))
                    {
                        break;
                    }

                    if (input.StartsWith("BATCH ", StringComparison.OrdinalIgnoreCase))
                    {
                        WriteBatchResult(session, input.Substring(6));
                        continue;
                    }

                    WriteSingleResult(session, input);
                }
            }

            return 0;
        }

        private static void WriteSingleResult(SteamSession session, string input)
        {
            if (!uint.TryParse(input.Trim(), NumberStyles.None, CultureInfo.InvariantCulture, out var appId) ||
                appId == 0)
            {
                Console.WriteLine("INVALID");
                return;
            }

            Console.WriteLine(session.Apps.IsOwned(appId) ? "OWNED" : "NOT_OWNED");
        }

        private static void WriteBatchResult(SteamSession session, string input)
        {
            var owned = ParseAppIds(input)
                .Distinct()
                .Take(MaximumBatchSize)
                .Where(session.Apps.IsOwned)
                .OrderBy(appId => appId);
            Console.WriteLine("OWNED " + string.Join(",", owned));
        }

        private static IEnumerable<uint> ParseAppIds(string input)
        {
            foreach (var token in input.Split(','))
            {
                if (uint.TryParse(
                        token.Trim(),
                        NumberStyles.None,
                        CultureInfo.InvariantCulture,
                        out var appId) &&
                    appId > 0)
                {
                    yield return appId;
                }
            }
        }
    }
}

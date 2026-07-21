using System.Collections.Generic;
using System.Globalization;

namespace Boostify.Runtime.Steam.Schemas
{
    public static class AchievementCatalog
    {
        private const int AchievementStatType = 4;
        private const int GroupAchievementStatType = 5;

        public static IReadOnlyList<string> ReadNames(string schemaPath, uint appId)
        {
            var root = BinaryKvReader.ReadFile(schemaPath);
            var stats = root?
                .Find(appId.ToString(CultureInfo.InvariantCulture))?
                .Find("stats");
            if (stats == null)
            {
                return new string[0];
            }

            var result = new List<string>();
            var unique = new HashSet<string>();
            foreach (var stat in stats.Children)
            {
                var type = stat.Find("type_int")?.AsInt32(
                    stat.Find("type")?.AsInt32() ?? 0)
                    ?? stat.Find("type")?.AsInt32()
                    ?? 0;
                if (type != AchievementStatType && type != GroupAchievementStatType)
                {
                    continue;
                }

                var bits = stat.Find("bits");
                if (bits == null)
                {
                    continue;
                }

                foreach (var bit in bits.Children)
                {
                    var name = bit.Find("name")?.AsString();
                    if (!string.IsNullOrWhiteSpace(name) && unique.Add(name))
                    {
                        result.Add(name);
                    }
                }
            }

            return result;
        }
    }
}

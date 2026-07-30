using System.Collections.Generic;
using System.Globalization;

namespace Boostify.Runtime.Steam.Schemas
{
    public static class AchievementCatalog
    {
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
                // Достижения лежат в статах с подузлом "bits" — и только у них он есть
                // (INT/FLOAT/AVGRATE-статы его не имеют). Раньше стат сначала отбирался по
                // числовому типу (4/5), но Steam пишет "type" то числом (4), то строкой
                // ("ACHIEVEMENTS"): на строковом варианте Convert.ToInt32 бросал исключение,
                // тип обнулялся, и достижения ~трети игр просто не находились. Наличие "bits"
                // — признак надёжнее и не зависит от того, как записан тип.
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

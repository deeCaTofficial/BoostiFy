using System;
using System.Collections.Generic;
using System.Globalization;

namespace Boostify.Runtime.Steam.Schemas
{
    internal sealed class KvNode
    {
        private readonly List<KvNode> _children = new();

        public KvNode(string name, object value = null)
        {
            Name = name ?? string.Empty;
            Value = value;
        }

        public string Name { get; }
        public object Value { get; }
        public IReadOnlyList<KvNode> Children => _children;

        public void Add(KvNode child)
        {
            if (child == null)
            {
                throw new ArgumentNullException(nameof(child));
            }

            _children.Add(child);
        }

        public KvNode Find(string name)
        {
            foreach (var child in _children)
            {
                if (string.Equals(child.Name, name, StringComparison.OrdinalIgnoreCase))
                {
                    return child;
                }
            }

            return null;
        }

        public string AsString(string fallback = "")
        {
            return Value == null ? fallback : Convert.ToString(Value, CultureInfo.InvariantCulture);
        }

        public int AsInt32(int fallback = 0)
        {
            if (Value == null)
            {
                return fallback;
            }

            try
            {
                return Convert.ToInt32(Value, CultureInfo.InvariantCulture);
            }
            catch (Exception)
            {
                return fallback;
            }
        }
    }
}

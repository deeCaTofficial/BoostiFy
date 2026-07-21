using System;
using System.IO;
using System.Text;

namespace Boostify.Runtime.Steam.Schemas
{
    internal static class BinaryKvReader
    {
        private const int MaximumDepth = 128;
        private const int MaximumStringBytes = 1024 * 1024;

        private enum ValueType : byte
        {
            Object = 0,
            String = 1,
            Int32 = 2,
            Float32 = 3,
            Pointer = 4,
            WideString = 5,
            Color = 6,
            UInt64 = 7,
            End = 8,
        }

        public static KvNode ReadFile(string path)
        {
            if (!File.Exists(path))
            {
                return null;
            }

            try
            {
                using (var stream = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                using (var reader = new BinaryReader(stream, Encoding.UTF8, leaveOpen: false))
                {
                    var root = new KvNode("<root>");
                    ReadChildren(reader, root, 0);
                    return root;
                }
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static void ReadChildren(BinaryReader reader, KvNode parent, int depth)
        {
            if (depth > MaximumDepth)
            {
                throw new FormatException("KeyValue nesting limit exceeded.");
            }

            while (true)
            {
                var type = (ValueType)reader.ReadByte();
                if (type == ValueType.End)
                {
                    return;
                }

                var name = ReadNullTerminated(reader, Encoding.UTF8, 1);
                var node = new KvNode(name, ReadValue(reader, type, depth));
                if (type == ValueType.Object)
                {
                    node = new KvNode(name);
                    ReadChildren(reader, node, depth + 1);
                }

                parent.Add(node);
            }
        }

        private static object ReadValue(BinaryReader reader, ValueType type, int depth)
        {
            switch (type)
            {
                case ValueType.Object:
                    return null;
                case ValueType.String:
                    return ReadNullTerminated(reader, Encoding.UTF8, 1);
                case ValueType.WideString:
                    return ReadNullTerminated(reader, Encoding.Unicode, 2);
                case ValueType.Int32:
                    return reader.ReadInt32();
                case ValueType.Float32:
                    return reader.ReadSingle();
                case ValueType.Pointer:
                case ValueType.Color:
                    return reader.ReadUInt32();
                case ValueType.UInt64:
                    return reader.ReadUInt64();
                default:
                    throw new FormatException($"Unsupported KeyValue type: {(byte)type} at depth {depth}.");
            }
        }

        private static string ReadNullTerminated(BinaryReader reader, Encoding encoding, int unitSize)
        {
            using (var buffer = new MemoryStream())
            {
                while (buffer.Length < MaximumStringBytes)
                {
                    var unit = reader.ReadBytes(unitSize);
                    if (unit.Length != unitSize)
                    {
                        throw new EndOfStreamException();
                    }

                    var terminator = true;
                    for (var index = 0; index < unit.Length; index++)
                    {
                        if (unit[index] != 0)
                        {
                            terminator = false;
                            break;
                        }
                    }

                    if (terminator)
                    {
                        return encoding.GetString(buffer.ToArray());
                    }

                    buffer.Write(unit, 0, unit.Length);
                }
            }

            throw new FormatException("KeyValue string limit exceeded.");
        }
    }
}

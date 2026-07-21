using System;
using System.IO;
using System.Linq;
using System.Text;
using Boostify.Runtime.Steam.Schemas;

namespace Boostify.Runtime.Worker
{
    internal static class RuntimeDiagnostics
    {
        public static int Run()
        {
            var tempPath = Path.Combine(Path.GetTempPath(), $"boostify-schema-{Guid.NewGuid():N}.bin");
            try
            {
                WriteSchemaFixture(tempPath);
                var names = AchievementCatalog.ReadNames(tempPath, 10);
                if (names.Count != 1 || names.Single() != "ACH_TEST")
                {
                    Console.WriteLine("SELF_TEST_FAILED schema-reader");
                    return 1;
                }

                Console.WriteLine("SELF_TEST_OK");
                return 0;
            }
            finally
            {
                try
                {
                    File.Delete(tempPath);
                }
                catch (Exception)
                {
                    // The operating system can clean a diagnostic temp file later.
                }
            }
        }

        private static void WriteSchemaFixture(string path)
        {
            using (var stream = File.Create(path))
            using (var writer = new BinaryWriter(stream, Encoding.UTF8))
            {
                WriteObject(writer, "10", () =>
                    WriteObject(writer, "stats", () =>
                        WriteObject(writer, "0", () =>
                        {
                            WriteInt32(writer, "type_int", 4);
                            WriteObject(writer, "bits", () =>
                                WriteObject(writer, "0", () =>
                                    WriteString(writer, "name", "ACH_TEST")));
                        })));
                writer.Write((byte)8);
            }
        }

        private static void WriteObject(BinaryWriter writer, string name, Action content)
        {
            writer.Write((byte)0);
            WriteCString(writer, name);
            content();
            writer.Write((byte)8);
        }

        private static void WriteInt32(BinaryWriter writer, string name, int value)
        {
            writer.Write((byte)2);
            WriteCString(writer, name);
            writer.Write(value);
        }

        private static void WriteString(BinaryWriter writer, string name, string value)
        {
            writer.Write((byte)1);
            WriteCString(writer, name);
            WriteCString(writer, value);
        }

        private static void WriteCString(BinaryWriter writer, string value)
        {
            writer.Write(Encoding.UTF8.GetBytes(value));
            writer.Write((byte)0);
        }
    }
}

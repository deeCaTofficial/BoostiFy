using System;
using System.IO;
using System.Text;

namespace Boostify.Runtime.Worker
{
    internal static class Program
    {
        private static int Main(string[] args)
        {
            ConfigureConsoleEncoding();
            WorkerLog.Trace($"Main started: {string.Join(" ", args)}");

            try
            {
                var options = WorkerOptions.Parse(args);
                if (!options.IsValid)
                {
                    Console.WriteLine($"[ERROR] {options.ValidationError}");
                    Console.WriteLine(
                        $"Usage: {AppDomain.CurrentDomain.FriendlyName} --appid <AppID> [--unlock-all] [--exit-after <seconds>] | --server | --self-test");
                    return 1;
                }
                if (options.SelfTestMode)
                {
                    return RuntimeDiagnostics.Run();
                }

                return options.ServerMode
                    ? OwnershipProtocol.Run()
                    : BoostSession.Run(options);
            }
            catch (Exception exception)
            {
                Console.WriteLine("[FATAL ERROR] An unexpected error occurred in the engine.");
                Console.WriteLine($"Error Message: {exception.Message}");
                WorkerLog.Fatal($"[FATAL] {exception}");
                return -1;
            }
        }

        private static void ConfigureConsoleEncoding()
        {
            try
            {
                var utf8 = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
                Console.OutputEncoding = utf8;
                Console.InputEncoding = utf8;
            }
            catch (IOException)
            {
                // Windowed builds can have no attached console.
            }
        }
    }
}

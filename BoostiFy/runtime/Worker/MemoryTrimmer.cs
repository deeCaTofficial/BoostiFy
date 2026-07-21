using System;
using System.Runtime.InteropServices;

namespace Boostify.Runtime.Worker
{
    internal static class MemoryTrimmer
    {
        public static void TrimWorkingSet()
        {
            try
            {
                GC.Collect();
                GC.WaitForPendingFinalizers();
                EmptyWorkingSet(GetCurrentProcess());
            }
            catch (Exception)
            {
                // This is an optional memory optimization.
            }
        }

        [DllImport("kernel32.dll")]
        private static extern IntPtr GetCurrentProcess();

        [DllImport("psapi.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool EmptyWorkingSet(IntPtr process);
    }
}

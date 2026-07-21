using System;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32;

namespace Boostify.Runtime.Steam.Interop
{
    internal sealed class SteamClientLibrary : IDisposable
    {
        private const uint LoadWithAlteredSearchPath = 0x00000008;

        private readonly IntPtr _module;
        private readonly CreateInterfaceDelegate _createInterface;
        private readonly GetCallbackDelegate _getCallback;
        private readonly FreeLastCallbackDelegate _freeLastCallback;
        private bool _disposed;

        private SteamClientLibrary(
            string installDirectory,
            IntPtr module,
            CreateInterfaceDelegate createInterface,
            GetCallbackDelegate getCallback,
            FreeLastCallbackDelegate freeLastCallback)
        {
            InstallDirectory = installDirectory;
            _module = module;
            _createInterface = createInterface;
            _getCallback = getCallback;
            _freeLastCallback = freeLastCallback;
        }

        public string InstallDirectory { get; }

        public static SteamClientLibrary Open()
        {
            var installDirectory = SteamInstallation.Find();
            if (string.IsNullOrWhiteSpace(installDirectory))
            {
                throw new SteamAccessException(
                    SteamAccessFailure.SteamNotInstalled,
                    "failed to get Steam install path");
            }

            var libraryPath = Path.Combine(installDirectory, "steamclient.dll");
            var module = LoadLibraryEx(libraryPath, IntPtr.Zero, LoadWithAlteredSearchPath);
            if (module == IntPtr.Zero)
            {
                throw new SteamAccessException(
                    SteamAccessFailure.NativeLibraryLoadFailed,
                    $"failed to load Steam client library: {libraryPath}");
            }

            try
            {
                return new SteamClientLibrary(
                    installDirectory,
                    module,
                    LoadExport<CreateInterfaceDelegate>(module, "CreateInterface"),
                    LoadExport<GetCallbackDelegate>(module, "Steam_BGetCallback"),
                    LoadExport<FreeLastCallbackDelegate>(module, "Steam_FreeLastCallback"));
            }
            catch
            {
                FreeLibrary(module);
                throw;
            }
        }

        public IntPtr CreateInterface(string version)
        {
            ThrowIfDisposed();
            return _createInterface(version, IntPtr.Zero);
        }

        public void DrainCallbacks(int pipe)
        {
            ThrowIfDisposed();
            while (_getCallback(pipe, out _, out _))
            {
                _freeLastCallback(pipe);
            }
        }

        public void Dispose()
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
            FreeLibrary(_module);
        }

        private static TDelegate LoadExport<TDelegate>(IntPtr module, string name) where TDelegate : class
        {
            var address = GetProcAddress(module, name);
            if (address == IntPtr.Zero)
            {
                throw new SteamAccessException(
                    SteamAccessFailure.ExportMissing,
                    $"Steam client export is missing: {name}");
            }

            return (TDelegate)(object)Marshal.GetDelegateForFunctionPointer(address, typeof(TDelegate));
        }

        private void ThrowIfDisposed()
        {
            if (_disposed)
            {
                throw new ObjectDisposedException(nameof(SteamClientLibrary));
            }
        }

        [StructLayout(LayoutKind.Sequential, Pack = 1)]
        private struct CallbackMessage
        {
            public int User;
            public int Id;
            public IntPtr Data;
            public int DataSize;
        }

        [UnmanagedFunctionPointer(CallingConvention.Cdecl, CharSet = CharSet.Ansi)]
        private delegate IntPtr CreateInterfaceDelegate(string version, IntPtr returnCode);

        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        [return: MarshalAs(UnmanagedType.I1)]
        private delegate bool GetCallbackDelegate(int pipe, out CallbackMessage message, out int callHandle);

        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        [return: MarshalAs(UnmanagedType.I1)]
        private delegate bool FreeLastCallbackDelegate(int pipe);

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern IntPtr LoadLibraryEx(string fileName, IntPtr file, uint flags);

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Ansi)]
        private static extern IntPtr GetProcAddress(IntPtr module, string name);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool FreeLibrary(IntPtr module);
    }

    internal static class SteamInstallation
    {
        public static string Find()
        {
            foreach (var view in new[] { RegistryView.Registry32, RegistryView.Registry64 })
            {
                var machinePath = ReadRegistryPath(RegistryHive.LocalMachine, view);
                if (IsSteamDirectory(machinePath))
                {
                    return machinePath;
                }

                var userPath = ReadRegistryPath(RegistryHive.CurrentUser, view);
                if (IsSteamDirectory(userPath))
                {
                    return userPath;
                }
            }

            return null;
        }

        private static string ReadRegistryPath(RegistryHive hive, RegistryView view)
        {
            try
            {
                using (var baseKey = RegistryKey.OpenBaseKey(hive, view))
                using (var steamKey = baseKey.OpenSubKey(@"Software\Valve\Steam"))
                {
                    return (steamKey?.GetValue("InstallPath") ?? steamKey?.GetValue("SteamPath")) as string;
                }
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static bool IsSteamDirectory(string path)
        {
            return !string.IsNullOrWhiteSpace(path) && File.Exists(Path.Combine(path, "steamclient.dll"));
        }
    }
}

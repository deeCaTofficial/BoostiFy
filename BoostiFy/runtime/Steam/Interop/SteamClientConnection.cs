using System;
using System.Runtime.InteropServices;

namespace Boostify.Runtime.Steam.Interop
{
    internal sealed class SteamClientConnection
    {
        private const int CreatePipeSlot = 0;
        private const int ReleasePipeSlot = 1;
        private const int ConnectGlobalUserSlot = 2;
        private const int ReleaseUserSlot = 4;
        private const int GetUtilsSlot = 9;
        private const int GetUserStatsSlot = 13;
        private const int GetAppsSlot = 15;

        private readonly VTableBinding _native;

        public SteamClientConnection(IntPtr instance)
        {
            _native = new VTableBinding(instance);
        }

        public int CreatePipe()
        {
            return _native.Bind<CreatePipeDelegate>(CreatePipeSlot)(_native.Instance);
        }

        public bool ReleasePipe(int pipe)
        {
            return _native.Bind<ReleasePipeDelegate>(ReleasePipeSlot)(_native.Instance, pipe);
        }

        public int ConnectGlobalUser(int pipe)
        {
            return _native.Bind<ConnectGlobalUserDelegate>(ConnectGlobalUserSlot)(_native.Instance, pipe);
        }

        public void ReleaseUser(int pipe, int user)
        {
            _native.Bind<ReleaseUserDelegate>(ReleaseUserSlot)(_native.Instance, pipe, user);
        }

        public IntPtr GetUtils(int pipe)
        {
            using (var version = Utf8String.From("SteamUtils005"))
            {
                return _native.Bind<GetUtilsDelegate>(GetUtilsSlot)(
                    _native.Instance,
                    pipe,
                    version.Pointer);
            }
        }

        public IntPtr GetUserStats(int user, int pipe)
        {
            using (var version = Utf8String.From("STEAMUSERSTATS_INTERFACE_VERSION013"))
            {
                return _native.Bind<GetUserInterfaceDelegate>(GetUserStatsSlot)(
                    _native.Instance,
                    user,
                    pipe,
                    version.Pointer);
            }
        }

        public IntPtr GetApps(int user, int pipe)
        {
            using (var version = Utf8String.From("STEAMAPPS_INTERFACE_VERSION008"))
            {
                return _native.Bind<GetUserInterfaceDelegate>(GetAppsSlot)(
                    _native.Instance,
                    user,
                    pipe,
                    version.Pointer);
            }
        }

        [UnmanagedFunctionPointer(CallingConvention.ThisCall)]
        private delegate int CreatePipeDelegate(IntPtr self);

        [UnmanagedFunctionPointer(CallingConvention.ThisCall)]
        [return: MarshalAs(UnmanagedType.I1)]
        private delegate bool ReleasePipeDelegate(IntPtr self, int pipe);

        [UnmanagedFunctionPointer(CallingConvention.ThisCall)]
        private delegate int ConnectGlobalUserDelegate(IntPtr self, int pipe);

        [UnmanagedFunctionPointer(CallingConvention.ThisCall)]
        private delegate void ReleaseUserDelegate(IntPtr self, int pipe, int user);

        [UnmanagedFunctionPointer(CallingConvention.ThisCall)]
        private delegate IntPtr GetUtilsDelegate(IntPtr self, int pipe, IntPtr version);

        [UnmanagedFunctionPointer(CallingConvention.ThisCall)]
        private delegate IntPtr GetUserInterfaceDelegate(IntPtr self, int user, int pipe, IntPtr version);
    }
}

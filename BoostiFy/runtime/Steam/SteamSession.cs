using System;
using System.Globalization;
using System.Runtime.InteropServices;
using Boostify.Runtime.Steam.Features;
using Boostify.Runtime.Steam.Interop;

namespace Boostify.Runtime.Steam
{
    public sealed class SteamSession : IDisposable
    {
        private const int GetAppIdSlot = 9;

        private SteamClientLibrary _library;
        private SteamClientConnection _connection;
        private int _pipe;
        private int _user;
        private bool _disposed;

        private SteamSession()
        {
        }

        public AppOwnership Apps { get; private set; }
        public Achievements Achievements { get; private set; }
        public string InstallDirectory => _library?.InstallDirectory;

        public static SteamSession Open(uint appId)
        {
            var session = new SteamSession();
            try
            {
                if (appId > 0)
                {
                    Environment.SetEnvironmentVariable(
                        "SteamAppId",
                        appId.ToString(CultureInfo.InvariantCulture));
                }

                session._library = SteamClientLibrary.Open();
                var clientPointer = session._library.CreateInterface("SteamClient018");
                if (clientPointer == IntPtr.Zero)
                {
                    throw new SteamAccessException(
                        SteamAccessFailure.ClientInterfaceMissing,
                        "failed to create SteamClient018");
                }

                session._connection = new SteamClientConnection(clientPointer);
                session._pipe = session._connection.CreatePipe();
                if (session._pipe == 0)
                {
                    throw new SteamAccessException(
                        SteamAccessFailure.PipeCreationFailed,
                        "failed to create Steam pipe");
                }

                session._user = session._connection.ConnectGlobalUser(session._pipe);
                if (session._user == 0)
                {
                    throw new SteamAccessException(
                        SteamAccessFailure.UserConnectionFailed,
                        "failed to connect to Steam global user");
                }

                var utilsPointer = session._connection.GetUtils(session._pipe);
                if (appId > 0 && GetCurrentAppId(utilsPointer) != appId)
                {
                    throw new SteamAccessException(
                        SteamAccessFailure.AppIdMismatch,
                        "appID mismatch");
                }

                var appsPointer = session._connection.GetApps(session._user, session._pipe);
                if (appsPointer == IntPtr.Zero)
                {
                    throw new SteamAccessException(
                        SteamAccessFailure.ClientInterfaceMissing,
                        "STEAMAPPS_INTERFACE_VERSION008 is unavailable");
                }
                session.Apps = new AppOwnership(appsPointer);
                session.Achievements = new Achievements(
                    session._connection.GetUserStats(session._user, session._pipe));
                return session;
            }
            catch
            {
                session.Dispose();
                throw;
            }
        }

        public void PumpCallbacks()
        {
            ThrowIfDisposed();
            _library.DrainCallbacks(_pipe);
        }

        public void Dispose()
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
            if (_connection != null && _pipe != 0)
            {
                if (_user != 0)
                {
                    _connection.ReleaseUser(_pipe, _user);
                    _user = 0;
                }

                _connection.ReleasePipe(_pipe);
                _pipe = 0;
            }

            _library?.Dispose();
            _library = null;
            _connection = null;
        }

        private static uint GetCurrentAppId(IntPtr utilsPointer)
        {
            if (utilsPointer == IntPtr.Zero)
            {
                return 0;
            }

            var native = new VTableBinding(utilsPointer);
            var getAppId = native.Bind<GetAppIdDelegate>(GetAppIdSlot);
            return getAppId(native.Instance);
        }

        private void ThrowIfDisposed()
        {
            if (_disposed)
            {
                throw new ObjectDisposedException(nameof(SteamSession));
            }
        }

        [UnmanagedFunctionPointer(CallingConvention.ThisCall)]
        private delegate uint GetAppIdDelegate(IntPtr self);
    }
}

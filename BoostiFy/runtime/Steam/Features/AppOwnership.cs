using System;
using System.Runtime.InteropServices;
using Boostify.Runtime.Steam.Interop;

namespace Boostify.Runtime.Steam.Features
{
    public sealed class AppOwnership
    {
        private const int IsSubscribedAppSlot = 6;
        private readonly VTableBinding _native;
        private readonly IsSubscribedAppDelegate _isSubscribedApp;

        internal AppOwnership(IntPtr instance)
        {
            if (instance == IntPtr.Zero)
            {
                return;
            }

            _native = new VTableBinding(instance);
            _isSubscribedApp = _native.Bind<IsSubscribedAppDelegate>(IsSubscribedAppSlot);
        }

        public bool IsAvailable => _native != null;

        public bool IsOwned(uint appId)
        {
            return appId > 0 && _native != null && _isSubscribedApp(_native.Instance, appId);
        }

        [UnmanagedFunctionPointer(CallingConvention.ThisCall)]
        [return: MarshalAs(UnmanagedType.I1)]
        private delegate bool IsSubscribedAppDelegate(IntPtr self, uint appId);
    }
}

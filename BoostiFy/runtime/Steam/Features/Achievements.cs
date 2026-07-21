using System;
using System.Runtime.InteropServices;
using Boostify.Runtime.Steam.Interop;

namespace Boostify.Runtime.Steam.Features
{
    public sealed class Achievements
    {
        private const int GetAchievementSlot = 5;
        private const int SetAchievementSlot = 6;
        private const int StoreStatsSlot = 9;

        private readonly VTableBinding _native;
        private readonly GetAchievementDelegate _getAchievement;
        private readonly SetAchievementDelegate _setAchievement;
        private readonly StoreStatsDelegate _storeStats;

        internal Achievements(IntPtr instance)
        {
            if (instance == IntPtr.Zero)
            {
                return;
            }

            _native = new VTableBinding(instance);
            _getAchievement = _native.Bind<GetAchievementDelegate>(GetAchievementSlot);
            _setAchievement = _native.Bind<SetAchievementDelegate>(SetAchievementSlot);
            _storeStats = _native.Bind<StoreStatsDelegate>(StoreStatsSlot);
        }

        public bool IsAvailable => _native != null;

        public bool TryGetUnlocked(string achievementName, out bool unlocked)
        {
            unlocked = false;
            if (_native == null || string.IsNullOrWhiteSpace(achievementName))
            {
                return false;
            }

            using (var name = Utf8String.From(achievementName))
            {
                return _getAchievement(_native.Instance, name.Pointer, out unlocked);
            }
        }

        public bool Unlock(string achievementName)
        {
            if (_native == null || string.IsNullOrWhiteSpace(achievementName))
            {
                return false;
            }

            using (var name = Utf8String.From(achievementName))
            {
                return _setAchievement(_native.Instance, name.Pointer);
            }
        }

        public bool Commit()
        {
            return _native != null && _storeStats(_native.Instance);
        }

        [UnmanagedFunctionPointer(CallingConvention.ThisCall)]
        [return: MarshalAs(UnmanagedType.I1)]
        private delegate bool GetAchievementDelegate(
            IntPtr self,
            IntPtr name,
            [MarshalAs(UnmanagedType.I1)] out bool unlocked);

        [UnmanagedFunctionPointer(CallingConvention.ThisCall)]
        [return: MarshalAs(UnmanagedType.I1)]
        private delegate bool SetAchievementDelegate(IntPtr self, IntPtr name);

        [UnmanagedFunctionPointer(CallingConvention.ThisCall)]
        [return: MarshalAs(UnmanagedType.I1)]
        private delegate bool StoreStatsDelegate(IntPtr self);
    }
}

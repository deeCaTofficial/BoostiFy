using System;

namespace Boostify.Runtime.Steam
{
    public enum SteamAccessFailure
    {
        Unknown = 0,
        SteamNotInstalled,
        NativeLibraryLoadFailed,
        ExportMissing,
        ClientInterfaceMissing,
        PipeCreationFailed,
        UserConnectionFailed,
        AppIdMismatch,
    }

    public sealed class SteamAccessException : Exception
    {
        public SteamAccessException(SteamAccessFailure failure, string message)
            : base(message)
        {
            Failure = failure;
        }

        public SteamAccessException(SteamAccessFailure failure, string message, Exception innerException)
            : base(message, innerException)
        {
            Failure = failure;
        }

        public SteamAccessFailure Failure { get; }
    }
}

using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

namespace Boostify.Runtime.Steam.Interop
{
    internal sealed class VTableBinding
    {
        private readonly Dictionary<Tuple<int, Type>, Delegate> _bindings = new();
        private readonly IntPtr _vtable;

        public VTableBinding(IntPtr instance)
        {
            if (instance == IntPtr.Zero)
            {
                throw new ArgumentException("Native interface pointer cannot be null.", nameof(instance));
            }

            Instance = instance;
            _vtable = Marshal.ReadIntPtr(instance);
            if (_vtable == IntPtr.Zero)
            {
                throw new InvalidOperationException("Native interface has no virtual table.");
            }
        }

        public IntPtr Instance { get; }

        public TDelegate Bind<TDelegate>(int slot) where TDelegate : class
        {
            if (slot < 0)
            {
                throw new ArgumentOutOfRangeException(nameof(slot));
            }

            var key = Tuple.Create(slot, typeof(TDelegate));
            if (!_bindings.TryGetValue(key, out var function))
            {
                var address = Marshal.ReadIntPtr(_vtable, slot * IntPtr.Size);
                if (address == IntPtr.Zero)
                {
                    throw new MissingMethodException($"Native vtable slot {slot} is empty.");
                }

                function = Marshal.GetDelegateForFunctionPointer(address, typeof(TDelegate));
                _bindings.Add(key, function);
            }

            return (TDelegate)(object)function;
        }
    }

    internal sealed class Utf8String : IDisposable
    {
        private Utf8String(IntPtr pointer)
        {
            Pointer = pointer;
        }

        public IntPtr Pointer { get; private set; }

        public static Utf8String From(string value)
        {
            if (value == null)
            {
                return new Utf8String(IntPtr.Zero);
            }

            var bytes = Encoding.UTF8.GetBytes(value);
            var pointer = Marshal.AllocHGlobal(bytes.Length + 1);
            Marshal.Copy(bytes, 0, pointer, bytes.Length);
            Marshal.WriteByte(pointer, bytes.Length, 0);
            return new Utf8String(pointer);
        }

        public void Dispose()
        {
            if (Pointer == IntPtr.Zero)
            {
                return;
            }

            Marshal.FreeHGlobal(Pointer);
            Pointer = IntPtr.Zero;
        }
    }
}

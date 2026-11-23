"""Encrypt saved secrets with Windows DPAPI (only the same Windows user can decrypt them)."""
import base64
import sys

PREFIX = "dpapi:"

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32

    def _call(func, data):
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in, blob_out = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), _Blob()
        # CRYPTPROTECT_UI_FORBIDDEN = 0x1
        if not func(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)):
            raise OSError("DPAPI call failed")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            _kernel32.LocalFree(blob_out.pbData)

    def encrypt(text):
        if not text:
            return ""
        return PREFIX + base64.b64encode(_call(_crypt32.CryptProtectData, text.encode())).decode()

    def decrypt(value):
        if not value or not value.startswith(PREFIX):
            return value or ""
        try:
            return _call(_crypt32.CryptUnprotectData, base64.b64decode(value[len(PREFIX):])).decode()
        except OSError:
            return ""

else:
    # Other systems (development): stored as-is in the user's settings file
    def encrypt(text):
        return text or ""

    def decrypt(value):
        return "" if (value or "").startswith(PREFIX) else (value or "")

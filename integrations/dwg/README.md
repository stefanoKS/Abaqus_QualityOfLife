# Native DWG reader

`bin/dwg-inventory.exe` is an application-owned helper linked against
[ACadSharp](https://github.com/DomCR/ACadSharp) 3.8.35 (MIT, `bin/ACadSharp.dll`). It decodes DWG
bytes directly and prints a model-space inventory as JSON on stdout.

- Source: `src/DwgInventory.cs`, built with the .NET Framework 4.8 compiler
  (`C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /target:exe /platform:x64 /optimize+ /out:bin/dwg-inventory.exe /reference:ACadSharp.dll src/DwgInventory.cs`).
  Ship the rebuilt binary with `ACadSharp.dll` beside it.
- Runtime: .NET Framework 4.8, present on Windows 10 1903+ and Windows 11. No SDK, no CAD
  converter, no network access and no CAD automation are required.
- Exit codes: 0 ok, 64 usage, 65 corrupt file, 66 decode failure, 67 unsupported DWG version.
  Failures still print `{"error": {"code": ..., "message": ...}}`.
- Provenance: the helper reports its own name/version and the SHA-256 of the bytes it read, so an
  import can be traced to an exact drawing revision.
- Licence: ACadSharp is MIT; keep `ACadSharp.dll` unmodified and retain this notice when redistributing.

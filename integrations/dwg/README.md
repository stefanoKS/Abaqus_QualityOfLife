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
- Coordinates: **this helper emits world coordinates (WCS)** for `LINE`, `ARC`, `CIRCLE` and
  `LWPOLYLINE`. It applies the entity's object coordinate system (OCS) exactly once, using the
  ACadSharp/CSMath arbitrary-axis basis derived from the native extrusion normal, before block
  insertion transforms. `LINE` endpoints are already WCS. `ARC` reports the WCS centre, radius,
  endpoints, interior midpoint and a **signed** sweep (negative when the extrusion reflects the
  source plane); `LWPOLYLINE` reports WCS vertices and a bulge sign corrected for reflection.
  A non-planar extrusion (normal not parallel to WCS Z) is reported as
  `transformError: "unsupported-nonplanar"` instead of being projected, and the Python importer
  records that typed reason. Legacy inventories without `sweep` are still read with the OCS angle
  rule.
- Primitive `sweep` is serialized at full double precision so an exact 90-degree arc is not
  rounded just above one quarter-turn and split twice.
- Licence: ACadSharp is MIT; keep `ACadSharp.dll` unmodified and retain this notice when redistributing.

# Abaqus 2024 integration

The host Python process writes an input deck and launches a configured local installation. Extraction runs under Abaqus Python and imports only its bundled libraries. Configure the running API and worker with the same launcher path.

~~~powershell
$env:SIMPLIFY_ABAQUS_LAUNCHER = 'C:\SIMULIA\Commands\abq2024.bat'
~~~

A submitted analysis uses a fresh run directory with fixed internal names. The worker invokes the equivalent of the following commands. The first consumes solver licenses.

~~~text
abq2024 job=analysis input=analysis.inp cpus=1 interactive
abq2024 python extract_odb.py
~~~

The pilot supports an XY plane-stress seal with bonded material regions and one open, horizontally spanning, vertically closing panel. The profile must be single-valued in X except for vertical facets. The writer orders the panel from right to left so a horizontal R2D2 facet has its SPOS normal toward the seal. The assembly offset precedes the signed step travel. Initial vertical clearance is calculated over overlapping piecewise-linear mesh facets. Contact, deformed clearance and reaction during loading require analysis.

The template writes first-order CPS3/CPS4R cells from Gmsh, linear elasticity or first-order hyperfoam with uniaxial nominal stress, axial strain and lateral strain data, and explicit section thickness in mm. General contact uses hard normal behavior and the assigned friction coefficient. The implicit dynamic step uses a ramp, nonlinear geometry and an unsymmetric solution. Geometry-specific contact corrections from confidential decks require separate validation. The synthetic example's material curves are fictional.

Results v1 stores topology once in `results.json`, one requested frame per `frame-NNNNN.json`, and signed panel U2/RF2 history in `history.csv`. Element labels, node connectivity and displacements are scoped by instance. Results retain CAD region IDs, Abaqus set names, units, section thickness, force normalization, and solver or demo provenance. Real frame field records include stored output position, local coordinates where present, and integration and section point identity. For a requested contact variable, suffixed field names identify the original contact output. Missing variables are listed per frame and across the run. The extractor aligns histories by piecewise-linear interpolation on their common time interval. The CSV includes the total reaction in N alongside the selected total or per-mm force. DEMO produces synthetic nodal U and a synthetic curve.

## Diagnostics

- A launcher path must be absolute, local, and explicitly configured. Windows batch paths containing shell expansion characters are rejected. The adapter also supports executable launchers.
- Queue and license messages are read from `solver.log`, `analysis.log` and the Abaqus/Standard status file. An Abaqus launcher can exit with code zero following a child Python exception. Inspect `extract.log` when the results index is missing. Solving requires an explicit successful status record, a nonempty ODB, an acceptable exit code and no recognized fatal diagnostic.
- Keep the ODB and original run artifacts after a failed extraction. Retry from the dashboard once the ODB version, disk space or launcher configuration is corrected.
- The app expects a time-domain ODB produced for its submitted setup. Arbitrary ODB upload, model remapping, viewer-equivalent stress contours and 3D analysis are outside this adapter.

## License-free verification

~~~powershell
$env:SIMPLIFY_ABAQUS_TEST_LAUNCHER = 'C:\SIMULIA\Commands\abq2024.bat'
.venv\Scripts\python -m pytest tests/test_abaqus.py -q
~~~

The installed Abaqus 2024 Python 3.10.5 parsed the generated synthetic deck with `inpParser`. The integration test also created a manufactured ODB with two instances, overlapping labels, nodal displacements, integration-point stress and independently sampled U2/RF2 histories. It ran the actual read-only extractor and verified the database checksum. No license-consuming analysis or data check was run. Numerical validation still requires an authorized solver run with independently checked force, deformation, contact onset and mesh convergence.

The public 2024 documentation endpoint was inaccessible during implementation. The publicly available vendor manuals below informed the adapter alongside tests with the installed 2024 runtime.

- The execution procedure supports direct input files, CPU selection and interactive runs. [Analysis execution](https://docs.software.vt.edu/abaqusv2025/English/SIMACAEEXCRefMap/simaexc-c-analysisproc.htm)
- Element ordering controls the contact normal for two-node rigid profiles. [Rigid elements](https://docs.software.vt.edu/abaqusv2026/English/SIMACAEELMRefMap/simaelm-c-rigid.htm)
- Hyperfoam accepts fitted uniaxial test data with a lateral strain column. [Uniaxial data](https://docs.software.vt.edu/abaqusv2026/English/SIMACAEKEYRefMap/simakey-r-uniaxialtestdata.htm)
- Output locations distinguish nodal and integration-point values, and variables can vary by frame. [Reading fields](https://docs.software.vt.edu/abaqusv2025/English/SIMACAECMDRefMap/simacmd-c-odbintroreadfieldpyc.htm)

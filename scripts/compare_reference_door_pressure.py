"""Compare the production door-pressure extraction with the independent reader.

The independent reader (``reference_door_pressure.py``) traverses a supplied ODB
directly. The production extractor (``reference_extract.py``) writes a normal
portable result using the shared extraction path. This host-side script runs
both at the four acceptance frames and reports every numeric difference.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CASES = ("GENKOU", "HK01", "HK02")
PROFILES = (
    "UPPER_LOWER_BPLR-1",
    "UPPER_LOWER_BPLRBARA-1",
    "UPPER_LOWER_HINGE-1",
    "UPPER_LOWER_HINGEBARA-1",
    "UPPER_ROOF-1",
    "UPPER_ROOFBARA-1",
)
FRAMES = (("Step-1", -1), ("Step-2", 0), ("Step-2", 50), ("Step-2", -1))
TOLERANCE = {"station_mm": 0.0001, "pressure_kpa": 0.001, "force_n": 0.0000001}


def reader(launcher, odb, step, frame):
    command = [
        str(launcher),
        "python",
        str(ROOT / "scripts" / "reference_door_pressure.py"),
        str(odb),
        "--step",
        step,
        "--frame",
        str(frame),
        "--samples",
    ]
    for profile in PROFILES:
        command += ["--instance", profile]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"reference reader failed for {odb} {step} {frame}:\n{done.stderr[-4000:]}")
    return json.loads(done.stdout)


def production_frame(extract, step, frame):
    index = json.loads((extract / "results.json").read_text(encoding="utf-8"))
    by_step = {}
    for position, entry in enumerate(index["frames"]):
        by_step.setdefault(entry.get("step"), []).append(position)
    try:
        position = by_step[step][frame]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"no production frame {step} {frame} in {extract}") from exc
    return index, json.loads((extract / index["frames"][position]["file"]).read_text(encoding="utf-8"))


def compare(index, frame, report):
    profiles = {entry["alias"]: entry for entry in index["door_pressure"]["profiles"]}
    frame_profiles = frame["door_pressure"]["profiles"]
    summary = {
        "nodes": 0,
        "positive": 0,
        "station_mm": 0.0,
        "pressure_kpa": 0.0,
        "force_n": 0.0,
        "station_node": None,
        "pressure_node": None,
        "force_node": None,
        "mirror_ok": True,
        "profiles": {},
    }
    for name, profile in report["profiles"].items():
        definition = profiles[name]
        data = frame_profiles[definition["id"]]
        if not data.get("supported"):
            raise RuntimeError(f"production profile {name} is unsupported")
        labels = definition["labels"]
        stations = definition["stations_mm"]
        samples = profile["samples"]
        if [row["node"] for row in samples] != labels:
            raise RuntimeError(f"{name} label order differs from the independent reader")
        profile_max = {"station_mm": 0.0, "pressure_kpa": 0.0, "force_n": 0.0}
        for position, row in enumerate(samples):
            summary["nodes"] += 1
            station_error = abs(float(stations[position]) - float(row["s_mm"]))
            if station_error > summary["station_mm"]:
                summary["station_mm"] = station_error
                summary["station_node"] = row["node"]
            if station_error > profile_max["station_mm"]:
                profile_max["station_mm"] = station_error
            measured = data["pressure_kpa"][position]
            expected = row["pressure_kPa"]
            if (measured is None) != (expected is None):
                raise RuntimeError(f"{name} pressure null mask differs at node {row['node']}")
            if measured is not None:
                error = abs(float(measured) - float(expected))
                if error > summary["pressure_kpa"]:
                    summary["pressure_kpa"] = error
                    summary["pressure_node"] = row["node"]
                if error > profile_max["pressure_kpa"]:
                    profile_max["pressure_kpa"] = error
                if float(measured) > 0:
                    summary["positive"] += 1
            vector = data["cnormf_n"][position]
            expected_vector = row["cnormf_N"]
            if (vector is None) != (expected_vector is None):
                raise RuntimeError(f"{name} force null mask differs at node {row['node']}")
            if vector is not None:
                if len(vector) != len(expected_vector):
                    raise RuntimeError(f"{name} force component count differs at node {row['node']}")
                for component, (one, other) in enumerate(zip(vector, expected_vector)):
                    error = abs(float(one) - float(other))
                    if error > summary["force_n"]:
                        summary["force_n"] = error
                        summary["force_node"] = [row["node"], component]
                    if error > profile_max["force_n"]:
                        profile_max["force_n"] = error
        summary["profiles"][name] = {
            "nodes": len(samples),
            "positive": profile["positive_pressure_nodes"],
            "peak_kpa": profile["peak"]["pressure_kPa"] if profile["peak"] else None,
            "peak_node": profile["peak"]["node"] if profile["peak"] else None,
            **profile_max,
        }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=Path(r"I:\GithubProjects\abaqussurfacePressure"))
    parser.add_argument("--extract-root", type=Path, default=ROOT / ".local" / "evidence" / "door-panel-pressure")
    parser.add_argument("--launcher", default=r"C:\SIMULIA\Commands\abq2024.bat")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = {"tolerance": TOLERANCE, "cases": {}}
    failures = []
    for case in CASES:
        odb = args.reference / f"20231129_{case}.odb"
        extract = args.extract_root / f"extract-{case}"
        if not extract.is_dir():
            raise SystemExit(f"missing production extraction: {extract}")
        case_result = {"odb": str(odb), "frames": {}}
        for step, frame in FRAMES:
            report = reader(args.launcher, odb, step, frame)
            index, payload = production_frame(extract, step, frame)
            summary = compare(index, payload, report)
            summary["native_frame"] = report["frame_id"]
            summary["time_s"] = report["time_s"]
            case_result["frames"][f"{step}:{frame}"] = summary
            for key, tolerance in TOLERANCE.items():
                if summary[key] > tolerance:
                    failures.append(
                        f"{case} {step} {frame}: {key} {summary[key]:.12g} > {tolerance}"
                    )
            print(
                f"{case:6} {step} frame {frame:4} native {report['frame_id']:4} "
                f"nodes {summary['nodes']:4} positive {summary['positive']:3} "
                f"dS {summary['station_mm']:.3e} mm  dP {summary['pressure_kpa']:.3e} kPa  "
                f"dF {summary['force_n']:.3e} N"
            )
        results["cases"][case] = case_result
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"report: {args.output}")
    if failures:
        print("FAILED:\n  " + "\n  ".join(failures))
        return 1
    print("result: production extraction matches the independent reader at every station")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Fast two-phase video scanning:
Phase 1: Quick exiftool scan for pitch (fast)
Phase 2: Slow ffmpeg scan for altitude (only on candidates)

Saves results incrementally to avoid losing progress.
"""

import json
import subprocess
import sys
import re
from pathlib import Path

# Filtering thresholds
PITCH_MIN = -95.0
PITCH_MAX = -85.0
ALTITUDE_MIN = 40.0
ALTITUDE_MAX = 140.0


def batch_exiftool(video_dir: Path, batch_size: int = 50) -> list[dict]:
    """Fast batch metadata extraction with exiftool."""
    videos = list(video_dir.glob("*.mp4")) + list(video_dir.glob("*.MP4"))
    all_metadata = []

    for i in range(0, len(videos), batch_size):
        batch = videos[i:i+batch_size]
        batch_paths = [str(v) for v in batch]

        try:
            result = subprocess.run(
                ["exiftool", "-json", "-CameraPitch", "-GPSLatitude",
                 "-GPSLongitude", "-CreateDate", "-Duration"] + batch_paths,
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                all_metadata.extend(data)
                print(f"  Batch {i//batch_size + 1}: {len(batch)} videos")
        except Exception as e:
            print(f"  Batch error: {e}")

    return all_metadata


def parse_pitch(pitch_str) -> float | None:
    """Parse camera pitch value to float."""
    if pitch_str is None:
        return None
    if isinstance(pitch_str, (int, float)):
        return float(pitch_str)
    try:
        return float(str(pitch_str).replace(" deg", "").strip())
    except ValueError:
        return None


def get_altitude(video_path: str) -> float | None:
    """Extract altitude from subtitle stream (slow)."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", video_path, "-t", "2", "-map", "0:2", "-f", "srt", "-"],
            capture_output=True,
            text=True,
            timeout=120
        )
        match = re.search(r'H\s+([\d.]+)m', result.stdout)
        if match:
            return float(match.group(1))
    except Exception:
        pass
    return None


def main(video_dir: str, output_file: str = "scan_results.json"):
    video_dir = Path(video_dir)
    output_path = Path(output_file)

    # Load existing results
    results = {"good": [], "bad": [], "candidates": [], "phase": 1}
    processed = set()

    if output_path.exists():
        with open(output_path) as f:
            results = json.load(f)
        for v in results.get("good", []) + results.get("bad", []):
            processed.add(v["file"])
        for v in results.get("candidates", []):
            processed.add(v["file"])
        print(f"Resuming: {len(processed)} already processed, phase {results.get('phase', 1)}")

    def save():
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)

    # Phase 1: Fast exiftool scan
    if results.get("phase", 1) == 1:
        print("\n=== Phase 1: Fast pitch scan (exiftool) ===")
        all_meta = batch_exiftool(video_dir)

        for meta in all_meta:
            filename = Path(meta.get("SourceFile", "")).name
            if filename in processed:
                continue

            pitch = parse_pitch(meta.get("CameraPitch"))
            has_gps = bool(meta.get("GPSLatitude"))

            if not has_gps:
                results["bad"].append({"file": filename, "reason": "no GPS"})
            elif pitch is None:
                results["bad"].append({"file": filename, "reason": "no pitch"})
            elif not (PITCH_MIN <= pitch <= PITCH_MAX):
                results["bad"].append({"file": filename, "reason": f"pitch={pitch:.1f}"})
            else:
                # Candidate for phase 2
                results["candidates"].append({
                    "file": filename,
                    "pitch": pitch,
                    "date": meta.get("CreateDate", "").split()[0].replace(":", "-") if meta.get("CreateDate") else None,
                    "lat": meta.get("GPSLatitude"),
                    "lon": meta.get("GPSLongitude"),
                    "duration": meta.get("Duration")
                })

            processed.add(filename)

        results["phase"] = 2
        save()
        print(f"\nPhase 1 complete:")
        print(f"  Candidates (nadir pitch): {len(results['candidates'])}")
        print(f"  Rejected: {len(results['bad'])}")

    # Phase 2: Slow altitude check on candidates
    if results.get("phase", 2) == 2 and results.get("candidates"):
        print(f"\n=== Phase 2: Altitude check ({len(results['candidates'])} candidates) ===")

        remaining = []
        for i, candidate in enumerate(results["candidates"], 1):
            filepath = video_dir / candidate["file"]
            print(f"[{i}/{len(results['candidates'])}] {candidate['file']}...", end=" ", flush=True)

            altitude = get_altitude(str(filepath))

            if altitude is None:
                print(f"REJECT (no altitude data)")
                results["bad"].append({"file": candidate["file"], "reason": "no altitude"})
            elif not (ALTITUDE_MIN <= altitude <= ALTITUDE_MAX):
                print(f"REJECT (alt={altitude:.1f}m)")
                results["bad"].append({"file": candidate["file"], "reason": f"alt={altitude:.1f}"})
            else:
                print(f"GOOD (alt={altitude:.1f}m)")
                candidate["altitude"] = altitude
                results["good"].append(candidate)

            # Save every 5
            if i % 5 == 0:
                results["candidates"] = results["candidates"][i:]
                save()

        results["candidates"] = []
        results["phase"] = 3
        save()

    # Summary
    print(f"\n{'='*50}")
    print(f"Final Results:")
    print(f"  Good (nadir + ~120m): {len(results['good'])}")
    print(f"  Bad: {len(results['bad'])}")

    if results["good"]:
        # Group by date
        by_date = {}
        for v in results["good"]:
            d = v.get("date", "unknown")
            by_date.setdefault(d, []).append(v)
        print(f"\nGood videos by date:")
        for date in sorted(by_date.keys()):
            print(f"  {date}: {len(by_date[date])} videos")

    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    video_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    output = sys.argv[2] if len(sys.argv) > 2 else "scan_results.json"
    main(video_dir, output)

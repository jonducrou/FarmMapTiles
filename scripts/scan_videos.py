#!/usr/bin/env python3
"""
Scan DJI drone videos and filter for nadir mapping flights.

Criteria:
- Camera Pitch ≈ -90° (nadir, pointing straight down)
- Altitude ≈ 120m

Output: JSON manifest grouped by date
"""

import json
import subprocess
import sys
import re
from pathlib import Path
from collections import defaultdict

# Filtering thresholds
PITCH_MIN = -95.0  # Allow some tolerance
PITCH_MAX = -85.0
ALTITUDE_MIN = 40.0
ALTITUDE_MAX = 140.0


SAMPLE_INTERVAL_SEC = 5.0  # Sample telemetry at this stride through the video


def parse_subtitle_telemetry(video_path: str, timeout: int = 120) -> list | None:
    """Parse the full DJI telemetry subtitle stream.

    DJI embeds per-frame telemetry in a subtitle stream with format:
    GPS (lon, lat, sats), D dist, H altitude, H.S horiz_speed, V.S vert_speed

    Returns a list of {time, lat, lon, alt, hspeed} samples, or None on failure.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", video_path, "-map", "0:s:0?", "-f", "srt", "-"],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if not result.stdout:
            return None
    except subprocess.TimeoutExpired:
        print("TIMEOUT", end=" ")
        return None
    except Exception:
        return None

    time_pattern = re.compile(r'(\d\d):(\d\d):(\d\d),(\d\d\d)\s*-->')
    telem_pattern = re.compile(
        r'GPS\s*\(([-\d.]+),\s*([-\d.]+),\s*\d+\).*?H\s+([-\d.]+)m.*?H\.S\s+([\d.]+)m/s'
    )

    samples = []
    current_time = 0.0
    for line in result.stdout.splitlines():
        tm = time_pattern.search(line)
        if tm:
            h, m, s, ms = map(int, tm.groups())
            current_time = h * 3600 + m * 60 + s + ms / 1000
            continue
        gm = telem_pattern.search(line)
        if gm:
            lon, lat, alt, hspeed = map(float, gm.groups())
            samples.append({
                "time": current_time,
                "lat": lat,
                "lon": lon,
                "alt": alt,
                "hspeed": hspeed,
            })
    return samples


def find_usable_sections(samples: list, interval: float = SAMPLE_INTERVAL_SEC) -> list:
    """Walk telemetry at ~interval stride and return contiguous usable sections.

    A sample is usable if its altitude is within the mapping altitude range.
    Returns a list of {start, end, avg_alt} dicts (times in seconds).
    """
    if not samples:
        return []

    picked = []
    next_t = 0.0
    for s in samples:
        if s["time"] >= next_t:
            picked.append(s)
            next_t = s["time"] + interval

    def usable(s):
        return ALTITUDE_MIN <= s["alt"] <= ALTITUDE_MAX

    sections = []
    start = None
    alts = []
    last_time = 0.0
    for s in picked:
        if usable(s):
            if start is None:
                start = s["time"]
                alts = []
            alts.append(s["alt"])
            last_time = s["time"]
        elif start is not None:
            sections.append({
                "start": round(start, 1),
                "end": round(last_time, 1),
                "avg_alt": round(sum(alts) / len(alts), 1),
            })
            start = None
    if start is not None:
        sections.append({
            "start": round(start, 1),
            "end": round(last_time, 1),
            "avg_alt": round(sum(alts) / len(alts), 1),
        })
    return sections


def get_video_metadata(video_path: str) -> dict | None:
    """Extract metadata from a video using exiftool."""
    try:
        result = subprocess.run(
            [
                "exiftool", "-json",
                "-CameraPitch",
                "-GPSLatitude",
                "-GPSLongitude",
                "-GPSAltitude",
                "-CreateDate",
                "-Duration",
                video_path
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        if data:
            return data[0]
        return None

    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        print(f"  Error processing {video_path}: {e}", file=sys.stderr)
        return None


def parse_pitch(pitch_str: str | float | None) -> float | None:
    """Parse camera pitch value to float."""
    if pitch_str is None:
        return None
    if isinstance(pitch_str, (int, float)):
        return float(pitch_str)
    # Handle string like "-90.00" or "-90.00 deg"
    try:
        return float(str(pitch_str).replace(" deg", "").strip())
    except ValueError:
        return None


def parse_altitude(alt_str: str | float | None) -> float | None:
    """Parse altitude value to float."""
    if alt_str is None:
        return None
    if isinstance(alt_str, (int, float)):
        return float(alt_str)
    # Handle string like "120.00 m" or "120.00"
    try:
        return float(str(alt_str).replace(" m", "").strip())
    except ValueError:
        return None


def parse_date(date_str: str | None) -> str | None:
    """Parse CreateDate to YYYY-MM-DD format."""
    if not date_str:
        return None
    # Format: "2023:02:18 14:30:00" -> "2023-02-18"
    try:
        date_part = date_str.split()[0]
        return date_part.replace(":", "-")
    except (IndexError, AttributeError):
        return None


def is_valid_mapping_video(metadata: dict, sections: list) -> tuple[bool, list[str]]:
    """Check if video meets mapping criteria.

    Valid if the camera is nadir AND at least one sampled section of the flight
    is within the mapping altitude range.

    Returns (is_valid, list of rejection reasons)
    """
    pitch = parse_pitch(metadata.get("CameraPitch"))
    lat = metadata.get("GPSLatitude")
    lon = metadata.get("GPSLongitude")

    reasons = []

    if not lat or not lon:
        reasons.append("no GPS")

    if pitch is None or not (PITCH_MIN <= pitch <= PITCH_MAX):
        reasons.append(f"pitch={pitch}")

    if not sections:
        reasons.append("no usable altitude section")

    return (len(reasons) == 0, reasons)


def scan_videos(video_dir: str, output_file: str = "manifest.json", save_every: int = 10):
    """Scan all videos in directory and create manifest with incremental saves."""
    video_dir = Path(video_dir)
    output_path = Path(output_file)

    if not video_dir.exists():
        print(f"Error: Directory not found: {video_dir}", file=sys.stderr)
        sys.exit(1)

    # Find all MP4 files
    videos = list(video_dir.glob("*.mp4")) + list(video_dir.glob("*.MP4"))
    print(f"Found {len(videos)} video files")

    # Load existing results to resume
    valid_videos = []
    rejected_videos = []
    processed_files = set()

    if output_path.exists():
        try:
            with open(output_path) as f:
                existing = json.load(f)
            # Extract already processed files
            for date_videos in existing.get('dates', {}).values():
                for v in date_videos:
                    valid_videos.append(v)
                    processed_files.add(v['file'])
            for v in existing.get('rejected', []):
                rejected_videos.append(v)
                processed_files.add(v['file'])
            print(f"Resuming: {len(processed_files)} already processed")
        except (json.JSONDecodeError, KeyError):
            pass

    def save_results():
        """Save current results to file."""
        by_date = defaultdict(list)
        for v in valid_videos:
            if v.get("date"):
                by_date[v["date"]].append(v)

        manifest = {
            "summary": {
                "total_scanned": len(valid_videos) + len(rejected_videos),
                "valid": len(valid_videos),
                "rejected": len(rejected_videos),
                "dates": len(by_date)
            },
            "dates": dict(sorted(by_date.items())),
            "rejected": rejected_videos
        }

        with open(output_path, "w") as f:
            json.dump(manifest, f, indent=2)

    for i, video in enumerate(sorted(videos), 1):
        # Skip already processed
        if video.name in processed_files:
            continue
        print(f"[{i}/{len(videos)}] Scanning {video.name}...", end=" ", flush=True)

        metadata = get_video_metadata(str(video))
        if not metadata:
            print("SKIP (no metadata)")
            rejected_videos.append({"file": video.name, "reason": "no metadata"})
            continue

        # Sample telemetry from the full subtitle stream
        telemetry = parse_subtitle_telemetry(str(video))
        sections = find_usable_sections(telemetry) if telemetry else []

        is_valid, reasons = is_valid_mapping_video(metadata, sections)

        if is_valid:
            date = parse_date(metadata.get("CreateDate"))
            pitch = parse_pitch(metadata.get("CameraPitch"))
            # Report overall stats across usable sections
            avg_alt = round(
                sum(s["avg_alt"] * (s["end"] - s["start"] + 1) for s in sections)
                / sum((s["end"] - s["start"] + 1) for s in sections),
                1,
            )
            usable_seconds = round(sum(s["end"] - s["start"] for s in sections), 1)

            valid_videos.append({
                "file": video.name,
                "date": date,
                "pitch": pitch,
                "altitude": avg_alt,
                "usable_sections": sections,
                "usable_seconds": usable_seconds,
                "lat": metadata.get("GPSLatitude"),
                "lon": metadata.get("GPSLongitude"),
                "duration": metadata.get("Duration")
            })
            print(f"VALID (date={date}, pitch={pitch:.1f}°, alt={avg_alt}m, "
                  f"{len(sections)} section(s), {usable_seconds}s usable)")
        else:
            rejected_videos.append({
                "file": video.name,
                "reason": ", ".join(reasons)
            })
            print(f"REJECT ({', '.join(reasons)})")

        # Save incrementally
        processed_count = len(valid_videos) + len(rejected_videos) - len(processed_files)
        if processed_count > 0 and processed_count % save_every == 0:
            save_results()
            print(f"  [Saved {len(valid_videos)} valid, {len(rejected_videos)} rejected]")

    # Final save
    save_results()

    # Group by date
    by_date = defaultdict(list)
    for v in valid_videos:
        if v["date"]:
            by_date[v["date"]].append(v)

    # Create manifest
    manifest = {
        "summary": {
            "total_scanned": len(videos),
            "valid": len(valid_videos),
            "rejected": len(rejected_videos),
            "dates": len(by_date)
        },
        "dates": dict(sorted(by_date.items())),
        "rejected": rejected_videos
    }

    # Write manifest
    output_path = Path(output_file)
    with open(output_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n{'='*50}")
    print(f"Summary:")
    print(f"  Total videos scanned: {len(videos)}")
    print(f"  Valid mapping videos: {len(valid_videos)}")
    print(f"  Rejected: {len(rejected_videos)}")
    print(f"  Unique dates: {len(by_date)}")
    print(f"\nManifest written to: {output_path}")

    if by_date:
        print(f"\nDates with valid videos:")
        for date in sorted(by_date.keys()):
            print(f"  {date}: {len(by_date[date])} videos")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Default: scan current directory
        video_dir = "."
    else:
        video_dir = sys.argv[1]

    output = sys.argv[2] if len(sys.argv) > 2 else "manifest.json"
    scan_videos(video_dir, output)

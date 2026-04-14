#!/usr/bin/env python3
"""
Extract frames from DJI drone videos with GPS geotags.

Reads embedded subtitle stream for per-frame GPS telemetry and selects
frames based on GPS distance travelled (not fixed time intervals).
This gives even spatial coverage regardless of drone speed.

Writes EXIF GPS data to extracted JPG frames for use with OpenDroneMap.
"""

import json
import math
import subprocess
import sys
import re
import os
from pathlib import Path
from datetime import datetime


def parse_subtitle_telemetry(srt_content: str) -> list[dict]:
    """Parse DJI subtitle telemetry into list of GPS points.

    Format: GPS (lon, lat, sats), D dist, H alt, H.S hspeed, V.S vspeed
    Example: GPS (151.9271, -28.6970, 19), D 683.75m, H 120.00m, H.S 0.00m/s, V.S 0.00m/s
    """
    telemetry = []

    # SRT format: index, timecode, content, blank line
    # Timecodes: 00:00:00,000 --> 00:00:00,033
    pattern = re.compile(
        r'(\d+)\n'
        r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n'
        r'(.*?)\n\n',
        re.DOTALL
    )

    gps_pattern = re.compile(
        r'GPS \(([\d.]+), ([-\d.]+), \d+\).*?H\s+([\d.]+)m.*?H\.S\s+([\d.]+)m/s'
    )

    for match in pattern.finditer(srt_content + '\n\n'):
        index = int(match.group(1))
        start_time = match.group(2)
        content = match.group(4)

        gps_match = gps_pattern.search(content)
        if gps_match:
            lon = float(gps_match.group(1))
            lat = float(gps_match.group(2))
            alt = float(gps_match.group(3))
            hspeed = float(gps_match.group(4))

            # Convert timecode to seconds
            h, m, rest = start_time.split(':')
            s, ms = rest.split(',')
            time_sec = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

            telemetry.append({
                'index': index,
                'time': time_sec,
                'lat': lat,
                'lon': lon,
                'alt': alt,
                'hspeed': hspeed
            })

    return telemetry


def get_video_telemetry(video_path: str) -> list[dict]:
    """Extract telemetry from video's subtitle stream."""
    result = subprocess.run(
        ["ffmpeg", "-i", video_path, "-map", "0:2", "-f", "srt", "-"],
        capture_output=True,
        text=True,
        timeout=120
    )
    return parse_subtitle_telemetry(result.stdout)


def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", video_path],
        capture_output=True,
        text=True
    )
    data = json.loads(result.stdout)
    return float(data['format']['duration'])


# Mapping flight filter thresholds
ALTITUDE_MIN = 40.0    # metres
ALTITUDE_MAX = 140.0
MIN_HSPEED = 1.0       # m/s — reject hovering/stationary frames


def filter_mapping_telemetry(telemetry: list[dict]) -> list[dict]:
    """Filter telemetry to only include usable mapping frames.

    Keeps entries where:
    - Altitude is within mapping range (40-140m)
    - Drone is moving (horizontal speed > 1 m/s)

    This means a single video can contain takeoff, hovering, and mapping
    segments — only the mapping segments will produce frames.
    """
    filtered = [
        e for e in telemetry
        if ALTITUDE_MIN <= e['alt'] <= ALTITUDE_MAX
        and e['hspeed'] >= MIN_HSPEED
    ]
    return filtered


def haversine_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two GPS coordinates."""
    R = 6371000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def frame_distance_for_altitude(altitude_m: float, overlap: float = 0.80) -> float:
    """Calculate frame spacing in metres for a given altitude and desired overlap.

    Uses DJI camera FOV (~84°) to compute ground footprint width, then
    spaces frames to achieve the target front overlap percentage.

    At 50m:  footprint ~90m, spacing ~18m (at 80% overlap)
    At 120m: footprint ~216m, spacing ~43m (at 80% overlap)
    """
    fov_half_rad = math.radians(42)  # half of 84° FOV
    footprint_width = 2 * altitude_m * math.tan(fov_half_rad)
    return footprint_width * (1 - overlap)


def select_frames_by_distance(telemetry: list[dict], overlap: float = 0.80) -> list[dict]:
    """Select telemetry points spaced by GPS distance, scaled by altitude.

    Frame spacing adapts to altitude — higher altitude means larger ground
    footprint, so frames can be spaced further apart while maintaining
    the same overlap percentage.

    Always includes the first point. Each subsequent point is selected
    when distance from the last selected point exceeds the altitude-derived
    spacing threshold.

    Args:
        telemetry: List of telemetry dicts with lat, lon, alt, time
        overlap: Target front overlap (0.0–1.0, default 0.80 = 80%)

    Returns:
        List of selected telemetry entries
    """
    if not telemetry:
        return []

    selected = [telemetry[0]]

    for entry in telemetry[1:]:
        last = selected[-1]
        dist = haversine_metres(last['lat'], last['lon'], entry['lat'], entry['lon'])
        threshold = frame_distance_for_altitude(entry['alt'], overlap)
        if dist >= threshold:
            selected.append(entry)

    return selected


def select_frames_by_time(telemetry: list[dict], interval_sec: float) -> list[dict]:
    """Select telemetry points at fixed time intervals (legacy mode)."""
    if not telemetry:
        return []

    duration = telemetry[-1]['time']
    selected = []
    t = 0
    while t <= duration:
        closest = min(telemetry, key=lambda e: abs(e['time'] - t))
        if abs(closest['time'] - t) <= 0.5:
            selected.append(closest)
        t += interval_sec

    return selected


def extract_frame_at_time(video_path: str, time_sec: float, output_path: str,
                          quality: int = 95) -> bool:
    """Extract a single frame at a specific time from the video."""
    q = int((100 - quality) / 5) + 1  # ffmpeg uses 1-31, lower is better
    result = subprocess.run([
        "ffmpeg", "-y",
        "-ss", f"{time_sec:.3f}",
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", str(q),
        output_path
    ], capture_output=True)
    return result.returncode == 0


def write_gps_exif(frame_path: str, lat: float, lon: float, alt: float):
    """Write GPS EXIF tags to a JPEG frame."""
    lat_ref = 'S' if lat < 0 else 'N'
    lon_ref = 'W' if lon < 0 else 'E'

    subprocess.run([
        "exiftool", "-overwrite_original",
        f"-GPSLatitude={abs(lat)}",
        f"-GPSLatitudeRef={lat_ref}",
        f"-GPSLongitude={abs(lon)}",
        f"-GPSLongitudeRef={lon_ref}",
        f"-GPSAltitude={alt}",
        "-GPSAltitudeRef=Above Sea Level",
        frame_path
    ], capture_output=True)


def extract_frames(
    video_path: str,
    output_dir: str,
    overlap: float = 0.80,
    quality: int = 95
) -> int:
    """Extract frames from video at altitude-adaptive GPS distance intervals.

    Frame spacing is calculated from altitude and camera FOV to maintain
    consistent overlap. Higher altitude = wider footprint = larger spacing.

    Args:
        video_path: Path to video file
        output_dir: Directory for output frames
        overlap: Target front overlap 0.0-1.0 (default 0.80 = 80%)
        quality: JPEG quality (1-100)

    Returns:
        Number of frames extracted
    """
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Extracting telemetry from {video_path.name}...")
    telemetry = get_video_telemetry(str(video_path))
    print(f"  Found {len(telemetry)} telemetry entries")

    if not telemetry:
        print("  ERROR: No telemetry found")
        return 0

    # Filter to only usable mapping segments
    mapping_telemetry = filter_mapping_telemetry(telemetry)
    rejected = len(telemetry) - len(mapping_telemetry)
    if rejected > 0:
        print(f"  Filtered to {len(mapping_telemetry)} mapping entries ({rejected} rejected: wrong altitude or hovering)")

    if not mapping_telemetry:
        print("  ERROR: No usable mapping telemetry (check altitude and movement)")
        return 0

    # Select frames by altitude-adaptive distance
    selected = select_frames_by_distance(mapping_telemetry, overlap)
    avg_alt = sum(e['alt'] for e in selected) / len(selected) if selected else 0
    avg_spacing = frame_distance_for_altitude(avg_alt, overlap)
    print(f"  Selected {len(selected)} frames ({overlap*100:.0f}% overlap, ~{avg_spacing:.0f}m spacing at avg {avg_alt:.0f}m alt)")

    if not selected:
        print("  ERROR: No frames selected")
        return 0

    # Compute total distance covered (mapping segments only)
    total_dist = 0
    for i in range(1, len(mapping_telemetry)):
        total_dist += haversine_metres(
            mapping_telemetry[i - 1]['lat'], mapping_telemetry[i - 1]['lon'],
            mapping_telemetry[i]['lat'], mapping_telemetry[i]['lon']
        )
    print(f"  Total flight distance: {total_dist:.0f}m")

    # Extract each selected frame
    base_name = video_path.stem
    frames_extracted = 0

    for i, tel in enumerate(selected, 1):
        frame_path = output_dir / f"{base_name}_{i:04d}.jpg"

        if extract_frame_at_time(str(video_path), tel['time'], str(frame_path), quality):
            write_gps_exif(str(frame_path), tel['lat'], tel['lon'], tel['alt'])
            frames_extracted += 1

            if frames_extracted % 50 == 0:
                print(f"  Extracted {frames_extracted}/{len(selected)} frames...")
        else:
            print(f"  WARNING: Failed to extract frame at {tel['time']:.1f}s")

    print(f"  Extracted {frames_extracted} geotagged frames")
    return frames_extracted


def process_manifest(manifest_path: str, output_base: str, overlap: float = 0.80):
    """Process all videos from a manifest file."""
    with open(manifest_path) as f:
        manifest = json.load(f)

    output_base = Path(output_base)

    for date, videos in manifest.get('dates', {}).items():
        print(f"\n{'='*50}")
        print(f"Processing date: {date}")
        print(f"  Videos: {len(videos)}")

        date_dir = output_base / date
        date_dir.mkdir(parents=True, exist_ok=True)

        total_frames = 0
        for video_info in videos:
            video_path = Path(video_info['file'])
            if not video_path.exists():
                print(f"  WARNING: Video not found: {video_path}")
                continue

            frames = extract_frames(str(video_path), str(date_dir), overlap)
            total_frames += frames

        print(f"\n  Total frames for {date}: {total_frames}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  extract_frames.py <video.mp4> [output_dir] [overlap]")
        print("  extract_frames.py --manifest <manifest.json> [output_dir] [overlap]")
        print("")
        print("  overlap: Target front overlap 0.0-1.0 (default: 0.80 = 80%)")
        print("           Frame spacing adapts to altitude automatically:")
        print("           At 50m:  ~18m spacing (80% overlap)")
        print("           At 120m: ~43m spacing (80% overlap)")
        sys.exit(1)

    if sys.argv[1] == "--manifest":
        if len(sys.argv) < 3:
            print("Error: manifest file required")
            sys.exit(1)
        manifest_path = sys.argv[2]
        output_dir = sys.argv[3] if len(sys.argv) > 3 else "frames"
        overlap = float(sys.argv[4]) if len(sys.argv) > 4 else 0.80
        process_manifest(manifest_path, output_dir, overlap)
    else:
        video_path = sys.argv[1]
        output_dir = sys.argv[2] if len(sys.argv) > 2 else "frames"
        overlap = float(sys.argv[3]) if len(sys.argv) > 3 else 0.80
        extract_frames(video_path, output_dir, overlap)

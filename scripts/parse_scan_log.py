#!/usr/bin/env python3
"""
Parse scan log output into good/bad lists.
Use this if the main scan was interrupted.
"""

import re
import json
import sys

def parse_log(log_path: str, output_path: str = "scan_results.json"):
    """Parse scan log and extract good/bad lists."""

    good = []
    bad = []

    with open(log_path) as f:
        for line in f:
            # Match: [N/M] Scanning filename... VALID/REJECT (reason)
            match = re.match(
                r'\[(\d+)/(\d+)\] Scanning (.+?)\.\.\. (VALID|REJECT|SKIP)(.*)',
                line.strip()
            )
            if match:
                num, total, filename, status, details = match.groups()

                if status == 'VALID':
                    # Parse: (date=2023-02-18, pitch=-90.0°, alt=120.0m)
                    detail_match = re.search(
                        r'date=([^,]+), pitch=([^°]+)°, alt=([^m]+)m',
                        details
                    )
                    if detail_match:
                        good.append({
                            'file': filename,
                            'date': detail_match.group(1),
                            'pitch': float(detail_match.group(2)),
                            'altitude': float(detail_match.group(3))
                        })
                else:
                    # Parse rejection reason
                    reason = details.strip(' ()')
                    bad.append({
                        'file': filename,
                        'reason': reason if reason else status
                    })

    results = {
        'summary': {
            'good': len(good),
            'bad': len(bad),
            'total': len(good) + len(bad)
        },
        'good': good,
        'bad': bad
    }

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Parsed {len(good) + len(bad)} videos")
    print(f"  Good: {len(good)}")
    print(f"  Bad: {len(bad)}")
    print(f"Results saved to: {output_path}")

    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: parse_scan_log.py <log_file> [output.json]")
        sys.exit(1)

    log_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "scan_results.json"
    parse_log(log_path, output_path)

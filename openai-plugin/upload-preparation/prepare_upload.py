"""Prepare two Rumbo upload fields from the authorized UTF-8 bytes on stdin."""
import argparse
import hashlib
import json
import re
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reviewed-sha256', help='Digest recorded when these source bytes were reviewed.')
    args = parser.parse_args()
    if args.reviewed_sha256 is not None and not re.fullmatch('[0-9a-f]{64}', args.reviewed_sha256):
        parser.error('use the 64 lowercase hexadecimal digits of the recorded source digest')
    try:
        source = sys.stdin.buffer.read(128 * 1024 + 1)
    except OSError as error:
        parser.exit(1, 'Could not read the authorized input: ' + str(error) + '\n')
    if len(source) > 128 * 1024:
        parser.exit(2, 'Text exceeds the 128 KiB Rumbo upload limit.\n')
    try:
        content = source.decode('utf-8')
    except UnicodeDecodeError:
        parser.exit(2, 'Source is not valid UTF-8 text.\n')
    digest = hashlib.sha256(source).hexdigest()
    if args.reviewed_sha256 is not None and digest != args.reviewed_sha256:
        parser.exit(3, 'Source changed since review. Inspect the current file before preparing a replacement.\n')
    print(json.dumps({'content': content, 'expected_sha256': digest}))


if __name__ == '__main__':
    main()

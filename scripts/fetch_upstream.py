#!/usr/bin/env python3
"""Download the pinned third-party assets FlyHead needs and verify their identity.

  python scripts/fetch_upstream.py                  # fly-brain model code + FlyWire v783 data (~105 MB)
  python scripts/fetch_upstream.py --annotations    # also the FlyWire annotation TSV (~32 MB, for tools/build_registry.py)

Model: eonsystemspbc/fly-brain at a fixed commit (GPL-2.0, not vendored here); files go to
FLYHEAD_UPSTREAM_DIR (default third_party/fly-brain). Every file is checked against its Git blob
SHA-1 and size from configs/fly/upstream_manifest.json; existing files are verified, not overwritten.
"""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from flyhead import paths  # noqa: E402

ANNOTATIONS = dict(
    repository='flyconnectome/flywire_annotations', commit='8587524c1748ce5ef2080822a2fc890fc03bf597',
    files=[dict(path='supplemental_files/Supplemental_file1_neuron_annotations.tsv', bytes=31718505,
                git_blob_sha1='afea3e15a5671f5da0b9f7dd2e932d328c3b57a0',
                sha256='9a4f8b2f843196074431ebd7cd883536afa1be86c8a4ce90970441e8be81d1be')])


def identity(path):
    data = path.read_bytes()
    blob = hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()
    return len(data), blob, hashlib.sha256(data).hexdigest()


def fetch(repository, commit, item, target):
    if target.exists():
        size, blob, sha = identity(target)
        if size != item['bytes'] or blob != item['git_blob_sha1']:
            raise SystemExit('IDENTITY MISMATCH (existing file): %s' % target)
        print('ok      %s' % target)
        return sha
    url = item.get('url') or 'https://raw.githubusercontent.com/%s/%s/%s' % (repository, commit, item['path'])
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + '.part')
    request = urllib.request.Request(url, headers={'User-Agent': 'flyhead-fetch/1'})
    with urllib.request.urlopen(request, timeout=60) as response, part.open('wb') as out:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    size, blob, sha = identity(part)
    if size != item['bytes'] or blob != item['git_blob_sha1']:
        part.unlink()
        raise SystemExit('IDENTITY MISMATCH (download): %s' % item['path'])
    part.replace(target)
    print('fetched %s (%d bytes, sha256 %s)' % (target, size, sha))
    return sha


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--annotations', action='store_true', help='also fetch the FlyWire annotation TSV')
    a = ap.parse_args()
    manifest = json.loads((paths.CONFIGS / 'fly' / 'upstream_manifest.json').read_text())
    out = paths.upstream_dir()
    for item in manifest['files']:
        fetch(manifest['repository'], manifest['commit'], item, out / item['path'])
    if a.annotations:
        for item in ANNOTATIONS['files']:
            sha = fetch(ANNOTATIONS['repository'], ANNOTATIONS['commit'], item,
                        REPO / 'third_party' / 'flywire_annotations' / Path(item['path']).name)
            if sha != item['sha256']:
                raise SystemExit('SHA256 MISMATCH: %s' % item['path'])
    print('upstream ready in %s (set FLYHEAD_UPSTREAM_DIR to use another location)' % out)


if __name__ == '__main__':
    main()

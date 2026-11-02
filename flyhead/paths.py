"""Filesystem locations, resolved from environment variables with repository defaults.

Nothing in the package hardcodes a host path; every location used at runtime comes from here.

FLYHEAD_UPSTREAM_DIR  pinned eonsystemspbc/fly-brain checkout with code/ and data/
                      (scripts/fetch_upstream.py fills it; default: <repo>/third_party/fly-brain)
FLYHEAD_CACHE_DIR     weight cache of the upstream loader (default: <repo>/cache)
FLYHEAD_RUNS_DIR      run outputs (default: <repo>/runs)
FLYHEAD_MAPS_DIR      map packages (default: <repo>/maps)
FLYHEAD_REGISTRY      neuron registry JSON (default: configs/fly/loom_registry.json)
"""
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIGS = REPO / 'configs'


def _dir(var, default):
    return Path(os.environ.get(var) or default).expanduser()


def upstream_dir():
    return _dir('FLYHEAD_UPSTREAM_DIR', REPO / 'third_party' / 'fly-brain')


def cache_dir():
    return _dir('FLYHEAD_CACHE_DIR', REPO / 'cache')


def runs_dir():
    return _dir('FLYHEAD_RUNS_DIR', REPO / 'runs')


def maps_dir():
    return _dir('FLYHEAD_MAPS_DIR', REPO / 'maps')


def registry_path():
    return _dir('FLYHEAD_REGISTRY', CONFIGS / 'fly' / 'loom_registry.json')


def load_registry(path=None):
    return json.loads(Path(path or registry_path()).read_text())


def keepin_exclude_path():
    return CONFIGS / 'fly' / 'keepin_exclude.json'

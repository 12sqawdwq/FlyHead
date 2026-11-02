"""Bounded full-graph probe. Synthetic visual input and shadow readout only."""
from pathlib import Path
import contextlib
import hashlib
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = Path('<SERVER_ROOT>/inference_service/deployments/flywire_lif_001')
GIB = 1024 ** 3
sys.path.insert(0, str(ROOT))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def mem_guard():
    available = next(int(x.split()[1]) * 1024 for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))
    rss = next(int(x.split()[1]) * 1024 for x in Path('/proc/self/status').read_text().splitlines() if x.startswith('VmRSS:'))
    if available < 12 * GIB or rss > 12 * GIB:
        raise RuntimeError('MEMORY_GUARD')
    return available, rss


lock = json.loads((ROOT / 'protocol_lock.json').read_text())
for row in lock['local_files']:
    assert sha(ROOT / row['path']) == row['sha256'], row['path']
for row in lock['external_files']:
    assert sha(row['path']) == row['sha256'], row['path']
for key in ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS']:
    os.environ[key] = '4'
import pyarrow  # upstream compatibility requirement: before torch
import numpy as np
import pandas as pd
import scipy.sparse as sparse
from scipy.sparse.csgraph import shortest_path
import torch
from fly_mapping.vision import VisualEncoder
from fly_mapping.commands import IntentDecoder

registry = json.loads((ROOT / 'config/neuron_registry.json').read_text())
profile = json.loads((ROOT / 'config/mapping_profile.json').read_text())
run = ROOT / 'runs/probe_001'
if run.exists():
    raise RuntimeError('NO_AUTOMATIC_RERUN')
run.mkdir(parents=True)
report = {'status': 'RUNNING', 'evidence': 'SYNTHETIC_VISUAL_FULL_GRAPH_PROBE',
          'protocol_sha256': sha(ROOT / 'protocol_lock.json'), 'motion_published': False,
          'model_graph_cropped': False, 'conditions': {}}
(run / 'status.json').write_text(json.dumps(report, indent=2) + '\n')
try:
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA_UNAVAILABLE_NO_CPU_SUBSTITUTION')
    free, total = torch.cuda.mem_get_info(0)
    available, rss = mem_guard()
    if free < 16 * GIB or available < 24 * GIB:
        raise RuntimeError('STARTUP_RESOURCE_GATE')
    torch.cuda.set_per_process_memory_fraction(12 * GIB / total, 0)
    torch.cuda.reset_peak_memory_stats(0)
    report['gpu'] = {'name': torch.cuda.get_device_name(0), 'capability': list(torch.cuda.get_device_capability(0)),
                     'torch': torch.__version__, 'cuda': torch.version.cuda, 'arch_list': torch.cuda.get_arch_list()}
    sys.path.insert(0, str(BASE / 'upstream/code'))
    import run_pytorch as backend
    id_to_i, i_to_id = backend.get_hash_tables(str(BASE / 'upstream/data/2025_Completeness_783.csv'))
    n = len(id_to_i)
    if n != registry['model_neurons']:
        raise RuntimeError('REGISTRY_MODEL_SIZE_MISMATCH')
    for cell in registry['cells'].values():
        assert id_to_i[int(cell['root_id'])] == cell['model_index']
    inputs = [registry['cells'][key]['model_index'] for key in registry['visual_input_keys']]
    outputs = [registry['cells'][key]['model_index'] for key in registry['readout_keys']]
    cache = ROOT / 'cache/weights_001'
    cache.mkdir(parents=True)
    if list(cache.iterdir()):
        raise RuntimeError('PREEXISTING_PICKLE_CACHE_REFUSED')
    started = time.perf_counter()
    with contextlib.redirect_stdout(sys.stderr):
        weights_cpu = backend.get_weights(str(BASE / 'upstream/data/2025_Connectivity_783.parquet'),
                                          str(BASE / 'upstream/data/2025_Completeness_783.csv'), str(cache), csr=True)
    if tuple(weights_cpu.shape) != (n, n) or not torch.isfinite(weights_cpu.values()).all():
        raise RuntimeError('INVALID_COMPLETE_GRAPH')
    report['model'] = {'neurons': n, 'sparse_entries': weights_cpu._nnz(), 'dt_ms': backend.DT,
                       'parameters': backend.MODEL_PARAMS, 'dtype': str(weights_cpu.dtype)}
    graph = sparse.csr_matrix(((weights_cpu.values().numpy() != 0).astype(np.uint8),
                              weights_cpu.col_indices().numpy(), weights_cpu.crow_indices().numpy()), shape=(n, n))
    graph.eliminate_zeros()
    # Weight rows are postsynaptic. Transpose for presynaptic -> postsynaptic paths.
    graph = graph.transpose().tocsr()
    distances = shortest_path(graph, directed=True, unweighted=True, indices=inputs)
    report['structural_paths'] = {
        input_key: {output_key: int(distances[a, outputs[b]]) if np.isfinite(distances[a, outputs[b]]) else None
                    for b, output_key in enumerate(registry['readout_keys'])}
        for a, input_key in enumerate(registry['visual_input_keys'])}
    report['structural_path_caveat'] = 'Signed graph reachability only, not neural response or steering direction.'
    del graph, distances
    weights = weights_cpu.to('cuda:0')
    del weights_cpu
    model = backend.TorchModel(1, n, backend.DT, backend.MODEL_PARAMS, weights,
                              exc_indices=inputs, device='cuda:0').eval()
    torch.cuda.synchronize()
    report['setup_and_structure_seconds'] = time.perf_counter() - started
    image = np.random.default_rng(71).integers(0, 256, (120, 160), dtype=np.uint8)
    model_identity = report['protocol_sha256']
    scenarios = [('ZERO', None), ('TONIC', 0), ('LEFT_IMAGE_MOTION', -4), ('RIGHT_IMAGE_MOTION', 4)]
    for name, shift in scenarios:
        mem_guard()
        if shift is None:
            drive = {'rates_hz': {registry['cells'][key]['root_id']: 0.0 for key in registry['visual_input_keys']},
                     'valid': True, 'features': {}, 'reason': 'zero_input_control'}
        else:
            encoder = VisualEncoder(registry, profile, name, 'OFFLINE_FIXTURE_CLOCK')
            encoder.consume(image, session_id=name, sequence=1, source_ns=1_000_000_000,
                            now_ns=1_000_000_000, clock_id='OFFLINE_FIXTURE_CLOCK')
            drive = encoder.consume(np.roll(image, shift, axis=1), session_id=name, sequence=2,
                                    source_ns=1_100_000_000, now_ns=1_100_000_000,
                                    clock_id='OFFLINE_FIXTURE_CLOCK')
            if not drive['valid']:
                raise RuntimeError('SYNTHETIC_ENCODER_NOT_READY:' + name)
        rates = torch.zeros(1, n, dtype=torch.float32, device='cuda:0')
        for neuron_id, rate in drive['rates_hz'].items():
            if neuron_id not in {registry['cells'][key]['root_id'] for key in registry['visual_input_keys']}:
                raise RuntimeError('UNDECLARED_STIMULATION_TARGET')
            rates[0, id_to_i[int(neuron_id)]] = rate
        state = model.state_init()
        counts = torch.zeros(n, dtype=torch.int32, device='cuda:0')
        generator = torch.Generator(device='cuda:0').manual_seed(20260922)
        torch.cuda.synchronize()
        start = time.perf_counter()
        with torch.no_grad():
            for step in range(1000):
                state = model(rates, *state, generator=generator)
                counts.add_(state[2][0].to(torch.int32))
                if (step + 1) % 100 == 0:
                    mem_guard()
                    if not all(torch.isfinite(tensor).all().item() for tensor in state):
                        raise RuntimeError('NONFINITE_STATE')
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - start
        all_counts = counts.cpu().numpy()
        np.save(run / (name + '_counts.npy'), all_counts, allow_pickle=False)
        readout = {registry['cells'][key]['root_id']: int(all_counts[registry['cells'][key]['model_index']])
                   for key in registry['readout_keys']}
        decoder = IntentDecoder(registry, profile, session_id=name,
                                clock_id='OFFLINE_FIXTURE_CLOCK', model_identity=model_identity)
        offline_intent = decoder.decode(readout, window_s=0.1, session_id=name, sequence=2,
                                        source_ns=1_100_000_000, now_ns=1_100_000_000,
                                        clock_id='OFFLINE_FIXTURE_CLOCK', model_identity=model_identity,
                                        brain_healthy=True, input_valid=True)
        condition = {'drive': drive, 'neural_counts_by_id': readout, 'total_spikes': int(all_counts.sum()),
                     'active_neurons': int(np.count_nonzero(all_counts)), 'input_spikes': int(all_counts[inputs].sum()),
                     'wall_seconds': elapsed, 'simulated_seconds': 0.1,
                     'model_only_realtime_ratio': 0.1 / elapsed, 'model_only_exceeds_100ms': elapsed > 0.1,
                     'offline_shadow_intent': offline_intent,
                     'source_clock_or_hardware_admission_tested': False,
                     'counts_file': name + '_counts.npy', 'counts_sha256': sha(run / (name + '_counts.npy'))}
        report['conditions'][name] = condition
        (run / 'status.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'condition': name, 'spikes': condition['total_spikes'],
                          'readout_spikes': sum(readout.values()), 'wall_seconds': elapsed}), flush=True)
    report['peak_cuda_allocated_bytes'] = torch.cuda.max_memory_allocated(0)
    report['peak_cuda_reserved_bytes'] = torch.cuda.max_memory_reserved(0)
    report['resources_end'] = dict(zip(['host_available_bytes', 'rss_bytes'], mem_guard()))
    assert report['conditions']['ZERO']['total_spikes'] == 0
    report['status'] = 'PASS_TECHNICAL_PROBE'
    report['behavior_validated'] = False
    report['visual_readout_nonzero'] = any(sum(c['neural_counts_by_id'].values()) > 0 for name,c in report['conditions'].items() if name in ['LEFT_IMAGE_MOTION','RIGHT_IMAGE_MOTION'])
    (run / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
    (run / 'status.json').write_text(json.dumps(report, indent=2) + '\n')
except Exception as exc:
    report.update(status='FAIL', error=repr(exc))
    (run / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
    (run / 'status.json').write_text(json.dumps(report, indent=2) + '\n')
    raise

"""Resident full-connectome brain on a CUDA GPU: rates in, readout spike counts out.

Uses the pinned upstream model (eonsystemspbc/fly-brain code/run_pytorch.py, fetched by
scripts/fetch_upstream.py, never modified) with the event-propagation + CUDA Graph engines.
One window = WINDOW_BLOCKS x 10 ms; neural state persists between windows.
"""
import contextlib
import sys
import time
from pathlib import Path

import numpy as np
import torch

from flyhead import paths

N_NEURONS = 138639
N_SYNAPSE_RECORDS = 15091983


def load_backend(upstream=None):
    """Import the upstream run_pytorch module from the pinned checkout."""
    code = (Path(upstream) if upstream else paths.upstream_dir()) / 'code'
    if not (code / 'run_pytorch.py').exists():
        raise FileNotFoundError('upstream model not found in %s (run scripts/fetch_upstream.py)' % code)
    if str(code) not in sys.path:
        sys.path.insert(0, str(code))
    import run_pytorch
    return run_pytorch


class Brain:
    def __init__(self, registry, input_indices, cache_dir=None, seed=20261010, window_blocks=10, upstream=None):
        from .engines import GraphEngine
        from .event_model import EventModel
        backend = load_backend(upstream)
        data = (Path(upstream) if upstream else paths.upstream_dir()) / 'data'
        cache_dir = cache_dir or paths.cache_dir()
        self.window_blocks = window_blocks
        self.window_s = window_blocks * 0.010
        with contextlib.redirect_stdout(sys.stderr):
            cpu = backend.get_weights(str(data / '2025_Connectivity_783.parquet'),
                                      str(data / '2025_Completeness_783.csv'), str(cache_dir), csr=True)
        assert cpu._nnz() == N_SYNAPSE_RECORDS and tuple(cpu.shape) == (N_NEURONS, N_NEURONS)
        original = backend.TorchModel(1, N_NEURONS, backend.DT, backend.MODEL_PARAMS, cpu,
                                      exc_indices=input_indices, device='cuda').eval()
        outgoing = cpu.transpose(0, 1).to_sparse_csr()
        self.engine = GraphEngine(EventModel(original, outgoing).eval(), N_NEURONS)
        del outgoing, cpu
        torch.cuda.empty_cache()
        self.inputs = torch.tensor(input_indices, device='cuda')
        self.readout_keys = [(t, c['anatomical_side'], c['root_id'], c['model_index'])
                             for t, cells in registry['readouts'].items() for c in cells]
        self.readout_index = torch.tensor([k[3] for k in self.readout_keys], device='cuda')
        self.zero = torch.zeros(N_NEURONS, dtype=torch.float32, device='cuda')
        self.engine.reset(self.zero, seed)
        self.prev_total = None
        self.prev_readout = np.zeros(len(self.readout_keys), dtype=np.int64)
        self.windows = 0

    @torch.no_grad()
    def step(self, rates):
        """rates: per-input-cell Hz (registry order). Returns (readout counts, all-brain spikes, ms)."""
        t0 = time.perf_counter()
        self.engine.rates[0, self.inputs] = torch.as_tensor(rates, device='cuda')
        for _ in range(self.window_blocks):
            self.engine.block()
        torch.cuda.synchronize()
        if not self.engine.healthy():
            raise RuntimeError('NONFINITE_STATE')
        counts = self.engine.counts
        read = counts[self.readout_index].cpu().numpy().astype(np.int64)
        total = int(counts.sum().item())
        delta = read - self.prev_readout
        all_spikes = total - (self.prev_total or 0)
        self.prev_readout, self.prev_total = read, total
        self.windows += 1
        return delta, all_spikes, (time.perf_counter() - t0) * 1000.0

    def readouts_by_type(self, delta):
        """{(type, side): summed spikes in the window}."""
        out = {}
        for (t, side, _, _), n in zip(self.readout_keys, delta):
            out[(t, side)] = out.get((t, side), 0) + int(n)
        return out

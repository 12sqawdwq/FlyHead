"""Resident full-connectome brain on the 5090D GPU: rates in, readout spike counts out.

Reuses, read-only, the flywire_lif_001 upstream model (run_pytorch) and the video_004 engines
(EventModel + CUDA Graph). One window = WINDOW_BLOCKS x 10 ms; neural state persists.
"""
import contextlib
import sys
import time
from pathlib import Path

BASE = Path('<SERVER_ROOT>/inference_service/deployments/flywire_lif_001')
VENDOR = Path('<SERVER_ROOT>/inference_service/mappings/video_004/vendor')
sys.path[:0] = [str(VENDOR), str(BASE / 'upstream/code')]

import numpy as np  # noqa: E402
import torch  # noqa: E402


class Brain:
    def __init__(self, registry, input_indices, cache_dir, seed=20261010, window_blocks=10):
        import run_pytorch as backend
        from engines import GraphEngine
        from event_model import EventModel
        self.window_blocks = window_blocks
        self.window_s = window_blocks * 0.010
        with contextlib.redirect_stdout(sys.stderr):
            cpu = backend.get_weights(str(BASE / 'upstream/data/2025_Connectivity_783.parquet'),
                                      str(BASE / 'upstream/data/2025_Completeness_783.csv'), str(cache_dir), csr=True)
        assert cpu._nnz() == 15091983 and tuple(cpu.shape) == (138639, 138639)
        original = backend.TorchModel(1, 138639, backend.DT, backend.MODEL_PARAMS, cpu,
                                      exc_indices=input_indices, device='cuda').eval()
        outgoing = cpu.transpose(0, 1).to_sparse_csr()
        self.engine = GraphEngine(EventModel(original, outgoing).eval(), 138639)
        del outgoing, cpu
        torch.cuda.empty_cache()
        self.inputs = torch.tensor(input_indices, device='cuda')
        self.readout_keys = [(t, c['anatomical_side'], c['root_id'], c['model_index'])
                             for t, cells in registry['readouts'].items() for c in cells]
        self.readout_index = torch.tensor([k[3] for k in self.readout_keys], device='cuda')
        self.zero = torch.zeros(138639, dtype=torch.float32, device='cuda')
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

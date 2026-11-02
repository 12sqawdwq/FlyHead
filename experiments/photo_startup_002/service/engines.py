"""Same upstream equations, optional 100-step CUDA Graph execution."""
import torch


class EagerEngine:
    def __init__(self, model, n):
        self.model = model
        self.rates = torch.zeros((1, n), dtype=torch.float32, device='cuda')
        self.state = list(model.state_init())
        self.counts = torch.zeros(n, dtype=torch.int32, device='cuda')

    def reset(self, rates, seed):
        self.rates.copy_(rates.reshape(1, -1))
        for target, initial in zip(self.state, self.model.state_init()):
            target.copy_(initial)
        self.counts.zero_()
        torch.cuda.manual_seed(seed)
        torch.cuda.synchronize()

    def block(self):
        state = self.state
        for _ in range(100):
            state = self.model(self.rates, *state)
            self.counts.add_(state[2][0].to(torch.int32))
        # Stable buffer addresses permit replay across persistent-state blocks.
        for target, output in zip(self.state, state):
            target.copy_(output)

    def healthy(self):
        return all(torch.isfinite(x).all().item() for x in self.state)


class GraphEngine(EagerEngine):
    def __init__(self, model, n):
        super().__init__(model, n)
        stream = torch.cuda.Stream()
        stream.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(stream):
            # Warm the exact workload, outside capture and outside timing.
            super().block()
        torch.cuda.current_stream().wait_stream(stream)
        torch.cuda.synchronize()
        self.reset(torch.zeros_like(self.rates), 20260923)
        self.graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(self.graph):
            super().block()
        torch.cuda.synchronize()

    def block(self):
        self.graph.replay()

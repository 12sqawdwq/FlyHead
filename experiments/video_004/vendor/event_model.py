"""Exact integer-weight event propagation on the COMPLETE connectome."""
import torch
import triton
import triton.language as tl


@triton.jit
def compact_spikes(spikes, active, count, N:tl.constexpr, BLOCK:tl.constexpr):
    idx=tl.program_id(0)*BLOCK+tl.arange(0,BLOCK)
    flag=(tl.load(spikes+idx,idx<N,other=0)>0).to(tl.int32)
    total=tl.sum(flag,0)
    if total>0:
        base=tl.atomic_add(count,total,sem='relaxed')
        rank=tl.cumsum(flag,0)-1
        tl.store(active+base+rank,idx,(idx<N)&(flag>0))


@triton.jit
def propagate(active,count,ptr,target,weight,acc,BLOCK:tl.constexpr):
    number=tl.load(count)
    # A fixed launch grid dynamically covers ALL active sources, without a cap.
    for slot in range(tl.program_id(0),number,tl.num_programs(0)):
        source=tl.load(active+slot)
        first=tl.load(ptr+source);last=tl.load(ptr+source+1)
        for base in range(first,last,BLOCK):
            edge=base+tl.arange(0,BLOCK)
            dst=tl.load(target+edge,edge<last,other=0)
            w=tl.load(weight+edge,edge<last,other=0)
            tl.atomic_add(acc+dst,w,edge<last,sem='relaxed')


class EventModel(torch.nn.Module):
    def __init__(self, original, outgoing_cpu):
        super().__init__()
        self.original=original
        self.n=outgoing_cpu.shape[0]
        self.ptr=outgoing_cpu.crow_indices().to(dtype=torch.int32,device='cuda')
        self.target=outgoing_cpu.col_indices().to(dtype=torch.int32,device='cuda')
        self.weight=outgoing_cpu.values().to(dtype=torch.int32,device='cuda')
        self.active=torch.empty(self.n,dtype=torch.int32,device='cuda')
        self.number=torch.zeros(1,dtype=torch.int32,device='cuda')
        self.acc=torch.zeros(self.n,dtype=torch.int32,device='cuda')

    def state_init(self):
        return self.original.state_init()

    def forward(self,rates,conductance,delay_buffer,spikes,v,refrac,generator=None):
        poisson=self.original.poisson(rates,generator=generator)
        voltage=self.original.scale*poisson
        self.number.zero_();self.acc.zero_()
        compact_spikes[(triton.cdiv(self.n,1024),)](spikes,self.active,self.number,self.n,1024)
        propagate[(128,)](self.active,self.number,self.ptr,self.target,self.weight,self.acc,256)
        recurrent=self.original.scale*self.acc.to(torch.float32).unsqueeze(0)
        return self.original.neurons(recurrent,voltage,conductance,delay_buffer,spikes,v,refrac)

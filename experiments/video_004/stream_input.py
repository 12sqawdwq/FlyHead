"""Fixed existing visual proxies, extended only to genuine temporal input."""
import numpy as np
from fly_mapping.vision import VisualEncoder


class StreamInput:
    def __init__(self, registry, startup, profile, session):
        self.registry=registry
        self.lc9=startup['lc9']
        self.hs=[registry['cells'][k] for k in registry['visual_input_keys']]
        self.input_indices=[c['model_index'] for c in self.hs]+[c['model_index'] for c in self.lc9]
        self.encoder=VisualEncoder(registry,profile,session,'OFFLINE_MEDIA_REPLAY')
        self.session=session

    def encode(self, image, frame_index, arm):
        source_ns=1_000_000_000+frame_index*100_000_000
        if image is None:
            return np.zeros(185,dtype=np.float32),{'frame_present':False,'hs_valid':False,'reason':'no_input_tail','features':{},'lc9_rates_hz':{'left':0.0,'right':0.0}}
        packet=self.encoder.consume(image,session_id=self.session,sequence=frame_index,source_ns=source_ns,now_ns=source_ns,clock_id='OFFLINE_MEDIA_REPLAY')
        if packet['fault_latched']:raise RuntimeError('ENCODER_FAULT:'+str(packet['reason']))
        grey=image.astype(np.float32)/255 @ np.array([.299,.587,.114],dtype=np.float32)
        contrast={side:float(grey[:,i*80:(i+1)*80].std()) for i,side in enumerate(['left','right'])}
        lc9_rates={side:float(200*np.clip(v/.25,0,1)) if arm!='HS_ONLY' else 0.0 for side,v in contrast.items()}
        rates=np.array([packet['rates_hz'].get(c['root_id'],0.0) for c in self.hs]+[lc9_rates[c['side']] for c in self.lc9],dtype=np.float32)
        assert rates.shape==(185,) and np.isfinite(rates).all() and 0<=rates.min()<=rates.max()<=200
        return rates,{'frame_present':True,'hs_valid':packet['valid'],'reason':packet['reason'],'features':packet.get('features',{}),'lc9_rates_hz':lc9_rates,'contrast':contrast}

import unittest
from eeg_stimulus import Encoder
class Tests(unittest.TestCase):
    def test_direction(self):
        e=Encoder();self.assertEqual(e.encode([.9,.1],0,0.,0.)[0],{'left':32.,'right':0.})
        self.assertEqual(e.encode([.1,.9],1,0.,0.)[0],{'left':0.,'right':32.})
    def test_rejects_zero(self):
        for p,s,t,n,on in [([.5,.5],0,0.,0.,True),([1.,0.],0,0.,1.,True),([1.,0.],0,1.,0.,True),([1.,0.],0,0.,0.,False),([float('nan'),0.],0,0.,0.,True),([.9,.9],0,0.,0.,True)]:
            self.assertEqual(Encoder().encode(p,s,t,n,on)[0],{'left':0.,'right':0.})
    def test_no_retention(self):
        e=Encoder();e.encode([1.,0.],0,0.,0.)
        self.assertEqual(e.encode([1.,0.],0,0.,0.)[1],'sequence_rejected')
        self.assertEqual(e.encode([.5,.5],1,0.,0.)[0],{'left':0.,'right':0.})
if __name__=='__main__':unittest.main()

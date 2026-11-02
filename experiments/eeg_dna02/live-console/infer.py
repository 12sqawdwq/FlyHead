"""Run real TCFormer inference in its existing environment; selected official test trials only."""
import contextlib,json,sys,pathlib
req=json.loads(sys.argv[1]);subject=req['subject'];start=req['start'];count=req['count']
assert type(subject)is int and 1<=subject<=9 and type(start)is int and start>=0 and type(count)is int and 1<=count<=10
with contextlib.redirect_stdout(sys.stderr):
 sys.path.insert(0,'<SERVER_HOME>/projects/eeg-robot-sdk')
 from decoder import Decoder
 d=Decoder('<SERVER_HOME>/projects/tcformer-paper',subject=subject,seed=0)
 x,y=d.replay_data()
 if start+count>len(x):raise ValueError('Selected trials exceed test set')
 rows=[]
 for i in range(start,start+count):
  p=d.predict(x[i]).tolist()
  rows.append(dict(trial=i,truth=int(y[i]),probabilities=p,waveform_uv=x[i,:,::10].tolist(),sampling_rate=250,channels=['C3','Cz','C4']))
print(json.dumps(dict(subject=subject,rows=rows,input_shape=list(x.shape[1:]),total_trials=len(x),source='official_test_raw_EEG_fresh_TCFormer_inference')))

"""Read-only interpretation of frozen counts; no model inference or tuning."""
from pathlib import Path
import base64,csv,hashlib,json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
r=json.loads((ROOT/'run_003/RESULTS.json').read_text(encoding='utf-8'))
v=json.loads((ROOT/'evidence/VALIDATION_CONTEXT.json').read_text(encoding='utf-8'))
reg=json.loads((ROOT/'config/readout_registry.json').read_text(encoding='utf-8'))
lc=json.loads((ROOT/'config/startup_registry.json').read_text(encoding='utf-8'))
labels=json.loads((ROOT/'config/model_labels.json').read_text(encoding='utf-8'))
conditions={x['name']:x for x in json.loads((ROOT/'config/conditions.json').read_text(encoding='utf-8'))}
inputs={x['model_index'] for x in lc['lc9']}|{reg['cells'][k]['model_index'] for k in reg['visual_input_keys']}
rows=[]
for t in r['trials']:
    path=ROOT/'run_003'/t['counts_file'];assert hashlib.sha256(path.read_bytes()).hexdigest()==t['counts_sha256']
    count=np.load(path,allow_pickle=False)
    trace=np.load(ROOT/'run_003'/t['trace_file'],allow_pickle=False)
    downstream=[int(i) for i in np.argsort(-count,kind='stable') if count[i]>0 and int(i) not in inputs][:20]
    rows.append(dict(trial=t,metadata=conditions[t['condition']]['metadata'],bins=np.diff(trace,axis=0,prepend=np.zeros((1,8),dtype=trace.dtype)).tolist(),
                     downstream=[dict(labels[i],model_index=i,spikes=int(count[i])) for i in downstream]))
with (ROOT/'TRIALS.csv').open('w',encoding='utf-8-sig',newline='') as f:
    keys=['trial_id','condition','seed','all_spikes','active_neurons','wall_seconds']+reg['readout_keys']+['shadow_v_m_s','shadow_yaw_rad_s']
    w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
    for t in r['trials']:
        w.writerow({**{k:t[k] for k in keys[:6]},**t['readout_counts'],'shadow_v_m_s':t['shadow_intent']['shadow_forward_m_s'],'shadow_yaw_rad_s':t['shadow_intent']['shadow_yaw_rad_s']})
photos={p:base64.b64encode((ROOT/'inputs'/(p+'_resized.png')).read_bytes()).decode() for p in ['china','flower','blank']}
data=json.dumps({'rows':rows,'photos':photos,'readouts':reg['readout_keys'],'registry':reg['cells'],'means':v['conditions']},ensure_ascii=False).replace('<','\\u003c')
html=r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>照片 → 果蝇神经活动</title>
<style>body{font:16px system-ui;background:#f4f6fa;color:#16263e;margin:28px auto;max-width:1200px;padding:0 22px}h1{font-size:30px}h2{font-size:21px}section{background:white;padding:22px;margin:16px 0;border:1px solid #dce4ed;border-radius:10px}.grid{display:grid;grid-template-columns:280px 1fr;gap:24px}img{width:240px;image-rendering:auto;border-radius:5px}select{font-size:17px;max-width:100%;padding:8px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:8px;border-bottom:1px solid #e4e9f0}code{font-size:13px}small{color:#4c5f75}.tag{background:#e5f1fa;padding:6px 12px;border-radius:15px}svg{width:100%;height:auto}pre{white-space:pre-wrap;font-size:13px}.scroll{overflow:auto}</style>
<h1>照片 → 感觉代理 → 完整脑模型 → 神经读出</h1>
<p>2张公开照片 · 25条件 × 3种子 · 每次500ms · 138639神经元 / 15091983连接</p>
<p><span class="tag">离线照片响应</span> <span class="tag">ROS发布关闭</span></p>
<section><label>选择试验： <select id="choose"></select></label><p id="info"></p>
<div class="grid"><div><img id="photo"><p id="caption"></p><pre id="input"></pre></div><div><h2>固定行为／诊断读出</h2><div id="readouts"></div><p id="intent"></p></div></div></section>
<section><h2>神经发放时间图</h2><p>每列10ms；颜色为该时间箱内尖峰数，固定色标0–4+。不是摄像机帧时间。</p><div id="heat"></div></section>
<section><h2>最活跃下游细胞（排除185个直接输入）</h2><p>按冻结全脑计数排序的描述性列表，不替换上方固定动作读出。</p><div id="downstream" class="scroll"></div></section>
<section><h2>全部条件的三种子均值</h2><div id="means" class="scroll"></div></section>
<section><h2>如何解释</h2><p>静态照片通过左右半图RMS对比度映射到LC9；人工平移通过六HS运动代理进入模型。这不是物体语义识别或真实视网膜感受野重建。</p><p>照片结果来自mapping_002/run_003，后续事件传播优化保存在optimization_003，不把两次运行混为一体。前进支路会影响转向响应，尤其右转：观察的是网络耦合，不是三个独立的运动按钮。</p><p>原图许可与作者：<a href="photos/README.txt">仓库原始说明</a>，CC BY 2.0。图像已中心裁剪、缩放；左右运动条件为人工平移。</p><p>完整逐次数据：<a href="TRIALS.csv">TRIALS.csv</a>；原始全脑计数和轨迹：run_003/。</p></section>
<script>const D=__DATA__;
const E=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const table=(heads,rows)=>'<table><thead><tr>'+heads.map(x=>'<th>'+E(x)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(x=>'<td>'+E(x)+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
const select=document.getElementById('choose');D.rows.forEach((r,i)=>{let o=document.createElement('option');o.value=i;o.textContent=r.trial.trial_id;select.appendChild(o)});
function draw(){let row=D.rows[Number(select.value)],t=row.trial,m=row.metadata;let p=m.photo||'blank';document.getElementById('photo').src='data:image/png;base64,'+D.photos[p];document.getElementById('caption').textContent=m.photo?m.photo+' / '+m.direction+' / '+m.branch:'合成刺激控制（无照片）';
document.getElementById('info').textContent='全脑 '+t.all_spikes+' 个尖峰 · '+t.active_neurons+' 个活动细胞 · seed '+t.seed;
document.getElementById('input').textContent=m.lc9_rates_hz?'实际LC9输入（Hz）\n'+JSON.stringify(m.branch==='HS_ONLY'?{left:0,right:0}:m.lc9_rates_hz,null,2)+'\nHS质量: '+m.hs_valid+'\nHS支路: '+(m.branch==='LC9_ONLY'?'关闭':'开启')+'\n图片显示基准图；左右移为人工变换。':JSON.stringify(m,null,2);
document.getElementById('readouts').innerHTML=table(['细胞','root_id','尖峰数','Hz'],D.readouts.map(k=>[k,D.registry[k].root_id,t.readout_counts[k],t.readout_counts[k]*2]));
document.getElementById('intent').textContent='影子意图：'+t.shadow_intent.state+'；v='+t.shadow_intent.shadow_forward_m_s.toFixed(3)+' m/s；ω='+t.shadow_intent.shadow_yaw_rad_s.toFixed(3)+' rad/s。没有下发运动。';
let svg='<svg viewBox="0 0 1080 260"><text x="160" y="16">0ms</text><text x="986" y="16">500ms</text>';
D.readouts.forEach((key,j)=>{svg+='<text x="0" y="'+(45+j*26)+'" font-size="15">'+E(key)+'</text>';row.bins.forEach((bin,i)=>{let c=bin[j];svg+='<rect x="'+(160+i*18)+'" y="'+(27+j*26)+'" width="17" height="23" fill="hsl(213,75%,'+(96-Math.min(c,4)*19)+'%)"><title>'+E(key)+' '+(i*10)+'–'+((i+1)*10)+'ms: '+c+'</title></rect>'})});svg+='</svg>';document.getElementById('heat').innerHTML=svg;
document.getElementById('downstream').innerHTML=table(['类型','侧别','root_id','计数','Hz'],row.downstream.map(x=>[x.cell_type||'未命名',x.side,x.root_id,x.spikes,x.spikes*2]));}
select.addEventListener('change',draw);select.value=D.rows.findIndex(x=>x.trial.condition==='china_STATIC_COMBINED');draw();
document.getElementById('means').innerHTML=table(['条件','P9左 Hz','P9右 Hz','DNa02左 Hz','DNa02右 Hz','影子v','影子ω'],D.means.map(x=>[x.condition,x.mean_readout_hz.DNp09_left.toFixed(1),x.mean_readout_hz.DNp09_right.toFixed(1),x.mean_readout_hz.DNa02_left.toFixed(1),x.mean_readout_hz.DNa02_right.toFixed(1),x.mean_v.toFixed(3),x.mean_yaw.toFixed(3)]));</script></html>'''
(ROOT/'PHOTO_RESPONSE.html').write_bytes(html.replace('__DATA__',data).encode('utf-8'))
print('PHOTO_RESPONSE.html and TRIALS.csv created from frozen results')

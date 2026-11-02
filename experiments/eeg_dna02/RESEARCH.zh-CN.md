# EEG → 果蝇刺激接入调研与基线

核查日期：2026-10-13。只读研究，未改变远端业务源码、未启动模型或机器人。

## 备份范围与来源

source/ 是 5090 上 <SERVER_ROOT> 的选定源码镜像，共 78 文件；eeg-fly-source-manifest.json 保存逐文件 SHA256，下载后全部核验通过。包含 loom_005、video_004/vendor 仿真引擎、上游 PyTorch 模型及 distributed_control/server 后端；不含大体积连接组数据、环境、密钥、网页或完整运行日志，不是整机备份。压缩包另存本目录。

上游 eonsystemspbc/fly-brain，部署协议固定提交 a3db62f9436074e485c0278290c2164ed6150808。来源身份以随附 PROTOCOL 和下载清单为准。

## 当前实际刺激路径

brain_link.py 实例化 LidarRetinaV3。on_scan 选择距地面 0.08–0.50 m 的障碍点，转入车体坐标。reflex 模式从视网膜输入排除靠近已知地图障碍的点，但保护包络仍检查全部选定点。

retina.py：24 个方向扇区，每区取距离的第 10 百分位；距离有效范围 0.30–6 m。V3 在世界坐标汇聚最近 0.30 秒点云，并用 EMA=0.5 平滑距离。历史超过 0.50 秒间隔清空。

设假定物体宽度 W=0.30 m，距离 d，角宽 theta=2*atan(W/(2*d))。选择接近 0.30 秒的历史基线，至少 0.20 秒。只有连续两次距离分别缩小超过 0.005 m、且当前距离小于 3 m，才计算：

loom=max((theta_now-theta_old)/dt - 0.12, 0)，单位 rad/s。

每侧分别取最大 loom：
- LC4：min(200, 400*loom) Hz。
- LPLC2：仅角宽 >=20° 的扇区参与，其余公式同 LC4。
- LC9：前方左右各 30° 内最近距离 free；120*clip((free-0.5)/(2.5-0.5),0,1) Hz。

例如通过全部接近门槛后角宽增长率为 0.20 rad/s，则 loom=0.08，LC4=32 Hz；free=1.5 m 时 LC9=60 Hz。不能用文件顶部旧 V1 的增益 600 或 V2 的死区 0.05 描述当前 V3。

## 从频率到神经刺激

rates_vector 和 input_indices 均硬编码 ('LC4','LPLC2','LC9') 顺序，同一类型同一侧每个细胞获得相同 Hz 值，非分摊群体总频率。当前输入共有 LC4 104、LPLC2 210、LC9 179 个细胞（注册表可复核）。DNa02 目前只在 readouts，消息添加 DNa02 键仍会被向量构造忽略。

brain.py 将向量写入 engine.rates[0,input_indices]。上游 PoissonSpikeGenerator 实际每步做 Bernoulli(rate*dt/1000)，dt=0.1 ms；抽样值乘 scalePoisson=250，随后受 wScale=0.275 及神经方程作用。40 Hz 对应每步概率 0.004，100 ms 内期望 4 次外部事件，不保证恰好 4 次，也不等于输出放电率 40 Hz。

每个 GraphEngine block=100步=10 ms，默认窗口10个block=100 ms；状态连续保留。readouts_by_type 按类型/侧别求和，除窗口秒数得到群体聚合 Hz；解码器再对左右值求平均或差值。

关键隐藏影响：TorchModel 的 exc_indices 不仅指定受刺激细胞，还把这些细胞 refrac_steps 设为 0。其他细胞默认不应期 2.2 ms。直接把 DNa02 加入 input_indices 会同时改变它的不应期，不能称为只改输入、不改神经动力学。应将“可注入索引”和“继承上游零不应期索引”明确分开；第一实验保留原 LC 神经元的设置，不自动清零新增 DNa02 的不应期，并记录模型变体。

其他神经参数：tauSyn=5 ms、tDelay=1.8 ms、tauMem=20 ms、vRest/vReset=-52 mV、vThreshold=-45 mV。建议保持不变。

## DNa02 身份（此快照限定）

|侧别|FlyWire root_id|模型下标|
|---|---|---|
|右|720575940604737708|904|
|左|720575940629327659|92992|

下标只适用于此连接组文件和排序，不能跨版本直接复用。注册表中 field_to_eye_assignment_validated 和 robot_yaw_sign_calibrated 仍为 false；历史实验报告有侧别观察，不能因此改写该身份声明。

## EEG 编码建议：尚未实现、尚未标定

新建 eeg_stimulus.py，验证两类概率有限、范围0–1、和为1、类别顺序及源时间。依据真实采集时间而非仅推理完成时间拒绝积压输入。左右概率差 d=pL-pR；置信度不足则零刺激，通过门槛后 rateL=gain*max(d,0)，rateR=gain*max(-d,0)。可选平滑与频率变化率限制，需报告新增延迟。gain 上限必须校准，40 Hz 只是说明示例。

建议配置变量：enabled=false、confidence_threshold、max_input_age_ms、gain_hz、max_rate_hz、ema_tau_s、slew_hz_per_s、pulse_ms、cooldown_ms、decoder_version、model_identity、class_order、target_root_ids。均不得把未标定值当验收参数。输出记录原概率、平滑概率、左右刺激频率、拒绝原因。

EEG-only 校准时 LC 输入归零；combined 实验才加入真实/离线雷达刺激。尤其 LC9 会产生前进驱动，仅增加 DNa02 不会使整套系统自动变成“只转向”。同名输入必须规定唯一所有者或明确融合规则，禁止隐式覆盖。

## 需要改哪些文件

|文件|计划改动|
|---|---|
|新增 config/eeg_stimulus.json|编码、目标身份、时间和模式参数，默认关闭|
|新增 eeg_stimulus.py|概率校验、门控、平滑、频率编码；不依赖 ROS，不发底盘命令|
|新增输入布局模块/扩展注册表|保留 readouts，增加独立 EEG 输入定义，固定顺序和重复索引检查|
|retina.py 的 rates_vector/input_indices|移除只认识三类神经元的限制；旧雷达向量必须完全保持兼容|
|brain.py|区分刺激目标与零不应期目标；每窗口明确清除撤销输入；重建 GPU 图和身份记录|
|brain_service.py|接受 EEG/雷达分离消息与时间戳，拒绝乱序和过期；按窗口融合；锁定解码器版本|
|distributed_control/server/brain_link.py|EEG 状态与使能接入统一仲裁；停止不能只依靠零刺激|
|EEG SDK sender|发送概率及模型/标准化身份，不再从另一通道发布速度；此 SDK 源码未纳入本次镜像|
|网页|显示概率、刺激、读出、最终命令及拒绝原因；不做第一阶段必需项|
|decoder.py|第一阶段保持固定版本不变，作为输出观察器|

默认启动脚本 LOOM_DECODER=4；文件存在 V9 不代表 V9 正在使用。保留冻结、逃逸等覆盖关系。当前解码器历史速度上限高于新项目要求，禁止当作实车允许值；后续最终执行端仍需强制前后<=0.05 m/s、转向<=0.1 rad/s。

## 验证顺序

1. 纯函数检查：概率边界、非有限数、序号、时间、左右映射、撤销后无残留、旧输入兼容。
2. 不接机器人刺激扫频：固定解码器和模型身份，跨随机种子比较零/左/右刺激，记录读出、方向、饱和、副作用和撤销后持续活动。
3. EEG 数据回放及雷达联合回放：标记 dataset_replay，不宣称是真实在线 EEG。
4. shadow 联调：只记录结果，检查延迟、状态覆盖与停止路径。
5. 单独的实车验收，不能用前四步替代。

本次没有改动源镜像中的业务文件，也没有运行上述 GPU 实验。

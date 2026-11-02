# 蝇首 FlyHead

**用完整果蝇连接组当轮足机器人"刑天"的头。**

刑天在神话里断首后仍继续作战；本项目给它装上一个果蝇的脑。

FlyHead 在 GPU 上运行 FlyWire v783 完整果蝇连接组（138639 个神经元、15091983 条连接记录，
LIF 模型，PyTorch/CUDA），作为 DIABLO 轮足机器人的决策者，经 ROS 2 控制实车。
LiDAR 逼近信号经工程编码输入已鉴定的视觉投射神经元（LC4、LPLC2、LC9），
由下行神经元（巨纤维 DNp01、DNa02、DNp09、MDN）的放电解码出逃逸、转向和行走，
再经只能减速或归零、不能增加运动的安全包络后才发给底盘。

## 分层与边界

| 层 | 是什么 | 不是什么 |
| --- | --- | --- |
| 连接组仿真 | eonsystemspbc/fly-brain 固定提交的 LIF 模型，神经方程未改 | 标定过的果蝇；没有学习 |
| 刺激编码 | 工程代理：LiDAR 角扩张 → LC4/LPLC2，前方自由空间 → LC9 | 视网膜或生物视觉复原 |
| 神经元身份 | 精确 cell_type → root_id → 模型下标，注释文件 SHA 锁定 | 跨命名类型的同义合并 |
| 解码 | 下行神经元放电的固定公式 | 导航脚本或恒定速度 |
| 执行 | 解码意图经安全包络、围栏、keep-in 后的命令 | 把规划器输出冒充为神经决策 |

解剖侧别、LiDAR 视野侧和机器人转向符号是三张独立的表；注册表明确标注
视野→眼的对应和转向符号**尚未标定**。

## 目录（按功能解耦）

| 目录 | 内容 |
| --- | --- |
| `flyhead/fly/` | 果蝇：连接组模型、编码器（LiDAR 逼近、EEG）、解码器、脑服务 |
| `flyhead/slam/` | SLAM：KISS-ICP 里程计、重定位、地图层、原始录制 |
| `flyhead/navigation/` | 路线规划与跟踪、上位机停车/限速/绕行链 |
| `flyhead/server/` | 服务端：经 SSH 管理机器人会话、控制环、脑连接 |
| `flyhead/safety/` | 命令安全包络 |
| `flyhead/sim/` | 仿真环境：闭环仿真、合成场地 |
| `flyhead/monitor/` | 监视器：操作员网页控制台 + SSH 隧道 |
| `robot/` | 机器人部署：ROS 2 桥（LiDAR、IMU、底盘、姿态），独立运行 |
| `experiments/` | 各阶段协议、锁定结果和实际执行的脚本 |
| `docs/` | 架构、复现、SLAM 运维、导航方法、早期调研与规划 |

## 复现

见 [docs/reproduce.md](docs/reproduce.md)。不需要机器人和 GPU 也能跑单元测试与盲基线仿真；
有 CUDA GPU 时可把完整连接组放进仿真闭环。

## 实验结果

见 [experiments/README.md](experiments/README.md)。所有记录保持执行时原样；
协议锁文件中的服务器路径已替换为 `<SERVER_ROOT>` 等占位符（锁文件自身的哈希按原始字节计算）。

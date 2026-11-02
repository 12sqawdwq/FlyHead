# 果蝇视觉—神经—指令映射原型

本轮已实现并验证合成视觉的转向影子链。
完整模型实际在5090D运行，未裁剪神经图。
前进读出仍为零，当前运行速度仍慢于生物实时。
没有真实相机、ROS或运动输出。

入口：

- MAPPING.zh-CN.md：五层映射、14个细胞及指令定义。
- RESULTS.md：四条件真实神经输出、资源与限制。
- config/neuron_registry.json：精确root_id／索引。
- config/mapping_profile.json：显式工程映射参数。
- fly_mapping/vision.py：视觉代理编码。
- fly_mapping/commands.py：神经计数到影子指令。
- tests/test_mapping.py：32项组件检查。

```text
6个HS代理输入
  → 138639神经元／15091983连接完整模型
  → DNa02转向与DNp09前进读出
  → 仅影子意图，不发布ROS
```

源协议已锁定，不修改原四条件结果或静默调参。
当前结果锁为RESULT_LOCK_v2.json。
跨平台换行问题与原始失败见TECHNICAL_NOTE.md。

32项单元测试可单独运行，不调用GPU或机器人：

```bash
python -B -m unittest discover -s tests -v
```

tools/supervise_probe.py的执行槽已经使用，
拒绝原地重跑；不能删除runs或EXECUTION.json绕过。
后续实验使用明确的新协议／修订和新运行目录。

5090D路径：
`<SERVER_ROOT>/inference_service/mappings/visual_neural_001/`

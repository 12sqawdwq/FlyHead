# 完整连接组事件传播后端

结果：RESULTS.md。
核心：event_model.py。
同轮222–223ms降至46–48ms／100ms模拟。
6组500ms全脑计数和末状态与上游完全一致。
完整图保留，不是剪枝的小网络。

run.py是冻结的技术试验，不是常驻推理服务。
旧执行槽不可删除后重跑。
集成新服务时复用EventModel与已验证GraphEngine，
保持整数权重适用门、源时间检查和独立本机保护。

照片响应报告：mapping_002/PHOTO_RESPONSE.html。
两项实验的原始结果和计时不要混合改标。
无ROS、机器人或外部发送操作。

服务器：
`<SERVER_ROOT>/inference_service/mappings/event_optimization_003/`

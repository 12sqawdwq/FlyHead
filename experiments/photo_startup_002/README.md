# 照片响应与LC9启动通路

首先打开PHOTO_RESPONSE.html。
它包含75次试验选择、照片、神经ID／计数、
10ms时间图、下游活动细胞与全条件均值。
预览：PHOTO_RESPONSE_PREVIEW.png。
表格：TRIALS.csv。
结论和局限：RESULTS.md。

当前成功运行：run_003/。
run_001/与run_002/是已保留的模型前资源门失败。
不得删除旧槽、重新运行准备脚本覆盖固定照片输入。
原计划和两项资源修订都有独立SHA锁。

模型和CUDA Graph实际在5090D完成75次试验。
事件传播加速另见optimization_003/RESULTS.md，
不是本目录照片结果的历史后端。

没有相机、ROS发布、底盘操作或外部发送。
本地canonical目录：D:/PROJECT/xingtian_fly/mapping_002/。
服务器：
`<SERVER_ROOT>/inference_service/mappings/photo_startup_002/`

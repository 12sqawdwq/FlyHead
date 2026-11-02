# 归档技术记录

2026-09-23：跨平台验证文件换行与命名。

GPU探针及服务器验证已经完成后，
在Windows本地用同一冻结验证脚本复核计数。
脚本的Path.write_text采用平台默认换行。

因此本地JSON为CRLF，服务器JSON为LF。
额外的原始字节完全相同断言失败，保留该失败。
解析后字段完全一致，且全部原始计数数组SHA一致。
不能把这个失败改写为字节比较通过。

原始文件保留为：

- INDEPENDENT_VALIDATION_SERVER.json：Linux原始字节。
- INDEPENDENT_VALIDATION_LOCAL.json：Windows原始字节。

本地未命名后缀的INDEPENDENT_VALIDATION.json，
仍保留Windows版本；服务器同名文件保持Linux版本。
当前结果锁v2只引用上述显式带平台后缀的文件，
避免以同步覆盖方式消除原始差异。

v1结果锁保留在本地，不宣称其同名路径在两端一致。
v2仅修正归档引用，不改变数据、模型、指标或协议。
没有重新运行GPU，也没有修改已冻结验证脚本。

证据：evidence/VALIDATION_COMPARISON.json。

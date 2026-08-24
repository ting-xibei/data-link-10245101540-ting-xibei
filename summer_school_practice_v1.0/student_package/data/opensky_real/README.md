# OpenSky 真实状态向量（本地试验数据）

本目录由 OpenSky 官方匿名 REST API 实际下载，不是生成器构造的数据。它与 `../raw_states.json` 的用途不同：后者是含固定边界值和故意错误的合成教学样例，本目录用于真实数据兼容性试跑。

数据来自 The OpenSky Network：

- API：<https://opensky-network.org/api/states/all>
- 官方 REST 文档：<https://openskynetwork.github.io/opensky-api/rest.html>

文件：

- `source/*.json`：中央欧洲 WGS84 边界框的 3 次 API 原始响应，按收到的字节原样保存。
- `normalized_state_vectors.csv`：所有状态向量的字段平铺；空值保持为空，没有补值。
- `opensky_real_messages.bin`：有位置且通过教学协议量程检查的记录编码成 41 字节 TeachingLink 帧。
- `provenance.json`：查询 URL、抓取时刻、原始文件 SHA-256、记录数及数据处理声明。

匿名接口只提供最近状态，时间分辨率为 10 秒，并有调用额度。本课程包已将快照冻结为离线输入，学生不需要重新访问接口。没有插值、随机值或人工航空器记录。学生可使用本人完成的 M2-M3 代码读取这些输入，验证真实数据兼容性；逐记录往返参考结果不随学生包发布。

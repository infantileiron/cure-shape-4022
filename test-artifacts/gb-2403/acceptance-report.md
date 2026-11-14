# 分段补传批次 · 验收报告（gb-2403）

## 需求到实现对照

| 需求 | 实现 | 证据 |
|---|---|---|
| 增加补传批次，预先登记曲线及64点时间轴 | `BackfillBatch`（models/backfill.py）；创建时只存 curve_id/label 与等距64点 times，`segments/point_sources` 为空，状态 `collecting` | 测试「预登记状态为collecting/无片段/每曲线缺64点/时间轴64点」 |
| 按曲线和采样序号接收片段 | `POST /backfills/{id}/segments`，入参 curve_id + start_index(0..63) + values，服务端越界/未登记/非有限值拒绝 | 测试「起点越界在schema层拒绝」「片段曲线未登记」 |
| 乱序及重复片段不增加读数 | 片段按序号落入 `point_sources[curve][index]`；重复片段读数不新增，仅追加来源 | 「乱序：先收32-63点/补齐后齐点」「重复片段不增加读点数」 |
| 重叠同值保留全部来源 | 同一点的每次补传都追加 `{segment_id,batch_no,value}` 来源条目 | 「同点保留全部来源(2条)」「重叠同值保留来源」 |
| 异值则整次补传拒绝并指出冲突点，已收数据不变 | 先全量校验再落库；任一异值即 409，返回曲线/序号/已收值/被拒值/双方来源，批次仅登记 conflict，不写任何点、不增 segment | 「异值冲突已登记/冲突点定位正确/含双方值/含双方来源/整次拒绝：已收数据不变/无新segment」 |
| 并发补传与发布遵守同样规则 | 补传与发布均在事务内 `SELECT ... FOR UPDATE` 锁批次行，规则在同一事务判定 | 并发8线程乱序片段测试「并发后全部齐点/结果与到达顺序无关」「并发冲突后原值不变」 |
| 仅全部曲线齐点时可发布 | publish 先算 `missing`，有缺点即 409 并返回每条曲线缺点序号 | 「缺点发布被拒并指出缺点」 |
| 重复发布返回同一曲线集 | 已发布状态直接返回原 dataset_id，不新建 | 「重复发布返回同一曲线集」 |
| 发布后拒绝补传 | 非 collecting 状态接收片段直接 409 | 「批次已发布，发布后拒绝补传」 |
| 页面查看缺点、冲突及每点来源 | 前端「补传批次」页：64格网格（灰=已收/虚框=缺点/红=冲突/深=多来源），点击任一点列出全部来源片段，冲突面板列出被拒补传 | http-smoke 全链路 200/409；`npm run build` 严格类型检查通过 |
| 从发布的曲线集继续归并 | 创建批次可带 parent_batch_id：须来源已发布、同一时间轴、曲线有交集；续批独立收集发布 | 「续批记录parent/续批发布为新曲线集」及坏轴/无交集/未发布来源三类拒绝 |
| 片段到达顺序不影响结果 | 最终取值只取决于 curve_id + point_index，与到达先后无关；并发乱序发布结果与顺序输入逐点相等 | 「并发结果与到达顺序无关」 |

## 验证方式

- 服务层端到端：`python3 -I test_backfill.py`（SQLite 内存库 + 真实 SQLAlchemy 模型/服务，32 项断言全过，日志见 test-run.log）。
- HTTP 路由：TestClient 打桩认证跑真实 FastAPI 路由（http-smoke.log），覆盖创建、收片段、冲突 409、缺点 409、发布、重复发布、发布后拒绝、续批、列表/详情。
- 种子：seed_demo.py 新增三个演示批次（收数中含缺点与冲突、齐点发布、续批），连跑两次计数完全一致，保持幂等不覆盖。
- 前端：`npm run build`（tsc --noEmit + vite）通过。
- 说明：本地无 PostgreSQL/Docker，行级锁在 SQLite 下以应用互斥模拟串行语义；生产 PG 上 `with_for_update()` 为真实 `SELECT ... FOR UPDATE` 行锁，判定逻辑相同。

## 新增/改动文件

- 后端新增：models/backfill.py、schemas/backfill.py、services/backfills.py、routes/backfills.py；main.py 与 models/__init__.py 挂载；seed_demo.py 演示数据。
- 前端新增：api/backfills.ts、pages/Backfills.tsx、utils/backfill.ts；types、store、导航、枚举、样式、App 挂载；client.ts 支持对象型 409 详情的中文展开。
- 文档：README「分段补传批次」章节；migrations/001-initial.sql 注释补充新表。

# 数据契约 v1

Python 3.10+ 标准库。金额及数量通过 Decimal 计算，输出金额四舍五入到两位；数量输出为 JSON 数字。实际计算不要累加页面上舍入后的行金额。

## 五类输入

| 文件 | 关键字段 | 含义 |
| --- | --- | --- |
| profile.json | schema, mode, base_currency, monthly_income, monthly_expenses, emergency_months, accounts, assets | 用户配置、估计和资产字典 |
| opening.json | as_of, confirmed, positions | 同一时点的期初头寸 |
| events.jsonl | 逐行事件 | 期初后变化，只追加 |
| prices.json | quotes, fx | 当前价格集，保留来源和时点 |
| plan.json | status, targets, goals | 目标配置及资金用途 |

所有时间使用 ISO 8601 且必须带时区。事件发生时间必须严格晚于期初；记录时间不得早于发生时间。日期和价格示例见 examples/demo。

`accounts` 是 ID → 元数据的对象；`assets` 是 ID → 资产定义的对象。资产有 name、kind、currency、category、liquid。kind 为 cash/security/pending/liability。账户别名不需要真实机构或账号。

期初 positions 使用 account/asset/quantity。单一账户资产只能出现一行。负债本金用正数量，投影单独减去负债；不支持空头、衍生品保证金或自动计息。

## 估值与缺失

`value = quantity × price × FX`，FX 是每一单位外币折合多少本位币。本位币汇率固定 1；其他币种必须显式提供。现金也必须提供单价 1。未来日期价格不用于较早快照；缺价或缺汇率保持 null。

任一非零资产缺估值时，总资产和净资产为 null，known_assets 只提供已知小计。负债缺估值时负债和净资产为 null。未确认的空期初不是零资产。过七天的报价仍可显示，但必须提示原始日期；该阈值只是模板中的提示规则。

`--at` 过滤事件发生时间，并仅使用不晚于该时点的当前价格集。**这不是完整历史估值或当时已知信息的回测**：更正按文件中当前已知信息重述，profile/plan 没有历史版本，旧价格被替换后不会自动保留。需要历史能力时应扩展追加价格历史与双时间查询，不能把当前价格倒填历史。

## 事件

必填：id、kind、status、occurred_at、recorded_at、evidence、note、legs。status 是 confirmed 或 pending。每个 leg 包含 account、asset、quantity_delta。数量增为正、减为负；有效投影不允许负头寸。例子：

```json
{
  "id": "demo-income-002",
  "kind": "income",
  "status": "confirmed",
  "occurred_at": "2026-02-01T10:00:00+08:00",
  "recorded_at": "2026-02-01T10:05:00+08:00",
  "evidence": "synthetic:income:002",
  "note": "仅为虚构格式示例",
  "legs": [{"account": "demo-bank", "asset": "CASH-CNY", "quantity_delta": 500}]
}
```

| kind | 约束与记录方法 |
| --- | --- |
| income / expense | 只影响现金，收入所有腿为正，支出所有腿为负 |
| transfer | 同一资产跨账户，所有腿的数量合计为零；手续费另记 expense |
| trade | 同时有正负腿；买入包含现金扣款、份额增加，费用包含在现金扣款中 |
| settlement | 同时有正负腿；清掉在途，增加实际份额，不再次扣款 |
| adjustment | 有凭证的差异调整；不得用来掩盖不明对账差额 |

系统不自动推断成交汇率、手续费或资产之间的经济等价；这仍需核对原始凭证。trade/settlement 的正负约束只能发现漏腿的一类错误，不代表交易内容已正确。

同一 id 完全相同的重试为 no-op；相同 id 不同内容拒绝。evidence 是凭证内的唯一经济事件引用；一张单据多项记录请使用不同的行号后缀。重复 evidence 拒绝，除非用 supersedes 引用其最新版本。

更正用新 id、完整替代事件、`supersedes: "旧id"`。旧行保留，新事件替代旧事件的全部腿，不是叠加差额。已替代版本不可再次替代。pending 记录不生效；确认它时新增 confirmed 版本并 supersedes 旧记录。

申购实际扣款与 pending 状态不同：见 subscription.json → settlement.json。前者是已经发生的现金到在途资产转移，后者只是未核实线索。

## 规划口径

- 月结余 = 用户估计的月收入 − 月支出，不由少量样例流水外推。
- 应急可用额只计 liquid=true 的本位币现金，不自动把股票、外币、在途或信用额度当现金。
- 应急目标 = 月支出 × 自定月数。缺输入不猜。
- 配置分母 = 总资产（不扣负债）；targets 为空表示未配置，否则合计必须为 100。
- 配置差额是静态目标差，不是下单清单，不自动生成事件。
- 目标月投入 = max(0, 目标金额 − 专项已存金额) / 剩余月数。各目标独立求和，不自动优化优先级或处理共享资金。已存金额不再加进资产。
- 情景采用名义年率 / 12、每月末投入，忽略税费、通胀和波动。它是数学假设，不是收益预测。

CLI 所有 `--data` 参数放在子命令之前。快照 revision 是全部五类输入内容的 SHA-256，可以用于确认报告来自哪一份输入；它不是签名或凭证真实性证明。

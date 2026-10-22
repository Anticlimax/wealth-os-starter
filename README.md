# Wealth OS Starter

**把这个仓库交给大模型，搭建你自己的个人理财规划系统。**

一个以本地账本为中心的开源模板：资产负债、月度收支、应急储备、资产配置、目标预算、情景测算，以及可追溯的记账与复盘。面向中文用户，也可以让模型修改文案和本位币。

它来自个人财富系统的通用设计，公开版重新实现了精简核心，全部样例均为虚构。没有原始个人账本、历史报告、账户信息、部署配置或 Git 历史。它不是原工程的完整镜像，也不继承任何人的投资策略。

## 交给大模型开始

将下面这段话发给能操作本地文件和终端的大模型（如 Codex、Claude Code）：

```text
请克隆 https://github.com/Anticlimax/wealth-os-starter.git 并进入目录。
先阅读 AGENTS.md、README.md 和 docs/ONBOARDING.md，按仓库流程启动虚构演示并验证。
然后访谈我，帮助我建立个人理财系统：了解本位币、收入支出、资产负债、
应急需求和近期目标。未知信息保持 null，实际记录和计划分开。
把我的资料只写入 data/personal/；先给我可核对的建账草案，确认后才记入实际账本。
不要提交或上传我的财务数据，不要根据演示配置推荐投资，不要执行交易。
最后启动本地看板，告诉我日常怎样记账、核对和做月度复盘。
```

无需模型 API Key。模型负责协助整理资料和修改本地文件，程序负责确定性计算。仅能聊天、不能操作文件的模型可以生成草案，由你在本地运行命令。

## 两分钟体验

依赖：**Python 3.10+ 和 Git**，无第三方 Python 包，无 Node.js、数据库或云服务要求。

```bash
git clone https://github.com/Anticlimax/wealth-os-starter.git
cd wealth-os-starter
python3 -m wealthos --data data/demo init-demo
python3 -m wealthos --data data/demo validate
python3 -m wealthos --data data/demo serve
```

打开 **http://127.0.0.1:8787**。Windows 可将 `python3` 替换为 `py -3`。端口被占用时加 `--port 8788`。停止服务使用 Ctrl+C；下次直接运行 `serve`，无需重新初始化。`init-demo` 遇到已存在目录会拒绝覆盖。

演示资产 **105,000 CNY**、负债 **15,000 CNY**、净资产 **90,000 CNY**；月结余 **5,000 CNY**，两项目标月投入合计 **2,000 CNY**。这组数字是专门构造的教学样例。演示价格固定在 2026-01-01，页面会如实显示过期提示。

## 能做什么

| 功能 | 当前能力 |
| --- | --- |
| 资产负债 | 多账户、多币种，记录价格与汇率来源；负债单列 |
| 记账 | 追加事件、凭证去重、显式更正、未确认线索隔离 |
| 现金与在途 | 买入同时扣现金，已扣款待确认用在途资产，确认份额不重复扣款 |
| 财务规划 | 月结余、应急储备缺口、配置偏离、目标每月所需投入 |
| 复盘 | 同源 JSON 快照、Markdown 摘要、本地只读看板 |
| 情景分析 | 自选假设的复利计算，含零收益与负收益情景 |
| AI 接手 | 根目录 AGENTS.md、建账访谈、日常任务提示词和数据契约 |

当前没有自动行情、账单 OCR、银行连接、模型调用、交易、税务、成本批次、投资收益率、定时调度或云部署。不要把净资产变化解释为收益；不要把固定收益率情景解释为预测。详细边界见 [数据契约](docs/DATA_MODEL.md)。

## 建立你的系统

```bash
python3 -m wealthos --data data/personal init
```

按照 [首次建账](docs/ONBOARDING.md) 和模型一起填好本地资料。空白模板里的未知收支为 `null`，未确认期初净资产为未知，不显示成零。真实账户使用自己的别名，无需提供卡号、登录密码或 API 密钥。

```bash
python3 -m wealthos --data data/personal validate
python3 -m wealthos --data data/personal report
python3 -m wealthos --data data/personal export --output output/personal
python3 -m wealthos --data data/personal serve
```

`data/`、`output/`、`private/`、`backups/`、`scratch/` 默认被 Git 忽略。它们是本机明文文件，需使用你自己的磁盘权限、加密与备份方案。不要把整个目录上传公共托管。看板仅监听回环地址且只提供三个静态文件与计算后的快照；没有写入接口。

## 日常使用

在演示副本上记录一次虚构买入：

```bash
python3 -m wealthos --data data/demo add-event --file examples/events/trade.json --confirm
python3 -m wealthos --data data/demo report
```

同一个事件重复提交不会重复记账；相同 ID 不同内容会报错。真实记录应先保存到 `data/personal/drafts/` 并核对原始凭证，确认后再加 `--confirm`。参数是人工确认的工具约定，不是账户交易授权。

```bash
# 纯情景计算，不依赖账本，不写持仓
python3 -m wealthos scenario --initial 100000 --monthly 2000 --annual-return 0 --years 10
# 查看指定发生时间的头寸；规则与更正语义见数据契约
python3 -m wealthos --data data/demo snapshot --at 2026-01-06T23:59:59+08:00
# 回归与公开内容检查
python3 -m unittest discover -s tests -v
python3 scripts/check_public.py
```

更多可直接使用的对话：[建账](prompts/01-onboarding.md) · [记账](prompts/02-bookkeeping.md) · [月度复盘](prompts/03-monthly-review.md) · [扩展系统](prompts/04-extend.md)。

## 项目结构

```text
wealthos/        Python 账本、规划计算、命令行、本地服务
web/             无构建步骤的只读看板
examples/        明确标注的虚构资料与事件
prompts/         可以复制给大模型的任务
docs/           建账、数据模型、架构、隐私与扩展说明
tests/           财务边界、命令行与本地服务回归
scripts/         发布内容检查
data/           你的本地资料（被 Git 忽略）
output/         生成结果（被 Git 忽略）
```

设计与扩展路线见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)，贡献前阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。许可：[MIT](LICENSE)。这是记录与规划工具，不提供个性化金融建议。

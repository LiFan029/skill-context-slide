# 你的 AI Agent 是不是越用越笨？我写了个「滑动窗口」来解决

> 一个 LRU 滑动窗口方案，能自动清理 Agent 上下文里的过期「短期记忆」

---

## 起因

我日常重度使用 AI Agent（Hermes Agent），习惯同时加载很多技能（skill），让它帮我做各种事——看股票、写代码、跑 DND、查论文、管理服务器。

但用着用着发现一个问题：**Agent 越用越「笨」了。**

不是模型本身变笨，而是上下文里塞满了用不上的东西。举个例子：

1. 我让 Agent 加载了股票分析技能，聊了一轮 A 股行情
2. 然后切话题——让它帮我查一篇论文
3. 又切话题——聊 TRPG 跑团配置
4. 再切话题——让它查服务器日志

**问题是：股票技能的内容，在聊 TRPG 的时候，仍然占用着上下文 token。**

对 8K 上下文的本地小模型来说，一个技能可能占 2-3K tokens，3 个无关技能就吃掉接近一半的上下文预算。Agent 的注意力被稀释，推理质量明显下降。

## 现有的解决方案：等「压缩」

Hermes Agent 有一套 ContextCompressor 机制——当上下文达到一定阈值（比如 85%），会自动压缩消息历史，把旧对话浓缩成摘要。

但这里有一个坑：**压缩只会删对话历史，不会管 tool 加载的内容。**

Skill 的内容以 tool result 的形式留在上下文里，压缩扫不到它。所以即使 compression 触发，那些过期技能的全文依然躺在那里。

## 我们的方案：LRU 滑动窗口 + Stub 替换

思路很直接——**「满了就踢，要了再装」**。

在 compression 触发时，额外做一步清理：

1. **收集**：遍历所有 assistant 消息，找出所有 `skill_view(name)` 的调用
2. **LRU 窗口**：从后往前，保留最近 N 个**不同的**技能（默认 N=3）
3. **标记**：窗口外的 skill_view 结果标记为「待清理」
4. **替换**：把过期技能的内容替换成一个极短的 stub（`[已卸载]`）

核心设计原则：

- **不删消息**——用 stub 替换而非删除，保持 role 交替链完整
- **同名去重**——同一个技能多次调用只占 1 个 LRU 位
- **不影响其他 tool**——只清理 `skill_view` 的结果
- **卸载后可重载**——下次用到同名技能时重新加载，零净损失

## 测试验证

我们写了 11 个测试用例覆盖了所有场景：

- 正常路径 6 个：空输入安全、无操作、保留最近 3 个、4 技能淘汰最早、同名去重、role 交替保持
- 边界条件 5 个：批量加载、混合 tool、孤立 call_id、窗口为 0、卸载后重载

全部在 0.5 秒内通过。

## V2：自适应窗口

写完之后我发现一个问题——**固定窗口大小不适合所有模型。**

| 模型 | 上下文 | 3 个 skill 占比 | 合理窗口 |
|------|--------|----------------|---------|
| Llama 3.2 3B | 8K | ~37% | 1 |
| Qwen 2.5 7B | 32K | ~9% | 3 |
| GPT-4o | 128K | ~2% | 8 |
| DeepSeek V4 Flash | 100M | ~0.003% | 关闭 |

对 DeepSeek 这种 100M 上下文的模型来说，别说 3 个 skill，30 个也只占 0.03%，根本不需要操心。

所以 V2 的改进方向是：**根据模型的上下文长度，自动计算窗口大小。**

```python
avg_skill_size = 3000       # 平均每个 skill ~3K tokens
safety_factor = 4           # 保留 1/4 的预算给 skill

context_window = model.context_length or 32768
window = max(1, context_window // avg_skill_size // safety_factor)
```

- 32K 上下文 → 窗口 3
- 128K 上下文 → 窗口 10
- 100M 上下文 → 关闭 pruning

## 开源

这个方案已经整理成仓库开源了：

**GitHub：**[LiFan029/skill-context-slide](https://github.com/LiFan029/skill-context-slide)

包含：
- Hermes Agent 的侵入式补丁（107 行，零删除）
- 一键还原脚本
- 11 项完整测试套件
- 通用设计模式文档（不绑 Hermes，任何 Agent 都可实现）
- **上游 PR #57461**：向 NousResearch 提交了 `post_compress` hook（+22/-1 行）

目前兼容 Hermes Agent、Claude Code、OpenAI Codex、Cline、Continue、Cursor 等主流 Agent 框架。

---

如果你也在用 AI Agent，遇到过「越用越笨」的问题，欢迎来仓库看看。如果你有不同的解法，更欢迎来讨论。

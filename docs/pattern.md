# 设计模式：Agent 知识加载的 LRU 上下文窗口

## 问题

Agent 通过 tool_call 加载外部知识（技能文档、API 参考、代码库上下文等）到对话上下文中。每次加载的内容可能占用数百到数千 token。当话题切换后，这些内容不再相关，但由于保留在上下文中，持续消耗 token 预算并稀释 agent 的注意力。

## 约束

- 不提前猜测用户将需要什么（不要预加载）
- 不修改 index 或可用技能列表（保持透明）
- 仅在 context compression 等自然触发点操作（不拦截对话流）
- 不删除消息（保持 role 交替链完整）
- 重载成本极低（一次 tool 调用）

## 方案

**LRU 窗口 + stub 替换。**

### 四个步骤

1. **收集** — 遍历 assistant 消息，找到目标 tool（如 `skill_view`）的所有调用
2. **LRU 窗口** — 从后往前扫描，取最近 N 个不同名称的调用（去重）
3. **标记** — 窗口外的 call_id 加入淘汰集合
4. **替换** — 匹配的 tool result 内容替换为 stub（`[已卸载]`/`[evicted]`）

### 关键决策

- **窗口大小**：固定值（如 3），而非动态调整。简单可预测。
- **淘汰策略**：LRU 而非语义相关度。语义判断不可靠且成本高。
- **替换方式**：stub 而不是删除。避免破坏 message role 交替（LLM API 要求 strict alternation）。
- **触发时机**：仅在 compression 时，不拦截对话流。

### 异常安全

- 误删 → 下次使用时重新加载，零净损失
- 同名去重 → 同一个知识被多次加载只占一个窗口位
- 窗口=0 → 全部卸载

## 通用性

此模式适用于任何通过 tool_call 加载外部知识的 agent 架构，关键仅是找到相当于"compression 后处理"的 hook 点：

| Agent | Hook 点 | 适配方式 |
|-------|---------|----------|
| Hermes Agent | `ContextCompressor.compress()` 末尾 | 补丁或 post_compress 插件 |
| Claude Code | `/compact` 后处理 | 自定义 hook |
| Codex | 上下文管理中间件 | middleware |
| 其他 | 消息列表缩减路径 | 类似方案 |

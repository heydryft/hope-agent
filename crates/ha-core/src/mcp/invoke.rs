//! MCP 工具分发 trampoline（实现在 ha-mcp 的 `invoke` 模块）。
//!
//! 调用点：`tools::execution` 的 `mcp__` 逃逸口与 hooks runner 的
//! `McpTool` handler。工具级 approval 与沙箱在进入本层**之前**由 kernel
//! execution 通用包装完成——该契约随迁移保持不变。

use serde_json::Value;

/// 未接线 `Err`——与「MCP subsystem is not initialized」的既有报错同一
/// fail-explicit 语义（`is_mcp_tool_name` 门在前，正常流程只有配置了
/// MCP 却未接线的进程才会走到这）。
pub async fn call_tool(
    name: &str,
    args: &Value,
    ctx: &crate::tool_defs::ToolExecContext,
) -> anyhow::Result<String> {
    call_tool_with_format(
        name,
        args,
        ctx,
        crate::mcp_hooks::McpToolResultFormat::Conversation,
    )
    .await
}

/// Hook stdout is a machine protocol: structuredContent is the complete JSON
/// value, with the legacy text fallback only when that field is absent.
pub async fn call_tool_for_hook(
    name: &str,
    args: &Value,
    ctx: &crate::tool_defs::ToolExecContext,
) -> anyhow::Result<String> {
    call_tool_with_format(name, args, ctx, crate::mcp_hooks::McpToolResultFormat::Hook).await
}

async fn call_tool_with_format(
    name: &str,
    args: &Value,
    ctx: &crate::tool_defs::ToolExecContext,
    format: crate::mcp_hooks::McpToolResultFormat,
) -> anyhow::Result<String> {
    let Some(hooks) = crate::mcp_hooks::mcp_hooks() else {
        anyhow::bail!(
            "MCP subsystem is not wired in this process (ha_mcp::wire() missing); \
             tool '{}' cannot be dispatched",
            name
        );
    };
    (hooks.call_tool)(name, args, ctx, format).await
}

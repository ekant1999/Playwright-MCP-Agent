"""Error formatting utilities."""


def format_error(tool_name: str, error: Exception, suggestion: str = "") -> str:
    """Format an error message for MCP tool response."""
    error_msg = f"## ❌ Error in {tool_name}\n\n"
    error_msg += f"**Error:** {str(error)}\n\n"
    
    if suggestion:
        error_msg += f"**Suggestion:** {suggestion}\n"
    else:
        # Provide default suggestions based on error type
        error_str = str(error).lower()
        if "browser not launched" in error_str:
            error_msg += "**Suggestion:** Call browser_launch first.\n"
        elif "timeout" in error_str:
            error_msg += "**Suggestion:** The page took too long to load. Try increasing timeout or check your internet connection.\n"
        elif "not found" in error_str or "no element" in error_str:
            error_msg += "**Suggestion:** The selector may have changed or the element doesn't exist. Try a different selector.\n"
        elif "network" in error_str or "connection" in error_str:
            error_msg += "**Suggestion:** Check your internet connection and try again.\n"
        else:
            error_msg += "**Suggestion:** Please check the error message and try again with different parameters.\n"
    
    return error_msg

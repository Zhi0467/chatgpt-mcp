import subprocess
import time
from mcp.server.fastmcp import FastMCP
from chatgpt_mcp.chatgpt_automation import ChatGPTAutomation, check_chatgpt_access


def _read_screen_data() -> dict:
    """Read raw UI data from ChatGPT."""
    automation = ChatGPTAutomation()
    return automation.read_screen_content()


def _conversation_text_from_data(screen_data: dict) -> str:
    """Convert screen data into a single text snapshot."""
    if screen_data.get("status") != "success":
        return ""
    texts = screen_data.get("texts", [])
    return "\n".join(texts).strip()


def wait_for_response_completion(
    previous_snapshot: str = "",
    max_wait_time: int = 120,
    check_interval: float = 1.5,
    stable_cycles_required: int = 2,
) -> bool:
    """Wait until a new response appears and stabilizes.

    The original completion detector is brittle across app/localization changes.
    Instead, wait for conversation text to change from the pre-send snapshot and
    then remain stable for a few polling cycles without a typing cursor.
    """
    start_time = time.time()
    saw_change = previous_snapshot.strip() == ""
    last_snapshot = ""
    stable_cycles = 0

    while time.time() - start_time < max_wait_time:
        screen_data = _read_screen_data()
        current_snapshot = _conversation_text_from_data(screen_data)

        if not current_snapshot:
            time.sleep(check_interval)
            continue

        if not saw_change and current_snapshot != previous_snapshot:
            saw_change = True

        if not saw_change:
            time.sleep(check_interval)
            continue

        if "▍" in current_snapshot:
            stable_cycles = 0
        elif current_snapshot == last_snapshot:
            stable_cycles += 1
            if stable_cycles >= stable_cycles_required:
                return True
        else:
            stable_cycles = 1

        last_snapshot = current_snapshot
        time.sleep(check_interval)

    return False


def get_current_conversation_text() -> str:
    """Get the current conversation text from ChatGPT."""
    try:
        screen_data = _read_screen_data()

        if screen_data.get("status") == "success":
            current_content = _conversation_text_from_data(screen_data)

            # Clean up UI-only text fragments
            cleaned_result = current_content.strip()
            cleaned_result = (
                cleaned_result
                .replace("Regenerate", "")
                .replace("Continue generating", "")
                .replace("Edit prompt", "")
                .replace("Copy", "")
                .replace("▍", "")
                .strip()
            )

            return cleaned_result if cleaned_result else "No response received from ChatGPT."
        return "Failed to read ChatGPT screen."

    except Exception as e:
        return f"Error reading conversation: {str(e)}"


async def get_chatgpt_response(previous_snapshot: str = "") -> str:
    """Get the latest response from ChatGPT after sending a message.
    
    Returns:
        ChatGPT's latest response text
    """
    try:
        if wait_for_response_completion(previous_snapshot=previous_snapshot):
            return get_current_conversation_text()
        return "Timeout: ChatGPT response did not complete within the time limit."
        
    except Exception as e:
        raise Exception(f"Failed to get response from ChatGPT: {str(e)}")


async def ask_chatgpt(prompt: str) -> str:
    """Send a prompt to ChatGPT and return the response.
    
    Args:
        prompt: The text to send to ChatGPT
    
    Returns:
        ChatGPT's response
    """
    await check_chatgpt_access()
    
    try:
        # Snapshot before send so polling can detect the new response.
        before_snapshot = get_current_conversation_text()

        # 프롬프트에서 개행 문자 제거 및 더블쿼츠를 싱글쿼츠로 변경
        cleaned_prompt = prompt.replace('\n', ' ').replace('\r', ' ').replace('"', "'").strip()
        
        # Activate ChatGPT and send message using keystroke
        automation = ChatGPTAutomation()
        automation.activate_chatgpt()
        automation.send_message_with_keystroke(cleaned_prompt)
        
        # Get the response
        response = await get_chatgpt_response(previous_snapshot=before_snapshot)
        return response
        
    except Exception as e:
        raise Exception(f"Failed to send message to ChatGPT: {str(e)}")


async def new_chatgpt_chat() -> str:
    """Start a new chat conversation in ChatGPT.
    
    Returns:
        Success message or error
    """
    await check_chatgpt_access()
    
    try:
        automation = ChatGPTAutomation()
        result = automation.new_chat()
        
        if isinstance(result, tuple):
            success, method = result
            if success:
                return f"Successfully opened a new ChatGPT chat window using: {method}"
            else:
                return f"Failed to open a new chat window. Last tried method: {method}"
        else:
            # 이전 버전과의 호환성
            if result:
                return "Successfully opened a new ChatGPT chat window."
            else:
                return "Failed to open a new chat window. Please check if ChatGPT window is in the foreground."
            
    except Exception as e:
        raise Exception(f"Failed to create new chat: {str(e)}")


def setup_mcp_tools(mcp: FastMCP):
    """MCP 도구들을 설정"""
    
    @mcp.tool()
    async def ask_chatgpt_tool(prompt: str) -> str:
        """Send a prompt to ChatGPT and return the response."""
        return await ask_chatgpt(prompt)

    @mcp.tool()
    async def get_chatgpt_response_tool() -> str:
        """Get the latest response from ChatGPT after sending a message."""
        return await get_chatgpt_response()

    @mcp.tool()
    async def new_chatgpt_chat_tool() -> str:
        """Start a new chat conversation in ChatGPT."""
        return await new_chatgpt_chat()

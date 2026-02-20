import subprocess
import time
import re
from dataclasses import dataclass
from typing import Optional
from mcp.server.fastmcp import FastMCP
from chatgpt_mcp.chatgpt_automation import ChatGPTAutomation, check_chatgpt_access


DEFAULT_MAX_WAIT_TIME = 1800
TRANSIENT_UI_LINES = {
    "regenerate",
    "continue generating",
    "edit prompt",
    "copy",
    "thinking",
    "thinking...",
    "thinking…",
    "analyzing",
    "analyzing...",
    "searching",
    "searching...",
    "drafting",
    "working",
}
READINESS_PROBE_PATTERNS = (
    r"\breply with exactly\b",
    r"\banswer with exactly\b",
    r"\banswer with one word\b",
    r"\bone word:\s*(ready|working|ok|okay|mcp_ok)\b",
    r"\bmcp_ok\b",
)
READINESS_PROBE_MAX_CHARS = 180


@dataclass
class PendingPrompt:
    prompt: str
    previous_snapshot: str
    created_at: float


_pending_prompt: Optional[PendingPrompt] = None


def _set_pending_prompt(prompt: str, previous_snapshot: str) -> None:
    global _pending_prompt
    _pending_prompt = PendingPrompt(
        prompt=prompt,
        previous_snapshot=previous_snapshot,
        created_at=time.time(),
    )


def _get_pending_prompt() -> Optional[PendingPrompt]:
    return _pending_prompt


def _clear_pending_prompt() -> None:
    global _pending_prompt
    _pending_prompt = None


def _read_screen_data() -> dict:
    """Read raw UI data from ChatGPT."""
    automation = ChatGPTAutomation()
    return automation.read_screen_content()


def _conversation_text_from_data(screen_data: dict) -> str:
    """Convert screen data into a single text snapshot."""
    if screen_data.get("status") != "success":
        return ""
    texts = screen_data.get("texts", [])
    raw_snapshot = "\n".join(str(text) for text in texts).strip()
    return _clean_snapshot_text(raw_snapshot)


def _read_current_snapshot() -> str:
    """Read and normalize the current ChatGPT conversation snapshot."""
    screen_data = _read_screen_data()
    return _conversation_text_from_data(screen_data)


def _is_transient_ui_line(line: str) -> bool:
    """Detect non-answer UI/status lines that should not trigger completion."""
    normalized = line.strip()
    if not normalized:
        return False

    lowered = normalized.lower()
    if lowered in TRANSIENT_UI_LINES:
        return True
    if normalized == "▍":
        return True
    if lowered.startswith("thought for ") or lowered.startswith("reasoned for "):
        return True
    if len(normalized) <= 140 and (lowered.endswith("...") or lowered.endswith("…")):
        if re.match(r"^(computing|calculating|deriving|checking|verifying|working|thinking|analyzing|searching|drafting)\b", lowered):
            return True
    return bool(re.match(r"^(thinking|analyzing|searching|drafting|working)\b", lowered)) and len(normalized) <= 80


def _clean_snapshot_text(snapshot: str) -> str:
    """Normalize UI snapshots by removing transient/status-only lines."""
    cleaned_lines = []
    for raw_line in snapshot.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _is_transient_ui_line(line):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def _is_readiness_probe_prompt(prompt: str) -> bool:
    """Detect non-task readiness probes that should not be sent to ChatGPT."""
    normalized = " ".join(prompt.lower().split())
    if not normalized:
        return False
    if len(normalized) > READINESS_PROBE_MAX_CHARS:
        return False
    return any(re.search(pattern, normalized) for pattern in READINESS_PROBE_PATTERNS)


def _normalize_for_match(text: str) -> str:
    """Normalize text for robust prompt/response echo matching."""
    return " ".join(str(text).strip().lower().split())


def _is_prompt_echo_response(response: str, prompt: str) -> bool:
    """Return True when current text still looks like prompt-only echo."""
    normalized_response = _normalize_for_match(response)
    normalized_prompt = _normalize_for_match(prompt)

    if not normalized_response or not normalized_prompt:
        return False
    if normalized_response == normalized_prompt:
        return True

    # Allow tiny wrappers around the prompt (for example quotes/prefixes).
    return normalized_prompt in normalized_response and len(normalized_response) <= len(normalized_prompt) + 24


def _resolve_post_send_baseline(before_snapshot: str, prompt: str, max_wait: float = 8.0, interval: float = 0.4) -> str:
    """Capture a reliable post-send baseline that includes the prompt text."""
    prompt_normalized = _normalize_for_match(prompt)
    latest_snapshot = ""
    deadline = time.time() + max_wait

    while time.time() < deadline:
        snapshot = _read_current_snapshot()
        if snapshot:
            latest_snapshot = snapshot
            if prompt_normalized and prompt_normalized in _normalize_for_match(snapshot):
                return snapshot
        time.sleep(interval)

    if latest_snapshot:
        return latest_snapshot
    if before_snapshot:
        return f"{before_snapshot}\n{prompt}".strip()
    return prompt


def wait_for_response_completion(
    previous_snapshot: str = "",
    max_wait_time: int = DEFAULT_MAX_WAIT_TIME,
    check_interval: float = 1.5,
    stable_cycles_required: int = 2,
) -> tuple[bool, str]:
    """Wait until a new response appears and stabilizes.

    The original completion detector is brittle across app/localization changes.
    Instead, wait for conversation text to change from the pre-send snapshot and
    then remain stable for a few polling cycles without a typing cursor.
    """
    start_time = time.time()
    saw_change = previous_snapshot.strip() == ""
    last_snapshot = previous_snapshot
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
                return True, current_snapshot
        else:
            stable_cycles = 1

        last_snapshot = current_snapshot
        time.sleep(check_interval)

    return False, last_snapshot


def get_current_conversation_text() -> str:
    """Get the current conversation text from ChatGPT."""
    try:
        cleaned_result = _read_current_snapshot()
        if cleaned_result:
            return cleaned_result
        screen_data = _read_screen_data()
        if screen_data.get("status") == "success":
            return "No response received from ChatGPT."
        return "Failed to read ChatGPT screen."

    except Exception as e:
        return f"Error reading conversation: {str(e)}"


async def get_chatgpt_response(previous_snapshot: str = "", max_wait_time: int = DEFAULT_MAX_WAIT_TIME) -> str:
    """Get the latest response from ChatGPT after sending a message.
    
    Returns:
        ChatGPT's latest response text
    """
    try:
        pending = _get_pending_prompt()
        effective_snapshot = previous_snapshot

        if not effective_snapshot and pending:
            effective_snapshot = pending.previous_snapshot

        completed, _ = wait_for_response_completion(
            previous_snapshot=effective_snapshot,
            max_wait_time=max_wait_time,
        )
        if completed:
            response = get_current_conversation_text()
            if pending and _is_prompt_echo_response(response, pending.prompt):
                waited = int(time.time() - pending.created_at)
                return (
                    "ChatGPT response is still pending in the UI (prompt echo only). "
                    f"Elapsed wait: {waited}s. "
                    "Call get_chatgpt_response_tool again; do not send a new prompt yet."
                )
            _clear_pending_prompt()
            return response

        if pending:
            waited = int(time.time() - pending.created_at)
            return (
                "Timeout: ChatGPT response is still pending in the UI. "
                f"Elapsed wait: {waited}s. "
                "Call get_chatgpt_response_tool again; do not open a new chat yet."
            )

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

    pending = _get_pending_prompt()
    if pending:
        pending_age = int(time.time() - pending.created_at)
        return (
            "A previous ChatGPT response is still pending. "
            f"Elapsed wait: {pending_age}s. "
            "Call get_chatgpt_response_tool until completion before sending a new prompt."
        )
    
    try:
        # Snapshot before send so polling can detect the new response.
        before_snapshot = _read_current_snapshot()

        # 프롬프트에서 개행 문자 제거 및 더블쿼츠를 싱글쿼츠로 변경
        cleaned_prompt = prompt.replace('\n', ' ').replace('\r', ' ').replace('"', "'").strip()
        if _is_readiness_probe_prompt(cleaned_prompt):
            return (
                "Rejected prompt: looks like a readiness probe. "
                "Send one task-relevant prompt and wait via get_chatgpt_response_tool."
            )
        
        # Activate ChatGPT and send message using keystroke
        automation = ChatGPTAutomation()
        automation.activate_chatgpt()
        automation.send_message_with_keystroke(cleaned_prompt)

        # Baseline after send prevents false completion on prompt-echo snapshots.
        baseline_snapshot = _resolve_post_send_baseline(before_snapshot=before_snapshot, prompt=cleaned_prompt)
        _set_pending_prompt(cleaned_prompt, baseline_snapshot)
        
        # Get the response
        response = await get_chatgpt_response(previous_snapshot=baseline_snapshot)
        return response
        
    except Exception as e:
        raise Exception(f"Failed to send message to ChatGPT: {str(e)}")


async def new_chatgpt_chat() -> str:
    """Start a new chat conversation in ChatGPT.
    
    Returns:
        Success message or error
    """
    await check_chatgpt_access()

    pending = _get_pending_prompt()
    if pending:
        pending_age = int(time.time() - pending.created_at)
        return (
            "Cannot open a new chat: previous ChatGPT response is still pending. "
            f"Elapsed wait: {pending_age}s. "
            "Call get_chatgpt_response_tool until completion first."
        )
    
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

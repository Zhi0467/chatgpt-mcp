import subprocess
import time
import re
from dataclasses import dataclass
from typing import Optional
from mcp.server.fastmcp import FastMCP
from chatgpt_mcp.chatgpt_automation import ChatGPTAutomation, check_chatgpt_access


# Keep polling up to 40 minutes so long-running ChatGPT responses can be captured.
DEFAULT_MAX_WAIT_TIME = 2400
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
TRANSIENT_UI_SUBSTRINGS = (
    "network connection lost",
    "attempting to reconnect",
    "the request timed out",
    "something went wrong",
    "an error occurred",
)
TERMINAL_UI_FAILURE_SUBSTRINGS = (
    "the request timed out",
    "response failed",
)
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


def _raw_conversation_text_from_data(screen_data: dict) -> str:
    """Convert screen data into raw unfiltered text snapshot."""
    if screen_data.get("status") != "success":
        return ""
    texts = screen_data.get("texts", [])
    return "\n".join(str(text) for text in texts).strip()


def _read_current_snapshot() -> str:
    """Read and normalize the current ChatGPT conversation snapshot."""
    screen_data = _read_screen_data()
    return _conversation_text_from_data(screen_data)


def _read_current_raw_snapshot() -> str:
    """Read the current raw (unfiltered) ChatGPT conversation snapshot."""
    screen_data = _read_screen_data()
    return _raw_conversation_text_from_data(screen_data)


def _is_transient_ui_line(line: str) -> bool:
    """Detect non-answer UI/status lines that should not trigger completion."""
    normalized = line.strip()
    if not normalized:
        return False

    if normalized.replace("￼", "").strip() == "":
        return True

    lowered = normalized.lower()
    if lowered in TRANSIENT_UI_LINES:
        return True
    if any(fragment in lowered for fragment in TRANSIENT_UI_SUBSTRINGS):
        return True
    if normalized == "▍":
        return True
    if lowered.startswith("thought for ") or lowered.startswith("reasoned for "):
        return True
    if len(normalized) <= 120 and re.match(r"^(https?://|www\.)\S+$", lowered):
        # URL-only snippets can appear as interim retrieval progress before the final answer.
        return True
    if len(normalized) <= 120 and re.match(r"^[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s]*)?$", lowered):
        # Domain-only lines are often transient link previews, not completed answers.
        return True
    if len(normalized) <= 180 and (lowered.endswith("...") or lowered.endswith("…")):
        # Generic progress one-liners often start with a gerund (e.g., "Exploring ...").
        if re.match(r"^[a-z]+ing\b", lowered):
            return True
    if len(normalized) <= 100 and re.match(r"^[a-z]+ing\b", lowered):
        # Short gerund-only status line without sentence punctuation.
        if not re.search(r"[.!?=:]", normalized):
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


def _is_prompt_line(line: str, prompt: str) -> bool:
    """Return True when a line is effectively just the sent prompt."""
    line_norm = _normalize_for_match(line)
    prompt_norm = _normalize_for_match(prompt)
    if not line_norm or not prompt_norm:
        return False
    if line_norm == prompt_norm:
        return True

    prompt_prefixes = ("prompt: ", "user: ", "you: ")
    for prefix in prompt_prefixes:
        if line_norm == f"{prefix}{prompt_norm}":
            return True
    return False


def _strip_inline_prompt_prefix(response: str, prompt: str) -> str:
    """Strip a leading prompt prefix when prompt and answer share one line."""
    if not response or not prompt:
        return response

    trimmed = response.lstrip()
    prompt_variants = [prompt, " ".join(prompt.split())]
    labeled_prefixes = ("", "Prompt: ", "User: ", "You: ", "prompt: ", "user: ", "you: ")

    for variant in prompt_variants:
        candidate = variant.strip()
        if not candidate:
            continue
        for label in labeled_prefixes:
            prefix = f"{label}{candidate}"
            if trimmed.startswith(prefix):
                return trimmed[len(prefix) :].lstrip(" \n\r\t:-")

    words = [re.escape(token) for token in prompt.split()]
    if len(words) >= 4:
        fuzzy_pattern = r"^\s*(?:prompt:\s*|user:\s*|you:\s*)?" + r"\s+".join(words)
        fuzzy_match = re.match(fuzzy_pattern, response, flags=re.IGNORECASE)
        if fuzzy_match:
            return response[fuzzy_match.end() :].lstrip(" \n\r\t:-")

    return response


def _remove_prompt_echo_artifacts(response: str, prompt: str) -> str:
    """Strip prompt-only lines and transient UI noise from a response snapshot."""
    prefix_trimmed = _strip_inline_prompt_prefix(response, prompt)
    cleaned = _clean_snapshot_text(prefix_trimmed)
    if not cleaned:
        return ""

    kept_lines = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _is_prompt_line(line, prompt):
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines).strip()


def _extract_post_prompt_snapshot(snapshot: str, prompt: str) -> tuple[bool, str]:
    """Return text that appears after the latest visible instance of the sent prompt."""
    if not snapshot or not prompt:
        return False, ""

    prompt_variants = [prompt, " ".join(prompt.split())]
    for variant in prompt_variants:
        if not variant:
            continue
        index = snapshot.rfind(variant)
        if index != -1:
            return True, snapshot[index + len(variant):].strip()

    lines = [line.strip() for line in snapshot.splitlines() if line.strip()]
    if not lines:
        return False, ""

    prompt_norm = _normalize_for_match(prompt)
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        if _is_prompt_line(line, prompt):
            return True, "\n".join(lines[idx + 1 :]).strip()
        line_norm = _normalize_for_match(line)
        if prompt_norm and prompt_norm in line_norm and len(line_norm) <= len(prompt_norm) + 48:
            return True, "\n".join(lines[idx + 1 :]).strip()

    return False, ""


def _detect_terminal_ui_failure(snapshot: str) -> Optional[str]:
    """Detect terminal request failures shown in ChatGPT UI."""
    lowered = snapshot.lower()
    for token in TERMINAL_UI_FAILURE_SUBSTRINGS:
        if token in lowered:
            return token
    return None


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


def _snapshot_contains_prompt(snapshot: str, prompt: str) -> bool:
    """Return True when snapshot text contains the sent prompt."""
    normalized_snapshot = _normalize_for_match(snapshot)
    normalized_prompt = _normalize_for_match(prompt)
    if not normalized_snapshot or not normalized_prompt:
        return False
    return normalized_prompt in normalized_snapshot


def _is_prompt_echo_response(response: str, prompt: str) -> bool:
    """Return True when current text still looks like prompt-only echo."""
    normalized_response = _normalize_for_match(response)
    normalized_prompt = _normalize_for_match(prompt)

    if not normalized_response or not normalized_prompt:
        return False
    if normalized_response == normalized_prompt:
        return True

    if normalized_prompt in normalized_response:
        suffix = normalized_response.replace(normalized_prompt, "", 1).strip(" :-")
        if suffix and _is_transient_ui_line(suffix):
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
    return before_snapshot


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
            raw_response = _read_current_raw_snapshot()
            response = get_current_conversation_text()
            if pending:
                if not _snapshot_contains_prompt(raw_response, pending.prompt):
                    waited = int(time.time() - pending.created_at)
                    if waited >= 60:
                        _clear_pending_prompt()
                        return (
                            "ChatGPT snapshot does not include the sent prompt after waiting; "
                            "this suggests the message may not have been submitted. "
                            "Pending prompt was cleared; resend the prompt."
                        )
                    return (
                        "ChatGPT response is still pending in the UI (sent prompt not visible yet). "
                        f"Elapsed wait: {waited}s. "
                        "Call get_chatgpt_response_tool again; do not send a new prompt yet."
                    )
                prompt_found, post_prompt_snapshot = _extract_post_prompt_snapshot(raw_response, pending.prompt)
                scoped_snapshot = post_prompt_snapshot if prompt_found else raw_response
                response_source = scoped_snapshot if prompt_found else (scoped_snapshot or response)
                response = _remove_prompt_echo_artifacts(response_source, pending.prompt)
                if not response or _is_prompt_echo_response(response, pending.prompt):
                    terminal_failure = _detect_terminal_ui_failure(scoped_snapshot)
                    if terminal_failure:
                        _clear_pending_prompt()
                        return (
                            "ChatGPT reported a terminal UI failure before completing the answer "
                            f"({terminal_failure}). Pending prompt was cleared; resend the prompt."
                        )
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
        if not _snapshot_contains_prompt(baseline_snapshot, cleaned_prompt):
            return (
                "Failed to confirm the prompt appeared in ChatGPT UI after send. "
                "Please retry once ChatGPT input focus is stable."
            )
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

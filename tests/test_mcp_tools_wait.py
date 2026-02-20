import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from chatgpt_mcp import mcp_tools


class WaitForResponseCompletionTests(unittest.TestCase):
    def tearDown(self) -> None:
        mcp_tools._clear_pending_prompt()

    def test_wait_handles_ten_minute_delay_then_completes(self) -> None:
        baseline = "user: analyze architecture"
        final_snapshot = f"{baseline}\nassistant: long-form response complete"
        polls_before_change = int(600 / 1.5)
        poll_count = {"value": 0}
        now = {"value": 0.0}

        def fake_read_screen_data():
            poll_count["value"] += 1
            if poll_count["value"] <= polls_before_change:
                snapshot = baseline
            elif poll_count["value"] == polls_before_change + 1:
                snapshot = f"{baseline}\nassistant: drafting ▍"
            else:
                snapshot = final_snapshot
            return {"status": "success", "texts": [snapshot]}

        def fake_text_from_data(screen_data):
            return screen_data["texts"][0]

        def fake_time():
            return now["value"]

        def fake_sleep(seconds):
            now["value"] += seconds

        with patch.object(mcp_tools, "_read_screen_data", side_effect=fake_read_screen_data), patch.object(
            mcp_tools, "_conversation_text_from_data", side_effect=fake_text_from_data
        ), patch.object(mcp_tools.time, "time", side_effect=fake_time), patch.object(
            mcp_tools.time, "sleep", side_effect=fake_sleep
        ):
            completed, snapshot = mcp_tools.wait_for_response_completion(
                previous_snapshot=baseline,
                max_wait_time=1200,
                check_interval=1.5,
                stable_cycles_required=2,
            )

        self.assertTrue(completed)
        self.assertEqual(snapshot, final_snapshot)
        self.assertGreaterEqual(now["value"], 600.0)

    def test_wait_times_out_when_snapshot_never_changes(self) -> None:
        baseline = "user: waiting"
        now = {"value": 0.0}

        def fake_read_screen_data():
            return {"status": "success", "texts": [baseline]}

        def fake_text_from_data(screen_data):
            return screen_data["texts"][0]

        def fake_time():
            return now["value"]

        def fake_sleep(seconds):
            now["value"] += seconds

        with patch.object(mcp_tools, "_read_screen_data", side_effect=fake_read_screen_data), patch.object(
            mcp_tools, "_conversation_text_from_data", side_effect=fake_text_from_data
        ), patch.object(mcp_tools.time, "time", side_effect=fake_time), patch.object(
            mcp_tools.time, "sleep", side_effect=fake_sleep
        ):
            completed, snapshot = mcp_tools.wait_for_response_completion(
                previous_snapshot=baseline,
                max_wait_time=15,
                check_interval=1.5,
                stable_cycles_required=2,
            )

        self.assertFalse(completed)
        self.assertEqual(snapshot, baseline)
        self.assertGreaterEqual(now["value"], 15.0)

    def test_wait_ignores_transient_thinking_and_waits_for_real_reply(self) -> None:
        baseline = "user: give a deep critique"
        final_snapshot = f"{baseline}\nassistant: complete critique with concrete checks"
        poll_count = {"value": 0}
        now = {"value": 0.0}

        def fake_read_screen_data():
            poll_count["value"] += 1
            if poll_count["value"] <= 2:
                snapshot = baseline
            elif poll_count["value"] <= 8:
                snapshot = f"{baseline}\nThinking"
            else:
                snapshot = final_snapshot
            return {"status": "success", "texts": [snapshot]}

        def fake_text_from_data(screen_data):
            return mcp_tools._clean_snapshot_text(screen_data["texts"][0])

        def fake_time():
            return now["value"]

        def fake_sleep(seconds):
            now["value"] += seconds

        with patch.object(mcp_tools, "_read_screen_data", side_effect=fake_read_screen_data), patch.object(
            mcp_tools, "_conversation_text_from_data", side_effect=fake_text_from_data
        ), patch.object(mcp_tools.time, "time", side_effect=fake_time), patch.object(
            mcp_tools.time, "sleep", side_effect=fake_sleep
        ):
            completed, snapshot = mcp_tools.wait_for_response_completion(
                previous_snapshot=baseline,
                max_wait_time=60,
                check_interval=1.5,
                stable_cycles_required=2,
            )

        self.assertTrue(completed)
        self.assertEqual(snapshot, final_snapshot)
        self.assertGreaterEqual(now["value"], 12.0)

    def test_wait_default_supports_very_long_delays(self) -> None:
        baseline = "user: perform deep architecture critique"
        final_snapshot = f"{baseline}\nassistant: full critique complete"
        polls_before_change = int(1700 / 1.5)
        poll_count = {"value": 0}
        now = {"value": 0.0}

        def fake_read_screen_data():
            poll_count["value"] += 1
            if poll_count["value"] <= polls_before_change:
                snapshot = baseline
            elif poll_count["value"] == polls_before_change + 1:
                snapshot = f"{baseline}\nassistant: still working ▍"
            else:
                snapshot = final_snapshot
            return {"status": "success", "texts": [snapshot]}

        def fake_text_from_data(screen_data):
            return screen_data["texts"][0]

        def fake_time():
            return now["value"]

        def fake_sleep(seconds):
            now["value"] += seconds

        with patch.object(mcp_tools, "_read_screen_data", side_effect=fake_read_screen_data), patch.object(
            mcp_tools, "_conversation_text_from_data", side_effect=fake_text_from_data
        ), patch.object(mcp_tools.time, "time", side_effect=fake_time), patch.object(
            mcp_tools.time, "sleep", side_effect=fake_sleep
        ):
            completed, snapshot = mcp_tools.wait_for_response_completion(
                previous_snapshot=baseline,
                max_wait_time=mcp_tools.DEFAULT_MAX_WAIT_TIME,
                check_interval=1.5,
                stable_cycles_required=2,
            )

        self.assertTrue(completed)
        self.assertEqual(snapshot, final_snapshot)
        self.assertGreaterEqual(now["value"], 1700.0)


class PendingGuardrailTests(unittest.TestCase):
    def tearDown(self) -> None:
        mcp_tools._clear_pending_prompt()

    def test_ask_blocks_when_previous_response_pending(self) -> None:
        mcp_tools._set_pending_prompt("old prompt", "snapshot")
        with patch.object(mcp_tools, "check_chatgpt_access", new=AsyncMock(return_value=True)):
            result = asyncio.run(mcp_tools.ask_chatgpt("new prompt"))
        self.assertIn("still pending", result)

    def test_new_chat_blocks_when_previous_response_pending(self) -> None:
        mcp_tools._set_pending_prompt("old prompt", "snapshot")
        with patch.object(mcp_tools, "check_chatgpt_access", new=AsyncMock(return_value=True)):
            result = asyncio.run(mcp_tools.new_chatgpt_chat())
        self.assertIn("Cannot open a new chat", result)

    def test_ask_rejects_readiness_probe_prompt(self) -> None:
        with patch.object(mcp_tools, "check_chatgpt_access", new=AsyncMock(return_value=True)):
            result = asyncio.run(mcp_tools.ask_chatgpt("Please reply with one word: ready"))
        self.assertIn("Rejected prompt", result)


class PromptEchoGuardTests(unittest.TestCase):
    def tearDown(self) -> None:
        mcp_tools._clear_pending_prompt()

    def test_get_response_keeps_pending_when_snapshot_is_prompt_echo(self) -> None:
        prompt = "Solve a hard math problem with proofs."
        mcp_tools._set_pending_prompt(prompt, "baseline")

        with patch.object(mcp_tools, "wait_for_response_completion", return_value=(True, prompt)), patch.object(
            mcp_tools, "get_current_conversation_text", return_value=prompt
        ):
            result = asyncio.run(mcp_tools.get_chatgpt_response(previous_snapshot="baseline"))

        self.assertIn("prompt echo only", result)
        self.assertIsNotNone(mcp_tools._get_pending_prompt())

    def test_get_response_clears_pending_when_non_echo_answer_arrives(self) -> None:
        prompt = "Solve a hard math problem with proofs."
        final_response = f"{prompt}\nassistant: Full derivation and final answer."
        mcp_tools._set_pending_prompt(prompt, "baseline")

        with patch.object(mcp_tools, "wait_for_response_completion", return_value=(True, final_response)), patch.object(
            mcp_tools, "get_current_conversation_text", return_value=final_response
        ):
            result = asyncio.run(mcp_tools.get_chatgpt_response(previous_snapshot="baseline"))

        self.assertEqual(result, final_response)
        self.assertIsNone(mcp_tools._get_pending_prompt())

    def test_get_response_keeps_pending_when_prompt_plus_transient_progress_arrives(self) -> None:
        prompt = "Solve a hard math problem with proofs."
        progress_only = f"{prompt}\nExploring complex logarithm expressions and arctan identities…"
        mcp_tools._set_pending_prompt(prompt, "baseline")

        with patch.object(mcp_tools, "wait_for_response_completion", return_value=(True, progress_only)), patch.object(
            mcp_tools, "get_current_conversation_text", return_value=progress_only
        ):
            result = asyncio.run(mcp_tools.get_chatgpt_response(previous_snapshot="baseline"))

        self.assertIn("prompt echo only", result)
        self.assertIsNotNone(mcp_tools._get_pending_prompt())


class SnapshotCleaningTests(unittest.TestCase):
    def test_clean_snapshot_removes_transient_lines(self) -> None:
        snapshot = "Prompt line\nThinking\nCopy\nassistant: real answer"
        cleaned = mcp_tools._clean_snapshot_text(snapshot)
        self.assertEqual(cleaned, "Prompt line\nassistant: real answer")

    def test_clean_snapshot_removes_short_progress_ellipsis_lines(self) -> None:
        snapshot = "Prompt line\nComputing symbolic expression with X, Y variables…\nassistant: final answer"
        cleaned = mcp_tools._clean_snapshot_text(snapshot)
        self.assertEqual(cleaned, "Prompt line\nassistant: final answer")

    def test_clean_snapshot_removes_generic_gerund_ellipsis_progress_line(self) -> None:
        snapshot = "Prompt line\nExploring complex logarithm expressions and arctan identities…\nassistant: final answer"
        cleaned = mcp_tools._clean_snapshot_text(snapshot)
        self.assertEqual(cleaned, "Prompt line\nassistant: final answer")

    def test_is_prompt_echo_response_handles_small_wrapper(self) -> None:
        self.assertTrue(mcp_tools._is_prompt_echo_response("Prompt: solve this.", "solve this."))
        self.assertFalse(
            mcp_tools._is_prompt_echo_response("solve this.\nassistant: detailed answer", "solve this.")
        )


if __name__ == "__main__":
    unittest.main()

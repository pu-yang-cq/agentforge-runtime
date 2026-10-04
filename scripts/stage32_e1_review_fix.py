from pathlib import Path

path = Path("src/agentforge/application/run_manager.py")
text = path.read_text()
old = '''                except BusinessProgressionBlockedError as blocked:
                    run.failure_reason = blocked.failure_reason
                    await recorder.record_model_result_discarded_and_fail_run(
                        invocation,
                        run,
                        blocked.failure_reason,
                        expected_generation=expected_generation,
                    )
                    raise RunExecutionFailedError(run.failure_reason) from blocked
'''
new = '''                except BusinessProgressionBlockedError as blocked:
                    if blocked.code == "CANCEL_REQUESTED":
                        # Permission rejection was only an in-memory candidate
                        # business consequence. Cancellation won the Run-row
                        # serialization race, so discard that candidate rather
                        # than persist FAILED.
                        run.status = RunStatus.RUNNING
                        run.failure_reason = None
                        run.completed_at = None
                        run.request_cancel()
                        await recorder.record_model_result_discarded_and_cancel_run(
                            invocation,
                            run,
                            blocked.failure_reason,
                            expected_generation=expected_generation,
                        )
                        return None
                    run.failure_reason = blocked.failure_reason
                    await recorder.record_model_result_discarded_and_fail_run(
                        invocation,
                        run,
                        blocked.failure_reason,
                        expected_generation=expected_generation,
                    )
                    raise RunExecutionFailedError(run.failure_reason) from blocked
'''
if text.count(old) != 1:
    raise SystemExit(f"expected one denied cancellation anchor, found {text.count(old)}")
path.write_text(text.replace(old, new))

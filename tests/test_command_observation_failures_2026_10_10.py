"""Observation failures must not become instructions to terminate healthy work."""

from steward_cockpit import code_jobs as cj

from tests.test_command_supervision_2026_10_10 import command_env, _completed


_SUCCESS_CHILD = "import time; print('started', flush=True); time.sleep(0.25); print('success', flush=True)"


def _live_command(updates):
    command = updates.get("command")
    return isinstance(command, dict) and bool(command.get("pid"))


def _successful_command(env, thread, outcome):
    result = _completed(thread, outcome)
    assert result.returncode == 0
    assert "success" in result.stdout
    assert env.observations
    command = env.observations[-1]
    assert command["state"] == "completed"
    return command


def test_transient_observation_save_errors_do_not_kill_successful_child(command_env, monkeypatch):
    env = command_env
    original_transition = cj._transition
    failures = []

    def fail_first_two_command_updates(cdir, jobid, expected, **updates):
        if _live_command(updates) and len(failures) < 2:
            message = f"injected observation save failure {len(failures) + 1}"
            failures.append(message)
            raise OSError(message)
        return original_transition(cdir, jobid, expected, **updates)

    monkeypatch.setattr(cj, "_transition", fail_first_two_command_updates)
    thread, outcome = env.start(_SUCCESS_CHILD)
    command = _successful_command(env, thread, outcome)

    assert len(failures) == 2
    observation_error = command["last_observation_error"]
    assert failures[-1] in observation_error["text"]
    assert observation_error["at"] > 0


def test_strict_stop_read_failure_is_unknown_and_does_not_cancel_job(command_env, monkeypatch):
    env = command_env
    original_read = cj.read_jobs
    reads = []
    failed = False

    def fail_one_strict_read(*args, **kwargs):
        nonlocal failed
        reads.append(kwargs.get("strict"))
        if kwargs.get("strict") is True and not failed:
            failed = True
            raise PermissionError("injected registry read denied")
        return original_read(*args, **kwargs)

    monkeypatch.setattr(cj, "read_jobs", fail_one_strict_read)

    assert cj._stop_asked(env.job) is False
    assert failed
    assert reads == [True]

    thread, outcome = env.start(_SUCCESS_CHILD)
    _successful_command(env, thread, outcome)


def test_cleanup_not_yet_complete_is_retried_without_losing_zero_exit(command_env, monkeypatch):
    env = command_env
    original_popen = cj._popen_contained
    attempts = []

    def capture_with_delayed_cleanup(*args, **kwargs):
        run = original_popen(*args, **kwargs)
        run_type = type(run)
        original_end = run_type.end

        def end_once_unconfirmed(self, *end_args, **end_kwargs):
            if self is run:
                attempts.append("cleanup")
                if len(attempts) == 1:
                    # Simulate an unconfirmed cleanup result without touching the child.
                    return False
            return original_end(self, *end_args, **end_kwargs)

        monkeypatch.setattr(run_type, "end", end_once_unconfirmed)
        return run

    monkeypatch.setattr(cj, "_popen_contained", capture_with_delayed_cleanup)
    thread, outcome = env.start(_SUCCESS_CHILD)
    command = _successful_command(env, thread, outcome)

    assert len(attempts) >= 2
    assert not command.get("cleanup_detail")


def test_refused_observation_update_with_same_attempt_is_not_a_stop(command_env, monkeypatch):
    env = command_env
    original_transition = cj._transition
    refused = False

    def refuse_one_command_update(cdir, jobid, expected, **updates):
        nonlocal refused
        if _live_command(updates) and not refused:
            refused = True
            # The saved attempt/status remain unchanged; only observation was lost.
            return None
        return original_transition(cdir, jobid, expected, **updates)

    monkeypatch.setattr(cj, "_transition", refuse_one_command_update)
    thread, outcome = env.start(_SUCCESS_CHILD)
    command = _successful_command(env, thread, outcome)

    assert refused
    assert command["last_observation_error"]["text"]
    assert command["last_observation_error"]["at"] > 0

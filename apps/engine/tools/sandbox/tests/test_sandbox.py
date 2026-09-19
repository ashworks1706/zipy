"""The sandbox: the container it asks for, the names it refuses, and what it hands back."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from engine.core.types import (
    ChannelRef,
    MemberRef,
    OrgId,
    RequestContext,
    Role,
    SandboxError,
    SandboxRequest,
    WorkspaceRef,
    session_name,
    workspace_path,
)
from engine.tools.sandbox.container import (
    MARKER,
    OWNED,
    WORKSPACE,
    Completed,
    ContainerSandbox,
    clip,
    owner,
)
from engine.tools.sandbox.schemas import RunParams, SandboxSettings
from engine.tools.sandbox.tool import SandboxTool


class Runtime:
    """A stand-in container runtime that records its calls and answers from a script."""

    def __init__(self, answers=None, fail=None):
        self.calls = []
        self.stdin = []
        self._answers = answers or {}
        self._fail = fail

    async def __call__(self, args, stdin, timeout):
        self.calls.append(list(args))
        self.stdin.append(stdin)
        if self._fail is not None:
            raise self._fail
        for key, answer in self._answers.items():
            if key in " ".join(args):
                return answer
        return Completed(code=0, stdout="", stderr="")

    def called(self, needle):
        """Every call whose arguments carry the text."""
        return [call for call in self.calls if needle in " ".join(call)]


def ctx(org="org-1", member="u1"):
    return RequestContext(
        org_id=OrgId(org),
        channel=ChannelRef(WorkspaceRef("discord", "g1"), "c1"),
        member=MemberRef("discord", member),
        role=Role.OFFICER,
        display_name="Ash",
        request_id="req-1",
        received_at=datetime.now(UTC),
    )


def settings(**over):
    return SandboxSettings(**over)


def sandbox(runtime, **over):
    return ContainerSandbox(settings(**over), runner=runtime)


def started(when):
    return when.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- names


def test_a_session_name_takes_letters_digits_hyphen_and_underscore():
    assert session_name("  build_1-a ") == "build_1-a"
    for bad in ("", " ", "a" * 49, "has space", "semi;colon", "../x"):
        with pytest.raises(SandboxError):
            session_name(bad)


def test_a_workspace_name_cannot_leave_the_workspace():
    assert workspace_path("report.pdf") == "report.pdf"
    for bad in ("../etc/passwd", "a/b", ".hidden", "a..b", "", "x" * 65):
        with pytest.raises(SandboxError):
            workspace_path(bad)


def test_two_members_of_one_org_never_share_a_container():
    assert owner(OrgId("o"), MemberRef("discord", "u1")) != owner(
        OrgId("o"), MemberRef("discord", "u2")
    )


def test_two_orgs_never_share_a_container():
    member = MemberRef("discord", "u1")
    assert owner(OrgId("o-1"), member) != owner(OrgId("o-2"), member)


# ---------------------------------------------------------------- the container


@pytest.mark.anyio
async def test_a_one_off_command_runs_in_a_container_that_is_removed():
    runtime = Runtime()
    await sandbox(runtime).run(ctx(), SandboxRequest(command="echo hi"))
    args = runtime.calls[0]
    assert args[:3] == ["docker", "run", "--rm"]
    assert args[-3:] == ["sh", "-c", "echo hi"]


@pytest.mark.anyio
async def test_the_container_has_no_network_no_root_and_a_read_only_filesystem():
    runtime = Runtime()
    await sandbox(runtime).run(ctx(), SandboxRequest(command="echo hi"))
    sealed = " ".join(runtime.calls[0])
    assert "--network none" in sealed
    assert "--read-only" in sealed
    assert "--cap-drop ALL" in sealed
    assert "--security-opt no-new-privileges" in sealed
    assert "--user 65534:65534" in sealed


@pytest.mark.anyio
async def test_the_workspace_is_a_capped_tmpfs_that_cannot_execute():
    runtime = Runtime()
    await sandbox(runtime, workspace_mb=32).run(ctx(), SandboxRequest(command="echo hi"))
    sealed = " ".join(runtime.calls[0])
    assert f"{WORKSPACE}:rw,noexec,nosuid,size=32m" in sealed


@pytest.mark.anyio
async def test_memory_cpu_and_process_ceilings_reach_the_runtime():
    runtime = Runtime()
    await sandbox(runtime, memory="128m", cpus="0.5", pids=64).run(
        ctx(), SandboxRequest(command="echo hi")
    )
    sealed = " ".join(runtime.calls[0])
    assert "--memory 128m" in sealed
    assert "--cpus 0.5" in sealed
    assert "--pids-limit 64" in sealed


@pytest.mark.anyio
async def test_an_empty_command_is_refused_before_anything_runs():
    runtime = Runtime()
    with pytest.raises(SandboxError, match="empty"):
        await sandbox(runtime).run(ctx(), SandboxRequest(command="   "))
    assert runtime.calls == []


@pytest.mark.anyio
async def test_a_non_zero_exit_is_a_result_not_an_error():
    runtime = Runtime({"run --rm": Completed(code=2, stdout="", stderr="no such file")})
    out = await sandbox(runtime).run(ctx(), SandboxRequest(command="cat missing"))
    assert out.exit_code == 2
    assert out.stderr == "no such file"


@pytest.mark.anyio
async def test_long_output_keeps_the_head_and_the_tail():
    runtime = Runtime({"run --rm": Completed(code=0, stdout="a" * 100, stderr="")})
    out = await sandbox(runtime, max_output_chars=20).run(ctx(), SandboxRequest(command="yes"))
    assert out.stdout.startswith("a" * 10)
    assert out.stdout.endswith("a" * 10)
    assert "80 characters cut" in out.stdout


def test_clip_leaves_text_within_the_limit_alone():
    assert clip("short", 100) == "short"
    assert clip("short", 0) == "short"


@pytest.mark.anyio
async def test_a_runtime_that_will_not_start_is_a_sandbox_error():
    runtime = Runtime(fail=OSError("no such binary"))
    with pytest.raises(SandboxError, match="did not start"):
        await sandbox(runtime).run(ctx(), SandboxRequest(command="echo hi"))


@pytest.mark.anyio
async def test_a_command_past_its_budget_is_a_sandbox_error_naming_the_budget():
    runtime = Runtime(fail=TimeoutError())
    with pytest.raises(SandboxError, match="20.0 second budget"):
        await sandbox(runtime, timeout_secs=20.0).run(ctx(), SandboxRequest(command="sleep 60"))


# ---------------------------------------------------------------- sessions


@pytest.mark.anyio
async def test_a_session_starts_a_named_container_scoped_to_the_member():
    runtime = Runtime({"inspect --format {{.State.Running}}": Completed(0, "false", "")})
    await sandbox(runtime).run(ctx(), SandboxRequest(command="ls", session="build"))
    created = runtime.called("run --detach")[0]
    name = created[created.index("--name") + 1]
    assert name == f"{owner(OrgId('org-1'), MemberRef('discord', 'u1'))}build"
    assert f"--label {OWNED}" in " ".join(created).replace("--label ", "--label ")


@pytest.mark.anyio
async def test_a_running_session_is_resumed_rather_than_started_again():
    runtime = Runtime({"inspect --format {{.State.Running}}": Completed(0, "true", "")})
    await sandbox(runtime).run(ctx(), SandboxRequest(command="ls", session="build"))
    assert runtime.called("run --detach") == []
    assert runtime.called("exec")


@pytest.mark.anyio
async def test_every_session_command_notes_that_the_session_was_used():
    runtime = Runtime({"inspect --format {{.State.Running}}": Completed(0, "true", "")})
    await sandbox(runtime).run(ctx(), SandboxRequest(command="ls", session="build"))
    assert f"touch {MARKER}" in runtime.called("exec")[0][-1]


@pytest.mark.anyio
async def test_a_bad_session_name_is_refused_before_a_container_is_touched():
    runtime = Runtime()
    with pytest.raises(SandboxError):
        await sandbox(runtime).run(ctx(), SandboxRequest(command="ls", session="../escape"))
    assert runtime.calls == []


@pytest.mark.anyio
async def test_writing_a_file_sends_the_bytes_to_the_session_and_returns_its_path():
    runtime = Runtime({"inspect --format {{.State.Running}}": Completed(0, "true", "")})
    path = await sandbox(runtime).put(ctx(), "build", "notes.txt", b"hello")
    assert path == f"{WORKSPACE}/notes.txt"
    assert b"hello" in runtime.stdin


@pytest.mark.anyio
async def test_a_file_name_that_would_escape_the_workspace_is_refused():
    runtime = Runtime()
    with pytest.raises(SandboxError):
        await sandbox(runtime).put(ctx(), "build", "../../etc/passwd", b"x")
    assert runtime.calls == []


# ---------------------------------------------------------------- listing and reaping


def listing(names, org="org-1", member="u-1", started_at=None):
    at = started(started_at or datetime.now(UTC))
    lines = "\n".join(f"/{name}\t{org}\t{member}\t{at}" for name in names)
    return {
        "ps --quiet": Completed(0, "\n".join(f"id{n}" for n in range(len(names))), ""),
        "inspect --format {{.Name}}": Completed(0, lines, ""),
    }


@pytest.mark.anyio
async def test_the_runtime_is_the_session_registry_not_the_engine():
    runtime = Runtime(listing(["zipy-sb-aaaa-build"]))
    # A fresh sandbox object, holding no state, still sees the session.
    found = await sandbox(runtime).sessions()
    assert [s.name for s in found] == ["zipy-sb-aaaa-build"]
    assert found[0].org_id == "org-1"


@pytest.mark.anyio
async def test_no_live_session_asks_the_runtime_nothing_further():
    runtime = Runtime({"ps --quiet": Completed(0, "", "")})
    assert await sandbox(runtime).sessions() == []
    assert runtime.called("inspect") == []


@pytest.mark.anyio
async def test_sessions_can_be_narrowed_to_one_org():
    runtime = Runtime(listing(["zipy-sb-aaaa-build"], org="org-2"))
    assert await sandbox(runtime).sessions(OrgId("org-1")) == []
    assert len(await sandbox(runtime).sessions(OrgId("org-2"))) == 1


@pytest.mark.anyio
async def test_killing_a_session_removes_its_container():
    runtime = Runtime()
    assert await sandbox(runtime).kill("zipy-sb-aaaa-build") is True
    assert runtime.called("rm --force")[0][-1] == "zipy-sb-aaaa-build"


@pytest.mark.anyio
async def test_reaping_removes_only_the_sessions_past_their_idle_budget():
    old = datetime.now(UTC) - timedelta(hours=2)
    answers = listing(["zipy-sb-aaaa-old"], started_at=old)
    runtime = Runtime(answers)
    gone = await sandbox(runtime, session_idle_secs=60.0).reap_idle()
    assert gone == ["zipy-sb-aaaa-old"]


@pytest.mark.anyio
async def test_a_session_used_recently_survives_the_reaper():
    answers = listing(["zipy-sb-aaaa-fresh"])
    runtime = Runtime(answers)
    assert await sandbox(runtime, session_idle_secs=900.0).reap_idle() == []


# ---------------------------------------------------------------- the tool


def test_the_sandbox_needs_no_connected_account():
    assert SandboxTool.provider == ""


def test_an_org_cannot_change_what_the_container_may_do():
    for key in ("runtime", "image", "memory", "cpus", "pids", "workspace_mb", "timeout_secs"):
        assert key in SandboxTool.locked, key
    assert "max_output_chars" not in SandboxTool.locked


def test_the_audit_entry_names_the_session_or_the_command():
    tool = SandboxTool(settings())
    assert tool.target("run", RunParams(command="ls", session="build")) == "build"
    assert tool.target("run", RunParams(command="wc -l notes.txt")) == "wc -l notes.txt"


@pytest.mark.anyio
async def test_the_tool_runs_the_command_and_hands_back_what_it_produced():
    runtime = Runtime({"run --rm": Completed(code=0, stdout="42\n", stderr="")})
    tool = SandboxTool(settings(), runner=runtime)
    result = await tool.execute(ctx(), "run", RunParams(command="echo 42"), None)
    assert result.stdout == "42\n"
    assert result.exit_code == 0
    assert result.session is None


# ---------------------------------------------------------------- a sub-agent's workspace


def sub(parent="call-1", **over):
    """A context as a sub-agent runs under."""
    return replace(ctx(**over), depth=1, parent=parent)


def test_a_sub_agent_does_not_get_the_parents_workspace():
    """Both would have named a session build and landed in one container."""
    assert owner(OrgId("org-1"), MemberRef("discord", "u1")) != owner(
        OrgId("org-1"), MemberRef("discord", "u1"), "call-1"
    )


def test_two_sub_agents_of_one_member_do_not_share_a_workspace():
    member = MemberRef("discord", "u1")
    assert owner(OrgId("o"), member, "call-1") != owner(OrgId("o"), member, "call-2")


def test_a_members_own_sessions_still_persist_across_their_requests():
    member = MemberRef("discord", "u1")
    assert owner(OrgId("o"), member) == owner(OrgId("o"), member, "")


@pytest.mark.anyio
async def test_a_sub_agent_session_is_named_for_its_delegation():
    runtime = Runtime({"inspect --format {{.State.Running}}": Completed(0, "false", "")})
    await sandbox(runtime).run(sub(), SandboxRequest(command="ls", session="build"))
    created = runtime.called("run --detach")[0]
    name = created[created.index("--name") + 1]
    assert name == f"{owner(OrgId('org-1'), MemberRef('discord', 'u1'), 'call-1')}build"


@pytest.mark.anyio
async def test_reaping_a_scope_removes_that_sub_agents_sessions_and_leaves_the_rest():
    mine = f"{owner(OrgId('org-1'), MemberRef('discord', 'u1'), 'call-1')}build"
    theirs = f"{owner(OrgId('org-1'), MemberRef('discord', 'u1'))}notes"
    runtime = Runtime(listing([mine, theirs]))

    gone = await sandbox(runtime).reap_scope(sub())

    assert gone == [mine]
    assert theirs not in gone

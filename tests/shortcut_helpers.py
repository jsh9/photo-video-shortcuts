"""
Helpers shared by every shortcut's tests: skipping when a tool is missing,
running commands, compiling the Swift helpers, and reading a generated
shortcut's actions (control flow, variables, script texts).
"""

import os
import shutil
import subprocess

import pytest


def need(condition, reason):
    """Skips a test locally when a tool or build is missing; fails in CI."""
    if not condition:
        if os.environ.get('CI'):
            pytest.fail(reason)

        pytest.skip(reason)


def run(cmd, **kw):
    return subprocess.run(
        [str(c) for c in cmd], capture_output=True, text=True, **kw
    )


def compile_swift(source, out):
    need(shutil.which('swiftc'), 'swiftc (Xcode) is needed')
    result = run(['swiftc', '-O', source, '-o', out])
    assert result.returncode == 0, result.stderr
    return out


# ---------------------------------------------------------------------------
# Generated shortcuts

CONTROL_FLOW = {
    'is.workflow.actions.conditional',
    'is.workflow.actions.repeat.each',
    'is.workflow.actions.repeat.count',
    'is.workflow.actions.choosefrommenu',
}
OBJ = '￼'  # where a variable sits inside a Shortcuts text field


def walk(actions):
    """(action, repeat depth) in order, checking control flow nests."""
    stack = []
    for action in actions:
        p = params(action)
        if ident(action) in CONTROL_FLOW:
            mode = p['WFControlFlowMode']
            if mode == 0:
                stack.append((p['GroupingIdentifier'], ident(action)))
            else:
                assert stack, f'{ident(action)} closes nothing'
                assert stack[-1] == (p['GroupingIdentifier'], ident(action))
                if mode == 2:
                    stack.pop()

        depth = sum(1 for _, kind in stack if kind.endswith('repeat.each'))
        yield action, depth

    assert not stack, f'unclosed blocks: {stack}'


def inside_if_on(actions, needle):
    """
    For each action, whether it runs inside the "then" branch of an If whose
    condition input mentions ``needle`` (e.g. a variable name or an output
    UUID), as (action, inside) pairs.
    """
    open_groups = []
    for action in actions:
        p = params(action)
        if ident(action) == 'is.workflow.actions.conditional':
            group, mode = p['GroupingIdentifier'], p['WFControlFlowMode']
            if mode == 0:
                open_groups.append((group, needle in repr(p['WFInput'])))
            elif mode == 1:
                open_groups[-1] = (group, False)  # the Otherwise branch
            else:
                open_groups.pop()

        yield action, any(inside for _, inside in open_groups)


def shell_scripts(actions, values):
    """The script text of each Run Shell Script action (the Mac shortcuts)."""
    return [
        render(params(a)['Script'], values)
        for a in actions
        if ident(a) == 'is.workflow.actions.runshellscript'
    ]


def ident(action):
    return action['WFWorkflowActionIdentifier']


def params(action):
    return action['WFWorkflowActionParameters']


def references(value):
    """Every variable or action output referenced inside a parameter."""
    if isinstance(value, dict):
        if value.get('Type') in ('ActionOutput', 'Variable'):
            yield value

        for v in value.values():
            yield from references(v)
    elif isinstance(value, list):
        for v in value:
            yield from references(v)


def render(field, values):
    """
    A text parameter as a string: each variable is replaced by
    values[OutputName or VariableName].
    """
    if isinstance(field, str):
        return field

    value = field['Value']
    text = value['string']
    attachments = sorted(
        value.get('attachmentsByRange', {}).items(),
        key=lambda kv: int(kv[0].strip('{}').split(',')[0]),
    )
    for _, ref in attachments:
        key = ref.get('OutputName') or ref.get('VariableName')
        text = text.replace(OBJ, str(values[key]), 1)

    return text

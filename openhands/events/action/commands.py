from dataclasses import dataclass, field
from typing import ClassVar

from openhands.core.schema import ActionType
from openhands.events.action.action import (
    Action,
    ActionConfirmationStatus,
    ActionSecurityRisk,
)


@dataclass
class CmdRunAction(Action):
    command: (
        str  # When `command` is empty, it will be used to print the current tmux window
    )
    is_input: bool = False  # if True, the command is an input to the running process
    thought: str = ''
    blocking: bool = False  # if True, the command will be run in a blocking manner, but a timeout must be set through _set_hard_timeout
    is_static: bool = False  # if True, runs the command in a separate process
    cwd: str | None = None  # current working directory, only used if is_static is True
    hidden: bool = (
        False  # if True, this command does not go through the LLM or event stream
    )
    action: str = ActionType.RUN
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN

    @property
    def message(self) -> str:
        return f'Running command: {self.command}'

    def __str__(self) -> str:
        ret = f'**CmdRunAction (source={self.source}, is_input={self.is_input})**\n'
        if self.thought:
            ret += f'THOUGHT: {self.thought}\n'
        ret += f'COMMAND:\n{self.command}'
        return ret

@dataclass
class ParallelCmdRunAction(Action):
    """Execute multiple commands in parallel."""
    commands: list[str] = field(default_factory=list)
    thought: str = ''
    max_concurrency: int = 10
    timeout_per_command: float | None = None
    cwd: str | None = None
    hidden: bool = False
    action: str = ActionType.RUN_PARALLEL
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN

    @property
    def message(self) -> str:
        commands_str = '; '.join(self.commands)
        return f'Running {len(self.commands)} commands in parallel: {commands_str}'

    def __str__(self) -> str:
        ret = f'**ParallelCmdRunAction (source={self.source}, {len(self.commands)} commands)**\n'
        if self.thought:
            ret += f'THOUGHT: {self.thought}\n'
        ret += 'COMMANDS:\n'
        for i, cmd in enumerate(self.commands, 1):
            ret += f'  {i}. {cmd}\n'
        return ret

@dataclass
class IPythonRunCellAction(Action):
    code: str
    thought: str = ''
    include_extra: bool = (
        True  # whether to include CWD & Python interpreter in the output
    )
    action: str = ActionType.RUN_IPYTHON
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN
    kernel_init_code: str = ''  # code to run in the kernel (if the kernel is restarted)

    def __str__(self) -> str:
        ret = '**IPythonRunCellAction**\n'
        if self.thought:
            ret += f'THOUGHT: {self.thought}\n'
        ret += f'CODE:\n{self.code}'
        return ret

    @property
    def message(self) -> str:
        return f'Running Python code interactively: {self.code}'

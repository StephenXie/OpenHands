import json
import re
from dataclasses import dataclass, field
from typing import Any, Self

from pydantic import BaseModel

from openhands.core.logger import openhands_logger as logger
from openhands.core.schema import ObservationType
from openhands.events.observation.observation import Observation

CMD_OUTPUT_PS1_BEGIN = '\n###PS1JSON###\n'
CMD_OUTPUT_PS1_END = '\n###PS1END###'
CMD_OUTPUT_METADATA_PS1_REGEX = re.compile(
    f'^{CMD_OUTPUT_PS1_BEGIN.strip()}(.*?){CMD_OUTPUT_PS1_END.strip()}',
    re.DOTALL | re.MULTILINE,
)

# Default max size for command output content
# to prevent too large observations from being saved in the stream
# This matches the default max_message_chars in LLMConfig
MAX_CMD_OUTPUT_SIZE: int = 30000


class CmdOutputMetadata(BaseModel):
    """Additional metadata captured from PS1"""

    exit_code: int = -1
    pid: int = -1
    username: str | None = None
    hostname: str | None = None
    working_dir: str | None = None
    py_interpreter_path: str | None = None
    prefix: str = ''  # Prefix to add to command output
    suffix: str = ''  # Suffix to add to command output

    @classmethod
    def to_ps1_prompt(cls) -> str:
        """Convert the required metadata into a PS1 prompt."""
        prompt = CMD_OUTPUT_PS1_BEGIN
        json_str = json.dumps(
            {
                'pid': '$!',
                'exit_code': '$?',
                'username': r'\u',
                'hostname': r'\h',
                'working_dir': r'$(pwd)',
                'py_interpreter_path': r'$(which python 2>/dev/null || echo "")',
            },
            indent=2,
        )
        # Make sure we escape double quotes in the JSON string
        # So that PS1 will keep them as part of the output
        prompt += json_str.replace('"', r'\"')
        prompt += CMD_OUTPUT_PS1_END + '\n'  # Ensure there's a newline at the end
        return prompt

    @classmethod
    def matches_ps1_metadata(cls, string: str) -> list[re.Match[str]]:
        matches = []
        for match in CMD_OUTPUT_METADATA_PS1_REGEX.finditer(string):
            try:
                json.loads(match.group(1).strip())  # Try to parse as JSON
                matches.append(match)
            except json.JSONDecodeError:
                logger.warning(
                    f'Failed to parse PS1 metadata: {match.group(1)}. Skipping.',
                    exc_info=True,
                )
                continue  # Skip if not valid JSON
        return matches

    @classmethod
    def from_ps1_match(cls, match: re.Match[str]) -> Self:
        """Extract the required metadata from a PS1 prompt."""
        metadata = json.loads(match.group(1))
        # Create a copy of metadata to avoid modifying the original
        processed = metadata.copy()
        # Convert numeric fields
        if 'pid' in metadata:
            try:
                processed['pid'] = int(float(str(metadata['pid'])))
            except (ValueError, TypeError):
                processed['pid'] = -1
        if 'exit_code' in metadata:
            try:
                processed['exit_code'] = int(float(str(metadata['exit_code'])))
            except (ValueError, TypeError):
                logger.warning(
                    f'Failed to parse exit code: {metadata["exit_code"]}. Setting to -1.'
                )
                processed['exit_code'] = -1
        return cls(**processed)


@dataclass
class CmdOutputObservation(Observation):
    """This data class represents the output of a command."""

    command: str
    observation: str = ObservationType.RUN
    # Additional metadata captured from PS1
    metadata: CmdOutputMetadata = field(default_factory=CmdOutputMetadata)
    # Whether the command output should be hidden from the user
    hidden: bool = False

    def __init__(
        self,
        content: str,
        command: str,
        observation: str = ObservationType.RUN,
        metadata: dict[str, Any] | CmdOutputMetadata | None = None,
        hidden: bool = False,
        **kwargs: Any,
    ) -> None:
        # Truncate content before passing it to parent
        # Hidden commands don't go through LLM/event stream, so no need to truncate
        truncate = not hidden
        if truncate:
            content = self._maybe_truncate(content)

        super().__init__(content)

        self.command = command
        self.observation = observation
        self.hidden = hidden
        if isinstance(metadata, dict):
            self.metadata = CmdOutputMetadata(**metadata)
        else:
            self.metadata = metadata or CmdOutputMetadata()

        # Handle legacy attribute
        if 'exit_code' in kwargs:
            self.metadata.exit_code = kwargs['exit_code']
        if 'command_id' in kwargs:
            self.metadata.pid = kwargs['command_id']

    @staticmethod
    def _maybe_truncate(content: str, max_size: int = MAX_CMD_OUTPUT_SIZE) -> str:
        """Truncate the content if it's too large.

        This helps avoid storing unnecessarily large content in the event stream.

        Args:
            content: The content to truncate
            max_size: Maximum size before truncation. Defaults to MAX_CMD_OUTPUT_SIZE.

        Returns:
            Original content if not too large, or truncated content otherwise
        """
        if len(content) <= max_size:
            return content

        # Truncate the middle and include a message about it
        half = max_size // 2
        original_length = len(content)
        truncated = (
            content[:half]
            + '\n[... Observation truncated due to length ...]\n'
            + content[-half:]
        )
        logger.debug(
            f'Truncated large command output: {original_length} -> {len(truncated)} chars'
        )
        return truncated

    @property
    def command_id(self) -> int:
        return self.metadata.pid

    @property
    def exit_code(self) -> int:
        return self.metadata.exit_code

    @property
    def error(self) -> bool:
        return self.exit_code != 0

    @property
    def message(self) -> str:
        return f'Command `{self.command}` executed with exit code {self.exit_code}.'

    @property
    def success(self) -> bool:
        return not self.error

    def __str__(self) -> str:
        return (
            f'**CmdOutputObservation (source={self.source}, exit code={self.exit_code}, '
            f'metadata={json.dumps(self.metadata.model_dump(), indent=2)})**\n'
            '--BEGIN AGENT OBSERVATION--\n'
            f'{self.to_agent_observation()}\n'
            '--END AGENT OBSERVATION--'
        )

    def to_agent_observation(self) -> str:
        ret = f'{self.metadata.prefix}{self.content}{self.metadata.suffix}'
        if self.metadata.working_dir:
            ret += f'\n[Current working directory: {self.metadata.working_dir}]'
        if self.metadata.py_interpreter_path:
            ret += f'\n[Python interpreter: {self.metadata.py_interpreter_path}]'
        if self.metadata.exit_code != -1:
            ret += f'\n[Command finished with exit code {self.metadata.exit_code}]'
        return ret

@dataclass
class ParallelCmdResult:
    """Result of a single command in a parallel execution."""
    command: str
    content: str
    metadata: CmdOutputMetadata = field(default_factory=CmdOutputMetadata)

    def __init__(
        self,
        command: str,
        content: str,
        metadata: dict[str, Any] | CmdOutputMetadata | None = None,
        **kwargs: Any,
    ) -> None:
        self.command = command
        self.content = content
        if isinstance(metadata, dict):
            self.metadata = CmdOutputMetadata(**metadata)
        else:
            self.metadata = metadata or CmdOutputMetadata()

        if 'exit_code' in kwargs:
            self.metadata.exit_code = kwargs['exit_code']
        if 'pid' in kwargs:
            self.metadata.pid = kwargs['pid']

    @property
    def exit_code(self) -> int:
        return self.metadata.exit_code

    @property
    def error(self) -> bool:
        return self.exit_code != 0

    @property
    def success(self) -> bool:
        return not self.error

    def to_dict(self) -> dict[str, Any]:
        return {
            'command': self.command,
            'content': self.content,
            'metadata': self.metadata.model_dump(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'ParallelCmdResult':
        return cls(
            command=data['command'],
            content=data['content'],
            metadata=data.get('metadata'),
        )


@dataclass
class ParallelCmdOutputObservation(Observation):
    """Output of multiple commands run in parallel."""

    results: list[ParallelCmdResult] = field(default_factory=list)
    observation: str = ObservationType.RUN_PARALLEL
    hidden: bool = False

    def __init__(
        self,
        content: str,
        results: list[ParallelCmdResult | dict[str, Any]] | None = None,
        observation: str = ObservationType.RUN_PARALLEL,
        hidden: bool = False,
        **kwargs: Any,
    ) -> None:
        # Truncate content before passing it to parent
        truncate = not hidden
        if truncate:
            content = CmdOutputObservation._maybe_truncate(content)

        super().__init__(content)

        self.observation = observation
        self.hidden = hidden

        self.results = []
        if results:
            for r in results:
                if isinstance(r, dict):
                    self.results.append(ParallelCmdResult.from_dict(r))
                else:
                    self.results.append(r)

    @property
    def error(self) -> bool:
        return any(r.error for r in self.results)

    @property
    def success(self) -> bool:
        return all(r.success for r in self.results)

    @property
    def message(self) -> str:
        success_count = sum(1 for r in self.results if r.success)
        return f'Executed {len(self.results)} commands: {success_count} succeeded, {len(self.results) - success_count} failed'

    def __str__(self) -> str:
        ret = f'**ParallelCmdOutputObservation (source={self.source}, {len(self.results)} results)**\n'
        ret += '--BEGIN AGENT OBSERVATION--\n'
        ret += f'{self.to_agent_observation()}\n'
        ret += '--END AGENT OBSERVATION--'
        return ret

    def to_agent_observation(self) -> str:
        parts = []
        for i, result in enumerate(self.results, 1):
            parts.append(f'=== Command {i}: {result.command} ===')
            parts.append(f'{result.metadata.prefix}{result.content}{result.metadata.suffix}')
            if result.metadata.working_dir:
                parts.append(f'[Working directory: {result.metadata.working_dir}]')
            parts.append(f'[Exit code: {result.exit_code}]')
        return '\n'.join(parts)

    def get_results_by_exit_code(self, exit_code: int) -> list[ParallelCmdResult]:
        """Filter results by exit code."""
        return [r for r in self.results if r.exit_code == exit_code]

    def get_successful_results(self) -> list[ParallelCmdResult]:
        """Get all results that completed successfully (exit_code == 0)."""
        return self.get_results_by_exit_code(0)

    def get_failed_results(self) -> list[ParallelCmdResult]:
        """Get all results that failed (exit_code != 0)."""
        return [r for r in self.results if r.exit_code != 0]

@dataclass
class IPythonRunCellObservation(Observation):
    """This data class represents the output of a IPythonRunCellAction."""

    code: str
    observation: str = ObservationType.RUN_IPYTHON
    image_urls: list[str] | None = None

    @property
    def error(self) -> bool:
        return False  # IPython cells do not return exit codes

    @property
    def message(self) -> str:
        return 'Code executed in IPython cell.'

    @property
    def success(self) -> bool:
        return True  # IPython cells are always considered successful

    def __str__(self) -> str:
        result = f'**IPythonRunCellObservation**\n{self.content}'
        if self.image_urls:
            result += f'\nImages: {len(self.image_urls)}'
        return result

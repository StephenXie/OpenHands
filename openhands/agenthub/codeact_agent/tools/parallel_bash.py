from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk

from openhands.agenthub.codeact_agent.tools.prompt import refine_prompt
from openhands.agenthub.codeact_agent.tools.security_utils import (
    RISK_LEVELS,
    SECURITY_RISK_DESC,
)
from openhands.llm.tool_names import EXECUTE_PARALLEL_BASH_TOOL_NAME

_DETAILED_PARALLEL_BASH_DESCRIPTION = """Execute multiple bash commands in parallel for faster execution.

### Use Cases
* Running multiple independent grep/search commands simultaneously
* Executing parallel file operations that don't depend on each other
* Running multiple independent test commands at once
* Any scenario where you need to run several commands that don't depend on each other's output

### Command Execution
* All commands run in isolated subprocesses in parallel
* Each command has its own exit code and output
* Commands do NOT share state - each runs independently
* The result includes all outputs with their respective exit codes

### Best Practices
* Only use for truly independent commands - commands that don't depend on each other
* For dependent commands (where one needs the output of another), use regular execute_bash with && chaining
* Keep the number of parallel commands reasonable (default max 10) to avoid resource exhaustion
* Each command should be self-contained

### Output Handling
* Each command's output is labeled with the command and its exit code
* If any command fails, you can identify which specific command failed
* Total output may be truncated if very large

### Example Use Case
Running multiple grep searches in parallel:
commands: ["grep -r 'pattern1' ./src", "grep -r 'pattern2' ./src", "grep -r 'pattern3' ./src"]
"""

_SHORT_PARALLEL_BASH_DESCRIPTION = """Execute multiple bash commands in parallel for faster execution.
* Use for independent commands that don't depend on each other's output
* Great for running multiple grep/search commands simultaneously
* Each command runs in isolation with its own exit code
* Results are returned with each command's output labeled separately"""


def create_parallel_cmd_run_tool(
    use_short_description: bool = False,
) -> ChatCompletionToolParam:
    description = (
        _SHORT_PARALLEL_BASH_DESCRIPTION
        if use_short_description
        else _DETAILED_PARALLEL_BASH_DESCRIPTION
    )
    return ChatCompletionToolParam(
        type='function',
        function=ChatCompletionToolParamFunctionChunk(
            name=EXECUTE_PARALLEL_BASH_TOOL_NAME,
            description=refine_prompt(description),
            parameters={
                'type': 'object',
                'properties': {
                    'commands': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': refine_prompt(
                            'List of bash commands to execute in parallel. Each command runs in its own subprocess. Commands should be independent and not rely on each other\'s output.'
                        ),
                    },
                    'max_concurrency': {
                        'type': 'integer',
                        'description': 'Maximum number of commands to run simultaneously. Default is 10. Lower this if running resource-intensive commands.',
                        'default': 10,
                    },
                    'timeout_per_command': {
                        'type': 'number',
                        'description': 'Optional timeout in seconds for each individual command. If not provided, uses default timeout.',
                    },
                    'cwd': {
                        'type': 'string',
                        'description': 'Optional working directory for all commands. If not provided, uses current working directory.',
                    },
                    'security_risk': {
                        'type': 'string',
                        'description': SECURITY_RISK_DESC,
                        'enum': RISK_LEVELS,
                    },
                },
                'required': ['commands', 'security_risk'],
            },
        ),
    )

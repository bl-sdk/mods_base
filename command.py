from __future__ import annotations

import argparse
import fnmatch
import importlib
import shlex
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, overload

from unrealsdk import logging
from unrealsdk.commands import NEXT_LINE, add_command, has_command, remove_command


@dataclass
class AbstractCommand(ABC):
    cmd: str

    def __post_init__(self) -> None:
        for char in " \f\n\r\t\v":
            if char in self.cmd:
                raise ValueError("Command cannot contain whitespace")

    @abstractmethod
    def _handle_cmd(self, line: str, cmd_len: int) -> None:
        """
        Handles the command being run.

        Args:
            line: The full line which triggered the callback - including any whitespace.
            cmd_len: The length of the matched command, including leading whitespace - i.e.
                     `line[cmd_len]` points to the first whitespace char after the command (or off
                     the end of the string if there was none).
        """
        raise NotImplementedError

    def enable(self) -> None:
        """Enables this command."""
        self.disable()
        add_command(self.cmd, self._handle_cmd)

    def disable(self) -> None:
        """Disables this command."""
        remove_command(self.cmd)

    def is_registered(self) -> bool:
        """
        Checks if a command matching this one is registered.

        Note this doesn't necessarily mean it's registered to this command.

        Returns:
            True if a command matching this one is registered.
        """
        return has_command(self.cmd)


type ARGPARSE_CALLBACK = Callable[[argparse.Namespace], None]
type ARGPARSE_SPLITTER = Callable[[str], list[str]]


@dataclass
class ArgParseCommand(AbstractCommand):
    callback: ARGPARSE_CALLBACK
    parser: argparse.ArgumentParser
    splitter: ARGPARSE_SPLITTER

    def _handle_cmd(self, line: str, cmd_len: int) -> None:
        try:
            args = self.parser.parse_args(self.splitter(line[cmd_len:]))
            self.callback(args)
        # Help/version/invalid args all call exit by default, just suppress that
        except SystemExit:
            pass

    @overload
    def add_argument[T](
        self,
        *name_or_flags: str,
        action: str | type[argparse.Action] = ...,
        nargs: int | str | None = None,
        const: Any = ...,
        default: Any = ...,
        type: Callable[[str], Any] | argparse.FileType | str = ...,
        choices: Iterable[T] | None = ...,
        required: bool = ...,
        help: str | None = ...,
        metavar: str | tuple[str, ...] | None = ...,
        dest: str | None = ...,
        version: str = ...,
        **kwargs: Any,
    ) -> argparse.Action: ...
    @overload
    def add_argument(self, *args: Any, **kwargs: Any) -> argparse.Action: ...

    def add_argument(self, *args: Any, **kwargs: Any) -> argparse.Action:
        """Wrapper which forwards to the parser's add_argument method."""
        return self.parser.add_argument(*args, **kwargs)

    def __call__(self, args: argparse.Namespace) -> None:
        """Wrapper which forwards to the callback."""
        self.callback(args)


class _FormatterClass(Protocol):
    def __call__(self, *, prog: str) -> argparse.HelpFormatter: ...


@overload
def command(
    cmd: str | None = None,
    splitter: ARGPARSE_SPLITTER = shlex.split,
    *,
    prog: str | None = None,
    usage: str | None = None,
    description: str | None = None,
    epilog: str | None = None,
    parents: Sequence[argparse.ArgumentParser] = [],
    formatter_class: _FormatterClass = ...,
    prefix_chars: str = "-",
    fromfile_prefix_chars: str | None = None,
    argument_default: Any = None,
    conflict_handler: str = "error",
    add_help: bool = True,
    allow_abbrev: bool = True,
    exit_on_error: bool = True,
) -> Callable[[ARGPARSE_CALLBACK], ArgParseCommand]: ...


@overload
def command(
    cmd: str | None = None,
    splitter: ARGPARSE_SPLITTER = shlex.split,
    **kwargs: Any,
) -> Callable[[ARGPARSE_CALLBACK], ArgParseCommand]: ...


@overload
def command(callback: ARGPARSE_CALLBACK, /) -> ArgParseCommand: ...


def command(
    cmd: str | None | ARGPARSE_CALLBACK = None,
    splitter: ARGPARSE_SPLITTER = shlex.split,
    **kwargs: Any,
) -> Callable[[ARGPARSE_CALLBACK], ArgParseCommand] | ArgParseCommand:
    """
    Decorator factory to create an argparse command.

    Note this returns the command object, not a function, so should always be the outermost level.

    Args:
        cmd: The command to register. If None, defaults to the wrapped function's name.
        splitter: A function which splits the full command line into individual args.
        **kwargs: Passed to `ArgumentParser` constructor.
    """
    # Disambiguate between being called as a decorator or a decorator factory
    cmd_name: str | None = None
    callback: ARGPARSE_CALLBACK | None = None
    if isinstance(cmd, Callable):
        callback = cmd
    else:
        cmd_name = cmd
    del cmd

    def decorator(func: Callable[[argparse.Namespace], None]) -> ArgParseCommand:
        nonlocal cmd_name
        cmd_name = cmd_name or func.__name__

        # It's important to set `prog`, since otherwise it defaults to `sys.argv[0]`, which causes
        # an index error since it's empty
        if "prog" not in kwargs:
            kwargs["prog"] = cmd_name

        return ArgParseCommand(cmd_name, func, argparse.ArgumentParser(**kwargs), splitter)

    if callback is None:
        return decorator

    return decorator(callback)


def capture_next_console_line(callback: Callable[[str], None]) -> None:
    """
    Captures the very next line submitted to console, regardless of what it is.

    Only triggers once. May re-register during the callback to capture multiple lines.

    Args:
        callback: The callback to run when  the next line is submitted.
    """
    if has_command(NEXT_LINE):
        raise RuntimeError(
            "Tried to register a next console line callback when one was already registered!",
        )

    add_command(NEXT_LINE, lambda line, _: callback(line))


def remove_next_console_line_capture() -> None:
    """If a next console line capture is currently active, removes it."""
    remove_command(NEXT_LINE)


@command(
    description=(
        "Reloads the selected Python modules.\n"
        "\n"
        "When matching multiple modules, reloads them all twice, in opposite orders, to try weed"
        " out any issues with order of initialization."
    ),
)
def rlm(args: argparse.Namespace) -> None:
    """Sample console command, which lets you more easily reload modules during development."""
    modules_to_reload: set[str] = set()

    module_patterns: list[str] = args.modules
    for pattern in module_patterns:
        modules_to_reload.update(fnmatch.filter(sys.modules.keys(), pattern))

    if not modules_to_reload:
        logging.error(
            "Failed to find any modules matching: "
            + ", ".join(f"'{pattern}'" for pattern in module_patterns),
        )
        return

    module_list = list(modules_to_reload)
    for module_name in module_list:
        importlib.reload(sys.modules[module_name])
    if len(module_list) > 1:
        for module_name in reversed(module_list):
            importlib.reload(sys.modules[module_name])


rlm.add_argument("modules", nargs="+", help="The modules to reload. May contain glob patterns.")
rlm.enable()

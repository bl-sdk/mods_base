from enum import IntFlag, auto
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Literal, overload

import unrealsdk
from unrealsdk.unreal import UObject

from .dot_sdkmod import open_in_mod_dir

# Need to define a few things first to avoid circular imports
__version_info__: tuple[int, int] = (1, 11)
__version__: str = f"{__version_info__[0]}.{__version_info__[1]}"
__author__: str = "bl-sdk"

# This avoids E402 for all the following imports
if True:
    MODS_DIR: Path = (
        _mod_dir
        if (_mod_dir := Path(__file__).parent.parent).is_dir()
        else _mod_dir.parent  # If in a .sdkmod, need to go up an extra folder
    )
    del _mod_dir

from .command import (
    AbstractCommand,
    ArgParseCommand,
    capture_next_console_line,
    command,
    remove_next_console_line_capture,
)
from .hook import HookType, bind_all_hooks, hook
from .html_to_plain_text import html_to_plain_text
from .keybinds import EInputEvent, KeybindType, keybind
from .mod import CoopSupport, Game, Library, Mod, ModType, RestartToDisable
from .mod_factory import build_mod
from .mod_list import (
    deregister_mod,
    get_ordered_mod_list,
    register_mod,
)
from .options import (
    JSON,
    BaseOption,
    BoolOption,
    ButtonOption,
    DropdownOption,
    GroupedOption,
    HiddenOption,
    KeybindOption,
    NestedOption,
    SliderOption,
    SpinnerOption,
    ValueOption,
)
from .settings import SETTINGS_DIR

__all__: tuple[str, ...] = (
    "ENGINE",
    "JSON",
    "MODS_DIR",
    "SETTINGS_DIR",
    "AbstractCommand",
    "ArgParseCommand",
    "BaseOption",
    "BoolOption",
    "ButtonOption",
    "CoopSupport",
    "DropdownOption",
    "EInputEvent",
    "Game",
    "GroupedOption",
    "HiddenOption",
    "HookType",
    "KeybindOption",
    "KeybindType",
    "Library",
    "Mod",
    "ModType",
    "NestedOption",
    "RestartToDisable",
    "SliderOption",
    "SpinnerOption",
    "ValueOption",
    "__version__",
    "__version_info__",
    "bind_all_hooks",
    "build_mod",
    "capture_next_console_line",
    "command",
    "deregister_mod",
    "get_ordered_mod_list",
    "get_pc",
    "hook",
    "html_to_plain_text",
    "keybind",
    "open_in_mod_dir",
    "register_mod",
    "remove_next_console_line_capture",
)

ENGINE: UObject


@overload
def get_pc() -> UObject: ...


@overload
def get_pc(*, possibly_loading: Literal[True] = True) -> UObject | None: ...


def get_pc(*, possibly_loading: bool = False) -> UObject | None:
    """
    Gets the main (local) player controller object.

    Note that this may return None if called during a loading screen. Since hooks and keybinds
    should never be able to trigger at this time, for convenience the default type hinting does not
    include this possibility. If running on another thread however, this can happen, pass the
    `possibly_loading` kwarg to update the type hinting.

    Args:
        possibly_loading: Changes the type hinting to possibly return None. No runtime impact.
    Returns:
        The player controller.
    """
    raise NotImplementedError


class ObjectFlags(IntFlag):
    """
    Useful values to assign to object flags, both for directly on an object and in construct_object.

    Note that not all flags are known in all games - though the type hinting always contains them
    all. Trying to use a flag in a game where it's not known will throw an attribute error.
    """

    if TYPE_CHECKING:
        # Prevents the object from getting garbage collected
        KEEP_ALIVE = auto()
        # Allows the object to be referenced by objects in other packages
        ALLOW_CROSS_PACKAGE_REFERENCES = auto()


match Game.get_tree():
    case Game.Willow1 | Game.Willow2:
        ENGINE = unrealsdk.find_object(  # pyright: ignore[reportConstantRedefinition]
            "WillowGameEngine",
            "Transient.WillowGameEngine_0",
        )

        _GAME_PLAYERS_PROP = ENGINE.Class._find_prop("GamePlayers")
        _ACTOR_PROP = _GAME_PLAYERS_PROP.Inner.PropertyClass._find_prop("Actor")

        @wraps(get_pc)
        def get_pc_willow(*, possibly_loading: bool = False) -> UObject | None:  # noqa: ARG001
            return ENGINE._get_field(_GAME_PLAYERS_PROP)[0]._get_field(_ACTOR_PROP)

        get_pc = get_pc_willow  # type: ignore

        @wraps(ObjectFlags, updated=())
        class WillowObjectFlags(ObjectFlags):  # type: ignore
            ALLOW_CROSS_PACKAGE_REFERENCES = 0x4
            KEEP_ALIVE = 0x4000

        ObjectFlags = WillowObjectFlags  # type: ignore

    case Game.Oak:
        ENGINE = unrealsdk.find_object(  # pyright: ignore[reportConstantRedefinition]
            "OakGameEngine",
            "/Engine/Transient.OakGameEngine_0",
        )

        _GAME_INSTANCE_PROP = ENGINE.Class._find_prop("GameInstance")
        _LOCAL_PLAYERS_PROP = _GAME_INSTANCE_PROP.PropertyClass._find_prop("LocalPlayers")
        _PLAYER_CONTROLLER_PROP = _LOCAL_PLAYERS_PROP.Inner.PropertyClass._find_prop(
            "PlayerController",
        )

        @wraps(get_pc)
        def get_pc_oak(*, possibly_loading: bool = False) -> UObject | None:  # noqa: ARG001
            return (
                ENGINE._get_field(_GAME_INSTANCE_PROP)
                ._get_field(_LOCAL_PLAYERS_PROP)[0]
                ._get_field(_PLAYER_CONTROLLER_PROP)
            )

        get_pc = get_pc_oak  # type: ignore

        @wraps(ObjectFlags, updated=())
        class OakObjectFlags(ObjectFlags):  # type: ignore
            KEEP_ALIVE = 0x80

        ObjectFlags = OakObjectFlags  # type: ignore

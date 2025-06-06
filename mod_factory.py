import contextlib
import functools
import inspect
import operator
import tomllib
import warnings
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, TypedDict

from .command import AbstractCommand
from .dot_sdkmod import open_in_mod_dir
from .hook import HookType
from .keybinds import KeybindType
from .mod import CoopSupport, Game, Mod, ModType
from .mod_list import deregister_mod, mod_list, register_mod
from .options import BaseOption, GroupedOption, NestedOption
from .settings import SETTINGS_DIR

_WARNING_SKIPS: tuple[str] = (str(Path(__file__).parent),)


def build_mod[T: Mod = Mod](
    *,
    cls: type[T] = Mod,
    deregister_same_settings: bool = True,
    inject_version_from_pyproject: bool = True,
    version_info_parser: Callable[[str], tuple[int, ...]] = (
        lambda v: tuple(int(x) for x in v.split("."))
    ),
    name: str | None = None,
    author: str | None = None,
    description: str | None = None,
    version: str | None = None,
    mod_type: ModType | None = None,
    supported_games: Game | None = None,
    coop_support: CoopSupport | None = None,
    settings_file: Path | None = None,
    keybinds: Sequence[KeybindType] | None = None,
    options: Sequence[BaseOption] | None = None,
    hooks: Sequence[HookType] | None = None,
    commands: Sequence[AbstractCommand] | None = None,
    auto_enable: bool | None = None,
    on_enable: Callable[[], None] | None = None,
    on_disable: Callable[[], None] | None = None,
) -> T:
    """
    Factory function to create and register a mod.

    Fields are gathered in three ways, in order of priority:
    - Args directly to this function.
    - A `pyproject.toml` in the same dir as the calling module.
    - Variables in the calling module's scope. Note the ordering of these is not necessarily stable.

    Arg             | `pyproject.toml`, in priority order  | Module Scope
    ----------------|--------------------------------------|--------------
    name            | tool.sdkmod.name, project.name       |
    author          | project.authors[n].name ^1           | __author__
    description     | project.description                  |
    version         | tool.sdkmod.version, project.version | __version__
                    | project.version                      | __version_info__
    mod_type        | tool.sdkmod.mod_type ^2              |
    supported_games | tool.sdkmod.supported_games ^3       |
    coop_support    | tool.sdkmod.coop_support ^4          |
    settings_file   |                                      | f"{__name__}.json" in the settings dir
    keybinds        |                                      | Keybind instances
    options         |                                      | OptionBase instances ^5
    hooks           |                                      | Hook instances
    commands        |                                      | AbstractCommand instances
    auto_enable     | tool.sdkmod.auto_enable              |
    on_enable       |                                      | on_enable
    on_disable      |                                      | on_disable

    ^1: Multiple authors are joined into a single string using commas + spaces.
    ^2: A string of one of the ModType enum value's name. Case sensitive.
        Note this only influences ordering in the mod menu. Setting 'mod_type = "Library"' is *not*
        equivalent to specifying cls=Library when calling this function.
    ^3: A list of strings of Game enum values' names. Case sensitive.
    ^4: A string of one of the CoopSupport enum value's name. Case sensitive.
    ^5: GroupedOption and NestedOption instances are deliberately ignored, to avoid possible issues
        gathering their child options twice. They must be explicitly passed via the arg.

    Any given fields are passed directly to the mod class constructor - and any missing ones are
    not. This means not specifying a field is equivalent to the class default - for example, usually
    mod type defaults to Standard, but when using 'cls=Library' it will default to Library.

    Extra Args:
        cls: The mod class to construct using. Can be used to select a subclass.
        deregister_same_settings: If true, deregisters any existing mods that use the same settings
                                  file. Useful so that reloading the module does not create multiple
                                  entries in the mods menu.
        inject_version_from_pyproject: If true, injects `__version__` and `__version_info__` back
                                       into the module scope with values parsed from the
                                       `pyproject.toml`. Does not overwrite existing values.
        version_info_parser: A function which parses the `project.version` field into a tuple of
                             ints, for when injecting __version_info__. The default implementation
                             only supports basic dot-separated decimal numbers.
    Returns:
        The created mod object.
    """

    module = inspect.getmodule(inspect.stack()[1].frame)
    if module is None:
        raise ValueError("Unable to find calling module when using build_mod factory!")

    fields: ModFactoryFields = {
        "name": name,
        "author": author,
        "description": description,
        "version": version,
        "_version_info": None,
        "mod_type": mod_type,
        "supported_games": supported_games,
        "coop_support": coop_support,
        "settings_file": settings_file,
        "keybinds": keybinds,
        "options": options,
        "hooks": hooks,
        "commands": commands,
        "auto_enable": auto_enable,
        "on_enable": on_enable,
        "on_disable": on_disable,
    }

    update_fields_with_pyproject(module, fields)

    if inject_version_from_pyproject:
        if not hasattr(module, "__version__") and fields["version"] is not None:
            module.__version__ = fields["version"]  # type: ignore
        if not hasattr(module, "__version_info__") and fields["_version_info"] is not None:
            version_info = version_info_parser(fields["_version_info"])
            module.__version_info__ = version_info  # type: ignore

    update_fields_with_module_attributes(module, fields)
    update_fields_with_module_search(module, fields)

    if deregister_same_settings and fields["settings_file"] is not None:
        deregister_using_settings_file(fields["settings_file"])

    # Strip out anything unspecified or private
    kwargs = {k: v for k, v in fields.items() if v is not None and not k.startswith("_")}

    mod = cls(**kwargs)  # type: ignore
    register_mod(mod)
    return mod


# ==================================================================================================


class ModFactoryFields(TypedDict):
    name: str | None
    author: str | None
    description: str | None
    version: str | None
    _version_info: str | None
    mod_type: ModType | None
    supported_games: Game | None
    coop_support: CoopSupport | None
    settings_file: Path | None
    keybinds: Sequence[KeybindType] | None
    options: Sequence[BaseOption] | None
    hooks: Sequence[HookType] | None
    commands: Sequence[AbstractCommand] | None
    auto_enable: bool | None
    on_enable: Callable[[], None] | None
    on_disable: Callable[[], None] | None


def load_pyproject(module: ModuleType) -> dict[str, Any]:
    """
    Tries to load a pyproject.toml in the same dir as the given module.

    Properly handles modules from inside a `.sdkmod`.

    Args:
        module: The module to look up the pyproject of.
    Returns:
        The parsed toml data, or an empty dict if unable to find a pyproject.toml.
    """
    pyproject = Path(inspect.getfile(module)).with_name("pyproject.toml")

    try:
        with open_in_mod_dir(pyproject, binary=True) as file:
            return tomllib.load(file)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return {}


def update_fields_with_pyproject_tool_sdkmod(
    sdkmod: dict[str, Any],
    fields: ModFactoryFields,
) -> None:
    """
    Updates the mod factory fields with data from the `tools.sdkmod` section of a`pyproject.toml`.

    Args:
        sdkmod: The `tools.sdkmod` section.
        fields: The current set of fields. Modified in place.
    """
    for simple_field in ("name", "version", "auto_enable"):
        if fields[simple_field] is None and simple_field in sdkmod:
            fields[simple_field] = sdkmod[simple_field]

    if fields["mod_type"] is None and "mod_type" in sdkmod:
        fields["mod_type"] = ModType.__members__.get(sdkmod["mod_type"])

    if fields["supported_games"] is None and "supported_games" in sdkmod:
        valid_games = [Game[name] for name in sdkmod["supported_games"] if name in Game.__members__]
        if valid_games:
            fields["supported_games"] = functools.reduce(operator.or_, valid_games)

    if fields["coop_support"] is None and "coop_support" in sdkmod:
        fields["coop_support"] = CoopSupport.__members__.get(sdkmod["coop_support"])


def update_fields_with_pyproject_project(
    project: dict[str, Any],
    fields: ModFactoryFields,
) -> None:
    """
    Updates the mod factory fields with data from the `project` section of a`pyproject.toml`.

    Args:
        project: The `project` section.
        fields: The current set of fields. Modified in place.
    """
    for simple_field, project_field in (
        ("name", "name"),
        ("version", "version"),
        ("description", "description"),
        ("_version_info", "version"),
    ):
        if fields[simple_field] is None and project_field in project:
            fields[simple_field] = project[project_field]

    if fields["author"] is None and "authors" in project:
        fields["author"] = ", ".join(
            author["name"] for author in project["authors"] if "name" in author
        )


def update_fields_with_pyproject(module: ModuleType, fields: ModFactoryFields) -> None:
    """
    Updates the mod factory fields with data gathered from the `pyproject.toml`.

    Args:
        module: The calling module to search for the `pyproject.toml` of.
        fields: The current set of fields. Modified in place.
    """
    toml_data = load_pyproject(module)

    # Check `tool.sdkmod` first, since we want it to have priority in cases we have multiple keys
    if ("tool" in toml_data) and ("sdkmod" in toml_data["tool"]):
        update_fields_with_pyproject_tool_sdkmod(toml_data["tool"]["sdkmod"], fields)

    if "project" in toml_data:
        update_fields_with_pyproject_project(toml_data["project"], fields)


def update_fields_with_module_attributes(module: ModuleType, fields: ModFactoryFields) -> None:
    """
    Updates the mod factory fields with data gathered from top level attributes in the module.

    Args:
        module: The calling module to search through.
        fields: The current set of fields. Modified in place.
    """
    for simple_field, attr in (
        ("name", "__name__"),
        ("author", "__author__"),
        ("version", "__version__"),
        ("on_enable", "on_enable"),
        ("on_disable", "on_disable"),
    ):
        if fields[simple_field] is not None:
            continue

        with contextlib.suppress(AttributeError):
            fields[simple_field] = getattr(module, attr)

    if fields["settings_file"] is None:
        fields["settings_file"] = SETTINGS_DIR / (module.__name__ + ".json")


def update_fields_with_module_search(  # noqa: C901 - difficult to split up
    module: ModuleType,
    fields: ModFactoryFields,
) -> None:
    """
    Updates the mod factory fields with data gathered by searching through all vars in the module.

    Args:
        module: The calling module to search through.
        fields: The current set of fields. Modified in place.
    """
    need_to_search_module = False

    new_keybinds: list[KeybindType] = []
    if find_keybinds := fields["keybinds"] is None:
        need_to_search_module = True

    new_options: list[BaseOption] = []
    if find_options := fields["options"] is None:
        need_to_search_module = True

    new_hooks: list[HookType] = []
    if find_hooks := fields["hooks"] is None:
        need_to_search_module = True

    new_commands: list[AbstractCommand] = []
    if find_commands := fields["commands"] is None:
        need_to_search_module = True

    if not need_to_search_module:
        return

    for _, value in inspect.getmembers(module):
        match value:
            case KeybindType() if find_keybinds:
                new_keybinds.append(value)

            case GroupedOption() | NestedOption() if find_options:
                warnings.warn(
                    f"{module.__name__}: {type(value).__name__} instances must be explicitly"
                    f" specified in the options list!",
                    stacklevel=2,
                    skip_file_prefixes=_WARNING_SKIPS,
                )
            case BaseOption() if find_options:
                new_options.append(value)

            case HookType() if find_hooks:
                hook: HookType = value  # pyright: ignore[reportUnknownVariableType]
                new_hooks.append(hook)

            case AbstractCommand() if find_commands:
                new_commands.append(value)

            case _:
                pass

    # Only assign each field if we actually found something, so we keep using the mod constructor's
    # default otherwise
    if find_keybinds and new_keybinds:
        fields["keybinds"] = new_keybinds

    if find_options and new_options:
        fields["options"] = new_options

    if find_hooks and new_hooks:
        fields["hooks"] = new_hooks

    if find_commands and new_commands:
        fields["commands"] = new_commands


def deregister_using_settings_file(settings_file: Path) -> None:
    """
    Deregisters all mods using the given settings file.

    Args:
        settings_file: The settings file path to deregister mods using.
    """
    mods_to_remove = [mod for mod in mod_list if mod.settings_file == settings_file]
    for mod in mods_to_remove:
        deregister_mod(mod)

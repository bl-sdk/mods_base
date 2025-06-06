import warnings
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field
from types import EllipsisType
from typing import TYPE_CHECKING, Any, Literal, Self, cast

from unrealsdk import logging

from .keybinds import KeybindType

if TYPE_CHECKING:
    from .mod import Mod

# Little ugly to repeat this from settings, but we can't import it from there cause it creates a
# strong circular dependency - we need to import it to get JSON before we can define most options,
# but it needs to import those options from us
type JSON = Mapping[str, JSON] | Sequence[JSON] | str | int | float | bool | None


@dataclass
class BaseOption(ABC):
    """
    Abstract base class for all options.

    Args:
        identifier: The option's identifier.
    Keyword Args:
        display_name: The option name to use for display. Defaults to copying the identifier.
        description: A short description about the option.
        description_title: The title of the description. Defaults to copying the display name.
        is_hidden: If true, the option will not be shown in the options menu.
    Extra attributes:
        mod: The mod this option stores it's settings in, or None if not (yet) associated with one.
    """

    identifier: str
    _: KW_ONLY
    display_name: str = None  # type: ignore
    description: str = ""
    description_title: str = None  # type: ignore
    is_hidden: bool = False

    mod: "Mod | None" = field(default=None, init=False, repr=False)

    @abstractmethod
    def __init__(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def _to_json(self) -> JSON | EllipsisType:
        """
        Turns this option into a JSON value.

        Returns:
            This option's JSON representation, or Ellipsis if it should be considered to have no
            value.
        """
        raise NotImplementedError

    @abstractmethod
    def _from_json(self, value: JSON) -> None:
        """
        Assigns this option's value, based on a previously retrieved JSON value.

        Args:
            value: The JSON value to assign.
        """
        raise NotImplementedError

    def __post_init__(self) -> None:
        if self.display_name is None:  # type: ignore
            self.display_name = self.identifier
        if self.description_title is None:  # type: ignore
            self.description_title = self.display_name


@dataclass
class ValueOption[J: JSON](BaseOption):
    """
    Abstract base class for all options storing a value.

    Args:
        identifier: The option's identifier.
        value: The option's value.
    Keyword Args:
        display_name: The option name to use for display. Defaults to copying the identifier.
        description: A short description about the option.
        description_title: The title of the description. Defaults to copying the display name.
        is_hidden: If true, the option will not be shown in the options menu.
        on_change: If not None, a callback to run before updating the value. Passed a reference to
                   the option object and the new value. May be set using decorator syntax.
    Extra Attributes:
        mod: The mod this option stores it's settings in, or None if not (yet) associated with one.
        default_value: What the value was originally when registered. Does not update on change.
    """

    value: J
    default_value: J = field(init=False)
    _: KW_ONLY
    on_change: Callable[[Self, J], None] | None = None

    @abstractmethod
    def __init__(self) -> None:
        raise NotImplementedError

    def _to_json(self) -> J:
        return self.value

    def __post_init__(self) -> None:
        super().__post_init__()
        self.default_value = self.value

    def __setattr__(self, name: str, value: Any) -> None:
        # Simpler to use `__setattr__` than a property to detect value changes
        if (
            name == "value"
            and self.on_change is not None
            and not hasattr(self, "_on_change_recursion_guard")
        ):
            self._on_change_recursion_guard = True
            self.on_change(self, value)
            del self._on_change_recursion_guard

        super().__setattr__(name, value)

    def __call__(self, on_change: Callable[[Self, J], None]) -> Self:
        """
        Sets the on change callback.

        This allows this class to be constructed using decorator syntax, though note it is *not* a
        decorator, it returns itself so must be the outermost level.

        Args:
            on_change: The callback to set.
        Returns:
            This option instance.
        """
        if self.on_change is not None:
            warnings.warn(
                f"{self.__class__.__qualname__}.__call__ was called on an option which already has"
                f" a on change callback.",
                stacklevel=2,
            )

        self.on_change = on_change
        return self


@dataclass
class HiddenOption[J: JSON](ValueOption[J]):
    """
    A generic option which is always hidden. Use this to persist arbitrary (JSON-encodeable) data.

    This class is explicitly intended to be modified programmatically, unlike the other options
    which are generally only modified by the mod menu.

    Args:
        identifier: The option's identifier.
    Keyword Args:
        display_name: The option name to use for display. Defaults to copying the identifier.
        description: A short description about the option.
        description_title: The title of the description. Defaults to copying the display name.
    Extra Attributes:
        is_hidden: Always true.
        mod: The mod this option stores it's settings in, or None if not (yet) associated with one.
    """

    # Need to redefine on change so that it binds to J@HiddenOption, not J@ValueOption
    on_change: Callable[[Self, J], None] | None = None  # pyright: ignore[reportIncompatibleVariableOverride]

    is_hidden: Literal[True] = field(  # pyright: ignore[reportIncompatibleVariableOverride]
        default=True,
        init=False,
    )

    def _from_json(self, value: JSON) -> None:
        self.value = cast(J, value)

    def save(self) -> None:
        """Saves the settings of the mod this option is associated with."""
        if self.mod is None:
            raise RuntimeError(
                "Tried to save a hidden option which does not have an associated mod.",
            )

        self.mod.save_settings()


@dataclass
class SliderOption(ValueOption[float]):
    """
    An option selecting a number within a range. Typically implemented as a slider.

    Args:
        identifier: The option's identifier.
        value: The option's value.
        min_value: The minimum value.
        max_value: The maximum value.
        step: How much the value should move each step of the slider. This does not mean your value
              will always be a multiple of the step, it may be possible to get intermediate values.
        is_integer: If True, the value is treated as an integer.
    Keyword Args:
        display_name: The option name to use for display. Defaults to copying the identifier.
        description: A short description about the option.
        description_title: The title of the description. Defaults to copying the display name.
        is_hidden: If true, the option will not be shown in the options menu.
        on_change: If not None, a callback to run before updating the value. Passed a reference to
                   the option object and the new value. May be set using decorator syntax.
    Extra Attributes:
        mod: The mod this option stores it's settings in, or None if not (yet) associated with one.
        default_value: What the value was originally when registered. Does not update on change.
    """

    min_value: float
    max_value: float
    step: float = 1
    is_integer: bool = True

    def __post_init__(self) -> None:
        super().__post_init__()

        # This is generally non-sensical, and we expect most menus will have problems with it
        # While you can easily get around it, block it as a first layer of defence
        if self.step > (self.max_value - self.min_value):
            raise ValueError("Can't give slider option a step larger than its allowed range")

        # This isn't as serious, but still show a warning
        if self.is_integer and any(
            x != int(x) for x in (self.value, self.min_value, self.max_value, self.step)
        ):
            warnings.warn(
                "Spinner has non-integer fields despite is_integer being True. This may cause"
                " unexpected rounding.",
                # +1 to skip the generated dataclass `__init__` too
                stacklevel=3,
            )

    def _from_json(self, value: JSON) -> None:
        try:
            self.value = float(value)  # type: ignore
            if self.is_integer:
                self.value = round(self.value)
        except ValueError:
            logging.error(
                f"'{value}' is not a valid value for option '{self.identifier}', sticking"
                f" with the default",
            )


@dataclass
class SpinnerOption(ValueOption[str]):
    """
    An option selecting one of a set of strings. Typically implemented as a spinner.

    Also see DropDownOption, which may be more suitable for larger numbers of choices.

    Args:
        identifier: The option's identifier.
        value: The option's value.
        choices: A list of choices for the value.
        wrap_enabled: If True, allows moving from the last choice back to the first, or vice versa.
    Keyword Args:
        display_name: The option name to use for display. Defaults to copying the identifier.
        description: A short description about the option.
        description_title: The title of the description. Defaults to copying the display name.
        is_hidden: If true, the option will not be shown in the options menu.
        on_change: If not None, a callback to run before updating the value. Passed a reference to
                   the option object and the new value. May be set using decorator syntax.
    Extra Attributes:
        mod: The mod this option stores it's settings in, or None if not (yet) associated with one.
        default_value: What the value was originally when registered. Does not update on change.
    """

    choices: list[str]
    wrap_enabled: bool = False

    def _from_json(self, value: JSON) -> None:
        value = str(value)
        if value in self.choices:
            self.value = value
        else:
            logging.error(
                f"'{value}' is not a valid value for option '{self.identifier}', sticking"
                f" with the default",
            )


@dataclass
class BoolOption(ValueOption[bool]):
    """
    An option toggling a boolean value. Typically implemented as an "on/off" spinner.

    Args:
        identifier: The option's identifier.
        value: The option's value.
        true_text: If not None, overwrites the default text used for the True option.
        false_text: If not None, overwrites the default text used for the False option.
    Keyword Args:
        display_name: The option name to use for display. Defaults to copying the identifier.
        description: A short description about the option.
        description_title: The title of the description. Defaults to copying the display name.
        is_hidden: If true, the option will not be shown in the options menu.
        on_change: If not None, a callback to run before updating the value. Passed a reference to
                   the option object and the new value. May be set using decorator syntax.
    Extra Attributes:
        mod: The mod this option stores it's settings in, or None if not (yet) associated with one.
        default_value: What the value was originally when registered. Does not update on change.
    """

    true_text: str | None = None
    false_text: str | None = None

    def _from_json(self, value: JSON) -> None:
        # Special case a false string
        if isinstance(value, str) and value.strip().lower() == "false":
            value = False

        self.value = bool(value)


@dataclass
class DropdownOption(ValueOption[str]):
    """
    An option selecting one of a set of strings. Typically implemented as a dropdown menu.

    Also see SpinnerOption, which may be more suitable for smaller numbers of choices.

    Args:
        identifier: The option's identifier.
        value: The option's value.
        choices: A list of choices for the value.
    Keyword Args:
        display_name: The option name to use for display. Defaults to copying the identifier.
        description: A short description about the option.
        description_title: The title of the description. Defaults to copying the display name.
        is_hidden: If true, the option will not be shown in the options menu.
        on_change: If not None, a callback to run before updating the value. Passed a reference to
                   the option object and the new value. May be set using decorator syntax.
    Extra Attributes:
        mod: The mod this option stores it's settings in, or None if not (yet) associated with one.
        default_value: What the value was originally when registered. Does not update on change.
    """

    choices: list[str]

    def _from_json(self, value: JSON) -> None:
        value = str(value)
        if value in self.choices:
            self.value = value
        else:
            logging.error(
                f"'{value}' is not a valid value for option '{self.identifier}', sticking"
                f" with the default",
            )


@dataclass
class ButtonOption(BaseOption):
    """
    An entry in the options list which may be pressed to trigger a callback.

    May also be used without a callback, as a way to just inject plain entries, e.g. for extra
    descriptions.

    Args:
        identifier: The option's identifier.
    Keyword Args:
        display_name: The option name to use for display. Defaults to copying the identifier.
        description: A short description about the option.
        description_title: The title of the description. Defaults to copying the display name.
        is_hidden: If true, the option will not be shown in the options menu.
        on_press: If not None, the callback to run when the button is pressed. Passed a reference to
                  the option object.
    Extra Attributes:
        mod: The mod this option stores it's settings in, or None if not (yet) associated with one.
    """

    _: KW_ONLY
    on_press: Callable[[Self], None] | None = None

    def _to_json(self) -> EllipsisType:
        return ...

    def _from_json(self, value: JSON) -> None:
        pass

    def __call__(self, on_press: Callable[[Self], None]) -> Self:
        """
        Sets the on press callback.

        This allows this class to be constructed using decorator syntax, though note it is *not* a
        decorator, it returns itself so must be the outermost level.

        Args:
            on_press: The callback to set.
        Returns:
            This option instance.
        """
        if self.on_press is not None:
            warnings.warn(
                f"{self.__class__.__qualname__}.__call__ was called on an option which already has"
                f" a on press callback.",
                stacklevel=2,
            )

        self.on_press = on_press
        return self


@dataclass
class KeybindOption(ValueOption[str | None]):
    """
    An option selecting a keybinding.

    Note this class only deals with displaying a key and letting the user rebind it, use `Keybind`
    to handle press callbacks.

    Args:
        identifier: The option's identifier.
        value: The option's value.
        is_rebindable: True if the key may be rebound.
    Keyword Args:
        display_name: The option name to use for display. Defaults to copying the identifier.
        description: A short description about the option.
        description_title: The title of the description. Defaults to copying the display name.
        is_hidden: If true, the option will not be shown in the options menu.
        on_change: If not None, a callback to run before updating the value. Passed a reference to
                   the option object and the new value. May be set using decorator syntax.
    Extra Attributes:
        mod: The mod this option stores it's settings in, or None if not (yet) associated with one.
        default_value: What the value was originally when registered. Does not update on change.
    """

    is_rebindable: bool = True

    def _from_json(self, value: JSON) -> None:
        if value is None:
            self.value = None
        else:
            self.value = str(value)

    @classmethod
    def from_keybind(cls, bind: KeybindType) -> Self:
        """
        Constructs an option bound from a keybind.

        Changes to the option will be applied back onto the keybind (though not in reverse).

        Args:
            bind: The keybind to construct from.
        Returns:
            A new binding option.
        """
        option = cls(
            identifier=bind.identifier,
            value=bind.key,
            is_rebindable=bind.is_rebindable,
            display_name=bind.display_name,
            description=bind.description,
            description_title=bind.description_title,
            is_hidden=bind.is_hidden,
            on_change=lambda _, new_key: setattr(bind, "key", new_key),
        )
        option.default_value = bind.default_key
        return option


@dataclass
class GroupedOption(BaseOption):
    """
    A titled group of options, which appear inline.

    Note that this class must be explicitly specified in the options list of a mod, it is *not*
    picked up by the automatic gathering. This is to avoid issues where storing the child options in
    separate variables might cause them to be gathered twice.

    Args:
        name: The option's name, used as the group title.
        children: The group of child options.
    Keyword Args:
        display_name: The option name to use for display. Defaults to copying the identifier.
        description: A short description about the option.
        description_title: The title of the description. Defaults to copying the display name.
        is_hidden: If true, the option will not be shown in the options menu.
    Extra Attributes:
        mod: The mod this option stores it's settings in, or None if not (yet) associated with one.
    """

    children: Sequence[BaseOption]

    def _to_json(self) -> JSON:
        return {
            option.identifier: child_json
            for option in self.children
            if (child_json := option._to_json()) is not ...
        }

    def _from_json(self, value: JSON) -> None:
        if isinstance(value, Mapping):
            for option in self.children:
                if option.identifier not in value:
                    continue
                option._from_json(value[option.identifier])
        else:
            logging.error(
                f"'{value}' is not a valid value for option '{self.identifier}', sticking"
                f" with the default",
            )


@dataclass
class NestedOption(BaseOption):
    """
    A nested group of options, which appear in a new menu.

    Note that this class must be explicitly specified in the options list of a mod, it is *not*
    picked up by the automatic gathering. This is to avoid issues where storing the child options in
    separate variables might cause them to be gathered twice.

    Args:
        identifier: The option's identifier.
        children: The group of child options.
    Keyword Args:
        display_name: The option name to use for display. Defaults to copying the identifier.
        description: A short description about the option.
        description_title: The title of the description. Defaults to copying the display name.
        is_hidden: If true, the option will not be shown in the options menu.
    Extra Attributes:
        mod: The mod this option stores it's settings in, or None if not (yet) associated with one.
    """

    children: Sequence[BaseOption]

    def _to_json(self) -> JSON:
        return {
            option.identifier: child_json
            for option in self.children
            if (child_json := option._to_json()) is not ...
        }

    def _from_json(self, value: JSON) -> None:
        if isinstance(value, Mapping):
            for option in self.children:
                if option.identifier not in value:
                    continue
                option._from_json(value[option.identifier])
        else:
            logging.error(
                f"'{value}' is not a valid value for option '{self.identifier}', sticking"
                f" with the default",
            )

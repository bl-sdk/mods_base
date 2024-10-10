# Mods Base
A common set of classes for describing mods made with
[pyunrealsdk](https://github.com/bl-sdk/pyunrealsdk/), as well as various common utilities.

Aimed at the Borderlands series, though likely suitable for others with slight modification.

### Setting up a new Mod Manager
While this repo contains all the base info for a new mod manager, you still need to add a few other
game specific things:

- A mod menu. Consider using [console_mod_menu](https://github.com/bl-sdk/console_mod_menu/)
  while developing, though you likely want to create a gui version for users.

- A keybind implementation, which overwrites `KeybindType.enable` and `KeybindType.disable`, and
  sets up some hooks to run the callbacks as appropriate.

- An initialization script. This should import this and the keybind implementation, then find and
  import all mods, and finally call `mods_base.mod_list.register_base_mod `

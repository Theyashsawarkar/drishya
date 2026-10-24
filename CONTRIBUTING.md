# Contributing to drishya

Thanks for helping. Bug reports, ideas and pull requests are welcome.

## Development setup

```sh
git clone https://github.com/Theyashsawarkar/drishya ~/code/drishya
cd ~/code/drishya
python -m py_compile drishya/*.py bin/drishya
python -m unittest discover -s tests -v
./bin/drishya daemon        # in one terminal; then ./bin/drishya play <file or link>
```

## How it fits together

See the "How it works" section of the README and `CLAUDE.md`: the core
owns the player and the queue; views only read it and call its methods;
anything slow runs in `core.bg`.

## Rules

- **Keys are discoverable**: a `# keybind: Drishya/<scope> | <keys> | <Verb> <object>`
  line and a row in the README (CI checks).
- **Never block the main loop**, never log or store a password.
- Every change gets a `CHANGELOG.md` entry; releases are tags `vX.Y.Z`
  with `VERSION` in `drishya/__init__.py` bumped.

## Pull requests

Describe what and why, and tick the template's checklist. By contributing
you agree your work is released under the [MIT License](LICENSE).

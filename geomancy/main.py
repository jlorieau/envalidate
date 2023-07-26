"""
The program entry point.

This file is located in the root module directory, rather than the 'cli'
submodule because it may access functionality from all submodules
"""
import typing as t
import argparse
import logging
from pathlib import Path
import tomllib

import yaml

from . import get_version
from .config import Config
from .checks import CheckBase
from .environment import load_env

__description__ = (Path(__file__).parent / "__description__.txt").read_text().strip()

logger = logging.getLogger(__name__)  # Create a default logger
config = Config()  # Set up config defaults for the CLI

# Set current version
config.VERSION = get_version()

# Default paths for checks files
config.CLI.CHECKS_PATHS = [
    "pyproject.toml",
    ".geomancy.toml",
    "geomancy.toml",
    "geomancy.yaml",
    "geomancy.yml",
]

# Default file extensions for TOML files
config.CLI.TOML_EXTS = [".toml"]

# Default file extensions for YAML files
config.CLI.YAML_EXTS = [".yml", ".yaml"]

# Default paths for settings
config.CLI.SETTINGS_PATHS = ["{HOME}/.geomancerrc"]

# Default names for config sections in checks files
config.CLI.CONFIG_NAMES = ["config", "Config"]


def filepath(string: str, required: bool = True) -> t.Union["Path", None]:
    """Given a path string, verifies that the path is an existing file and
    converts it to a path.

    Parameters
    ----------
    string
        The path string to verify and convert
    required
        If True, log an error and exit the program if the file does not exist

    Returns
    -------
    path
        The path for the existing file
    """
    path = Path(string)
    if not path.is_file():
        if required:
            logger.error(f"Could not find the file given by the path {string}")
            exit(1)
        return None
    return path


def setup_parser() -> argparse.ArgumentParser:
    """Set up the CLI parser"""
    # Create the parser
    parser = argparse.ArgumentParser(description=__description__)

    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s " + get_version(),
        help="Print the current version",
    )
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug mode")
    parser.add_argument(
        "-e",
        "--env",
        action="append",
        type=filepath,
        help="Optional environment file(s) to load",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Overwrite environment variables from files",
    )
    parser.add_argument(
        "--disable-color", action="store_true", help="Disable colors in the terminal"
    )
    parser.add_argument("--config", action="store_true", help="Print default config")
    parser.add_argument(
        "checks_files",
        type=filepath,
        nargs="*",
        help="Optional file containing checks to run",
    )

    return parser


def setup_logging(debug: bool = False):
    """Set up the default logging"""
    logging.basicConfig(
        level=logging.DEBUG if debug else None,
        format="%(levelname)s:%(name)s: %(message)s",
    )


def action_check(args: argparse.Namespace) -> t.Union[bool, None]:
    """Handle execution of the 'check' sub-command

    Parameters
    ----------
    args
        The sub-parser arguments

    Returns
    -------
    result
        True if the checks ran successfully
        False if one of the checks failed
        None if no valid checks files were found
    """
    # Check the specified files
    if len(args.checks_files) > 0:
        # Use the specified checks_files, if available
        checks_files = args.checks_files
    else:
        # Otherwise use the default paths in the config
        checks_files = [filepath(p, required=False) for p in config.CLI.CHECKS_PATHS]
        checks_files = [p for p in checks_files if p is not None]

    # Nothing to do if no checks files were found
    if len(checks_files) == 0:
        logger.error(f"Could not find a checks file")
        return None

    # Convert the checks_files into root checks
    checks = []
    for checks_file in checks_files:
        # Parse the file by filetype
        if checks_file.suffix in config.CLI.TOML_EXTS:
            with open(checks_file, "rb") as f:
                d = tomllib.load(f)

        elif checks_file.suffix in config.CLI.YAML_EXTS:
            with open(checks_file, "r") as f:
                d = yaml.load(f, Loader=yaml.SafeLoader)

        else:
            continue

        # pyproject.toml files have their items placed under the [tool.geomancy]
        # section
        if checks_file.name == "pyproject.toml":
            d = d.get("tool", dict()).get("geomancy", dict())

        # Load config section, if available
        for config_name in config.CLI.CONFIG_NAMES:
            config_section = d.pop(config_name, None)
            if isinstance(config_section, dict):
                config.update(config_section)

        # Load the rest into a root CheckBase
        check = CheckBase.load(d, name=str(checks_file))
        if check is not None:
            checks.append(check)

    # Create a root check, if there are a lot of checks
    if len(checks) > 1:
        checks = [CheckBase(name="Multiple files", sub_checks=checks)]

    # Run the checks
    return all(check.check() for check in checks)


def action_env(args, parser) -> int:
    """Hand the environment files (-e) options"""
    # The '--overwrite' flag only makes sense if environment files (-e) are
    # specified
    if args.overwrite and args.env is None:
        parser.error(
            f"The --overwrite flag can only be used when environment files "
            f"(--env) are specified"
        )

    env_files = args.env if args.env is not None else []
    count = 0
    for filepath in env_files:
        count += load_env(filepath, overwrite=args.overwrite)
    return count


def main_cli(args: t.Optional[t.List[str]] = None):
    # Parse the CLI arguments
    parser = setup_parser()
    args = parser.parse_args(args)  # parse root parser args

    # Setup the default logger
    setup_logging(debug=args.debug)
    logger.debug(f"CLI parsed args: {args}")

    # Process the --config flag
    if args.config:
        config.pprint_toml()
        exit(0)

    # Process the --disable-color flag
    if args.disable_color:
        config.TERM.USE_COLOR = False

    # Process the -e/--env files and --overwrite
    action_env(args=args, parser=parser)

    # Process the checks
    result = action_check(args)
    if result is None:
        parser.print_help()

"""Install the built wheel in an isolated environment and check its public metadata."""

import os
import subprocess
import tempfile
import tomllib
import venv
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as stream:
        expected_version = str(tomllib.load(stream)["project"]["version"])

    wheel = root / "dist" / f"bloch_trace-{expected_version}-py3-none-any.whl"
    sdist = root / "dist" / f"bloch_trace-{expected_version}.tar.gz"
    if not wheel.is_file() or not sdist.is_file():
        raise SystemExit("Build the wheel and sdist first: poetry build")

    with tempfile.TemporaryDirectory(prefix="trace-sdk-smoke-") as temporary:
        directory = Path(temporary)
        environment = directory / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run(
            [
                str(interpreter),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                str(wheel),
            ],
            check=True,
            cwd=directory,
        )
        subprocess.run(
            [
                str(interpreter),
                "-I",
                "-c",
                "import sys; "
                "from importlib.metadata import version; "
                "from importlib.resources import files; "
                "import bloch_trace; "
                "assert bloch_trace.__version__ == version('bloch-trace') == sys.argv[1]; "
                "assert files('bloch_trace').joinpath('py.typed').is_file(); "
                "print('Installed package OK:', bloch_trace.__version__)",
                expected_version,
            ],
            check=True,
            cwd=directory,
        )


if __name__ == "__main__":
    main()

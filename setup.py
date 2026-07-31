"""Minimal setuptools hooks for embedding immutable build provenance."""

from __future__ import annotations

import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

ROOT = Path(__file__).resolve().parent
for candidate in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from build_artifact_identity import (  # noqa: E402
    resolve_build_identity,
    stage_package_identity,
    write_reproducible_sdist,
)


def _identity() -> dict[str, object]:
    return resolve_build_identity(
        repo_root=ROOT,
        package_root=ROOT / "src" / "portable_resume",
    )


class EmbeddedIdentitySdist(sdist):
    def make_release_tree(self, base_dir: str, files: list[str]) -> None:
        identity = _identity()
        super().make_release_tree(base_dir, files)
        stage_package_identity(
            Path(base_dir)
            / "src"
            / "portable_resume",
            identity,
        )

    def make_archive(
        self,
        base_name: str,
        format: str,
        root_dir: str | None = None,
        base_dir: str | None = None,
        owner: str | None = None,
        group: str | None = None,
    ) -> str:
        if format != "gztar" or base_dir is None:
            return super().make_archive(
                base_name,
                format,
                root_dir=root_dir,
                base_dir=base_dir,
                owner=owner,
                group=group,
            )
        release_tree = Path(root_dir or ".") / base_dir
        return str(
            write_reproducible_sdist(
                Path(f"{base_name}.tar.gz"),
                release_tree,
                archive_root_name=Path(base_dir).name,
            )
        )


class EmbeddedIdentityBuildPy(build_py):
    def run(self) -> None:
        identity = _identity()
        super().run()
        if self.editable_mode:
            return
        stage_package_identity(
            Path(self.build_lib)
            / "portable_resume",
            identity,
        )

    def get_outputs(self, include_bytecode: bool = True) -> list[str]:
        outputs = list(super().get_outputs(include_bytecode=include_bytecode))
        if not self.editable_mode:
            outputs.append(
                str(
                    Path(self.build_lib)
                    / "portable_resume"
                    / "resources"
                    / "build-identity.json"
                )
            )
        return outputs


setup(
    cmdclass={
        "build_py": EmbeddedIdentityBuildPy,
        "sdist": EmbeddedIdentitySdist,
    }
)

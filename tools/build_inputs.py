"""What a WindowTally release is built from beyond its runtime, each input pinned by the
SHA-256 its publisher lists.

Every release's runtime — CPython's embeddable package, with Tk from CPython's full
package of the same version — is pinned in ``release_core.py``, the release build's
shared core. A WindowTally release also carries Qt beside the runtime: the two wheels
below, whose abi3 builds serve every CPython from 3.10, and of which the release keeps
only what the window imports and the platform needs. The wheels carry neither Qt's licence
texts nor its list of third-party components, so the notices read both from Qt's own source
archive, pinned below too; a release carries nothing of that archive but those texts.
``fetch_build_inputs.py`` downloads ``INPUTS`` into ``build-inputs/`` (git-ignored) and
checks them; ``build_release.py`` checks them again before it uses them and downloads
nothing.

Moving to another Qt means changing all three pins together, for one release of Qt, and
``QT_VERSION``, fetching again, and building: a build runs the whole suite under the
interpreter it assembled. The Qt in the environment the suite runs under from source is
the same release.
"""
from __future__ import annotations

from release_core import RUNTIME_INPUTS, Input

QT_VERSION = "6.12.0"
"""The release of PySide6-Essentials, shiboken6 and qtbase a WindowTally release carries."""

PYSIDE6 = Input(
    f"pyside6_essentials-{QT_VERSION}-cp310-abi3-win_amd64.whl",
    "https://files.pythonhosted.org/packages/03/61/9a7e32a37b224f68506785bfb0f288d516098ec71681782d72b695a6c95d/"
    f"pyside6_essentials-{QT_VERSION}-cp310-abi3-win_amd64.whl",
    "c9a95102aa23c1f86516a30d5a9be37552d324eee7e567eb7508973f1218cb42", 82_153_795,
    f"https://pypi.org/pypi/PySide6-Essentials/{QT_VERSION}/json",
    "PySide6-Essentials: Qt's libraries and their Python bindings")
SHIBOKEN6 = Input(
    f"shiboken6-{QT_VERSION}-cp310-abi3-win_amd64.whl",
    "https://files.pythonhosted.org/packages/2a/b6/bee97e7a2edeab72aafabb46ee5adc939790a638d107860b4cad7a20e407/"
    f"shiboken6-{QT_VERSION}-cp310-abi3-win_amd64.whl",
    "a1906cb8116869178c64b6bab52623bbc8b4ceed7b30bfc3c9aa0f6e67f6438e", 1_265_476,
    f"https://pypi.org/pypi/shiboken6/{QT_VERSION}/json",
    "shiboken6: the runtime PySide6's bindings need")
QT_SOURCE = Input(
    f"qtbase-everywhere-src-{QT_VERSION}.tar.xz",
    f"https://download.qt.io/archive/qt/6.12/{QT_VERSION}/submodules/qtbase-everywhere-src-{QT_VERSION}.tar.xz",
    "a951bd163c7b80fc6b8c88d7668fb56abf91c152373e13c10666763238131307", 51_220_268,
    f"https://download.qt.io/archive/qt/6.12/{QT_VERSION}/submodules/qtbase-everywhere-src-{QT_VERSION}.tar.xz.sha256",
    "Qt's source: its licence texts and the third-party components the notices name")
QT_INPUTS = (PYSIDE6, SHIBOKEN6, QT_SOURCE)
"""WindowTally's own inputs."""
INPUTS = (*RUNTIME_INPUTS, *QT_INPUTS)
"""Every input ``fetch_build_inputs.py`` obtains: the runtime's, then WindowTally's own."""

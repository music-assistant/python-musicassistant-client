"""Setup of Music Assistant client."""
import os
from pathlib import Path

from setuptools import find_packages, setup

PROJECT_DIR = Path(__file__).parent.resolve()
README_FILE = PROJECT_DIR / "README.md"
VERSION = "0.0.15"

with open("requirements.txt") as f:
    INSTALL_REQUIRES = f.read().splitlines()

PACKAGE_FILES = []
for (path, directories, filenames) in os.walk("musicassistant_client/"):
    for filename in filenames:
        PACKAGE_FILES.append(os.path.join("..", path, filename))

setup(
    name="musicassistant_client",
    version=VERSION,
    url="https://github.com/marcelveldt/python-musicassistant-client",
    download_url="https://github.com/marcelveldt/python-musicassistant-client",
    author="Marcel van der Veldt",
    author_email="m.vanderveldt@outlook.com",
    description="Basic client for connecting to Music Assistant over websockets and REST.",
    long_description=README_FILE.read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    packages=find_packages(exclude=["test.*", "test"]),
    python_requires=">=3.7",
    include_package_data=True,
    install_requires=INSTALL_REQUIRES,
    package_data={"musicassistant_client": PACKAGE_FILES},
    zip_safe=False,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Topic :: Home Automation",
    ],
)

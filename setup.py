#!/usr/bin/python
# -*- coding: utf-8 -*-
from setuptools import setup, Command
import sys

# sys.path.pop(0)
# sys.path.append(".")
import sdist_upip
import os

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()


class CleanCommand(Command):
    """Custom clean command to tidy up the project root."""

    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        os.system("rm -vrf ./dist ./*.pyc ./*.egg-info ./MANIFEST")


setup(
    name="micropython-iotmanager",
    version="0.2.0",
    author="Oliver Fueckert",
    author_email="oliver@fueckert.com",
    description="IoT Manager for ESP32 supporting WiFi config and OTA",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/cubinet-code/micropython-iotmanager",
    classifiers=[
        "Programming Language :: Python :: Implementation :: MicroPython",
        "Intended Audience :: Developers",
        "Topic :: System :: Hardware",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
    ],
    license="GPLv3",
    cmdclass={
        "sdist": sdist_upip.sdist,
        "clean": CleanCommand,
    },
    py_modules=["IotManager"],
)

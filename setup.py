#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import re
import sys
sys.path.pop(0)
from setuptools import setup
sys.path.append("./sdist_upip")
import sdist_upip

version = '0.2.2'
version_reference = os.getenv('GITHUB_REF', default=version)
release_version_search = re.search(r'(\d+.\d+.\d+)', version_reference)
if release_version_search:
    release_version = release_version_search.group()
    print(f'Version: {release_version}')
else:
    release_version = version
    print(f'Version: {release_version}')

setup(
    name="micropython-iotmanager",
    version=release_version,
    author="Oliver Fueckert",
    author_email="oliver@fueckert.com",
    description="IoT Manager for ESP32 supporting WiFi config and OTA",
    long_description=open("README.md").read(),
    long_description_content_type='text/markdown',
    project_urls={
        "Source": "https://github.com/cubinet-code/micropython-iotmanager"
    },
    packages=[''],
    classifiers=[
        "Programming Language :: Python :: Implementation :: MicroPython",
        "Intended Audience :: Developers",
        "Topic :: System :: Hardware",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
    ],
    license="GPLv3",
    cmdclass={'sdist': sdist_upip.sdist}
)

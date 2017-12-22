from setuptools import setup, find_packages

from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

with open(path.join(here, "README.md")) as f:
    long_desc = f.read()

setup(
    name="pyumlgen",
    version="0.1.1",
    description="Generate UML diagrams with type information from python modules",
    author="ben simms",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "pyumlgen=pyumlgen:main"
        ]
    }
)

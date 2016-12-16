#!/usr/bin/python3

from setuptools import setup, find_packages
from waypaste.version import __version__
setup(
    name="waypaste",
    version=__version__,
    packages=['waypaste'],
    entry_points={
        'console_scripts': [
            'waypaste = waypaste'
        ]
    },

    install_requires=['pywayland'],

    author="Lyude Paul",
    author_email="thatslyude@gmail.com",
    description="CLI paste utility for wayland desktop environments"
)

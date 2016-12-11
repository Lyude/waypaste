#!/usr/bin/python3

from setuptools import setup, find_packages
setup(
    name="waypaste",
    version="0.1",
    packages=['waypaste'],
    entry_points={
        'console_scripts': [
            'waypaste = waypaste.main:main'
        ]
    },

    install_requires=['pywayland'],

    author="Lyude Paul",
    author_email="thatslyude@gmail.com",
    description="CLI paste utility for wayland desktop environments"
)

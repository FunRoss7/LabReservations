from setuptools import setup, find_packages

setup(
    name='labreserve',
    version='0.1.0',
    packages=find_packages(),
    install_requires=[
        'click>=7.0',
        'PyYAML>=5.1',
    ],
    entry_points={
        'console_scripts': [
            'labreserve=labreserve.cli:main',
        ],
    },
    python_requires='>=3.6',
)

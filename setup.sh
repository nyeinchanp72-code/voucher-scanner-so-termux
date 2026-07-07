#!/bin/bash

echo "Updating and upgrading Termux packages..."
pkg update && pkg upgrade -y

echo "Installing Python and required packages..."
pkg install python -y
pkg install clang make libjpeg-turbo -y

echo "Installing Python libraries..."
pip install cython requests aiohttp ping3 opencv-python ddddocr numpy pycryptodome

echo "Compiling the script for Termux..."
cat <<EOF > setup_termux.py
from setuptools import setup
from Cython.Build import cythonize
setup(
    ext_modules = cythonize("scanner.py", compiler_directives={'language_level': "3"})
)
EOF

python setup_termux.py build_ext --inplace

echo "Cleaning up..."
rm scanner.py
rm scanner.c
rm setup_termux.py
rm -rf build/

echo "Done! You can now run the tool using 'python -c \"import scanner; scanner.main()\"' if it has a main function, or use a runner script."

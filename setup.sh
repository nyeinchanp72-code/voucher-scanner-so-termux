#!/bin/bash

echo "🚀 Setting up Voucher Scanner for Termux..."

# Update and install dependencies
pkg update && pkg upgrade -y
pkg install python clang make libjpeg-turbo -y

# Install Python requirements
echo "📦 Installing Python libraries (this may take a few minutes)..."
pip install cython aiohttp ping3 requests opencv-python ddddocr numpy pycryptodome

# Compile the script using Cython
echo "🛠️ Compiling scanner.py..."
cat <<EOF > setup_termux.py
from setuptools import setup
from Cython.Build import cythonize
setup(
    ext_modules = cythonize("scanner.py", compiler_directives={'language_level': "3"})
)
EOF

python setup_termux.py build_ext --inplace

# Cleanup
echo "🧹 Cleaning up source files..."
rm scanner.py
rm -rf build/
rm setup_termux.py
# Note: Keep the .so file for running

echo "✅ Setup complete! You can now run the tool."
echo "🚀 Use: python run.py"

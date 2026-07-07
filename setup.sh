#!/bin/bash

echo "🚀 Setting up Voucher Scanner for Termux..."

# Update and install dependencies
pkg update && pkg upgrade -y
pkg install python clang make libjpeg-turbo -y

# Install Python requirements
echo "📦 Installing Python libraries (this may take a few minutes)..."
pip install aiohttp ping3 requests opencv-python ddddocr numpy pycryptodome pyarmor

echo "✅ Dependencies installed."
echo "✅ Setup complete! You can now run the tool."
echo "🚀 Use: python run.py"

#!/bin/bash
set -e  # Exit on error

echo "🧹 Cleaning previous builds..."
rm -rf dist/ build/ *.egg-info/

echo "📦 Building package..."
uv run hatch build

echo "✅ Checking distribution..."
uv run twine check dist/*

echo ""
echo "✨ Build complete! Distribution files:"
ls -lh dist/

echo ""
echo "📤 To publish to PyPI, run:"
echo "   uv run twine upload dist/*"
echo ""
echo "📤 To publish to TestPyPI first, run:"
echo "   uv run twine upload --repository testpypi dist/*"

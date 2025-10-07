git checkout -b package-setup
mkdir -p squint/examples
git mv SQUINT.py squint/compiler.py           # if present locally
git mv SQUINT_FloquetVisualizer.py squint/visualizer.py
git add squint/__init__.py squint/cli.py
git add pyproject.toml .gitignore
git add squint/examples/*.squint              # add your three examples
git commit -m "Package setup: squint/ + pyproject + console script"
git push -u origin package-setup

# For a repo with a plain .git/hooks/pre-commit (or a script that installs one).
# Add these lines to it. They warn and never block the commit.
if [ -f scripts/seams_check.py ]; then
  python3 scripts/seams_check.py >/dev/null || python3 scripts/seams_check.py
  python3 scripts/seams_check.py --staged | grep -v "No seam has a copy left behind" || true
fi

# Synthetic .NET logs

Hand-written, not from Genie. They exercise the format-independent parser
(`Exception.ToString()` layout, inner exceptions, async frames, masking).
Real Genie samples go in `tests/fixtures/logs/<bot>/` and get their own `expected.json`.
All names, emails and numbers here are invented.

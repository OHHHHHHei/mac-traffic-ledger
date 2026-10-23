# Contributing

Python 3.10+ is required. Runtime collection targets macOS; database tests also run on Linux.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

Keep the collector local-first and free of runtime third-party dependencies.
Preserve delta accounting, restart baselines and the separation of DIRECT/PROXY traffic.
Use synthetic connection data in tests and examples. Do not submit live databases,
subscription credentials, personal executable paths or browsing-history screenshots.

Describe the change and relevant validation in a pull request. If changing collection
frequency or storage, explain the impact on attribution, short-connection loss and memory.

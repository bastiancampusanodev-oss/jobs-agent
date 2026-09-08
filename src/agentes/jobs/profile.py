from __future__ import annotations

from agentes.config import load_yaml


def load_job_context() -> str:
    candidate = load_yaml("config/candidate.yaml")
    rules = load_yaml("config/jobs.yaml")
    cvs = load_yaml("config/cvs.yaml")
    import yaml

    return "\n\n".join(
        [
            "# CANDIDATE FACTS\n" + yaml.safe_dump(candidate, allow_unicode=True, sort_keys=False),
            "# JOB RULES\n" + yaml.safe_dump(rules, allow_unicode=True, sort_keys=False),
            "# AVAILABLE CVS\n" + yaml.safe_dump(cvs, allow_unicode=True, sort_keys=False),
        ]
    )

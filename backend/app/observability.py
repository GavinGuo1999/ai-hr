import os
from contextlib import contextmanager


@contextmanager
def trace_generation(name: str, model: str, application_id: int | None,
                     prompt_version: int, round_no: int | None, input_chars: int):
    """Only low-risk metadata leaves the app. Never capture resumes or answers."""
    enabled = os.getenv("LANGFUSE_SEND_TRACES") == "1" and all(os.getenv(key) for key in (
        "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL",
    ))
    if not enabled:
        yield None
        return
    from langfuse import get_client  # lazy import after environment is configured

    client = get_client()
    with client.start_as_current_observation(
        as_type="generation", name=name, model=model,
        input={"input_chars": input_chars},
        metadata={"application_id": application_id, "prompt_version": prompt_version,
                  "round_no": round_no},
        version=str(prompt_version),
    ) as observation:
        yield observation

"""Arize Phoenix tracing setup (P3).

Call init_tracing() once at program start (gated on USE_PHOENIX / USE_ARIZE).
All spans flow to:
  - local Phoenix (PHOENIX_COLLECTOR_ENDPOINT) during judging — zero network risk
  - Arize cloud (ARIZE_API_KEY + ARIZE_SPACE_ID) post-hackathon

With USE_CLAUDE=True, openinference-instrumentation-claude-agent-sdk
auto-captures every Anthropic call as a child span inside your manual spans.
"""
from __future__ import annotations

from . import config

_provider = None
_tracer = None


def init_tracing() -> bool:
    """Initialize OTel exporter. Returns True if tracing is active."""
    global _provider, _tracer

    if not (config.USE_PHOENIX or config.USE_ARIZE):
        return False

    try:
        from opentelemetry import trace

        if config.USE_ARIZE:
            # Arize cloud via arize-otel register()
            from arize.otel import register
            _provider = register(
                space_id=config.ARIZE_SPACE_ID,
                api_key=config.ARIZE_API_KEY,
                project_name=config.ARIZE_PROJECT_NAME,
            )
        else:
            # Local Phoenix via raw OTLP
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            resource = Resource(attributes={
                "service.name": config.ARIZE_PROJECT_NAME,
                "project.name": config.ARIZE_PROJECT_NAME,  # required — HTTP 500 without it
            })
            _provider = TracerProvider(resource=resource)
            otlp_url = config.PHOENIX_ENDPOINT.rstrip("/") + "/v1/traces"
            _provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_url))
            )
            trace.set_tracer_provider(_provider)

        _tracer = trace.get_tracer("immune")

        # auto-instrument Anthropic API calls
        try:
            from openinference.instrumentation.anthropic import AnthropicInstrumentor
            AnthropicInstrumentor().instrument()
        except ImportError:
            pass

        return True

    except ImportError:
        return False


def get_tracer():
    return _tracer


def shutdown() -> None:
    if _provider and hasattr(_provider, "force_flush"):
        _provider.force_flush()
        _provider.shutdown()

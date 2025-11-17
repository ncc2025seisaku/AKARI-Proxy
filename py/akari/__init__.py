"""Python wrapper package for AKARI UDP core utilities."""

from .udp_codec import main as udp_codec_main  # noqa: F401

__all__ = ["udp_codec", "udp_codec_main"]
